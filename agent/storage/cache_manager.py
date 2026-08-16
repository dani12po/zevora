from pathlib import Path
from .retention import expired_files

class CacheManager:
    def __init__(self, root: Path): self.root=root
    def expired(self, ttl_days): return expired_files(self.root/'data'/'cache',ttl_days)
