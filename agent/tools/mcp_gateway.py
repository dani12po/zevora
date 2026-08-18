"""Workspace-scoped MCP tools with explicit mutation and command boundaries."""
import json
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from agent.config import ROOT
from agent.core.project_index import IGNORED_PARTS
from agent.tools.workspace_permissions import WorkspacePermissionPolicy
from .permissions import Permission

PROJECTS_ROOT = ROOT / 'projects'
PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)
MCP_CONFIG_FILE = ROOT / 'config' / 'mcp.json'
MAX_TEXT_BYTES = 1_000_000
MAX_READ_BYTES = 200_000
MAX_COMMAND_OUTPUT = 100_000
_CONFIG_LOCK = Lock()


def _atomic_json_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + '\n',
        encoding='utf-8',
    )
    temporary.replace(path)

REGISTERED_TOOLS = {
    'list_directory': Permission.ALLOW,
    'read_file': Permission.ALLOW,
    'search_files': Permission.ALLOW,
    'file_exists': Permission.ALLOW,
    'get_file_info': Permission.ALLOW,
    'create_file': Permission.APPROVAL,
    'write_file': Permission.APPROVAL,
    'edit_file': Permission.APPROVAL,
    'delete_file': Permission.APPROVAL,
    'move_file': Permission.APPROVAL,
    'copy_file': Permission.APPROVAL,
    'execute_command': Permission.ALLOW,
    'git': Permission.ALLOW,
    'create_project': Permission.APPROVAL,
    'package_manager': Permission.APPROVAL,
}


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    tool: str
    output: object
    approval_required: bool = False


