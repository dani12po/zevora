from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

@dataclass(frozen=True)
class RetentionCandidate: path: Path; reason: str; size_bytes: int
def expired_files(root: Path, days: int, now=None) -> list[RetentionCandidate]:
    cutoff=(now or datetime.now(timezone.utc))-timedelta(days=days); result=[]
    if not root.exists(): return result
    for path in root.rglob('*'):
        if path.is_file() and datetime.fromtimestamp(path.stat().st_mtime,timezone.utc)<cutoff: result.append(RetentionCandidate(path,f'older than {days} days',path.stat().st_size))
    return result
