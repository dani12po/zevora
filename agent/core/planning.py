"""Strict parsing for cloud-generated MCP plans; prose is never executable."""
import json
import re
from collections.abc import Collection
from typing import Any

from agent.core.execution import AgentAction

ALLOWED_TOOLS = {
    'list_directory', 'read_file', 'search_files', 'file_exists', 'get_file_info',
    'create_file', 'write_file', 'edit_file', 'delete_file', 'move_file',
    'copy_file', 'execute_command', 'git',
}
_JSON_BLOCK = re.compile(r'^\s*```(?:json)?\s*(.*?)\s*```\s*$', re.DOTALL | re.IGNORECASE)


def _allowed_tools(allowed_tools: Collection[str] | None) -> set[str]:
    if allowed_tools is None:
        return set(ALLOWED_TOOLS)
    return ALLOWED_TOOLS.intersection(allowed_tools)


def planning_system_prompt(
    max_actions: int = 30, allowed_tools: Collection[str] | None = None
) -> str:
    available = _allowed_tools(allowed_tools)
    tools = ', '.join(sorted(available)) or 'none'
    guidance = []
    if available.intersection({'create_file', 'write_file'}):
        creation_tools = ' or '.join(
            name for name in ('write_file', 'create_file') if name in available
        )
        guidance.append(
            f'For a new file, generate its complete requested content in the {creation_tools} '
            'arguments; do not answer with a code sample instead of an action. '
            'Inspection is not required before creating a new file.'
        )
    if 'edit_file' in available:
        guidance.append(
            'Inspection is preferred before editing an existing file. For edits use '
            'edit_file with exact old_text and new_text.'
        )
    if 'execute_command' in available:
        guidance.append('For commands provide one command without shell chaining.')
    return (
        'You are Zevora, the private hybrid AI coding agent of the ZEVORA workspace, '
        'acting as the tool planner. Return JSON only, never Markdown or prose. '
        'Schema: {"needs_tools":boolean,"actions":[{"tool":string,'
        '"arguments":object,"purpose":string}]}. '
        f'Use at most {max_actions} actions and only these tools: {tools}. '
        'Use an available tool whenever the user explicitly requests a matching action '
        'in the selected project. '
        + ' '.join(guidance) + ' '
        'Do not include approved; backend permission policy owns approval.'
    )


def parse_action_plan(
    response: str,
    max_actions: int = 30,
    allowed_tools: Collection[str] | None = None,
) -> list[AgentAction]:
    """Accept one exact JSON document and reject unknown or disabled actions."""
    available_tools = _allowed_tools(allowed_tools)
    candidate = response.strip()
    fenced = _JSON_BLOCK.fullmatch(candidate)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        payload = json.loads(candidate)
    except (json.JSONDecodeError, TypeError) as error:
        raise ValueError('Provider did not return a valid structured action plan') from error
    if not isinstance(payload, dict) or not isinstance(payload.get('needs_tools'), bool):
        raise ValueError('Action plan must contain needs_tools boolean')
    actions = payload.get('actions', [])
    if not isinstance(actions, list):
        raise ValueError('Action plan actions must be a list')
    if not payload['needs_tools']:
        if actions:
            raise ValueError('Action plan cannot include actions when needs_tools is false')
        return []
    if not actions:
        raise ValueError('Action plan requires at least one action')
    if len(actions) > max_actions:
        raise ValueError(f'Action plan exceeds {max_actions} tool calls')

    parsed: list[AgentAction] = []
    for item in actions:
        if not isinstance(item, dict):
            raise ValueError('Each action must be an object')
        tool = item.get('tool')
        arguments = item.get('arguments')
        purpose = item.get('purpose', '')
        if tool not in available_tools:
            raise ValueError(f'Action plan contains unsupported or disabled tool: {tool}')
        if not isinstance(arguments, dict):
            raise ValueError('Action arguments must be an object')
        if not isinstance(purpose, str) or len(purpose) > 500:
            raise ValueError('Action purpose must be a string up to 500 characters')
        parsed.append(AgentAction(tool=tool, arguments=arguments, approved=False, purpose=purpose))
    return parsed


def public_action(action: AgentAction) -> dict[str, Any]:
    # A selected workspace authorizes filesystem changes inside its root. Only
    # separately scoped operations such as restricted commands need approval.
    requires_approval = False
    if action.tool == 'execute_command':
        from agent.tools.mcp_gateway import LocalMCPGateway
        risk, _ = LocalMCPGateway.command_policy(action.arguments.get('command', ''))
        requires_approval = risk != 'SAFE'
    return {
        'tool': action.tool,
        'arguments': action.arguments,
        'approved': False,
        'purpose': action.purpose,
        'requires_approval': requires_approval,
    }
