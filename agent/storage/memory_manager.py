MEMORY_TIERS=('short_term','working','long_term','compressed_knowledge')
def tier_for_score(score: float) -> str:
    return 'compressed_knowledge' if score >= .8 else ('long_term' if score >= .5 else 'short_term')
