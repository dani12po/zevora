import json, sqlite3
from pathlib import Path
from .metadata import ModelMetadata

class ModelRegistry:
    def __init__(self,database:Path):
        database.parent.mkdir(parents=True,exist_ok=True); self.database=database
        with self.connection() as conn: conn.execute('CREATE TABLE IF NOT EXISTS models (provider TEXT, model_id TEXT, metadata TEXT NOT NULL, PRIMARY KEY(provider,model_id))')
    def connection(self): return sqlite3.connect(self.database)
    def upsert(self,model:ModelMetadata):
        with self.connection() as conn: conn.execute('INSERT OR REPLACE INTO models VALUES(?,?,?)',(model.provider,model.model_id,json.dumps(model.to_dict())))
    def list(self,provider=None):
        with self.connection() as conn:
            rows=conn.execute('SELECT metadata FROM models'+(' WHERE provider=?' if provider else ''),((provider,) if provider else ())).fetchall()
        return [json.loads(row[0]) for row in rows]
    def replace_provider(self,provider,models):
        with self.connection() as conn:
            conn.execute('DELETE FROM models WHERE provider=?',(provider,))
            conn.executemany('INSERT INTO models VALUES(?,?,?)',[(m.provider,m.model_id,json.dumps(m.to_dict())) for m in models])
