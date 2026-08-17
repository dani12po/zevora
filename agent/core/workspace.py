"""Project-aware persistence and safe workspace metadata, never full-repo copies."""
import hashlib, json, sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from .project_index import index_project

class WorkspaceManager:
    def __init__(self,database:Path,allowed_root:Path|None=None):
        self.database=database; self.allowed_root=allowed_root; database.parent.mkdir(parents=True,exist_ok=True)
        with self.connection() as conn: conn.executescript('''CREATE TABLE IF NOT EXISTS workspace_projects (id INTEGER PRIMARY KEY, name TEXT, path TEXT UNIQUE, metadata TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS workspace_permissions (workspace_id INTEGER PRIMARY KEY, preferences TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS chats (id TEXT PRIMARY KEY, title TEXT, project_id INTEGER, created_at TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS chat_messages (id INTEGER PRIMARY KEY, chat_id TEXT, role TEXT, content TEXT, metadata TEXT, created_at TEXT);''')
    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.database, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA busy_timeout=30000')
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    def _safe(self,path):
        resolved=Path(path).resolve()
        if resolved.parent == resolved: raise ValueError('Select a project folder, not an entire drive')
        if self.allowed_root:
            root=self.allowed_root.resolve()
            if resolved!=root and root not in resolved.parents: raise ValueError(f'Workspace must be inside {root}')
        return resolved
    def _metadata(self,path):
        names={item.name.lower() for item in path.iterdir()}; manifests=[]; framework=[]
        for file,label in [('package.json','Node.js'),('pyproject.toml','Python'),('requirements.txt','Python'),('Cargo.toml','Rust'),('go.mod','Go')]:
            if file.lower() in names: manifests.append(file); framework.append(label)
        if 'next.config.js' in names or 'next.config.mjs' in names: framework.append('Next.js')
        if '.git' in names: framework.append('Git')
        return {'frameworks':framework,'manifests':manifests,'is_git':'.git' in names}
    def load(self,path):
        root=self._safe(path)
        if not root.is_dir(): raise ValueError('Project directory not found')
        meta=self._metadata(root); now=datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute('INSERT INTO workspace_projects(name,path,metadata,created_at,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET metadata=excluded.metadata,updated_at=excluded.updated_at',(root.name,str(root),json.dumps(meta),now,now))
            row=conn.execute('SELECT * FROM workspace_projects WHERE path=?',(str(root),)).fetchone()
        return self.project(row)
    def project(self,row):
        project = {**dict(row),'metadata':json.loads(row['metadata'] or '{}')}
        with self.connection() as conn:
            permission = conn.execute(
                'SELECT preferences FROM workspace_permissions WHERE workspace_id=?',
                (project['id'],),
            ).fetchone()
        project['permissions'] = json.loads(permission['preferences']) if permission else {
            'terminal': 'ask', 'git': 'ask', 'external_filesystem': 'ask',
        }
        return project

    def permissions(self, workspace_id: int) -> dict:
        project = self.get(workspace_id)
        if not project:
            raise ValueError('Project not found')
        return project['permissions']

    def set_permissions(self, workspace_id: int, preferences: dict) -> dict:
        allowed = {'terminal', 'git', 'external_filesystem'}
        values = {key: value for key, value in preferences.items() if key in allowed}
        valid = {'ask', 'deny', 'session', 'always'}
        if any(value not in valid for value in values.values()):
            raise ValueError('Invalid workspace permission preference')
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                '''INSERT INTO workspace_permissions(workspace_id,preferences,updated_at)
                   VALUES(?,?,?) ON CONFLICT(workspace_id) DO UPDATE SET
                   preferences=excluded.preferences,updated_at=excluded.updated_at''',
                (workspace_id, json.dumps(values), now),
            )
        return self.permissions(workspace_id)
    def projects(self):
        with self.connection() as conn:
            rows = conn.execute(
                'SELECT * FROM workspace_projects ORDER BY updated_at DESC'
            ).fetchall()
        return [
            self.project(row)
            for row in rows
            if Path(row['path']).is_dir()
        ]
    def get(self,id):
        with self.connection() as conn: row=conn.execute('SELECT * FROM workspace_projects WHERE id=?',(id,)).fetchone()
        return self.project(row) if row else None
    def audit(self,id):
        project=self.get(id)
        if not project: raise ValueError('Project not found')
        rows=index_project(Path(project['path'])); languages={row['language'] for row in rows if row['language']!='Unknown'}
        audit={'project_id':id,'files_indexed':len(rows),'languages':sorted(languages),'frameworks':project['metadata']['frameworks'],'health_score':max(0,100-min(35,len(rows)//100)),'findings':[],'incremental':False}
        return audit
    def create_chat(self,title='New chat',project_id=None):
        stamp=datetime.now(timezone.utc); chat_id='chat_'+hashlib.sha256(f'{stamp.timestamp()}:{title}'.encode()).hexdigest()[:12]
        with self.connection() as conn: conn.execute('INSERT INTO chats VALUES(?,?,?,?,?)',(chat_id,title,project_id,stamp.isoformat(),stamp.isoformat()))
        return self.get_chat(chat_id)
    def chats(self):
        with self.connection() as conn: return [dict(row) for row in conn.execute('SELECT * FROM chats ORDER BY updated_at DESC LIMIT 100')]
    def get_chat(self,id):
        with self.connection() as conn:
            chat=conn.execute('SELECT * FROM chats WHERE id=?',(id,)).fetchone(); messages=conn.execute('SELECT role,content,metadata,created_at FROM chat_messages WHERE chat_id=? ORDER BY id',(id,)).fetchall()
        return {**dict(chat),'messages':[dict(row) for row in messages]} if chat else None
    def add_message(self,chat_id,role,content,metadata=None):
        now=datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor=conn.execute('INSERT INTO chat_messages(chat_id,role,content,metadata,created_at) VALUES(?,?,?,?,?)',(chat_id,role,content,json.dumps(metadata or {}),now)); conn.execute('UPDATE chats SET updated_at=? WHERE id=?',(now,chat_id))
            return cursor.lastrowid
    def add_exchange(self,chat_id,user_content,assistant_content,metadata=None):
        """Persist a completed exchange atomically so failed requests leave no half-chat."""
        now=datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                'INSERT INTO chat_messages(chat_id,role,content,metadata,created_at) VALUES(?,?,?,?,?)',
                (chat_id,'user',user_content,'{}',now),
            )
            cursor=conn.execute(
                'INSERT INTO chat_messages(chat_id,role,content,metadata,created_at) VALUES(?,?,?,?,?)',
                (chat_id,'assistant',assistant_content,json.dumps(metadata or {}),now),
            )
            conn.execute('UPDATE chats SET updated_at=? WHERE id=?',(now,chat_id))
            return cursor.lastrowid
    def set_title(self,chat_id,title):
        with self.connection() as conn: conn.execute('UPDATE chats SET title=? WHERE id=?',(title[:80],chat_id))
