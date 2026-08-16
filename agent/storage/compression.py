from pathlib import Path
import gzip, hashlib, json
try:
    import zstandard as zstd
except ImportError: zstd=None

def checksum(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''): digest.update(chunk)
    return digest.hexdigest()
def _encode(records): return ''.join(json.dumps(row,separators=(',',':'),ensure_ascii=False)+'\n' for row in records).encode()
def compress_records(records: list[dict], destination: Path) -> dict:
    raw=_encode(records); destination.parent.mkdir(parents=True,exist_ok=True)
    if zstd:
        destination=destination.with_suffix('.jsonl.zst') if destination.suffix not in ('.zst','.gz') else destination
        destination.write_bytes(zstd.ZstdCompressor(level=6).compress(raw)); codec='zstd'
    else:
        destination=destination.with_suffix('.jsonl.gz') if destination.suffix not in ('.zst','.gz') else destination.with_suffix('.gz')
        with gzip.open(destination,'wb',compresslevel=6) as target: target.write(raw)
        codec='gzip'
    restored=decompress_records(destination)
    if restored != records: raise ValueError('Archive verification failed; source must be retained')
    compressed=destination.stat().st_size
    return {'path':str(destination),'codec':codec,'checksum':checksum(destination),'original_size':len(raw),'compressed_size':compressed,'compression_ratio':compressed/len(raw) if raw else 1,'record_count':len(records)}
def decompress_records(path: Path) -> list[dict]:
    raw=zstd.ZstdDecompressor().decompress(path.read_bytes()) if path.suffix=='.zst' and zstd else gzip.open(path,'rb').read()
    return [json.loads(line) for line in raw.decode().splitlines() if line]
