from datetime import datetime, timedelta, timezone
import os
from agent.storage.retention import expired_files
def test_retention_identifies_old_file(tmp_path):
    old=tmp_path/'old.log'; old.write_text('x'); then=(datetime.now(timezone.utc)-timedelta(days=20)).timestamp(); os.utime(old,(then,then))
    assert [x.path for x in expired_files(tmp_path,14)] == [old]
