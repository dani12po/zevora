import re

def compress_context(items: list[str], max_chars=6000) -> dict:
    """Deduplicate lines while retaining short facts, decisions, and open tasks."""
    seen=set(); lines=[]
    for item in items:
        for line in item.splitlines():
            clean=' '.join(line.split())
            key=clean.lower()
            if clean and key not in seen: seen.add(key); lines.append(clean)
    selected=[]; remaining=max_chars
    for line in lines:
        if remaining<=0: break
        selected.append(line[:remaining]); remaining-=len(selected[-1])+1
    return {'text':'\n'.join(selected),'original_chars':sum(map(len,items)),'compressed_chars':sum(map(len,selected))+max(0,len(selected)-1),'retained_lines':len(selected)}
