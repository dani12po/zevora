"""ZEVORA Local Intelligence Engine.

Consolidates Memory, Cache, Experience, Knowledge, and Retrieval into a
unified interface.  This module does NOT perform AI inference — it manages
the local data layer that reduces API calls and enriches context sent to
cloud providers.

Architecture (blueprint §5):
    Memory Engine      — short-term, long-term, project, experience, provider
    Cache Engine       — exact-match prompt cache with TTL + invalidation
    Experience Engine  — per-provider routing history
    Knowledge Engine   — compressed reusable solution patterns
    Retrieval Engine   — relevant memory + knowledge lookup for prompt context
    Routing Intel      — provider performance tracking
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class IntelligenceStats:
    """Snapshot returned by ``LocalIntelligenceEngine.stats()``."""
    memory_count: int
    knowledge_count: int
    experience_count: int
    cache_count: int
    cache_hit_rate: float
    api_calls_avoided: int
    total_api_calls: int


class LocalIntelligenceEngine:
    """Unified gateway to ZEVORA's local data layer.

    Parameters
    ----------
    db_path : Path
        Path to the main SQLite database (``data/database/agent.db``).
    """

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._ensure_tables()

    # ── connection helper ────────────────────────────────────────────────
    def connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ── schema ───────────────────────────────────────────────────────────
    def _ensure_tables(self):
        with self.connection() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS knowledge (
                id INTEGER PRIMARY KEY,
                task_type TEXT NOT NULL,
                context TEXT,
                problem TEXT NOT NULL,
                solution_pattern TEXT NOT NULL,
                provider TEXT,
                model TEXT,
                confidence REAL DEFAULT 0.5,
                importance REAL DEFAULT 0.5,
                normalized_hash TEXT,
                hit_count INTEGER DEFAULT 0,
                last_accessed TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(task_type, problem)
            );
            CREATE INDEX IF NOT EXISTS idx_knowledge_task ON knowledge(task_type);
            CREATE INDEX IF NOT EXISTS idx_knowledge_problem ON knowledge(problem);
            """)
            for column, definition in [
                ('importance', 'REAL DEFAULT 0.5'),
                ('normalized_hash', 'TEXT'),
                ('last_accessed', 'TEXT'),
            ]:
                try:
                    conn.execute(f'ALTER TABLE knowledge ADD COLUMN {column} {definition}')
                except sqlite3.OperationalError:
                    pass
            conn.execute(
                'CREATE INDEX IF NOT EXISTS idx_knowledge_normalized ON knowledge(normalized_hash)'
            )

    # ── Knowledge Extraction (blueprint §8) ──────────────────────────────
    def extract_knowledge(
        self,
        prompt: str,
        response: str,
        task_type: str,
        provider: str,
        model: str,
        project: str | None = None,
    ) -> dict | None:
        """Extract reusable knowledge from an API response.

        Instead of storing the full 10 000-token response, we extract:
        - problem (from prompt, max 200 chars)
        - solution_pattern (from response, max 500 chars)
        - context (project / task metadata)

        Returns the stored knowledge record, or None if extraction fails.
        """
        # Derive concise, normalized problem and solution records.
        problem = ' '.join(prompt[:200].split())
        solution_lines = [
            ln.strip() for ln in response.split('\n')
            if ln.strip() and not ln.strip().startswith('#')
        ]
        solution_pattern = '\n'.join(solution_lines[:10])[:500]

        if not problem or not solution_pattern:
            return None

        normalized = re.sub(r'[^a-z0-9]+', ' ', problem.lower()).strip()
        normalized_hash = hashlib.sha256(
            f'{task_type}:{project or ""}:{normalized}'.encode('utf-8')
        ).hexdigest()
        importance = min(1.0, round(
            0.35 + (0.15 if project else 0) +
            (0.15 if '`' in response else 0) + min(len(solution_pattern) / 2000, 0.25),
            2,
        ))
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            row = conn.execute(
                'SELECT * FROM knowledge WHERE normalized_hash=?', (normalized_hash,)
            ).fetchone()
            if row:
                conn.execute(
                    """UPDATE knowledge
                       SET solution_pattern=?, provider=?, model=?, importance=?,
                           updated_at=?, hit_count=hit_count+1
                       WHERE id=?""",
                    (solution_pattern, provider, model, importance, now, row['id']),
                )
            else:
                try:
                    conn.execute(
                        """INSERT INTO knowledge
                           (task_type, context, problem, solution_pattern,
                            provider, model, confidence, importance, normalized_hash,
                            hit_count, last_accessed, created_at, updated_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (task_type, project or '', problem, solution_pattern,
                         provider, model, 0.5, importance, normalized_hash,
                         0, now, now, now),
                    )
                except sqlite3.IntegrityError:
                    conn.execute(
                        """UPDATE knowledge
                           SET solution_pattern=?, provider=?, model=?, importance=?,
                               normalized_hash=?, updated_at=?, hit_count=hit_count+1
                           WHERE task_type=? AND problem=?""",
                        (solution_pattern, provider, model, importance,
                         normalized_hash, now, task_type, problem),
                    )
            row = conn.execute(
                'SELECT * FROM knowledge WHERE normalized_hash=? OR (task_type=? AND problem=?) ORDER BY id LIMIT 1',
                (normalized_hash, task_type, problem),
            ).fetchone()
        return dict(row) if row else None

    # ── Knowledge Retrieval (blueprint §12) ──────────────────────────────
    def retrieve_knowledge(
        self,
        query: str,
        task_type: str | None = None,
        limit: int = 5,
        project: str | None = None,
    ) -> list[dict]:
        """Rank bounded local records by term overlap, type, reuse, and project affinity."""
        query_terms = set(re.findall(r'[a-z0-9_./-]{2,}', query.lower()))
        if not query_terms:
            return []
        with self.connection() as conn:
            rows = conn.execute(
                'SELECT * FROM knowledge ORDER BY updated_at DESC LIMIT 250'
            ).fetchall()
            ranked: list[tuple[float, sqlite3.Row]] = []
            for row in rows:
                text_terms = set(re.findall(
                    r'[a-z0-9_./-]{2,}',
                    f"{row['problem']} {row['solution_pattern']}".lower(),
                ))
                overlap = len(query_terms & text_terms) / max(1, len(query_terms))
                if overlap == 0:
                    continue
                score = overlap
                if task_type and row['task_type'] == task_type:
                    score += 0.2
                if project and row['context'] == project:
                    score += 0.25
                score += min(float(row['importance'] or 0.5), 1.0) * 0.1
                score += min(int(row['hit_count'] or 0), 20) * 0.005
                ranked.append((score, row))
            selected = [row for _, row in sorted(
                ranked, key=lambda item: (-item[0], -item[1]['id'])
            )[:limit]]
            now = datetime.now(timezone.utc).isoformat()
            for row in selected:
                conn.execute(
                    'UPDATE knowledge SET hit_count=hit_count+1,last_accessed=? WHERE id=?',
                    (now, row['id']),
                )
        results = [dict(row) for row in selected]
        for result in results:
            result['hit_count'] += 1
        return results

    # ── Stats (blueprint §20 — Local Intelligence page) ──────────────────
    def stats(self, store_db_path: Path | None = None) -> IntelligenceStats:
        """Aggregate statistics across all local intelligence tables.

        ``store_db_path`` should point to the main agent.db that contains
        ``memories``, ``exact_cache``, ``experiences``, and ``usage_events``.
        If the knowledge table is in the same DB the parameter can be None.
        """
        db = store_db_path or self.db_path
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row

            def _count(table: str) -> int:
                try:
                    return conn.execute(f'SELECT COUNT(*) c FROM {table}').fetchone()['c']
                except sqlite3.OperationalError:
                    return 0

            memory_count = _count('memories')
            knowledge_count = _count('knowledge')
            experience_count = _count('experiences')
            cache_count = _count('exact_cache')

            # Usage events for hit rate
            try:
                row = conn.execute(
                    "SELECT COUNT(*) total, COALESCE(SUM(cache_hit),0) hits "
                    "FROM usage_events"
                ).fetchone()
                total_api = row['total'] or 0
                cache_hits = row['hits'] or 0
            except sqlite3.OperationalError:
                total_api, cache_hits = 0, 0

            hit_rate = round(cache_hits / total_api * 100, 1) if total_api else 0.0

        return IntelligenceStats(
            memory_count=memory_count,
            knowledge_count=knowledge_count,
            experience_count=experience_count,
            cache_count=cache_count,
            cache_hit_rate=hit_rate,
            api_calls_avoided=cache_hits,
            total_api_calls=total_api,
        )

    # ── Context builder (blueprint §12 — Context Selection) ──────────────
    def build_context(
        self,
        prompt: str,
        task_type: str,
        project: str | None = None,
        store=None,
    ) -> str:
        """Build minimal enrichment context from local intelligence.

        Gathers: relevant knowledge + relevant memories.
        Returns a single string to inject into the system prompt.
        """
        parts: list[str] = []

        # Knowledge
        knowledge = self.retrieve_knowledge(prompt, task_type, limit=3, project=project)
        if knowledge:
            klines = []
            for k in knowledge:
                klines.append(f"- [{k['task_type']}] {k['problem'][:80]}: {k['solution_pattern'][:200]}")
            parts.append('Relevant knowledge:\n' + '\n'.join(klines))

        # Memory (via Store if available)
        if store is not None:
            memories = store.search_memory(prompt, project, limit=3)
            if memories:
                mlines = [f"- {m['content'][:150]}" for m in memories]
                parts.append('Relevant memory:\n' + '\n'.join(mlines))

        return '\n\n'.join(parts)

    def prune(self, knowledge_days: int = 180) -> dict:
        """Remove expired low-value intelligence while retaining reused knowledge."""
        with self.connection() as conn:
            cursor = conn.execute(
                """DELETE FROM knowledge
                   WHERE datetime(COALESCE(last_accessed, updated_at)) < datetime('now', ?)
                     AND COALESCE(hit_count, 0)=0
                     AND COALESCE(importance, 0.5) < 0.75""",
                (f'-{max(1, knowledge_days)} days',),
            )
            removed = cursor.rowcount
        return {'knowledge_removed': removed}
