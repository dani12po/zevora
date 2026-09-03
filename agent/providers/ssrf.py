"""Provider base-URL validation to bound the server-side request surface (SSRF)."""
import ipaddress
import re
from urllib.parse import urlsplit

RESERVED_HOSTNAMES = frozenset({
    'metadata', 'metadata.google.internal',
    'instance-data', 'instance-data.ec2.internal',
    'kubernetes.default.svc', 'localhost', 'localhost.localdomain',
})

_RANGE_BLOCKED = 'Blocked provider base URL: {host} is a reserved/link-local/loopback address and cannot be used as a cloud provider endpoint'


def _parse_candidate(base_url: str) -> urlsplit:
    split = urlsplit(str(base_url or '').strip())
    if split.scheme not in ('http', 'https'):
        raise ValueError('Provider base URL must use http or https')
    if not split.hostname:
        raise ValueError('Provider base URL must include a host')
    return split


def _block(host: str) -> bool:
    host = host.strip().rstrip('.').lower()
    if host in RESERVED_HOSTNAMES:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if address.is_loopback or address.is_link_local or address.is_unspecified:
        return True
    if address.version == 4 and address in ipaddress.ip_network('169.254.0.0/16'):
        return True
    if address.version == 6 and (address.ipv4_mapped and _block(str(address.ipv4_mapped))):
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
