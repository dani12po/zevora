"""Workspace-scoped permission policy with ephemeral session grants.

The policy is deliberately separate from tool execution: it answers whether an
operation needs a user decision, while the gateway remains responsible for
safe path resolution and actual I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any


FILESYSTEM_READ = {'list_directory', 'read_file', 'search_files', 'file_exists', 'get_file_info'}
FILESYSTEM_MUTATION = {'create_file', 'write_file', 'edit_file', 'move_file', 'copy_file'}
DESTRUCTIVE_TOOLS = {'delete_file', 'delete_directory'}
VALID_MODES = {'ask', 'deny', 'session', 'always'}


@dataclass
class PermissionDecision:
    allowed: bool
    approval_required: bool = False
    permission_type: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    reason: str = ''


class WorkspacePermissionPolicy:
    """Policy for one selected workspace.

    ``session_grants`` intentionally lives only in memory. Persistent settings
    are supplied by the workspace manager and contain policy modes, not grants.
    """

    def __init__(self, workspace_root: Path, preferences: dict[str, str] | None = None):
        self.workspace_root = Path(workspace_root).resolve()
        supplied = preferences or {}
        self.preferences = {
            'terminal': supplied.get('terminal', 'ask'),
            'git': supplied.get('git', 'ask'),
            'external_filesystem': supplied.get('external_filesystem', 'deny'),
        }
        if any(mode not in VALID_MODES for mode in self.preferences.values()):
            raise ValueError('Invalid workspace permission preference')
        self.session_grants: set[tuple[str, str]] = set()
        self.always_grants: set[tuple[str, str]] = set()
        self._lock = Lock()

    def resolve(self, path: str | Path) -> Path:
        return Path(path).expanduser().resolve() if Path(path).is_absolute() else (self.workspace_root / str(path)).resolve()

    def is_within_workspace(self, path: str | Path) -> bool:
        resolved = self.resolve(path)
        try:
            resolved.relative_to(self.workspace_root)
            return True
        except ValueError:
            return False

    def _grant_key(self, kind: str, value: str | Path) -> tuple[str, str]:
        return kind, str(value).lower()

    def grant(self, kind: str, value: str | Path, scope: str = 'once') -> None:
        if scope not in {'once', 'session', 'always'}:
            raise ValueError('Invalid permission grant scope')
        if scope == 'once':
            return
        with self._lock:
            target = self.session_grants if scope == 'session' else self.always_grants
            target.add(self._grant_key(kind, value))

    def revoke(self, kind: str | None = None, value: str | Path | None = None) -> None:
        with self._lock:
            for grants in (self.session_grants, self.always_grants):
                grants.difference_update({key for key in grants if (kind is None or key[0] == kind) and (value is None or key[1] == str(value).lower())})

    def check(self, tool: str, args: dict[str, Any], approved: bool = False) -> PermissionDecision:
        if tool in FILESYSTEM_READ | FILESYSTEM_MUTATION | DESTRUCTIVE_TOOLS:
            paths = [args.get('path', '')]
            if tool in {'move_file', 'copy_file'}:
                paths = [args.get('source', ''), args.get('destination', '')]
            outside = [str(self.resolve(path)) for path in paths if not self.is_within_workspace(path)]
            if outside:
                return PermissionDecision(
                    False, False, 'external_filesystem',
                    {'paths': outside}, 'Paths outside the selected workspace are blocked',
                )
            if tool in FILESYSTEM_MUTATION | DESTRUCTIVE_TOOLS and not approved:
                return PermissionDecision(
                    False, True, 'filesystem_mutation',
                    {'tool': tool, 'paths': paths},
                    'Filesystem changes require explicit confirmation',
                )

        if tool in {'execute_command', 'terminal'}:
            return self._check_scoped_permission(
                'terminal', str(args.get('command', '')), approved,
                {'command': str(args.get('command', '')),
                 'working_directory': str(self.workspace_root),
                 'risk': args.get('risk', 'UNKNOWN')},
            )
        if tool == 'git':
            return self._check_scoped_permission(
                'git', str(args.get('operation', 'status')), approved,
                {'operation': str(args.get('operation', 'status')),
                 'working_directory': str(self.workspace_root)},
            )
        return PermissionDecision(True)

    def _check_scoped_permission(self, kind: str, value: str, approved: bool,
                                 details: dict[str, Any]) -> PermissionDecision:
        mode = self.preferences.get(kind, 'ask')
        key = f'{value}|{self.workspace_root}'
        grant = self._grant_key(kind, key)
        if mode == 'deny':
            return PermissionDecision(False, permission_type=kind, details=details,
                                      reason=f'{kind.title()} access denied by workspace settings')
        if approved or mode in {'session', 'always'}:
            return PermissionDecision(True)
        if grant in self.session_grants or grant in self.always_grants:
            return PermissionDecision(True)
        return PermissionDecision(
            False, True, kind, details,
            f'{kind.title()} access requires explicit confirmation',
        )
