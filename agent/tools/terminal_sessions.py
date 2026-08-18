"""Bounded, workspace-scoped terminal sessions for the coding workspace."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock, Thread
from time import monotonic
import subprocess
import uuid

from agent.tools.mcp_gateway import LocalMCPGateway


MAX_EVENTS = 500
MAX_OUTPUT = 256_000
DEFAULT_TIMEOUT = 120
MAX_TIMEOUT = 600


@dataclass
class TerminalSession:
    session_id: str
    root: Path
    command: str
    argv: list[str]
    risk: str
    process: subprocess.Popen
    timeout: int
    started_at: float = field(default_factory=monotonic)
    events: list[dict] = field(default_factory=list)
    output_bytes: int = 0
    status: str = 'running'
    exit_code: int | None = None
    timed_out: bool = False
    lock: Lock = field(default_factory=Lock, repr=False)

    def add_event(self, stream: str, text: str) -> None:
        if not text:
            return
        with self.lock:
            remaining = MAX_OUTPUT - self.output_bytes
            if remaining <= 0:
                return
            text = text[:remaining]
            self.output_bytes += len(text)
            self.events.append({'type': 'output', 'stream': stream, 'data': text})
            if len(self.events) > MAX_EVENTS:
                del self.events[:-MAX_EVENTS]

    def snapshot(self, after: int = 0) -> dict:
        with self.lock:
            events = self.events[after:]
            return {
                'session_id': self.session_id,
                'command': self.command,
                'risk': self.risk,
                'status': self.status,
                'exit_code': self.exit_code,
                'timed_out': self.timed_out,
                'cwd': str(self.root),
                'started_at': self.started_at,
                'events': events,
                'next': after + len(events),
            }


class TerminalSessionManager:
    def __init__(self, max_sessions: int = 16):
        self.max_sessions = max_sessions
        self._sessions: dict[str, TerminalSession] = {}
        self._lock = Lock()

    def start(self, root: Path, command: str, *, approved: bool = False,
              timeout: int = DEFAULT_TIMEOUT, cwd: str = '',
              preferences: dict[str, str] | None = None) -> dict:
        root = Path(root).resolve()
        gateway = LocalMCPGateway(root, preferences=preferences)
        risk, argv = gateway.command_policy(command)
        args = {'command': command, 'timeout': timeout, 'risk': risk}
        decision = gateway.permission_policy.check('execute_command', args, approved=approved)
        if not decision.allowed:
            return {
                'ok': False,
                'approval_required': decision.approval_required,
                'error': decision.reason,
                'details': decision.details,
                'risk': risk,
            }
        if risk == 'DANGEROUS':
            return {'ok': False, 'approval_required': False, 'error': 'Dangerous system commands are blocked', 'risk': risk}
        if risk == 'RESTRICTED' and not approved:
            return {'ok': False, 'approval_required': True, 'error': 'Explicit approval required', 'risk': risk}
        timeout = max(1, min(MAX_TIMEOUT, int(timeout)))
        workdir = (root / cwd).resolve() if cwd else root
        try:
            workdir.relative_to(root)
        except ValueError as error:
            raise ValueError('cwd must stay inside the workspace') from error
        if not workdir.is_dir():
            raise ValueError('cwd must be an existing directory')
        with self._lock:
            active = sum(item.status == 'running' for item in self._sessions.values())
            if active >= self.max_sessions:
                raise RuntimeError('Too many active terminal sessions')
            process = subprocess.Popen(
                argv, cwd=workdir, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, shell=False, bufsize=1,
            )
            session_id = 'term-' + uuid.uuid4().hex[:12]
            session = TerminalSession(session_id, workdir, command, argv, risk, process, timeout)
            self._sessions[session_id] = session
        for stream, pipe in (('stdout', process.stdout), ('stderr', process.stderr)):
            Thread(target=self._read_pipe, args=(session, stream, pipe), daemon=True).start()
        Thread(target=self._watch, args=(session,), daemon=True).start()
        return {'ok': True, **session.snapshot()}

    @staticmethod
    def _read_pipe(session: TerminalSession, stream: str, pipe) -> None:
        try:
            for line in iter(pipe.readline, ''):
                session.add_event(stream, line)
        finally:
            pipe.close()

    @staticmethod
    def _watch(session: TerminalSession) -> None:
        try:
            code = session.process.wait(timeout=session.timeout)
        except subprocess.TimeoutExpired:
            session.timed_out = True
            session.process.kill()
            code = session.process.wait()
            session.add_event('system', f'Command timed out after {session.timeout}s.\n')
        with session.lock:
            session.exit_code = code
            if session.status == 'killed':
                status = 'killed'
            else:
                status = 'completed' if code == 0 and not session.timed_out else 'failed'
                session.status = status
            session.events.append({'type': 'status', 'status': status, 'exit_code': code})

    def get(self, session_id: str, after: int = 0) -> dict | None:
        with self._lock:
            session = self._sessions.get(session_id)
        return session.snapshot(max(0, int(after))) if session else None

    def kill(self, session_id: str) -> dict | None:
        with self._lock:
            session = self._sessions.get(session_id)
        if not session:
            return None
        with session.lock:
            running = session.status == 'running'
            if running:
                # Commit user intent before releasing the process waiter. The
                # watcher owns the one final status event and actual exit code.
                session.status = 'killed'
                session.exit_code = -9
        if running:
            session.process.kill()
        return session.snapshot()

    def clear(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None
