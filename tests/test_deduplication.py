from agent.storage.deduplication import deduplicate_exact, deduplicate_semantic
def test_exact_dedup_tracks_usage():
    rows,stats=deduplicate_exact([{'prompt':'same'},{'prompt':'same'},{'prompt':'other'}])
    assert stats['records_after']==2 and next(x for x in rows if x['prompt']=='same')['usage_count']==2
def test_semantic_dedup():
    rows,stats=deduplicate_semantic([{'prompt':'create jwt authentication','response':'ok'},{'prompt':'create jwt authentication','response':'ok'}])
    assert stats['records_after']==1 and rows[0]['source_count']==2
