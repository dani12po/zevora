"""Controlled evolution pipeline over compact structured experiences."""
from datetime import datetime, timezone
import json
import sqlite3

from ..config import settings
from ..memory.store import Store
from ..skills.registry import Skill, SkillRegistry
from .evaluator import evaluate_outcome
from .pattern_extractor import extract_pattern


class EvolutionEngine:
    def __init__(self, store: Store, skills: SkillRegistry):
        self.store = store
        self.skills = skills
        with self.store.connection() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS evolution_patterns(
                content_hash TEXT PRIMARY KEY, pattern_json TEXT NOT NULL,
                observations INTEGER NOT NULL DEFAULT 1, successes INTEGER NOT NULL DEFAULT 0,
                failures INTEGER NOT NULL DEFAULT 0, confidence REAL NOT NULL DEFAULT .5,
                status TEXT NOT NULL DEFAULT 'candidate', created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL)''')

    def observe(self, experience: dict, quality_score: float) -> dict:
        """Record a compact pattern and evaluate it; raw task content is never accepted."""
        pattern = extract_pattern(experience)
        now = datetime.now(timezone.utc).isoformat()
        success = pattern['result'] == 'success'
        with self.store.connection() as conn:
            row = conn.execute(
                'SELECT observations,successes,failures FROM evolution_patterns WHERE content_hash=?',
                (pattern['content_hash'],),
            ).fetchone()
            observations = int(row['observations']) + 1 if row else 1
            successes = int(row['successes']) + int(success) if row else int(success)
            failures = int(row['failures']) + int(not success) if row else int(not success)
            evaluation = evaluate_outcome(
                success=success,
                verified=pattern['verified'],
                quality_score=float(quality_score),
                observations=observations,
                min_quality=settings.evolution_min_confidence,
            )
            status = 'validated' if evaluation.accepted else 'candidate'
            conn.execute('''INSERT OR REPLACE INTO evolution_patterns(
                content_hash,pattern_json,observations,successes,failures,confidence,status,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?)''', (
                pattern['content_hash'], json.dumps(pattern, sort_keys=True), observations,
                successes, failures, evaluation.confidence, status,
                row['created_at'] if row and 'created_at' in row.keys() else now, now,
            ))
        return {
            'pattern_hash': pattern['content_hash'], 'observations': observations,
            'status': status, 'confidence': evaluation.confidence,
            'reasons': list(evaluation.reasons),
        }

    def build_skill_candidate(self, pattern_hash: str) -> Skill:
        with self.store.connection() as conn:
            row = conn.execute(
                'SELECT * FROM evolution_patterns WHERE content_hash=?', (pattern_hash,)
            ).fetchone()
        if not row or row['status'] != 'validated':
            raise ValueError('only validated patterns can become skill candidates')
        pattern = json.loads(row['pattern_json'])
        skill_id = f"evolved-{pattern['task_class']}-{pattern_hash[:10]}"
        return Skill(
            skill_id=skill_id,
            name=f"Validated {pattern['task_class']} pattern",
            version='0.1.0',
            description='Candidate derived from repeated verified outcomes.',
            capabilities=(pattern['task_class'],),
            instructions=(
                f"Use the verified {pattern['task_class']} route pattern. "
                "All tool calls remain subject to MCP permission and approval policy."
            ),
            tool_requirements=(),
            confidence=float(row['confidence']),
            source='evolution',
            trust_state='untrusted',
        ).normalized()

    def register_validated_skill(self, candidate: Skill, *, approved: bool = False) -> Skill:
        if not approved or candidate.source != 'evolution':
            raise PermissionError('evolved skills require explicit validation approval')
        verified = Skill(**{**candidate.to_dict(), 'trust_state': 'verified'}).normalized()
        return self.skills.register(verified, replace=True)

    def create_training_candidate(self, pattern_hash: str) -> str:
        """Create a future dataset candidate; this never mutates model weights."""
        with self.store.connection() as conn:
            row = conn.execute(
                'SELECT pattern_json,status FROM evolution_patterns WHERE content_hash=?',
                (pattern_hash,),
            ).fetchone()
            if not row or row['status'] != 'validated':
                raise ValueError('training candidates require a validated pattern')
            now = datetime.now(timezone.utc).isoformat()
            conn.execute('''INSERT OR IGNORE INTO training_candidates(
                candidate_type,payload_json,content_hash,privacy_status,evaluation_status,created_at,updated_at)
                VALUES('validated_pattern',?,?, 'pending','validated',?,?)''',
                (row['pattern_json'], pattern_hash, now, now),
            )
        return pattern_hash

    def status(self) -> dict:
        with self.store.connection() as conn:
            counts = {}
            for table in ('structured_experiences', 'evolution_patterns', 'training_candidates'):
                counts[table] = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            counts['validated_patterns'] = conn.execute(
                "SELECT COUNT(*) FROM evolution_patterns WHERE status='validated'"
            ).fetchone()[0]
        return {
            'enabled': settings.evolution_enabled,
            'knowledge_evolution': 'enabled' if settings.evolution_enabled else 'disabled',
            'skill_evolution': 'validation_required',
            'model_evolution': 'dataset_candidates_only',
            **counts,
        }
