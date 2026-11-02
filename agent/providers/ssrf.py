"""Provider base-URL validation to bound the server-side request surface (SSRF)."""
import ipaddress
import re
from urllib.parse import urlsplit

RESERVED_HOSTNAMES = frozenset({
    'metadata', 'metadata.google.internal',
    'instance-data', 'instance-data.ec2.internal',
    'kubernetes.default.svc', 'localhost', 'localhost.localdomain',
})

# Cloud instance-metadata endpoints: reachable only from inside a VM, never a
# legitimate cloud *provider* API. Blocked even for user-configured local
# endpoints (Colab/Kaggle/llama.cpp servers never live on these addresses).
METADATA_HOSTS = frozenset({
    '169.254.169.254', 'fd00:ec2::254',
    'metadata.google.internal', 'metadata.goog',
    'instance-data', 'instance-data.ec2.internal',
    '100.100.100.200',
})

_RANGE_BLOCKED = 'Blocked provider base URL: {host} is a reserved/link-local/loopback address and cannot be used as a cloud provider endpoint'
_METADATA_BLOCKED = 'Blocked endpoint URL: {host} is a cloud instance-metadata address'
_NUMERIC_PART_RE = re.compile(r'0[xX][0-9a-fA-F]+|0[0-7]*|[0-9]+')


def _parse_candidate(base_url: str) -> urlsplit:
    split = urlsplit(str(base_url or '').strip())
    if split.scheme not in ('http', 'https'):
        raise ValueError('Provider base URL must use http or https')
    if not split.hostname:
        raise ValueError('Provider base URL must include a host')
    return split


def _normalize_host(host: str) -> str:
    """Decode integer/hex/octal host spellings to dotted quads.

    ``http://2130706433/``, ``http://0x7f.0.0.1/`` and ``http://0177.0.0.1/``
    all reach 127.0.0.1 but ``ipaddress`` rejects them as written, which would
    let them slip past the range check below.
    """
    host = host.strip().rstrip('.').lower()
    if re.fullmatch(r'[0-9]+', host):
        try:
            return str(ipaddress.ip_address(int(host)))
        except ValueError:
            return host
    parts = host.split('.')
    if len(parts) == 4 and all(_NUMERIC_PART_RE.fullmatch(part) for part in parts):
        try:
            numbers = [_parse_numeric_part(part) for part in parts]
        except ValueError:
            return host
        if all(0 <= number <= 255 for number in numbers):
            return '.'.join(str(number) for number in numbers)
    return host


def _parse_numeric_part(part: str) -> int:
    """Parse one dotted-quad part accepting 0x/0-octal/decimal spellings."""
    lowered = part.lower()
    if lowered.startswith('0x'):
        return int(lowered, 16)
    if len(lowered) > 1 and lowered.startswith('0'):
        return int(lowered, 8)
    return int(lowered, 10)


def is_metadata_host(host: str) -> bool:
    """True when the host is a cloud instance-metadata endpoint."""
    normalized = _normalize_host(host)
    if normalized in METADATA_HOSTS:
        return True
    try:
        return ipaddress.ip_address(normalized) in ipaddress.ip_network('169.254.0.0/16')
    except ValueError:
        return False


def _block(host: str) -> bool:
    host = _normalize_host(host)
    if host in RESERVED_HOSTNAMES:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    # Cloud provider APIs live on globally routable addresses. Anything else
    # (private, loopback, link-local, multicast, reserved, CGNAT, documentation
    # ranges) is refused here; loopback/dev endpoints have their own provider.
    if address.is_multicast or not address.is_global:
        return True
    if address.version == 6 and address.ipv4_mapped:
        try:
            return not address.ipv4_mapped.is_global
        except ValueError:
            return True
    return False


def assert_provider_base_url(base_url: str) -> str:
    """Validate a cloud provider base URL, rejecting reserved/link-local/loopback hosts.

    Deterministic (no DNS resolution) so construction stays fast and stable.
    Local/loopback OpenAI-compatible endpoints are served by a separate local
    provider class and are intentionally not routed through this guard.
    """
    split = _parse_candidate(base_url)
    if _block(split.hostname):
        raise ValueError(_RANGE_BLOCKED.format(host=split.hostname))
    return base_url


def assert_local_endpoint_url(base_url: str) -> str:
    """Validate an explicitly user-configured local endpoint URL.

    Loopback and private-network hosts are allowed (dev servers, LAN boxes),
    but cloud instance-metadata addresses never host a model server and stay
    blocked, and the scheme/host must still be explicit http(s).
    """
    split = _parse_candidate(base_url)
    if is_metadata_host(split.hostname):
        raise ValueError(_METADATA_BLOCKED.format(host=split.hostname))
    return base_url
