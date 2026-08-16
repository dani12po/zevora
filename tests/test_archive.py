from pathlib import Path
from agent.storage.archive import ArchiveManager
def test_archive_is_indexed(tmp_path):
    info=ArchiveManager(tmp_path).archive([{'task':'test','response':'ok'}],topic='experience')
    assert Path(info['path']).is_file()
