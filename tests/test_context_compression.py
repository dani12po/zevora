from agent.storage.context_compressor import compress_context
def test_context_deduplicates_and_bounds():
    output=compress_context(['Decision: use SQLite\nDecision: use SQLite','Open task: add cache'],max_chars=30)
    assert output['compressed_chars']<=30 and output['retained_lines']==2
