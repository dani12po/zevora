import re

PATTERNS = [
    re.compile(r'(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*["\']?[^\s"\']+'),
    re.compile(r'\bsk-[A-Za-z0-9_-]{16,}\b'),
    re.compile(r'(?i)bearer\s+[A-Za-z0-9._-]+'),
    re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
]

def redact(value: str) -> str:
    """Remove likely credentials before persistence or presentation."""
    for pattern in PATTERNS:
        value = pattern.sub('[REDACTED]', value)
    return value
