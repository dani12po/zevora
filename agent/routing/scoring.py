def score_model(capability_match, reliability=None, latency_ms=None, cost=None, historical_success=None):
    """Unknown values are neutral; no price or capability is invented."""
    score=capability_match*100
    if reliability is not None: score+=reliability*20
    if historical_success is not None: score+=historical_success*20
    if latency_ms is not None: score+=max(0,10-min(latency_ms/1000,10))
    if cost is not None: score+=max(0,10-min(cost*100,10))
    return round(score,2)
