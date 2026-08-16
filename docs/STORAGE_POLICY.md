# Storage Policy

The managed-data budget defaults to 30 GB, warning at 25 GB, critical at 28 GB. The budget leaves capacity on the 35 GB drive.

Emergency order is cache, temporary files, old logs, expired raw data, and low-value archives. The implementation does not automatically delete curated memory, evaluation data, datasets, models, source projects, or credentials.

Preview eligible cleanup without changes:

```powershell
python -m agent.storage.cli cleanup --dry-run
```
