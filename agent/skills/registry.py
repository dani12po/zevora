"""Versioned, on-demand Skill Registry with bounded untrusted content."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from ..config import settings


MAX_INSTRUCTIONS_CHARS = 8_000
MAX_EXAMPLES_CHARS = 4_000
MAX_CONTEXT_CHARS = 12_000


@dataclass(frozen=True)
class Skill:
    skill_id: str
    name: str
    version: str = '1.0.0'
    description: str = ''
    capabilities: tuple[str, ...] = ()
    instructions: str = ''
    examples: tuple[str, ...] = ()
    tool_requirements: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    confidence: float = .5
    usage_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    source: str = 'local'
    trust_state: str = 'trusted'
    content_hash: str = ''
    created_at: str = ''
    updated_at: str = ''

    def normalized(self) -> 'Skill':
        instructions = self.instructions.strip()[:MAX_INSTRUCTIONS_CHARS]
        examples = tuple(str(item).strip()[:MAX_EXAMPLES_CHARS] for item in self.examples if str(item).strip())
        payload = {
            'skill_id': self.skill_id.strip(), 'name': self.name.strip(), 'version': self.version.strip(),
            'description': self.description.strip(), 'capabilities': sorted(set(self.capabilities)),
            'instructions': instructions, 'examples': examples,
            'tool_requirements': sorted(set(self.tool_requirements)),
            'dependencies': sorted(set(self.dependencies)), 'source': self.source.strip() or 'local',
            'trust_state': self.trust_state if self.trust_state in {'untrusted', 'verified', 'trusted', 'rejected'} else 'untrusted',
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=list).encode()).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        return Skill(
            **payload, confidence=max(0.0, min(1.0, float(self.confidence))),
            usage_count=max(0, int(self.usage_count)), success_count=max(0, int(self.success_count)),
            failure_count=max(0, int(self.failure_count)), content_hash=self.content_hash or digest,
            created_at=self.created_at or now, updated_at=now,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self.normalized())


@dataclass(frozen=True)
class SkillMatch:
    skill: Skill
    score: float


class SkillRegistry:
    def __init__(self, database: Path | None = None):
        self.database = database or settings.skill_registry_file
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS skills(
                skill_id TEXT PRIMARY KEY, name TEXT NOT NULL, version TEXT NOT NULL,
                payload_json TEXT NOT NULL, confidence REAL NOT NULL DEFAULT .5,
                usage_count INTEGER NOT NULL DEFAULT 0, success_count INTEGER NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL, content_hash TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')

    def connection(self):
        conn = sqlite3.connect(self.database)
        conn.row_factory = sqlite3.Row
        return conn

    def register(self, skill: Skill, *, replace: bool = False) -> Skill:
        normalized = skill.normalized()
        with self.connection() as conn:
            if not replace and conn.execute('SELECT 1 FROM skills WHERE skill_id=?', (normalized.skill_id,)).fetchone():
                raise ValueError(f'skill already exists: {normalized.skill_id}')
            conn.execute('''INSERT OR REPLACE INTO skills(
                skill_id,name,version,payload_json,confidence,usage_count,success_count,
                failure_count,source,content_hash,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''', (
                normalized.skill_id, normalized.name, normalized.version,
                json.dumps(normalized.to_dict(), sort_keys=True), normalized.confidence,
                normalized.usage_count, normalized.success_count, normalized.failure_count,
                normalized.source, normalized.content_hash, normalized.created_at, normalized.updated_at,
            ))
        return normalized

    def get(self, skill_id: str) -> Skill | None:
        with self.connection() as conn:
            row = conn.execute('SELECT payload_json FROM skills WHERE skill_id=?', (skill_id,)).fetchone()
        return self._decode(row['payload_json']) if row else None

    def list(self, source: str | None = None) -> list[Skill]:
        query = 'SELECT payload_json FROM skills'
        args: tuple = ()
        if source:
            query += ' WHERE source=?'
            args = (source,)
        query += ' ORDER BY name, version'
        with self.connection() as conn:
            rows = conn.execute(query, args).fetchall()
        return [self._decode(row['payload_json']) for row in rows]

    def match(self, prompt: str, *, capabilities: set[str] | None = None, limit: int = 3) -> list[SkillMatch]:
        terms = set(re.findall(r'\w+', prompt.lower()))
        matches = []
        for skill in self.list():
            if skill.trust_state not in {'trusted', 'verified'}:
                continue
            skill_terms = set(re.findall(r'\w+', f'{skill.name} {skill.description} {" ".join(skill.capabilities)}'.lower()))
            overlap = len(terms & skill_terms)
            capability_bonus = len((capabilities or set()) & set(skill.capabilities)) * 0.5
            score = overlap + capability_bonus + skill.confidence * .1
            if score > 0:
                matches.append(SkillMatch(skill, score))
        return sorted(matches, key=lambda item: (-item.score, item.skill.skill_id))[:max(1, min(limit, 10))]

    def context_for(self, prompt: str, *, capabilities: set[str] | None = None, max_chars: int = MAX_CONTEXT_CHARS) -> tuple[str, list[str]]:
        selected = []
        used = []
        remaining = max(0, min(max_chars, MAX_CONTEXT_CHARS))
        for match in self.match(prompt, capabilities=capabilities):
            skill = match.skill
            block = f'Skill {skill.skill_id} v{skill.version}: {skill.instructions}'[:remaining]
            if not block.strip():
                continue
            selected.append(block)
            used.append(skill.skill_id)
            remaining -= len(block) + 2
            if remaining <= 0:
                break
            self._increment_usage(skill.skill_id)
        return '\n\n'.join(selected), used

    def record_result(self, skill_id: str, success: bool, confidence_delta: float = .02) -> None:
        with self.connection() as conn:
            row = conn.execute('SELECT confidence,success_count,failure_count,usage_count FROM skills WHERE skill_id=?', (skill_id,)).fetchone()
            if not row:
                return
            confidence = max(0.0, min(1.0, float(row['confidence']) + (confidence_delta if success else -confidence_delta)))
            conn.execute('''UPDATE skills SET confidence=?, usage_count=?, success_count=?, failure_count=?, updated_at=? WHERE skill_id=?''', (
                confidence, row['usage_count'] + 1, row['success_count'] + int(success),
                row['failure_count'] + int(not success), datetime.now(timezone.utc).isoformat(), skill_id,
            ))

    def _increment_usage(self, skill_id: str) -> None:
        with self.connection() as conn:
            conn.execute('UPDATE skills SET usage_count=usage_count+1, updated_at=? WHERE skill_id=?', (datetime.now(timezone.utc).isoformat(), skill_id))

    @staticmethod
    def _decode(payload: str) -> Skill:
        data = json.loads(payload)
        data['capabilities'] = tuple(data.get('capabilities', []))
        data['examples'] = tuple(data.get('examples', []))
        data['tool_requirements'] = tuple(data.get('tool_requirements', []))
        data['dependencies'] = tuple(data.get('dependencies', []))
        data['content_hash'] = data.get('content_hash', '')
        return Skill(**data).normalized()
