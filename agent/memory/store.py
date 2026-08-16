import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

class Store:
    def __init__(self, database: Path):
        database.parent.mkdir(parents=True, exist_ok=True)
        self.database = database
        self.initialize()

    def connection(self):
        conn = sqlite3.connect(self.database)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self):
        with self.connection() as conn:
            conn.executescript('''
            CREATE TABLE IF NOT EXISTS memories (
              id INTEGER PRIMARY KEY, kind TEXT NOT NULL, content TEXT NOT NULL,
              project TEXT, task_type TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS exact_cache (
              key TEXT PRIMARY KEY, prompt TEXT NOT NULL, response TEXT NOT NULL,
              provider TEXT NOT NULL, model TEXT NOT NULL, task_type TEXT,
              project TEXT, context_hash TEXT, quality_score REAL DEFAULT 1,
              expires_at TEXT, created_at TEXT NOT NULL, last_accessed TEXT,
              size_bytes INTEGER DEFAULT 0, hit_count INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS usage_events (
              id INTEGER PRIMARY KEY, provider TEXT, model TEXT, task_type TEXT,
              input_tokens INTEGER, output_tokens INTEGER, estimated_cost REAL,
              cache_hit INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS project_files (
              id INTEGER PRIMARY KEY, project TEXT NOT NULL, path TEXT NOT NULL,
              language TEXT, summary TEXT, content_hash TEXT, size_bytes INTEGER DEFAULT 0,
              search_text TEXT, indexed_at TEXT NOT NULL,
              UNIQUE(project, path)
            );
            CREATE TABLE IF NOT EXISTS experiences (
              id INTEGER PRIMARY KEY, task TEXT, provider TEXT, model TEXT, outcome TEXT,
              execution_ms INTEGER, metadata_json TEXT, created_at TEXT NOT NULL
            );''')
            conn.execute('''CREATE TABLE IF NOT EXISTS routing_experiences (
                id INTEGER PRIMARY KEY, route TEXT, provider TEXT, model TEXT, task_type TEXT,
                success INTEGER, quality_score REAL, latency_ms INTEGER, tool_usage TEXT, created_at TEXT NOT NULL)''')
            conn.executescript('''
            CREATE TABLE IF NOT EXISTS schema_meta (
              key TEXT PRIMARY KEY, value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memory_records (
              id INTEGER PRIMARY KEY, scope TEXT NOT NULL, content TEXT NOT NULL,
              content_hash TEXT NOT NULL, project TEXT, task_type TEXT,
              confidence REAL DEFAULT 0.5, importance REAL DEFAULT 0.5,
              usage_count INTEGER DEFAULT 0, created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL, UNIQUE(scope, content_hash, project)
            );
            CREATE TABLE IF NOT EXISTS structured_experiences (
              id INTEGER PRIMARY KEY, task_class TEXT NOT NULL, route TEXT,
              result TEXT NOT NULL, provider TEXT, model TEXT, skill_ids TEXT,
              confidence REAL DEFAULT 0.5, execution_time_ms INTEGER,
              reuse_count INTEGER DEFAULT 0, verified INTEGER DEFAULT 0,
              content_hash TEXT UNIQUE, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS context_metrics (
              id INTEGER PRIMARY KEY, task_type TEXT, provider TEXT, model TEXT,
              estimated_context_tokens INTEGER DEFAULT 0,
              compressed_tokens INTEGER DEFAULT 0, removed_tokens INTEGER DEFAULT 0,
              provider_tokens INTEGER DEFAULT 0, cache_saved_tokens INTEGER DEFAULT 0,
              context_hash TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS contribution_queue (
              id INTEGER PRIMARY KEY, contribution_type TEXT NOT NULL,
              payload_json TEXT NOT NULL, content_hash TEXT UNIQUE,
              consent_scope TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
              rejection_reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS training_candidates (
              id INTEGER PRIMARY KEY, candidate_type TEXT NOT NULL,
              payload_json TEXT NOT NULL, content_hash TEXT UNIQUE,
              privacy_status TEXT NOT NULL DEFAULT 'pending',
              evaluation_status TEXT NOT NULL DEFAULT 'pending',
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            ''')
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta(key,value) VALUES('store_schema_version','2')"
            )
            for table, columns in (
                ('exact_cache', [('last_accessed','TEXT'),('size_bytes','INTEGER DEFAULT 0'),('hit_count','INTEGER DEFAULT 0')]),
                ('project_files', [('content_hash','TEXT'),('size_bytes','INTEGER DEFAULT 0'),('search_text','TEXT')]),
            ):
                existing = {
                    row['name'] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()
                }
                for column, definition in columns:
                    if column not in existing:
                        conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')

    @staticmethod
    def key(prompt: str, context_hash: str = '') -> str:
        return hashlib.sha256((prompt + context_hash).encode()).hexdigest()

    def get_cache(self, prompt: str, context_hash: str = ''):
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            row=conn.execute('SELECT * FROM exact_cache WHERE key=? AND (expires_at IS NULL OR expires_at>?)', (self.key(prompt, context_hash), now)).fetchone()
            if row: conn.execute('UPDATE exact_cache SET last_accessed=?, hit_count=hit_count+1 WHERE key=?',(now,self.key(prompt, context_hash)))
            return row

    def put_cache(self, prompt, response, provider, model, task_type, project=None, context_hash='', ttl_hours=24):
        expires = datetime.fromtimestamp(datetime.now().timestamp() + ttl_hours * 3600, timezone.utc).isoformat()
        with self.connection() as conn:
            now=datetime.now(timezone.utc).isoformat()
            conn.execute('''INSERT OR REPLACE INTO exact_cache
                (key,prompt,response,provider,model,task_type,project,context_hash,quality_score,expires_at,created_at,last_accessed,size_bytes,hit_count)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (self.key(prompt, context_hash), prompt, response, provider, model, task_type, project, context_hash, 1, expires, now, now, len(response.encode()), 0))

    def replace_project_files(self, project: str, rows: list[dict]):
        """Atomically replace an index so deleted files cannot remain searchable."""
        with self.connection() as conn:
            conn.execute('DELETE FROM project_files WHERE project=?', (project,))
            conn.executemany(
                '''INSERT INTO project_files
                   (project,path,language,summary,content_hash,size_bytes,search_text,indexed_at)
                   VALUES(?,?,?,?,?,?,?,?)''',
                [(
                    project, row['path'], row['language'], row['summary'],
                    row.get('content_hash', ''), row.get('size_bytes', 0),
                    row.get('search_text', ''), row['indexed_at'],
                ) for row in rows],
            )

    def project_files(self, project: str) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                'SELECT * FROM project_files WHERE project=? ORDER BY path', (project,)
            ).fetchall()
        return [dict(row) for row in rows]

    def add_memory(self, kind, content, project=None, task_type=None):
        with self.connection() as conn:
            conn.execute('INSERT INTO memories(kind,content,project,task_type,created_at) VALUES(?,?,?,?,?)', (kind, content, project, task_type, datetime.now(timezone.utc).isoformat()))

    def search_memory(self, query, project=None, limit=5):
        sql = 'SELECT * FROM memories WHERE content LIKE ?'
        args = [f'%{query[:80]}%']
        if project:
            sql += ' AND project=?'; args.append(project)
        sql += ' ORDER BY id DESC LIMIT ?'; args.append(limit)
        with self.connection() as conn: return conn.execute(sql, args).fetchall()

    def usage(self):
        with self.connection() as conn:
            return dict(conn.execute('''SELECT COUNT(*) requests, COALESCE(SUM(cache_hit),0) cache_hits,
                COALESCE(SUM(estimated_cost),0) estimated_cost FROM usage_events
                WHERE date(created_at)=date('now')''').fetchone())
    def memory_categories(self):
        with self.connection() as conn:
            rows=conn.execute('SELECT kind, COUNT(*) count FROM memories GROUP BY kind').fetchall()
        result={'conversation':0,'project':0,'experience':0,'preferences':0}
        result.update({row['kind']:row['count'] for row in rows})
        return result
    def add_context_metrics(self, task_type, provider, model, metrics):
        """Persist counts and hashes only; never persist the context payload."""
        with self.connection() as conn:
            conn.execute(
                '''INSERT INTO context_metrics(
                   task_type,provider,model,estimated_context_tokens,compressed_tokens,
                   removed_tokens,provider_tokens,cache_saved_tokens,context_hash,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,datetime('now'))''',
                (
                    task_type, provider, model,
                    int(metrics.get('estimated_context_tokens', 0)),
                    int(metrics.get('compressed_tokens', 0)),
                    int(metrics.get('removed_tokens', 0)),
                    int(metrics.get('provider_tokens', 0)),
                    int(metrics.get('cache_saved_tokens', 0)),
                    str(metrics.get('context_hash', '')),
                ),
            )

    def add_structured_experience(self, record: dict):
        """Store a compact task outcome, never a full prompt or conversation."""
        import json
        normalized = {
            'task_class': str(record.get('task_class') or 'unknown'),
            'route': str(record.get('route') or ''),
            'result': str(record.get('result') or 'unknown'),
            'provider': str(record.get('provider') or ''),
            'model': str(record.get('model') or ''),
            'skill_ids': sorted(set(record.get('skill_ids') or [])),
            'confidence': float(record.get('confidence', .5)),
            'execution_time_ms': int(record.get('execution_time_ms') or 0),
            'verified': bool(record.get('verified', False)),
        }
        digest = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()
        with self.connection() as conn:
            conn.execute(
                '''INSERT OR IGNORE INTO structured_experiences(
                   task_class,route,result,provider,model,skill_ids,confidence,
                   execution_time_ms,reuse_count,verified,content_hash,created_at)
                   VALUES(?,?,?,?,?,?,?,?,0,?,?,datetime('now'))''',
                (
                    normalized['task_class'], normalized['route'], normalized['result'],
                    normalized['provider'], normalized['model'], json.dumps(normalized['skill_ids']),
                    normalized['confidence'], normalized['execution_time_ms'],
                    int(normalized['verified']), digest,
                ),
            )
        return digest

    def add_routing_experience(self,route,provider,model,task_type,success,quality_score,latency_ms,tool_usage):
        with self.connection() as conn: conn.execute("INSERT INTO routing_experiences(route,provider,model,task_type,success,quality_score,latency_ms,tool_usage,created_at) VALUES(?,?,?,?,?,?,?,?,datetime('now'))",(route,provider,model,task_type,int(success),quality_score,latency_ms,','.join(tool_usage)))

    def routing_performance(self, days: int = 30) -> dict[tuple[str, str], dict]:
        """Return bounded model/task performance used by adaptive routing."""
        with self.connection() as conn:
            rows = conn.execute(
                """SELECT provider,model,COUNT(*) attempts,
                          AVG(success) success_rate,AVG(quality_score) quality_score,
                          AVG(latency_ms) latency_ms
                   FROM routing_experiences
                   WHERE datetime(created_at) >= datetime('now', ?)
                   GROUP BY provider,model""",
                (f'-{max(1, min(days, 365))} days',),
            ).fetchall()
        return {
            (row['provider'], row['model']): {
                'attempts': row['attempts'],
                'success_rate': float(row['success_rate'] or 0),
                'quality_score': float(row['quality_score'] or 0),
                'latency_ms': float(row['latency_ms'] or 0),
            }
            for row in rows
        }

    def retention(self, dry_run: bool = True, memory_days: int = 90,
                  usage_days: int = 365, experience_days: int = 180) -> dict:
        """Plan or execute bounded retention for replaceable operational records."""
        predicates = {
            'exact_cache': "expires_at IS NOT NULL AND datetime(expires_at) <= datetime('now')",
            'memories': "kind='conversation' AND datetime(created_at) < datetime('now', ?)",
            'usage_events': "datetime(created_at) < datetime('now', ?)",
            'experiences': "datetime(created_at) < datetime('now', ?)",
            'routing_experiences': "datetime(created_at) < datetime('now', ?)",
        }
        args = {
            'exact_cache': (),
            'memories': (f'-{max(1, memory_days)} days',),
            'usage_events': (f'-{max(1, usage_days)} days',),
            'experiences': (f'-{max(1, experience_days)} days',),
            'routing_experiences': (f'-{max(1, experience_days)} days',),
        }
        counts = {}
        with self.connection() as conn:
            for table, predicate in predicates.items():
                count = conn.execute(
                    f'SELECT COUNT(*) count FROM {table} WHERE {predicate}', args[table]
                ).fetchone()['count']
                counts[table] = count
                if not dry_run and count:
                    conn.execute(f'DELETE FROM {table} WHERE {predicate}', args[table])
        return {'dry_run': dry_run, 'candidates': counts, 'total': sum(counts.values())}
