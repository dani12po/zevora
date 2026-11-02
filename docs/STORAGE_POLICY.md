# Storage Policy

The managed-data budget defaults to 30 GB, warning at 25 GB, critical at 28 GB. The budget leaves capacity on the 35 GB drive.

Emergency order is ephemeral cache, temporary files, old logs, expired raw data, and low-value archives. The implementation does not automatically delete curated memory, evaluation data, datasets, models, source projects, or credentials.

## Cache Categories

`data/cache/ephemeral_cache/` contains exact API results and other temporary acceleration data. It is subject to the configured cache TTL (168 hours by default) and may be removed by cleanup.

`data/cache/provider_config_cache/` contains persistent ZEVORA Local AI setup and provider configuration metadata, such as verified model paths, loaded-model state, analysis results, and credential references. It is configuration state, not disposable cache, and is never included in TTL expiry or cleanup plans. Chat history is stored only in `data/database/workspace.db`; full chat or message content must not be written to either cache category.

Preview eligible cleanup without changes:

```powershell
python -m agent.storage.cli cleanup --dry-run
```
