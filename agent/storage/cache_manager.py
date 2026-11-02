from pathlib import Path

from .retention import EPHEMERAL_CACHE, PROVIDER_CONFIG_CACHE, expired_cache_files


class CacheManager:
    def __init__(self, root: Path):
        self.root = root
        self.cache_root = root / "data" / "cache"

    @property
    def ephemeral_cache(self) -> Path:
        return self.cache_root / EPHEMERAL_CACHE

    @property
    def provider_config_cache(self) -> Path:
        return self.cache_root / PROVIDER_CONFIG_CACHE

    def ensure_categories(self) -> None:
        self.ephemeral_cache.mkdir(parents=True, exist_ok=True)
        self.provider_config_cache.mkdir(parents=True, exist_ok=True)

    def expired(self, ttl_days):
        return expired_cache_files(self.cache_root, ttl_days)
