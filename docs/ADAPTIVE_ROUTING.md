# Adaptive Hybrid Intelligence Router

ZEVORA routes in this order: `CACHE → LOCAL → LOCAL + MCP → CLOUD`. A route is selected from task complexity, verified model capabilities, local resource feasibility, required MCP tools, and known cloud pricing. It never uses a cloud request to make the routing decision.

`LOCAL + MCP` is returned as a tool plan until the user approves its write/execute actions; it is not reported as completed tool execution. Compact routing experiences record only route/model/task/success/quality/latency/tool metadata—never chain-of-thought or keys.

Settings are defined in `.env`: `ROUTING_MODE`, `LOCAL_FIRST`, `CLOUD_FALLBACK`, `MAX_LOCAL_RETRIES`, and `MAX_REPAIR_ATTEMPTS`.

In project mode, ZEVORA retrieves registered workspace metadata and indexes/audits only the selected workspace. Project paths outside `E:\Storage AI\Projects` are rejected by the workspace sandbox.
