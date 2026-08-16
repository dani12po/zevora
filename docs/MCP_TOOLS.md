# ZEVORA MCP Tool Gateway

```text
Chat -> Agent Core -> Model Router -> Local MCP Gateway -> E:\Storage AI\Projects\<project>
```

The gateway exposes read/list/search tools and a `create_project` tool rooted exclusively at `E:\Storage AI\Projects`. Creation, terminal, package manager, and git operations require explicit approval. The gateway rejects path traversal and does not provide unrestricted shell access.

Creation is on-demand; no project is created merely by starting ZEVORA.
