# ZEVORA AI Coding Workspace

The localhost UI is the primary coding workspace. It persists chat sessions, project association, and compact routing metadata in SQLite. Projects are explicitly loaded from the configured workspace root; the gateway does not grant unrestricted filesystem access.

Project audit creates a lightweight file metadata index and reports detected languages/frameworks without uploading or duplicating the repository. File writes, terminal operations, package operations, and git operations remain approval-gated MCP actions.