class LocalMCPGateway:
    """Execute real tools while preventing every path from escaping ``root``."""

    def __init__(self, root: Path = PROJECTS_ROOT, config_path: Path = MCP_CONFIG_FILE,
                 preferences: dict[str, str] | None = None):
        self.root = Path(root).resolve()
        self.config_path = Path(config_path).resolve()
        self.permission_policy = WorkspacePermissionPolicy(self.root, preferences)

    @staticmethod
    def canonical_tool(tool: str) -> str:
        return {'terminal': 'execute_command', 'project': 'create_project'}.get(tool, tool)

    def _config(self) -> dict:
        try:
            payload = json.loads(self.config_path.read_text(encoding='utf-8'))
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _config_with_migration(self) -> dict:
        payload = self._config()
        if 'tools' not in payload and 'enabled' not in payload:
            return payload
        enabled = payload.get('enabled', {})
        if not isinstance(enabled, dict):
            enabled = {}
        disabled = payload.get('disabled', {})
        if not isinstance(disabled, dict):
            disabled = {}
        for name in REGISTERED_TOOLS:
            if name in enabled and enabled[name] is False:
                disabled[name] = True
        migrated = {
            key: value for key, value in payload.items()
            if key not in {'tools', 'enabled', 'disabled'}
        }
        if disabled:
            migrated['disabled'] = disabled
        _atomic_json_write(self.config_path, migrated)
        return migrated

    def enabled_tools(self) -> set[str]:
        """All registered tools are enabled by default.

        ``config/mcp.json`` is only consulted to honour explicit per-tool
        *disables*. A missing file, an empty file, or an absent ``enabled``
        key all mean: every tool is on.  This way the gateway works
        correctly on first boot without requiring any UI page visit.
        """
        with _CONFIG_LOCK:
            payload = self._config_with_migration()
        disabled_overrides = payload.get('disabled', {})
        if not isinstance(disabled_overrides, dict):
            disabled_overrides = {}
        return {
            name for name in REGISTERED_TOOLS
            if not disabled_overrides.get(name, False)
        }

    def set_tool_enabled(self, tool: str, enabled: bool) -> dict:
        canonical = self.canonical_tool(tool)
        if canonical not in REGISTERED_TOOLS:
            raise ValueError(f'Tool is not registered: {tool}')
        if not isinstance(enabled, bool):
            raise ValueError('enabled must be a boolean')

        with _CONFIG_LOCK:
            payload = self._config_with_migration()
            # Only track explicit disables — enabled is the universal default.
            # Strip legacy 'enabled'/'tools' keys to keep config minimal.
            disabled = payload.get('disabled', {})
            if not isinstance(disabled, dict):
                disabled = {}
            if enabled:
                disabled.pop(canonical, None)   # remove disable override → back to default
            else:
                disabled[canonical] = True      # record disable override
            new_payload = {key: value for key, value in payload.items()
                           if key not in ('enabled', 'tools', 'disabled')}
            if disabled:
                new_payload['disabled'] = disabled
            _atomic_json_write(self.config_path, new_payload)
        return next(item for item in self.tools() if item['name'] == canonical)

    def tools(self):
        enabled = self.enabled_tools()
        return [
            {
                'name': name,
                'permission': permission.value,
                'enabled': name in enabled,
            }
            for name, permission in REGISTERED_TOOLS.items()
        ]

    def _path(self, path):
        resolved = (self.root / str(path or '')).resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise ValueError(f'Path must stay inside {self.root}')
        return resolved

    @staticmethod
    def _command(command):
        parts = shlex.split(command, posix=os.name != 'nt')
        if not parts:
            raise ValueError('Command is required')
        if any(token in {'&&', '||', ';', '|', '>', '>>', '<'} for token in parts):
            raise ValueError('Command chaining and redirection are not allowed')
        return parts

    @classmethod
    def command_policy(cls, command):
        """Return SAFE, RESTRICTED, or DANGEROUS without invoking a shell."""
        parts = cls._command(command)
        lowered = [part.lower() for part in parts]
        executable = Path(lowered[0]).name
        joined = ' '.join(lowered)
        dangerous = {
            'format', 'format.com', 'diskpart', 'fdisk', 'mkfs', 'shutdown',
            'reboot', 'reg', 'reg.exe', 'powershell', 'powershell.exe', 'cmd', 'cmd.exe',
        }
        if executable in dangerous or any(flag in lowered for flag in {'--delete', '--recursive', '-rf'}):
            return 'DANGEROUS', parts
        if executable in {'npm', 'npm.cmd'} and lowered[1:2] in (['install'], ['i']):
            return 'RESTRICTED', parts
        if executable in {'pip', 'pip.exe', 'pip3', 'pip3.exe'} and lowered[1:2] == ['install']:
            return 'RESTRICTED', parts
        if executable in {'git', 'git.exe'} and lowered[1:2] in (['checkout'], ['switch'], ['reset'], ['clean'], ['push']):
            return 'RESTRICTED', parts
        safe_python_module = (
            executable in {'python', 'python.exe', 'py'}
            and lowered[1:2] == ['-m']
            and lowered[2:3] in (['pytest'], ['compileall'])
        )
        safe = (
            (executable in {'npm', 'npm.cmd'} and (lowered[1:2] == ['test'] or lowered[1:3] == ['run', 'build']))
            or (executable in {'python', 'python.exe', 'py'} and '--version' in lowered)
            or safe_python_module
            or (executable in {'node', 'node.exe'} and ('--check' in lowered or '--version' in lowered))
            or (executable in {'git', 'git.exe'} and lowered[1:2] in (['status'], ['diff'], ['log']))
        )
        if not safe:
            raise ValueError('Command is not in the workspace command allowlist')
        return 'SAFE', parts

    def _copy(self, source, destination, move=False):
        source_path = self._path(source)
        destination_path = self._path(destination)
        if not source_path.exists():
            return False, 'Source not found'
        if destination_path.exists():
            return False, 'Destination already exists'
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        operation = shutil.move if move else (shutil.copytree if source_path.is_dir() else shutil.copy2)
        operation(source_path, destination_path)
        return True, {
            'source': source_path.relative_to(self.root).as_posix(),
            'destination': destination_path.relative_to(self.root).as_posix(),
        }

    def execute(self, tool, args=None, approved=False):
        try:
            return self._execute(tool, args, approved)
        except (KeyError, OSError, UnicodeError, ValueError) as error:
            return ToolResult(False, tool, f'{type(error).__name__}: {error}')

    def _execute(self, tool, args=None, approved=False):
        args = dict(args or {})
        canonical = self.canonical_tool(tool)
        permission = REGISTERED_TOOLS.get(canonical, Permission.DENY)
        if permission is Permission.DENY:
            return ToolResult(False, tool, 'Tool is not registered')
        if canonical not in self.enabled_tools():
            return ToolResult(False, tool, 'Tool is disabled in MCP settings')

        command_policy = None
        command = None
        if canonical == 'execute_command':
            try:
                command_policy, command = self.command_policy(args.get('command', ''))
            except ValueError as error:
                return ToolResult(False, tool, str(error))
            args['risk'] = command_policy

        decision = self.permission_policy.check(canonical, args, approved=approved)
        if not decision.allowed:
            return ToolResult(
                False, tool,
                {'message': decision.reason, **decision.details},
                decision.approval_required,
            )

        if canonical == 'execute_command':
            if command_policy == 'DANGEROUS':
                return ToolResult(False, tool, {
                    'message': 'Dangerous system commands are blocked',
                    'risk': command_policy,
                })
            if command_policy == 'RESTRICTED' and not approved:
                return ToolResult(False, tool, {
                    'message': 'Explicit approval required', 'risk': command_policy,
                    'command': args.get('command', ''),
                }, True)
        elif (
            permission is Permission.APPROVAL
            and not approved
            and decision.permission_type != 'workspace_filesystem'
        ):
            return ToolResult(False, tool, 'Explicit approval required', True)

        if canonical == 'create_project':
            name = args.get('name', '')
            if not name or Path(name).name != name or name in ('.', '..'):
                return ToolResult(False, tool, 'Invalid project name')
            target = self._path(name)
            if target.exists():
                return ToolResult(False, tool, 'Project already exists')
            target.mkdir(parents=True)
            return ToolResult(True, tool, {'project': str(target), 'name': target.name})

        if canonical == 'list_directory':
            path = self._path(args.get('path', ''))
            if not path.is_dir():
                return ToolResult(False, tool, 'Directory not found')
            entries = [{
                'name': item.name,
                'path': item.relative_to(self.root).as_posix(),
                'type': 'directory' if item.is_dir() else 'file',
            } for item in sorted(path.iterdir(), key=lambda item: item.name.lower())]
            return ToolResult(True, tool, entries[:500])

        if canonical == 'read_file':
            path = self._path(args.get('path'))
            if not path.is_file():
                return ToolResult(False, tool, 'File not found')
            offset = max(0, int(args.get('offset', 0)))
            limit = min(MAX_READ_BYTES, max(1, int(args.get('limit', 64_000))))
            with path.open('rb') as handle:
                handle.seek(offset)
                data = handle.read(limit)
                has_more = bool(handle.read(1))
            if b'\x00' in data:
                return ToolResult(False, tool, 'Binary file cannot be read as text')
            return ToolResult(True, tool, {
                'path': path.relative_to(self.root).as_posix(),
                'content': data.decode('utf-8', errors='replace'),
                'offset': offset, 'bytes_read': len(data),
                'next_offset': offset + len(data) if has_more else None,
            })

        if canonical == 'search_files':
            query = str(args.get('query', '')).lower()
            pattern = str(args.get('pattern', '')).lower()
            include_ignored = bool(args.get('include_ignored', False))
            results = []
            for item in self.root.rglob('*'):
                if not item.is_file():
                    continue
                relative = item.relative_to(self.root)
                if not include_ignored and any(part in IGNORED_PARTS for part in relative.parts):
                    continue
                relative_text = relative.as_posix()
                if query and query not in relative_text.lower():
                    continue
                if pattern and not item.match(pattern):
                    continue
                results.append(relative_text)
                if len(results) >= 500:
                    break
            return ToolResult(True, tool, results)

        if canonical == 'file_exists':
            path = self._path(args.get('path'))
            return ToolResult(True, tool, {'path': str(args.get('path', '')), 'exists': path.exists()})

        if canonical == 'get_file_info':
            path = self._path(args.get('path'))
            if not path.exists():
                return ToolResult(False, tool, 'Path not found')
            stat = path.stat()
            return ToolResult(True, tool, {
                'path': path.relative_to(self.root).as_posix(),
                'type': 'directory' if path.is_dir() else 'file',
                'size_bytes': stat.st_size, 'modified_ns': stat.st_mtime_ns,
            })

        if canonical in {'create_file', 'write_file'}:
            path = self._path(args.get('path'))
            content = args.get('content')
            if not isinstance(content, str):
                return ToolResult(False, tool, 'Text content is required')
            encoded = content.encode('utf-8')
            if len(encoded) > MAX_TEXT_BYTES:
                return ToolResult(False, tool, 'File exceeds 1 MB limit')
            if canonical == 'create_file' and path.exists():
                return ToolResult(False, tool, 'File already exists')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
            return ToolResult(True, tool, {
                'path': path.relative_to(self.root).as_posix(),
                'bytes': len(encoded),
                'preview': content[:400] + ('…' if len(content) > 400 else ''),
                'line_count': content.count('\n') + 1,
            })

        if canonical == 'edit_file':
            path = self._path(args.get('path'))
            old_text, new_text = args.get('old_text'), args.get('new_text')
            if not path.is_file():
                return ToolResult(False, tool, 'File not found')
            if not isinstance(old_text, str) or not old_text:
                return ToolResult(False, tool, 'old_text is required')
            if not isinstance(new_text, str):
                return ToolResult(False, tool, 'new_text is required')
            content = path.read_text(encoding='utf-8')
            occurrences = content.count(old_text)
            if occurrences != 1:
                return ToolResult(False, tool, f'old_text must match exactly once; found {occurrences}')
            updated = content.replace(old_text, new_text, 1)
            if len(updated.encode('utf-8')) > MAX_TEXT_BYTES:
                return ToolResult(False, tool, 'File exceeds 1 MB limit')
            path.write_text(updated, encoding='utf-8')
            return ToolResult(True, tool, {
                'path': path.relative_to(self.root).as_posix(),
                'bytes': len(updated.encode('utf-8')),
                'preview': new_text[:400] + ('…' if len(new_text) > 400 else ''),
                'line_count': updated.count('\n') + 1,
                'replacements': 1,
            })

        if canonical == 'delete_file':
            path = self._path(args.get('path'))
            if not path.is_file():
                return ToolResult(False, tool, 'File not found')
            size_bytes = path.stat().st_size
            path.unlink()
            return ToolResult(True, tool, {
                'path': path.relative_to(self.root).as_posix(),
                'bytes': size_bytes,
            })

        if canonical in {'move_file', 'copy_file'}:
            source_path = self._path(args.get('source'))
            size_bytes = source_path.stat().st_size if source_path.is_file() else None
            ok, output = self._copy(
                args.get('source'), args.get('destination'), canonical == 'move_file'
            )
            if ok and isinstance(output, dict) and size_bytes is not None:
                output['bytes'] = size_bytes
            return ToolResult(ok, tool, output)

        if canonical == 'git':
            operation = args.get('operation', 'status')
            if operation not in {'status', 'diff', 'log'}:
                return ToolResult(False, tool, 'Only git status, diff, and log are allowed')
            command = ['git', operation] + (['--oneline', '-10'] if operation == 'log' else [])
            return self._run_command(tool, command, 20, 'SAFE')

        if canonical == 'execute_command':
            timeout = min(300, max(1, int(args.get('timeout', 120))))
            return self._run_command(tool, command, timeout, command_policy)

        if canonical == 'package_manager':
            return ToolResult(False, tool, 'Package installation is disabled')
        return ToolResult(False, tool, 'Tool not implemented')

    def _run_command(self, tool, command, timeout, risk):
        try:
            completed = subprocess.run(
                command, cwd=self.root, capture_output=True, text=True,
                timeout=timeout, check=False, shell=False,
            )
            output = {
                'stdout': completed.stdout[-MAX_COMMAND_OUTPUT:],
                'stderr': completed.stderr[-MAX_COMMAND_OUTPUT:],
                'exit_code': completed.returncode,
                'risk': risk,
            }
            return ToolResult(completed.returncode == 0, tool, output)
        except subprocess.TimeoutExpired as error:
            return ToolResult(False, tool, {
                'stdout': (error.stdout or '')[-MAX_COMMAND_OUTPUT:],
                'stderr': (error.stderr or '')[-MAX_COMMAND_OUTPUT:],
                'exit_code': None, 'risk': risk, 'timed_out': True,
            })
        except OSError as error:
            return ToolResult(False, tool, {
                'stdout': '', 'stderr': f'Command failed: {type(error).__name__}',
                'exit_code': None, 'risk': risk,
            })
