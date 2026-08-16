from ..providers.errors import ProviderError

async def with_fallback(candidates, execute):
    """Try only candidates already capability-filtered by the selector."""
    errors=[]
    for candidate in candidates:
        try: return await execute(candidate), errors
        except ProviderError as error: errors.append({'provider':candidate.provider,'model':candidate.model_id,'error':type(error).__name__})
    raise ProviderError('No capable provider completed the task')
