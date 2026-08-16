def validate(response: str, requested_format: str='') -> dict:
    valid=bool(response and response.strip())
    if requested_format=='json':
        import json
        try: json.loads(response)
        except (json.JSONDecodeError,TypeError): valid=False
    return {'accepted':valid,'quality_score':.85 if valid else 0,'reason':'response_present' if valid else 'empty_or_invalid_response'}
