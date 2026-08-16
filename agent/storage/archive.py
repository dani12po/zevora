from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from .compression import compress_records

class ArchiveManager:
    def __init__(self, root: Path):
        self.root=root; self.index=root/'data'/'database'/'archive_index.db'; self.index.parent.mkdir(parents=True,exist_ok=True)
        with self.connection() as conn: conn.execute('CREATE TABLE IF NOT EXISTS archives (archive_id TEXT PRIMARY KEY, created_at TEXT, topic TEXT, project TEXT, record_count INTEGER, compressed_size INTEGER, original_size INTEGER, compression_ratio REAL, checksum TEXT, location TEXT)')
    def connection(self): return sqlite3.connect(self.index)
    def archive(self, records: list[dict], topic='experience', project=''):
        now=datetime.now(timezone.utc); target=self.root/'data'/'archive'/str(now.year)/f'{now.month:02d}'/f'{topic}_{now.date().isoformat()}'
        info=compress_records(records,target); archive_id=Path(info['path']).name
        with self.connection() as conn: conn.execute('INSERT OR REPLACE INTO archives VALUES(?,?,?,?,?,?,?,?,?,?)',(archive_id,now.isoformat(),topic,project,info['record_count'],info['compressed_size'],info['original_size'],info['compression_ratio'],info['checksum'],info['path']))
        return {'archive_id':archive_id,**info}
