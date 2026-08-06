"""Filter option preparation for the recording-backed Visits screen."""

from __future__ import annotations

from collections import OrderedDict

from django.utils.text import slugify

from apps.pages import company_analytics, user_analytics
from apps.pages.models import ProductArea
from apps.tracker.models import ProjectPageRule


DEFAULT_ENTITY_OPTION_LIMIT = 20
MAX_ENTITY_OPTION_LIMIT = 50
UNCLASSIFIED_AREA_ID = 'unclassified'
UNCLASSIFIED_AREA_NAME = 'Unclassified'
SUPPORTED_RANGE_KEYS = {
    'last_7_days',
    'last_30_days',
    'last_90_days',
    'last_180_days',
}


def _clean(value):
    return str(value or '').strip()


def normalize_entity_option_limit(value):
    try:
        limit = int(value or DEFAULT_ENTITY_OPTION_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_ENTITY_OPTION_LIMIT
    return max(1, min(limit, MAX_ENTITY_OPTION_LIMIT))


def _normalize_range_key(range_key):
    return range_key if range_key in SUPPORTED_RANGE_KEYS else 'last_30_days'


def _matches(query, *values):
    if not query:
        return True
    haystack = ' '.join(_clean(value) for value in values).casefold()
    return query.casefold() in haystack


def _company_options(payload, query, limit):
    options = []
    for row in (payload or {}).get('companies') or []:
        company_id = _clean(row.get('id') or row.get('companyId'))
        if not company_id:
            continue
        name = _clean(row.get('name') or row.get('companyName')) or company_id
        domain = _clean(row.get('domain'))
        if not _matches(query, name, domain, company_id):
            continue
        options.append({'id': company_id, 'name': name, 'domain': domain})
    if query:
        options.sort(key=lambda option: (option['name'].casefold(), option['id']))
    return options[:limit] if limit is not None else options


def _user_options(payload, query, limit):
    options = []
    for row in (payload or {}).get('users') or []:
        user_id = _clean(row.get('id') or row.get('userId'))
        if not user_id:
            continue
        name = _clean(row.get('name')) or _clean(row.get('email')) or user_id
        email = _clean(row.get('email'))
        company_name = _clean(row.get('companyName') or row.get('company'))
        if not _matches(query, name, email, user_id):
            continue
        options.append({
            'id': user_id,
            'name': name,
            'email': email,
            'companyName': company_name,
        })
    if query:
        options.sort(key=lambda option: (option['name'].casefold(), option['id']))
    return options[:limit] if limit is not None else options


def _company_cache(project, range_key):
    cache = company_analytics.get_cached_companies_overview_payload(
        project.id,
        range_key=range_key,
    )
    ready = bool(
        cache
        and company_analytics.is_current_companies_payload_schema(cache.get('schema_version'))
    )
    return cache if ready else None


def _user_cache(project, range_key):
    cache = user_analytics.get_cached_users_overview_payload(
        project.id,
        range_key=range_key,
    )
    ready = bool(
        cache
        and user_analytics.is_current_users_payload_schema(cache.get('schema_version'))
    )
    return cache if ready else None


def search_visits_entities(
    project,
    query='',
    limit=DEFAULT_ENTITY_OPTION_LIMIT,
    range_key='last_30_days',
):
    """Search prepared Companies and Users overview caches for one project."""

    query = _clean(query)[:200]
    limit = normalize_entity_option_limit(limit)
    range_key = _normalize_range_key(range_key)
    company_cache = _company_cache(project, range_key)
    user_cache = _user_cache(project, range_key)
    companies_pending = company_cache is None
    users_pending = user_cache is None

    return {
        'query': query,
        'range_key': range_key,
        'pending': companies_pending or users_pending,
        'companiesPending': companies_pending,
        'usersPending': users_pending,
        'companies': _company_options(
            (company_cache or {}).get('payload_json'),
            query,
            limit,
        ),
        'users': _user_options(
            (user_cache or {}).get('payload_json'),
            query,
            limit,
        ),
    }


def selected_visits_entity_label(project, entity_type, entity_id, range_key='last_30_days'):
    """Resolve the selected label from the prepared overview cache."""

    entity_id = _clean(entity_id)
    if not entity_id:
        return ''
    range_key = _normalize_range_key(range_key)
    if entity_type == 'company':
        cache = _company_cache(project, range_key)
        for option in _company_options((cache or {}).get('payload_json'), '', None):
            if option['id'] == entity_id:
                return option['name']
    if entity_type == 'user':
        cache = _user_cache(project, range_key)
        for option in _user_options((cache or {}).get('payload_json'), '', None):
            if option['id'] == entity_id:
                return option['name']
    return entity_id


def visits_entity_is_known(project, entity_type, entity_id, range_key='last_30_days'):
    """Whether a saved entity filter still names a company or user this project has.

    Returns ``None`` when the prepared overview the options come from has not
    been built yet. An unbuilt cache is not evidence that an identity is gone,
    so a caller sanitizing stored filter state can tell "this one was deleted"
    apart from "ask again once the overview exists".
    """

    entity_id = _clean(entity_id)
    if not entity_id or entity_type not in ('company', 'user'):
        return False
    range_key = _normalize_range_key(range_key)
    is_company = entity_type == 'company'
    cache = _company_cache(project, range_key) if is_company else _user_cache(project, range_key)
    if cache is None:
        return None
    read_options = _company_options if is_company else _user_options
    return any(
        option['id'] == entity_id
        for option in read_options(cache.get('payload_json'), '', None)
    )


def visits_page_filter_groups(project):
    """Build selectable Product Area groups and their active page rules."""

    groups = OrderedDict()
    for area in ProductArea.objects.filter(project=project).order_by('name', 'id'):
        groups[area.name.casefold()] = {
            'id': area.slug,
            'name': area.name,
            'pages': [],
        }

    rules = (
        ProjectPageRule.objects
        .filter(project=project, is_active=True)
        .order_by('product_area', 'page_name', 'id')
    )
    for rule in rules:
        area_name = _clean(rule.product_area) or UNCLASSIFIED_AREA_NAME
        key = area_name.casefold()
        if key not in groups:
            groups[key] = {
                'id': slugify(area_name) or UNCLASSIFIED_AREA_ID,
                'name': area_name,
                'pages': [],
            }
        groups[key]['pages'].append({
            'id': str(rule.id),
            'name': rule.page_name,
        })

    return sorted(groups.values(), key=lambda group: (group['name'].casefold(), group['id']))


def resolve_visits_page_filter(groups, filter_type, filter_id):
    """Return a validated page/area selection for the current project."""

    filter_id = _clean(filter_id)
    if filter_type == 'area':
        for group in groups:
            if str(group['id']) == filter_id:
                return {'type': 'area', 'id': filter_id, 'label': group['name']}
    if filter_type == 'page':
        for group in groups:
            for page in group['pages']:
                if str(page['id']) == filter_id:
                    return {'type': 'page', 'id': filter_id, 'label': page['name']}
    return {'type': '', 'id': '', 'label': ''}
