# Adaptive Hybrid Intelligence Router

ZEVORA always remains architecturally hybrid. In `AUTO`, the candidate order is
`CACHE -> LOCAL/CLOUD pool -> fallback pool`; routine work is local-first while
complex, architecture, migration, vision, and long-context work are cloud-first
when capable. `LOCAL_ONLY` and `CLOUD_ONLY` are routing constraints, not product
identity modes.

Eligibility is fail-closed and uses verified availability and health, explicit
capabilities, required MCP tool support, estimated context tokens versus model
window, local package installation and compatibility, and configured provider
policy. Unknown capabilities are not invented. Ranking combines capability
quality, estimated input/output cost, provider priority, configured defaults, and
mature success/quality/latency history. Immature history does not override the
configured baseline.

`LOCAL + MCP` is returned as a tool plan until the user approves its write/execute
actions; it is not reported as completed tool execution. Compact routing
experiences record only route/model/task/success/quality/latency/tool metadata,
never prompts, chain-of-thought, or keys. Context economy supplies bounded,
deduplicated token estimates to routing and records counts/hashes only.

Settings are defined in `.env`: `ROUTING_MODE`, `CLOUD_FALLBACK`,
`COST_OPTIMIZATION`, `ADAPTIVE_ROUTING`, and `MAX_REPAIR_ATTEMPTS`.

In project mode, ZEVORA retrieves registered workspace metadata and indexes/audits
only the selected workspace. Project paths outside the configured workspace root
are rejected by the workspace sandbox.
