from agent.storage.compression import compress_records, decompress_records, checksum
def test_compress_restore_and_checksum(tmp_path):
    records=[{'prompt':'hello','response':'world','n':i} for i in range(1000)]
    info=compress_records(records,tmp_path/'experience')
    assert decompress_records(__import__('pathlib').Path(info['path'])) == records
    assert checksum(__import__('pathlib').Path(info['path'])) == info['checksum']
    assert info['compressed_size'] < info['original_size']
