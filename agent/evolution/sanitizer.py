"""Privacy-first sanitizer for collective contributions."""
from dataclasses import dataclass
import json
import re
from typing import Any


SECRET_PATTERNS = (
    re.compile(r'(?i)(api[_-]?key|password|passwd|secret|access[_-]?token|private[_-]?key)\s*[:=]'),
    re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    re.compile(r'\b(?:sk|ghp|github_pat)_[A-Za-z0-9_-]{16,}\b'),
)
PRIVATE_PATH = re.compile(r'(?i)(?:[A-Z]:\\Users\\[^\\\s]+|/home/[^/\s]+|/Users/[^/\s]+)')
SENSITIVE_URL = re.compile(r'https?://[^\s]*(?:token|key|auth|private|internal)[^\s]*', re.I)
SOURCE_MARKERS = re.compile(r'(?m)^\s*(?:def |class |function |import |from |#include|package |SELECT .+ FROM )')
EMAIL = re.compile(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', re.I)

ALLOWED_FIELDS = {
    'skill': {'skill_id', 'version', 'description', 'capabilities', 'confidence', 'success_rate', 'content_hash'},
    'knowledge': {'task_class', 'route', 'result', 'provider_class', 'skill_ids', 'confidence', 'content_hash'},
    'routing': {'task_class', 'route', 'provider_class', 'success', 'latency_bucket', 'quality_bucket'},
    'evaluation': {'task_class', 'task_success', 'tool_correctness', 'verification_success', 'routing_success', 'latency_ms', 'token_efficiency', 'context_efficiency', 'regression_rate'},
}


@dataclass(frozen=True)
class SanitizationResult:
    accepted: bool
    payload: dict[str, Any] | None
    reasons: tuple[str, ...]


def sanitize(contribution_type: str, payload: dict[str, Any]) -> SanitizationResult:
    allowed = ALLOWED_FIELDS.get(contribution_type)
    if not allowed:
        return SanitizationResult(False, None, ('unsupported_contribution_type',))
    unknown = set(payload) - allowed
    if unknown:
        return SanitizationResult(False, None, ('unknown_fields',))
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    reasons = []
    if any(pattern.search(serialized) for pattern in SECRET_PATTERNS): reasons.append('secret_or_credential')
    if PRIVATE_PATH.search(serialized): reasons.append('private_path')
    if SENSITIVE_URL.search(serialized): reasons.append('sensitive_url')
    if SOURCE_MARKERS.search(serialized): reasons.append('source_or_proprietary_content')
    if EMAIL.search(serialized): reasons.append('pii')
    if len(serialized.encode()) > 16_000: reasons.append('payload_too_large')
    if reasons:
        return SanitizationResult(False, None, tuple(reasons))
    sanitized = {key: payload[key] for key in sorted(payload) if key in allowed}
    return SanitizationResult(True, sanitized, ())
