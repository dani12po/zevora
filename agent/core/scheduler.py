"""Persistent scheduled tasks for ZEVORA — cron-like automation in SQLite.
"""
from __future__ import annotations

import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

SCHEDULE_KINDS = ('once', 'daily', 'weekly', 'interval')
MAX_TASKS = 200
MAX_RESULT_CHARS = 4_000
_WEEKDAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


class ScheduledTaskStore:
    """SQLite-backed CRUD plus run history for scheduled tasks."""

    def __init__(self, database: Path):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    schedule_kind TEXT NOT NULL,
                    schedule_value TEXT NOT NULL DEFAULT '',
                    project_path TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    next_run_at TEXT,
                    last_run_at TEXT,
                    last_status TEXT NOT NULL DEFAULT '',
                    last_result TEXT NOT NULL DEFAULT '',
                    run_count INTEGER NOT NULL DEFAULT 0
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS scheduled_task_runs (
                    id INTEGER PRIMARY KEY,
                    task_id INTEGER NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    result TEXT NOT NULL DEFAULT ''
                )
            ''')

    def connection(self):
        conn = sqlite3.connect(self.database, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _row_to_task(self, row: sqlite3.Row) -> dict[str, Any]:
        task = dict(row)
        task['enabled'] = bool(task['enabled'])
        return task

    def list_tasks(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                'SELECT * FROM scheduled_tasks ORDER BY created_at DESC LIMIT ?',
                (MAX_TASKS,),
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                'SELECT * FROM scheduled_tasks WHERE id=?', (task_id,)
            ).fetchone()
        return self._row_to_task(row) if row else None

    def create_task(
        self, name: str, prompt: str, schedule_kind: str,
        schedule_value: str = '', project_path: str = '',
    ) -> dict[str, Any]:
        if schedule_kind not in SCHEDULE_KINDS:
            raise ValueError(f'schedule_kind must be one of {SCHEDULE_KINDS}')
        if not name.strip() or not prompt.strip():
            raise ValueError('name and prompt are required')
        if schedule_kind in ('daily', 'weekly') and not re.fullmatch(
            r'(\d{2}:\d{2}|[a-z]{3}:\d{2}:\d{2})', schedule_value or ''
        ):
            raise ValueError(
                'schedule_value must be HH:MM for daily, DDD:HH:MM for weekly (UTC)'
            )
        if schedule_kind == 'interval':
            minutes = int(schedule_value or 0)
            if minutes < 5 or minutes > 10_080:
                raise ValueError('interval minutes must be between 5 and 10080')
        now = _now().isoformat()
        with self.connection() as conn:
            count = conn.execute('SELECT COUNT(*) FROM scheduled_tasks').fetchone()[0]
            if count >= MAX_TASKS:
                raise ValueError(f'task limit reached ({MAX_TASKS})')
            cursor = conn.execute(
                '''INSERT INTO scheduled_tasks
                   (name,prompt,schedule_kind,schedule_value,project_path,
                    enabled,created_at,next_run_at)
                   VALUES(?,?,?,?,?,1,?,?)''',
                (
                    name.strip()[:200], prompt.strip()[:8_000], schedule_kind,
                    schedule_value, project_path, now,
                    self.compute_next_run(schedule_kind, schedule_value, None),
                ),
            )
            task_id = cursor.lastrowid
        if task_id is None:
            raise ValueError('failed to create task')
        return self.get_task(task_id)

    def update_task(self, task_id: int, **fields) -> dict[str, Any] | None:
        allowed = {'name', 'prompt', 'schedule_kind', 'schedule_value',
                   'project_path', 'enabled'}
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return self.get_task(task_id)
        if 'schedule_kind' in updates or 'schedule_value' in updates:
            current = self.get_task(task_id)
            if not current:
                return None
            kind = updates.get('schedule_kind', current['schedule_kind'])
            value = updates.get('schedule_value', current['schedule_value'])
            updates['next_run_at'] = self.compute_next_run(kind, value, None)
        set_clause = ', '.join(f'{key}=?' for key in updates)
        with self.connection() as conn:
            conn.execute(
                f'UPDATE scheduled_tasks SET {set_clause} WHERE id=?',
                (*updates.values(), task_id),
            )
        return self.get_task(task_id)

    def delete_task(self, task_id: int) -> bool:
        with self.connection() as conn:
            cursor = conn.execute('DELETE FROM scheduled_tasks WHERE id=?', (task_id,))
            conn.execute('DELETE FROM scheduled_task_runs WHERE task_id=?', (task_id,))
            return cursor.rowcount > 0

    def run_history(self, task_id: int, limit: int = 20) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                '''SELECT * FROM scheduled_task_runs WHERE task_id=?
                   ORDER BY started_at DESC LIMIT ?''',
                (task_id, max(1, min(int(limit), 100))),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_run(
        self, task_id: int, status: str, result: str,
        started_at: str, finished_at: str | None = None,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                '''INSERT INTO scheduled_task_runs (task_id,started_at,finished_at,status,result)
                   VALUES(?,?,?,?,?)''',
                (task_id, started_at, finished_at, status, result[:MAX_RESULT_CHARS]),
            )
            conn.execute(
                '''UPDATE scheduled_tasks SET last_run_at=?, last_status=?,
                   last_result=?, run_count=run_count+1 WHERE id=?''',
                (started_at, status, result[:MAX_RESULT_CHARS], task_id),
            )

    def due_tasks(self) -> list[dict[str, Any]]:
        now_iso = _now().isoformat()
        with self.connection() as conn:
            rows = conn.execute(
                '''SELECT * FROM scheduled_tasks
                   WHERE enabled=1 AND next_run_at IS NOT NULL AND next_run_at<=?''',
                (now_iso,),
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def mark_fired(self, task_id: int) -> None:
        task = self.get_task(task_id)
        if not task:
            return
        next_run = self.compute_next_run(
            task['schedule_kind'], task['schedule_value'], task['next_run_at'],
        )
        with self.connection() as conn:
            conn.execute(
                'UPDATE scheduled_tasks SET next_run_at=? WHERE id=?',
                (next_run, task_id),
            )

    @staticmethod
    def compute_next_run(
        kind: str, value: str, previous: str | None,
    ) -> str | None:
        now = _now()
        if kind == 'once':
            if previous:
                return None  # already fired; do not repeat
            target = _parse_iso(value) if value else None
            return (target or now).isoformat()
        if kind == 'interval':
            minutes = int(value or 30)
            return (now + timedelta(minutes=minutes)).isoformat()
        if kind == 'daily':
            hour, minute = (int(part) for part in (value or '09:00').split(':'))
            candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= now:
                candidate += timedelta(days=1)
            return candidate.isoformat()
        if kind == 'weekly':
            # value format: DDD:HH:MM where DDD is 3-letter weekday (UTC)
            try:
                weekday_token, clock = value.split(':', 1)
                hour, minute = (int(part) for part in clock.split(':'))
                weekday = _WEEKDAYS.index(weekday_token.lower())
            except (ValueError, AttributeError):
                weekday, hour, minute = 0, 9, 0
            candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            days_ahead = (weekday - candidate.weekday()) % 7
            if days_ahead == 0 and candidate <= now:
                days_ahead = 7
            candidate += timedelta(days=days_ahead)
            return candidate.isoformat()
        return None


class TaskScheduler:
    """Background thread that fires due tasks through a runner callback."""

    def __init__(self, store: ScheduledTaskStore, runner: Callable[[dict], str],
                 poll_seconds: int = 30):
        self.store = store
        self.runner = runner
        self.poll_seconds = max(10, int(poll_seconds))
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name='zevora-scheduler')
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.poll_seconds):
            try:
                self.tick()
            except Exception:
                continue  # never let the scheduler thread die

    def tick(self) -> list[dict[str, Any]]:
        fired = []
        for task in self.store.due_tasks():
            started = _now().isoformat()
            try:
                result = self.runner(task)
                self.store.record_run(task['id'], 'success', result, started,
                                      _now().isoformat())
            except Exception as error:
                self.store.record_run(task['id'], 'failed',
                                      f'{type(error).__name__}: {error}',
                                      started, _now().isoformat())
            self.store.mark_fired(task['id'])
            fired.append({'id': task['id'], 'name': task['name']})
        return fired
