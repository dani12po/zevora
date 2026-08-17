"""SQLite-backed provider/model catalog with backward-compatible metadata."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .metadata import ModelMetadata


class ModelRegistry:
    def __init__(self, database: Path):
        database.parent.mkdir(parents=True, exist_ok=True)
        self.database = database
        with self.connection() as conn:
            conn.execute(
                'CREATE TABLE IF NOT EXISTS models '
                '(provider TEXT, model_id TEXT, metadata TEXT NOT NULL, '
                'PRIMARY KEY(provider,model_id))'
            )
            conn.execute(
                'CREATE TABLE IF NOT EXISTS registry_meta '
                '(key TEXT PRIMARY KEY, value TEXT NOT NULL)'
            )
            conn.execute(
                "INSERT OR IGNORE INTO registry_meta(key,value) VALUES('schema_version','2')"
            )

    def connection(self):
        return sqlite3.connect(self.database)

    def upsert(self, model: ModelMetadata | dict):
        payload = model.to_dict() if isinstance(model, ModelMetadata) else dict(model)
        provider = str(payload.get('provider') or '')
        model_id = str(payload.get('model_id') or '')
        if not provider or not model_id:
            raise ValueError('model metadata requires provider and model_id')
        with self.connection() as conn:
            conn.execute(
                'INSERT OR REPLACE INTO models VALUES(?,?,?)',
                (provider, model_id, json.dumps(payload, sort_keys=True)),
            )

    def list(self, provider=None):
        with self.connection() as conn:
            rows = conn.execute(
                'SELECT metadata FROM models' + (' WHERE provider=?' if provider else ''),
                ((provider,) if provider else ()),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def replace_provider(self, provider, models):
        payloads = [m.to_dict() if isinstance(m, ModelMetadata) else dict(m) for m in models]
        with self.connection() as conn:
            conn.execute('DELETE FROM models WHERE provider=?', (provider,))
            conn.executemany(
                'INSERT INTO models VALUES(?,?,?)',
                [(
                    item.get('provider', provider),
                    item['model_id'],
                    json.dumps(item, sort_keys=True),
                ) for item in payloads],
            )

    def set_provider_health(self, provider: str, health_status: str) -> None:
        """Keep cached discovery rows from advertising stale provider health."""
        with self.connection() as conn:
            rows = conn.execute(
                'SELECT model_id, metadata FROM models WHERE provider=?', (provider,)
            ).fetchall()
            for model_id, raw_metadata in rows:
                metadata = json.loads(raw_metadata)
                metadata['health_status'] = health_status
                if health_status != 'healthy':
                    metadata['availability'] = health_status
                conn.execute(
                    'UPDATE models SET metadata=? WHERE provider=? AND model_id=?',
                    (json.dumps(metadata, sort_keys=True), provider, model_id),
                )

    def installed_local_packages(self) -> list[dict]:
        return [item for item in self.list('local') if item.get('installed') is True]
