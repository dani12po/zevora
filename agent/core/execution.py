"""Deterministic project-agent orchestration around the constrained MCP gateway."""

from dataclasses import asdict, dataclass, field
from pathlib import Path
from time import monotonic
from typing import Any, Callable

from agent.config import settings
from agent.tools.mcp_gateway import LocalMCPGateway


@dataclass(frozen=True)
class AgentAction:
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    approved: bool = False
    purpose: str = ''


@dataclass
class AgentTrace:
    stages: list[dict[str, Any]] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)
    pending_approvals: list[dict[str, Any]] = field(default_factory=list)
    verified: bool | None = None

    def stage(self, name: str, status: str = 'completed', detail: Any = None):
        entry = {'stage': name, 'status': status}
        if detail is not None:
            entry['detail'] = detail
        self.stages.append(entry)

    def to_dict(self) -> dict:
        return asdict(self)


class ProjectAgentExecutor:
    """Execute caller-structured actions without converting model prose into commands."""

    MAX_ITERATIONS = 12
    MAX_TOOL_CALLS = 30
    TIMEOUT_SECONDS = 300
    MAX_OBSERVATION_CHARS = 20_000
    VERIFY_TOOLS = {'terminal', 'execute_command', 'git'}

    def __init__(self, project_root: Path, preferences: dict[str, str] | None = None):
        self.root = Path(project_root).resolve()
        if not self.root.is_dir():
            raise ValueError('Project directory not found')
        self.gateway = LocalMCPGateway(self.root, preferences=preferences)

    def execute(self, prompt: str, actions: list[AgentAction] | None = None,
                project_files: list[str] | None = None,
                progress_callback: Callable[[str, str, str], None] | None = None) -> AgentTrace:
        trace = AgentTrace()
        started = monotonic()

        def emit(stage: str, status: str = 'completed', detail: str = '') -> None:
            if progress_callback is None:
                return
            try:
                progress_callback(stage, status, detail)
            except Exception:
                # Progress is observational and must never affect tool execution.
                return
        max_iterations = max(1, min(self.MAX_ITERATIONS, settings.max_agent_iterations))
        max_tool_calls = max(1, min(self.MAX_TOOL_CALLS, settings.max_agent_tool_calls))
        timeout_seconds = max(1, min(self.TIMEOUT_SECONDS, settings.agent_timeout_seconds))
        requested_actions = list(actions or [])
        safe_actions = requested_actions[:max_tool_calls]
        trace.stage('UNDERSTAND', detail={
            'prompt_chars': len(prompt), 'max_iterations': max_iterations,
            'max_tool_calls': max_tool_calls, 'timeout_seconds': timeout_seconds,
        })
        emit('UNDERSTAND', detail='Understanding the request')
        trace.stage('PLAN', detail={
            'actions': [
                {'tool': action.tool, 'purpose': action.purpose,
                 'approval_supplied': action.approved}
                for action in safe_actions
            ],
            'truncated_actions': max(0, len(requested_actions) - len(safe_actions)),
        })
        trace.stage('INSPECT', detail={'project_files': list(project_files or [])})
        emit('INSPECT', detail='Inspecting project context')
        trace.stage('RETRIEVE', detail={'project_context_available': bool(project_files)})
        emit('RETRIEVE', detail='Retrieving project context')
        trace.stage('REASON', detail={
            'policy': 'Structured actions only; model prose is never executed.'
        })

        if not safe_actions:
            trace.stage('ACT', status='skipped', detail='No structured actions requested')
            emit('ACT', 'skipped', 'No workspace actions requested')
            trace.stage('OBSERVE', status='skipped')
            emit('OBSERVE', 'skipped', 'No tool results to observe')
            trace.stage('VERIFY', status='skipped')
            emit('VERIFY', 'skipped', 'No verification action requested')
            trace.verified = None
            return trace

        for index, action in enumerate(safe_actions):
            emit('ACT', 'running', f'Running {action.tool}')
            if monotonic() - started >= timeout_seconds:
                trace.observations.append({
                    'index': index, 'tool': action.tool, 'ok': False,
                    'output': 'Agent execution timeout reached', 'timed_out': True,
                })
                break
            try:
                result = self.gateway.execute(
                    action.tool, action.arguments, approved=action.approved
                )
                output = result.output
            except (KeyError, OSError, UnicodeError, ValueError) as error:
                result = None
                output = f'{type(error).__name__}: {error}'

            if isinstance(output, str):
                output = output[-self.MAX_OBSERVATION_CHARS:]
            observation = {
                'index': index, 'tool': action.tool,
                'ok': bool(result and result.ok), 'output': output,
            }
            if result and result.approval_required:
                observation['approval_required'] = True
                trace.pending_approvals.append({
                    'index': index, 'tool': action.tool,
                    'arguments': action.arguments, 'purpose': action.purpose,
                })
            trace.observations.append(observation)
            emit(
                'ACT',
                'completed' if observation['ok'] else 'failed',
                f'{action.tool} ' + ('completed' if observation['ok'] else 'failed'),
            )

        act_status = 'failed' if len(requested_actions) > max_tool_calls else 'completed'
        trace.stage('ACT', status=act_status, detail={
            'actions_executed': len(trace.observations),
            'limit_reached': len(requested_actions) > max_tool_calls,
        })
        trace.stage('OBSERVE', detail={'observations': len(trace.observations)})
        emit('OBSERVE', detail=f'Recorded {len(trace.observations)} tool result(s)')
        verification = [
            item for item in trace.observations if item['tool'] in self.VERIFY_TOOLS
        ]
        if verification:
            emit('VERIFY', 'running', 'Verifying workspace changes')
            trace.verified = all(item['ok'] for item in verification)
            trace.stage(
                'VERIFY', 'completed' if trace.verified else 'failed',
                {'checks': len(verification)},
            )
            emit(
                'VERIFY',
                'completed' if trace.verified else 'failed',
                'Workspace verification completed' if trace.verified else 'Workspace verification failed',
            )
        else:
            trace.verified = None
            trace.stage('VERIFY', status='skipped', detail='No verification action requested')
            emit('VERIFY', 'skipped', 'No verification action requested')
        return trace
