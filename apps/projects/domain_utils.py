import re
import ipaddress
from urllib.parse import urlparse

import tldextract


DOMAIN_LABEL_RE = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$')
_TLD_EXTRACTOR = tldextract.TLDExtract(
    suffix_list_urls=(),
    include_psl_private_domains=True,
)


def _hostname_from_value(value):
    raw_value = str(value or '').strip()
    if not raw_value:
        return ''

    candidate = raw_value if '://' in raw_value else f'https://{raw_value}'
    try:
        parsed = urlparse(candidate)
        if parsed.scheme not in {'http', 'https'}:
            return ''
        if parsed.username or parsed.password:
            return ''
        parsed.port
        hostname = parsed.hostname or ''
    except ValueError:
        return ''
    return hostname.strip('.').lower()


def _hostname_has_valid_domain_labels(hostname):
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        pass
    labels = [label for label in str(hostname or '').split('.') if label]
    if not labels or len(hostname) > 253:
        return False
    return all(DOMAIN_LABEL_RE.match(label) for label in labels)


def extract_registered_domain(value):
    hostname = _hostname_from_value(value)
    if not hostname or not _hostname_has_valid_domain_labels(hostname):
        return ''

    try:
        ipaddress.ip_address(hostname)
        return hostname
    except ValueError:
        pass

    extracted = _TLD_EXTRACTOR(hostname)
    registered_domain = getattr(extracted, 'top_domain_under_public_suffix', '')
    if not registered_domain:
        registered_domain = getattr(extracted, 'registered_domain', '')
    if registered_domain:
        return registered_domain.lower()
    if extracted.suffix and not extracted.domain:
        return ''
    return hostname.lower()


def is_valid_registered_domain(domain):
    hostname = _hostname_from_value(domain)
    return bool(hostname and extract_registered_domain(hostname) == hostname)


def normalize_workspace_website_url(value):
    raw_value = str(value or '').strip()
    if not raw_value:
        return ''
    hostname = _hostname_from_value(raw_value)
    return raw_value if hostname and _hostname_has_valid_domain_labels(hostname) else ''


def is_valid_workspace_website_url(value):
    return bool(normalize_workspace_website_url(value))


def normalize_allowed_domains(value):
    if value is None:
        return []
    if isinstance(value, str):
        raw_domains = value.replace(',', '\n').splitlines()
    else:
        raw_domains = value

    domains = []
    seen = set()
    for raw_domain in raw_domains:
        domain = extract_registered_domain(raw_domain)
        if not domain or not is_valid_registered_domain(domain) or domain in seen:
            continue
        seen.add(domain)
        domains.append(domain)
    return domains


def host_matches_allowed_domain(hostname, allowed_domain):
    hostname = _hostname_from_value(hostname)
    allowed_domain = _hostname_from_value(allowed_domain)
    if not hostname or not allowed_domain:
        return False
    return hostname == allowed_domain or hostname.endswith(f'.{allowed_domain}')


def request_matches_allowed_domains(request, project, candidate_url=''):
    allowed_domains = project.allowed_domains or []
    if not allowed_domains:
        return True

    candidates = [
        candidate_url,
        request.META.get('HTTP_ORIGIN', ''),
        request.META.get('HTTP_REFERER', ''),
    ]
    for candidate in candidates:
        hostname = _hostname_from_value(candidate)
        if not hostname:
            continue
        if any(host_matches_allowed_domain(hostname, domain) for domain in allowed_domains):
            return True
    return False
