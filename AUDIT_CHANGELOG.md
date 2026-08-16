# ZEVORA Audit Changelog

## UI structure and theme

- Replaced the generic navy/emerald palette with synchronized charcoal/copper design tokens in `static/styles.css` and both design-system masters.
- Split the browser application into route modules, kept each JavaScript file below 300 lines, and added local/cloud states and reduced-motion-safe route transitions.

## Security and provider handling

- `main.py`: added bounded request fields and structured API errors for invalid workspace, provider, and MCP input instead of leaking unhandled exceptions.
- `agent/providers/configuration.py`: blocked literal credentials in manifests, headers, request options, runtime environment, and exports. Credentials remain references with masked public state.
- `agent/providers/script_analyzer.py`: strengthened custom runtime analysis and trust validation before execution.
- `agent/providers/*_provider.py`: normalized provider transport failures so routing can continue through fallback instead of returning raw errors.
- `agent/tools/mcp_gateway.py`: tightened workspace path and approval checks for mutation and command execution paths.

## Routing and project indexing

- `agent/routing/hybrid_router.py`: regression coverage now includes unavailable providers, failed candidates, and capability filtering.
- `agent/core/project_index.py`: added an mtime/size-backed incremental index cache. Unchanged files reuse their digest and searchable content; deleted files are removed and changed files alone are re-read.

## Cache and retention

- `agent/storage/retention.py`: introduced explicit `ephemeral_cache` and `provider_config_cache` categories.
- `agent/storage/cleanup.py`: cleanup only expires `data/cache/ephemeral_cache`; persistent provider configuration is excluded. Deletion failures are logged and returned as structured failures instead of crashing the maintenance run.
- `docs/STORAGE_POLICY.md`: documents that chat history belongs only in `data/database/workspace.db`, exact response cache remains TTL-managed, and provider setup metadata is persistent.
- `requirements.txt` and `pyproject.toml`: removed unused `httpx2`; the application uses `httpx`.

## Workspace race and SQLite stability

- Root cause: overlapping `loadProject()` or `pickProject()` calls in `static/chat.js` could complete out of order. An older response would overwrite the project selected by a newer request, and a subsequent audit or chat could display or use the wrong project.
- Fix: project selection operations now carry a monotonic generation token. Only the latest operation may update the select, status, access state, or dialog. A manual selection also invalidates in-flight responses. Audit rendering already verifies the selected project ID before displaying its result.
- Root cause: `WorkspaceManager.connection()` used SQLite defaults with no busy timeout or WAL setup. Concurrent audit/chat activity could encounter immediate write contention and relied on implicit context behavior.
- Fix: `agent/core/workspace.py` now uses a closing transaction context manager, WAL, a 30-second busy timeout, explicit commit/rollback, and foreign-key enforcement.
- Regression coverage: `tests/test_workspace.py` exercises parallel A/B audits, concurrent chat writes, project identity, and the stale-response guard.

## Test infrastructure

- `pyproject.toml`: configured pytest with the repository root on the import path so the documented `pytest -q` command can collect `main.py` consistently on Windows.
- Final verification target: the complete suite, JavaScript syntax checks, Python compile checks, and `git diff --check`.
