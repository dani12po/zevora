from datetime import datetime, timedelta, timezone
import os

from agent.storage.retention import expired_cache_files, expired_files


def mark_old(path, days=20):
    path.write_text("x")
    then = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
    os.utime(path, (then, then))


def test_retention_identifies_old_file(tmp_path):
    old = tmp_path / "old.log"
    mark_old(old)
    assert [item.path for item in expired_files(tmp_path, 14)] == [old]


def test_cache_retention_excludes_persistent_provider_configuration(tmp_path):
    cache = tmp_path / "data" / "cache"
    ephemeral = cache / "ephemeral_cache" / "response.json"
    provider = cache / "provider_config_cache" / "local-provider.json"
    ephemeral.parent.mkdir(parents=True)
    provider.parent.mkdir(parents=True)
    mark_old(ephemeral)
    mark_old(provider)

    candidates = expired_cache_files(cache, 7)

    assert [item.path for item in candidates] == [ephemeral]
