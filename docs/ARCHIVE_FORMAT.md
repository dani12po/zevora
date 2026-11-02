# Archive Format

Archives are compact JSONL, compressed with Zstandard when installed and gzip otherwise. They are stored by `data/archive/YYYY/MM/`, verified by full decompression before a result is returned, hashed with SHA-256, and indexed in `data/database/archive_index.db`.

No source data should be removed until this verification succeeds. Archive indexes store location, topic, project, count, size, ratio, and checksum.
