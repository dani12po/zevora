"""Consent-aware, pre-sanitized collective contribution queue."""
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from ..config import settings
from ..memory.store import Store
from .registry import CollectiveRegistry
from .sanitizer import sanitize


CONSENT_SETTINGS = {
    'skill': 'collective_consent_skills',
    'knowledge': 'collective_consent_knowledge',
    'routing': 'collective_consent_routing',
    'evaluation': 'collective_consent_evaluation',
}


class ContributionQueue:
    def __init__(self, store: Store):
        self.store = store

    def enqueue(self, contribution_type: str, payload: dict[str, Any]) -> dict:
        consent_setting = CONSENT_SETTINGS.get(contribution_type)
        if not settings.collective_learning_enabled:
            return {'accepted': False, 'reason': 'collective_learning_disabled'}
        if not consent_setting or not bool(getattr(settings, consent_setting, False)):
            return {'accepted': False, 'reason': 'consent_required'}
        result = sanitize(contribution_type, payload)
        if not result.accepted or result.payload is None:
            return {'accepted': False, 'reason': ','.join(result.reasons) or 'sanitization_rejected'}
        serialized = json.dumps(result.payload, sort_keys=True, separators=(',', ':'))
        digest = hashlib.sha256(serialized.encode()).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        with self.store.connection() as conn:
            conn.execute('''INSERT OR IGNORE INTO contribution_queue(
                contribution_type,payload_json,content_hash,consent_scope,status,
                rejection_reason,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)''',
                (contribution_type, serialized, digest, consent_setting, 'sanitized', None, now, now),
            )
        return {'accepted': True, 'content_hash': digest, 'status': 'sanitized'}

    def pending(self) -> list[dict]:
        with self.store.connection() as conn:
            rows = conn.execute(
                "SELECT id,contribution_type,payload_json,content_hash FROM contribution_queue WHERE status='sanitized' ORDER BY id"
            ).fetchall()
        return [{
            'id': row['id'], 'type': row['contribution_type'],
            'payload': json.loads(row['payload_json']), 'content_hash': row['content_hash'],
        } for row in rows]

    async def publish(self, registry: CollectiveRegistry, *, approved: bool = False) -> dict:
        """Upload requires an explicit caller approval even after stored consent."""
        if not approved:
            raise PermissionError('publishing contributions requires explicit approval')
        pending = self.pending()
        if not pending:
            return {'published': 0, 'registry': 'none'}
        result = await registry.publish([
            {'type': item['type'], 'payload': item['payload'], 'content_hash': item['content_hash']}
            for item in pending
        ])
        now = datetime.now(timezone.utc).isoformat()
        with self.store.connection() as conn:
            conn.executemany(
                "UPDATE contribution_queue SET status='published',updated_at=? WHERE id=?",
                [(now, item['id']) for item in pending],
            )
        return result

    def status(self) -> dict:
        with self.store.connection() as conn:
            rows = conn.execute('SELECT status,COUNT(*) count FROM contribution_queue GROUP BY status').fetchall()
        return {
            'enabled': settings.collective_learning_enabled,
            'consent': {key: bool(getattr(settings, value, False)) for key, value in CONSENT_SETTINGS.items()},
            'queue': {row['status']: row['count'] for row in rows},
            'silent_uploads': False,
        }
