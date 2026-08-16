# Data Lifecycle

`RAW → sanitize → exact/hash deduplicate → quality score → semantic merge → consolidate → curate/archive → retention cleanup`.

Raw data has a configurable 30-day retention. Curated memory, approved datasets, models, and projects are never cleanup candidates. Embeddings are intentionally deferred until records pass scoring/deduplication.

Daily maintenance should only run cache/log/temp cleanup. Weekly consolidation and archive work must be skipped above 80% RAM/CPU pressure; all maintenance is dry-run by default.

`MaintenanceScheduler` supplies daily/weekly/monthly plans but intentionally does not start a background thread. This preserves lightweight idle behavior; the operator can schedule it later through Task Scheduler or another approved scheduler.
