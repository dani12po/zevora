from collections import defaultdict

def quality_score(record: dict) -> float:
    score=.35 if record.get('outcome')=='success' else .05
    score+=min(.2,float(record.get('reuse_count',0))*.02)+min(.2,float(record.get('feedback',0))*.1)
    score+=.15 if record.get('correction') else 0; score+=.1 if record.get('project') else 0
    return min(1.0,round(score,2))
def consolidate(records: list[dict]) -> list[dict]:
    groups=defaultdict(list)
    for item in records:
        groups[(item.get('project',''),item.get('topic') or item.get('task_type','general'))].append(item)
    result=[]
    for (project,topic),items in groups.items():
        valuable=[x for x in items if quality_score(x)>=.5]
        if not valuable: continue
        facts=[]
        for item in valuable:
            value=item.get('lesson') or item.get('response') or item.get('task','')
            if value and value not in facts: facts.append(value[:500])
        result.append({'tier':'compressed_knowledge','project':project,'topic':topic,'source_count':len(items),'confidence':round(sum(quality_score(x) for x in valuable)/len(valuable),2),'knowledge':'\n'.join(facts[:10])})
    return result
