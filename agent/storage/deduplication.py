from collections import defaultdict
from difflib import SequenceMatcher
import hashlib, json, re

def content_hash(record: dict) -> str:
    payload=json.dumps(record,sort_keys=True,separators=(',',':'),ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()
def deduplicate_exact(records: list[dict]) -> tuple[list[dict], dict]:
    canonical={}; duplicates=0
    for record in records:
        key=content_hash(record)
        if key in canonical:
            canonical[key]['usage_count']=canonical[key].get('usage_count',1)+1; duplicates+=1
        else:
            copy=dict(record); copy['content_hash']=key; copy['usage_count']=copy.get('usage_count',1); canonical[key]=copy
    return list(canonical.values()), {'duplicates_removed':duplicates,'records_before':len(records),'records_after':len(canonical)}
def _tokens(text): return set(re.findall(r'\w+',text.lower()))
def similarity(a: str,b: str) -> float:
    left,right=_tokens(a),_tokens(b)
    jaccard=len(left&right)/len(left|right) if left|right else 1.0
    return max(jaccard, SequenceMatcher(None,a.lower(),b.lower()).ratio())
def deduplicate_semantic(records: list[dict], threshold=.92) -> tuple[list[dict],dict]:
    buckets=defaultdict(list); output=[]; merged=0
    for record in records:
        text=str(record.get('prompt',''))+' '+str(record.get('response',''))
        topic=' '.join(sorted(_tokens(text))[:3]); found=None
        for candidate in buckets[topic]:
            ctext=str(candidate.get('prompt',''))+' '+str(candidate.get('response',''))
            if similarity(text,ctext)>=threshold: found=candidate; break
        if found:
            found['usage_count']=found.get('usage_count',1)+record.get('usage_count',1); found['source_count']=found.get('source_count',1)+1; merged+=1
        else:
            copy=dict(record); copy.setdefault('source_count',1); buckets[topic].append(copy); output.append(copy)
    return output, {'semantic_merged':merged,'records_before':len(records),'records_after':len(output)}
