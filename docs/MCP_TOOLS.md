# ZEVORA MCP Tool Gateway

```text
Chat -> Agent Core -> Model Router -> Local MCP Gateway -> <selected workspace>
```

The gateway exposes read/list/search tools and a `create_project` tool rooted
exclusively at the currently selected workspace. Creation, terminal, package
manager, and git operations require explicit approval. The gateway rejects path
traversal and does not provide unrestricted shell access.

Creation is on-demand; no project is created merely by starting ZEVORA.
