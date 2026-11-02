"""Compact pattern extraction without retaining raw prompts or conversations."""
import hashlib
import json


def extract_pattern(experience: dict) -> dict:
    pattern = {
        'task_class': str(experience.get('task_class') or 'unknown'),
        'route': str(experience.get('route') or ''),
        'provider': str(experience.get('provider') or ''),
        'model': str(experience.get('model') or ''),
        'skill_ids': sorted(set(experience.get('skill_ids') or [])),
        'result': str(experience.get('result') or 'unknown'),
        'verified': bool(experience.get('verified', False)),
    }
    pattern['content_hash'] = hashlib.sha256(json.dumps(pattern, sort_keys=True).encode()).hexdigest()
    return pattern
