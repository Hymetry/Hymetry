import logging
import threading
import time
from collections import OrderedDict
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.safestring import mark_safe

from apps.pages import filtered_overview, services
from apps.pages.table_pagination import paginate_cached_rows
from apps.pages.tasks import (
    build_pages_overview_cache_task,
    hydrate_pages_scatter_tooltips_cache_task,
)
from apps.projects import analytics_filter_state
from apps.projects.access import get_accessible_project_or_404
from apps.projects.company_attribute_filter_support import (
    build_company_attribute_filter_context,
    canonical_company_scope_redirect,
)
from apps.projects.decorators import require_project_member
from apps.projects.demo import DEMO_PROJECT_DISPLAY_NAME, get_demo_project
from apps.projects.company_attribute_filters import (
    load_company_attribute_filter_attributes,
    parse_company_attribute_filters,
)
from apps.projects.company_segments import (
    company_segment_urls,
    demo_company_segment_urls,
    resolve_company_scope,
)
from apps.projects.url_helpers import preserved_period_query_suffix, project_route


PAGES_RANGE_OPTIONS = (
    ('last_7_days', 'Last 7 complete days'),
    ('last_30_days', 'Last 30 complete days'),
    ('last_90_days', 'Last 90 complete days'),
    ('last_180_days', 'Last 180 complete days'),
)
SUPPORTED_RANGES = {key for key, _ in PAGES_RANGE_OPTIONS}
PAGES_RANGE_LABELS = dict(PAGES_RANGE_OPTIONS)
PAGES_PERIOD_RANGE_KEYS = {
    7: 'last_7_days',
    30: 'last_30_days',
    90: 'last_90_days',
    180: 'last_180_days',
}
PAGES_RANGE_DAYS = {range_key: days for days, range_key in PAGES_PERIOD_RANGE_KEYS.items()}
PRODUCT_AREA_QUERY_PARAM = 'product_area'

PAGE_METRICS_TABLE_PAGE_SIZE = 10
PAGE_DETAIL_COMPANIES_TABLE_PAGE_SIZE = 20
PAGE_DETAIL_CHAMPIONS_TABLE_PAGE_SIZE = 20
PAGES_TOP_ACTION_GROUP_LIMIT = 8
PAGES_TOP_ACTIONS_PER_GROUP_LIMIT = 5
PAGES_OVERVIEW_SANKEY_MAX_LINKS = 12
PAGES_OVERVIEW_SANKEY_MAX_NODES = 10
FILTERED_REBUILD_DISPATCH_DEDUP_SECONDS = 60
FILTERED_REBUILD_DISPATCH_DEDUP_MAX_ENTRIES = 2048


logger = logging.getLogger(__name__)
_filtered_rebuild_dispatch_lock = threading.Lock()
_filtered_rebuild_dispatches = OrderedDict()


PAGE_METRICS_SORT_GETTERS = {
    'page': lambda row: row.get('page_name') or '',
    'companies': lambda row: row.get('companies_count') or 0,
    'adoption': lambda row: row.get('adoption_pct') or 0,
    'users': lambda row: row.get('users_count') or 0,
    'penetration': lambda row: row.get('penetration_pct') or 0,
    'visits': lambda row: row.get('visits_count') or 0,
    'engaged': lambda row: row.get('engaged_seconds') or 0,
    'avg_visit': lambda row: row.get('avg_visit_seconds') or 0,
    'interaction': lambda row: row.get('interaction_pct') or 0,
    'clicks_per_visit': lambda row: row.get('clicks_per_visit') or 0,
}

PAGE_DETAIL_COMPANIES_SORT_GETTERS = {
    'company': lambda row: row.get('company') or '',
    'users': lambda row: row.get('users') or 0,
    'page_penetration': lambda row: row.get('pagePenetration') or 0,
    'visits': lambda row: row.get('visits') or 0,
    'engaged': lambda row: row.get('engagedSeconds') or 0,
    'avg_user': lambda row: row.get('engagedSeconds') / max(int(row.get('users') or 0), 1),
    'interaction': lambda row: row.get('interaction') or 0,
}

PAGE_DETAIL_CHAMPIONS_SORT_GETTERS = {
    'user': lambda row: row.get('user') or '',
    'company': lambda row: row.get('company') or '',
    'engaged': lambda row: row.get('engagedSeconds') or 0,
    'visits': lambda row: row.get('visits') or 0,
    'avg_visit': lambda row: row.get('engagedSeconds') / max(int(row.get('visits') or 0), 1),
    'clicks': lambda row: row.get('clicks') or 0,
}


def _analytics_number(value):
    if isinstance(value, str):
        value = value.strip().replace(',', '').replace('%', '')
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0


def _analytics_row_has_activity(row, keys):
    if not isinstance(row, dict):
        return False
    return any(_analytics_number(row.get(key)) > 0 for key in keys)


def _analytics_rows_have_activity(rows, keys):
    return isinstance(rows, list) and any(_analytics_row_has_activity(row, keys) for row in rows)


def _analytics_metric_has_activity(metric):
    if not isinstance(metric, dict):
        return False
    value = metric.get('currentValue', metric.get('value', metric.get('rawValue')))
    return _analytics_number(value) > 0


def _analytics_metrics_have_activity(metrics):
    return isinstance(metrics, list) and any(_analytics_metric_has_activity(metric) for metric in metrics)


def is_pages_overview_empty(payload):
    if not isinstance(payload, dict):
        return True
    rows = payload.get('change_aware_rows') or payload.get('rows') or []
    return not (
        _analytics_metrics_have_activity(payload.get('kpis'))
        or _analytics_rows_have_activity(
            rows,
            [
                'visits_count',
                'visits',
                'engaged_seconds',
                'engaged',
                'users_count',
                'users',
                'companies_count',
                'companies',
                'click_count',
                'clicks',
            ],
        )
    )


def is_page_detail_empty(payload):
    if not isinstance(payload, dict):
        return True
    metrics = payload.get('metrics') if isinstance(payload.get('metrics'), list) else []
    return not (
        any(_analytics_metric_has_activity(metric) for metric in metrics)
        or _analytics_rows_have_activity(payload.get('companies'), ['visits', 'engagedSeconds', 'users', 'companies'])
        or _analytics_rows_have_activity(payload.get('champions'), ['visits', 'engagedSeconds', 'clicks'])
        or _analytics_rows_have_activity(payload.get('actions'), ['clicks', 'users', 'companies'])
    )


def _page_detail_title(payload, fallback):
    page = payload.get('page') if isinstance(payload, dict) else {}
    page = page if isinstance(page, dict) else {}
    return (
        page.get('displayName')
        or page.get('pageName')
        or page.get('pageRuleId')
        or page.get('route')
        or fallback
        or 'Page'
    )


def _range_key(request):
    value = request.GET.get('range', 'last_30_days')
    return value if value in SUPPORTED_RANGES else 'last_30_days'


def _detail_range_key(request):
    period = request.GET.get('period')
    try:
        period_days = int(period) if period is not None else None
    except (TypeError, ValueError):
        period_days = None
    if period_days in PAGES_PERIOD_RANGE_KEYS:
        return PAGES_PERIOD_RANGE_KEYS[period_days]
    return _range_key(request)


def _show_peers(request):
    return str(request.GET.get('show_peers', '')).lower() in {'1', 'true', 'yes', 'on'}


def _product_area_query_values(request):
    return [
        str(value).strip()
        for value in request.GET.getlist(PRODUCT_AREA_QUERY_PARAM)
        if str(value).strip()
    ]


def _product_area_filter_label(options):
    selected_options = [option for option in options if option.get('is_selected')]
    if selected_options:
        return ', '.join(
            option.get('name') or option.get('key') or 'Product area'
            for option in selected_options
        )
    return 'Filter product area...'


def _product_area_query_suffix(selected_keys, company_attribute_pairs=()):
    params = [
        *((PRODUCT_AREA_QUERY_PARAM, key) for key in selected_keys or []),
        *company_attribute_pairs,
    ]
    query = urlencode(params)
    return f'&{query}' if query else ''


def _best_effort_queue_overview_rebuild(project_id, range_key):
    if not getattr(settings, 'PAGES_QUEUE_REBUILDS_ON_REQUEST', True):
        return False

    def enqueue():
        try:
            build_pages_overview_cache_task.apply_async(
                args=[project_id, range_key],
                retry=False,
                ignore_result=True,
            )
        except Exception:
            return

    threading.Thread(target=enqueue, daemon=True).start()
    return True


def _best_effort_queue_tooltip_rebuild(project_id, range_key):
    if not getattr(settings, 'PAGES_QUEUE_REBUILDS_ON_REQUEST', True):
        return False

    def enqueue():
        try:
            hydrate_pages_scatter_tooltips_cache_task.apply_async(
                args=[project_id, range_key],
                retry=False,
                ignore_result=True,
            )
        except Exception:
            return

    threading.Thread(target=enqueue, daemon=True).start()
    return True


def _empty_payload(project, range_key):
    start_date, end_date = services.resolve_period(project.timezone, range_key=range_key)
    previous_start, previous_end = services.previous_period(start_date, end_date)
    return {
        'schema_version': services.OVERVIEW_PAYLOAD_SCHEMA_VERSION,
        'project': {'id': project.id, 'name': project.name},
        'period': {
            'range_key': range_key,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'previous_start_date': previous_start.isoformat(),
            'previous_end_date': previous_end.isoformat(),
        },
        'freshness': {
            'generated_at': None,
            'source_max_event_ts': None,
            'is_stale': True,
            'pending_rebuild': True,
        },
        'kpis': [],
        'rows': [],
        'change_aware_rows': [],
        'page_metrics_rows': [],
        'product_area_summary': [],
        'productAreas': [],
        'top_pages_by_visits_over_time': {'granularity': 'day', 'labels': [], 'series': []},
        'top_pages_by_engaged_time_over_time': {'granularity': 'day', 'labels': [], 'series': []},
        'engaged_time_treemap': {'total_engaged_seconds': 0, 'nodes': []},
        'sankey': {'nodes': [], 'links': []},
        'two_way_movement': {'rows': [], 'limit': 10, 'total_pairs': 0},
        'top_actions_by_page': [],
        'top_actions_by_page_group': [],
        'company_engagement_by_product_area': [],
        'company_engagement_by_page_group': [],
        'top_clicked_elements': [],
    }


def _is_current_payload_schema(schema_version):
    return services.is_current_overview_payload_schema(schema_version)


def _payload_script_text(payload):
    return mark_safe(services.to_json_script_text(payload))


def _filter_page_metrics_rows(rows, request):
    query = str(request.GET.get('q') or '').strip().lower()
    if not query:
        return rows or []
    return [
        row for row in rows or []
        if query in str(row.get('page_name') or row.get('pageName') or '').lower()
    ]


def _page_metrics_table_payload(payload, request):
    rows = _filter_page_metrics_rows(
        payload.get('page_metrics_rows') or payload.get('change_aware_rows') or [],
        request,
    )
    return paginate_cached_rows(
        rows,
        request,
        default_page_size=PAGE_METRICS_TABLE_PAGE_SIZE,
        default_sort_key='companies',
        default_sort_direction='desc',
        sort_getters=PAGE_METRICS_SORT_GETTERS,
        fallback_getter=lambda row: row.get('page_name') or '',
    )


def _project_top_action_groups_for_client(groups):
    projected = []
    for group in groups or []:
        if not isinstance(group, dict):
            continue
        actions = sorted(
            (
                action
                for action in group.get('actions') or []
                if isinstance(action, dict)
            ),
            key=lambda action: _analytics_number(
                action.get('clicks', action.get('clicks_count')),
            ),
            reverse=True,
        )
        projected.append(
            {
                **group,
                'actions': actions[:PAGES_TOP_ACTIONS_PER_GROUP_LIMIT],
            }
        )
        if len(projected) >= PAGES_TOP_ACTION_GROUP_LIMIT:
            break
    return projected


def _project_sankey_for_client(sankey):
    sankey = sankey if isinstance(sankey, dict) else {}
    source_nodes = [
        node
        for node in sankey.get('nodes') or []
        if isinstance(node, dict)
    ]
    candidates = []
    for link in sankey.get('links') or []:
        if not isinstance(link, dict):
            continue
        source = str(link.get('source') or '').strip()
        target = str(link.get('target') or '').strip()
        value = _analytics_number(link.get('value'))
        if not source or not target or value <= 0:
            continue
        normalized_value = int(value) if value.is_integer() else value
        candidates.append(
            {
                **link,
                'source': source,
                'target': target,
                'value': normalized_value,
            },
        )
    candidates.sort(
        key=lambda link: _analytics_number(link.get('value')),
        reverse=True,
    )

    adjacency = {}
    selected_links = []
    selected_node_names = set()

    def would_create_cycle(source, target):
        if source == target:
            return True
        visited = set()
        stack = [target]
        while stack:
            node = stack.pop()
            if node == source:
                return True
            if node in visited:
                continue
            visited.add(node)
            stack.extend(adjacency.get(node, ()))
        return False

    for link in candidates:
        if len(selected_links) >= PAGES_OVERVIEW_SANKEY_MAX_LINKS:
            break
        source = link['source']
        target = link['target']
        added_node_count = sum(
            name not in selected_node_names
            for name in (source, target)
        )
        if (
            len(selected_node_names) + added_node_count
            > PAGES_OVERVIEW_SANKEY_MAX_NODES
        ):
            continue
        if would_create_cycle(source, target):
            continue
        selected_links.append(link)
        selected_node_names.update((source, target))
        adjacency.setdefault(source, set()).add(target)

    selected_nodes = [
        node
        for node in source_nodes
        if str(node.get('name') or node.get('label') or '').strip()
        in selected_node_names
    ]
    return {
        'nodes': selected_nodes,
        'links': selected_links,
    }


def _with_pages_overview_table_payload(payload, request):
    table_payload = _page_metrics_table_payload(payload, request)
    selector_rows = _page_selector_rows(payload.get('change_aware_rows') or payload.get('rows') or [])
    client_payload = {**payload}
    for server_only_key in (
        'rows',
        'page_metrics_rows',
        'kpi_daily_rows',
        'top_actions_by_page',
        'company_engagement_by_product_area',
    ):
        client_payload.pop(server_only_key, None)
    client_payload['top_actions_by_page_group'] = _project_top_action_groups_for_client(
        payload.get('top_actions_by_page_group'),
    )
    client_payload['company_engagement_by_page_group'] = (
        payload.get('company_engagement_by_page_group') or []
    )[:PAGES_TOP_ACTION_GROUP_LIMIT]
    client_payload['sankey'] = _project_sankey_for_client(payload.get('sankey'))
    client_payload['page_selector_rows'] = selector_rows
    client_payload['change_aware_rows'] = [
        {
            key: value
            for key, value in row.items()
            if key != 'daily_kpi_trends'
        }
        if isinstance(row, dict)
        else row
        for row in table_payload['rows']
    ]
    table_data = payload.get('tableData')
    client_payload['tableData'] = dict(table_data) if isinstance(table_data, dict) else {}
    client_payload['tableData']['pageMetrics'] = {
        key: value
        for key, value in table_payload.items()
        if key != 'rows'
    }
    return client_payload


def _page_detail_table_payload(payload, request, table_name):
    if table_name == 'companies':
        return paginate_cached_rows(
            payload.get('companies') or [],
            request,
            default_page_size=PAGE_DETAIL_COMPANIES_TABLE_PAGE_SIZE,
            default_sort_key='engaged',
            default_sort_direction='desc',
            sort_getters=PAGE_DETAIL_COMPANIES_SORT_GETTERS,
            fallback_getter=lambda row: row.get('company') or '',
        )
    if table_name == 'champions':
        return paginate_cached_rows(
            payload.get('champions') or [],
            request,
            default_page_size=PAGE_DETAIL_CHAMPIONS_TABLE_PAGE_SIZE,
            default_sort_key='engaged',
            default_sort_direction='desc',
            sort_getters=PAGE_DETAIL_CHAMPIONS_SORT_GETTERS,
            fallback_getter=lambda row: row.get('user') or '',
        )
    return None


def _with_page_detail_table_payloads(payload, request):
    if not payload:
        return payload
    companies_table = _page_detail_table_payload(payload, request, 'companies')
    champions_table = _page_detail_table_payload(payload, request, 'champions')
    client_payload = {**payload}
    client_payload['companies'] = companies_table['rows']
    client_payload['champions'] = champions_table['rows']
    client_payload.setdefault('tableData', {})['companies'] = companies_table
    client_payload.setdefault('tableData', {})['champions'] = champions_table
    return client_payload


def render_project_pages(request, project, *, is_demo_view=False):
    range_key = _range_key(request)
    company_attribute_filter_attributes = (
        load_company_attribute_filter_attributes(project)
    )
    company_scope = resolve_company_scope(
        request,
        project,
        attributes=company_attribute_filter_attributes,
        is_demo_view=is_demo_view,
    )
    company_attribute_filter_state = company_scope.state
    canonical_redirect = canonical_company_scope_redirect(request, company_scope)
    if canonical_redirect is not None:
        return canonical_redirect
    restored = analytics_filter_state.restore_redirect(
        request,
        project,
        analytics_filter_state.PAGES_OVERVIEW,
        is_demo_view=is_demo_view,
    )
    if restored is not None:
        return restored
    cache, queued = filtered_overview.read_variant(
        filtered_overview.PAGES,
        project,
        range_key,
        company_attribute_filter_state,
        fetch=services.get_cached_overview_payload,
        schema_is_current=_is_current_payload_schema,
    )
    cache_status = 'ready'
    payload = {}
    payload_script_text = None

    if cache:
        if cache.get('is_stale'):
            cache_status = 'stale'
            if not company_attribute_filter_state.active:
                _best_effort_queue_overview_rebuild(project.id, range_key)
        payload = services.normalize_overview_payload(cache.get('payload_json') or {})
        payload = _with_pages_overview_table_payload(payload, request)
        payload_script_text = _payload_script_text(payload)
    else:
        payload = services.normalize_overview_payload(_empty_payload(project, range_key))
        payload = _with_pages_overview_table_payload(payload, request)
        payload_script_text = _payload_script_text(payload)
        if company_attribute_filter_state.active:
            cache_status = 'preparing'
        else:
            cache_status = 'missing'
            _best_effort_queue_overview_rebuild(project.id, range_key)

    selected_product_area_keys = services.resolve_product_area_filter_keys(
        payload,
        _product_area_query_values(request),
    )
    product_area_options = services.overview_product_area_filter_options(payload)
    selected_product_area_key_set = set(selected_product_area_keys)
    product_area_options = [
        {
            **option,
            'is_selected': option.get('key') in selected_product_area_key_set,
        }
        for option in product_area_options
    ]
    if selected_product_area_keys:
        raw_payload = services.filter_overview_payload_by_product_areas(
            services.normalize_overview_payload((cache.get('payload_json') if cache else _empty_payload(project, range_key)) or {}),
            selected_product_area_keys,
        )
        payload = _with_pages_overview_table_payload(raw_payload, request)
        payload_script_text = _payload_script_text(payload)
    analytics_is_empty = is_pages_overview_empty(payload)
    analytics_is_preparing = cache_status == 'preparing'
    company_attribute_filter_context = build_company_attribute_filter_context(
        project,
        company_attribute_filter_state,
        surface='pages',
        preview_url=(
            reverse('demo_company_attribute_filter_preview')
            if is_demo_view
            else project_route(project, 'project_company_attribute_filter_preview')
        ),
        attributes=company_attribute_filter_attributes,
        scope=company_scope,
        segment_urls=(
            demo_company_segment_urls()
            if is_demo_view
            else company_segment_urls(project)
        ),
    )
    analytics_filter_state.remember(
        request,
        project,
        analytics_filter_state.PAGES_OVERVIEW,
        scope=company_scope,
        page_values={
            'range': range_key,
            'product_area': selected_product_area_keys,
        },
        is_demo_view=is_demo_view,
    )

    return render(
        request,
        'pages/overview.html',
        {
            'project': project,
            'pages_overview_payload': payload,
            'pages_overview_payload_json': payload_script_text,
            'pages_payload': payload,
            'pages_range_key': range_key,
            'pages_range_label': PAGES_RANGE_LABELS.get(range_key, PAGES_RANGE_LABELS['last_30_days']),
            'pages_range_options': PAGES_RANGE_OPTIONS,
            'pages_filter_query_suffix': _product_area_query_suffix(
                selected_product_area_keys,
                company_scope.canonical_pairs,
            ),
            'pages_cache_status': cache_status,
            'analytics_is_empty': analytics_is_empty,
            'analytics_is_preparing': analytics_is_preparing,
            'analytics_surface': 'pages',
            'analytics_variant_status_url': (
                reverse('demo_analytics_variant_status')
                if is_demo_view
                else project_route(project, 'project_analytics_variant_status')
            ),
            'analytics_empty_period_days': PAGES_RANGE_DAYS.get(range_key, 30),
            'pages_product_area_filter_options': product_area_options,
            'pages_product_area_filter_selected_keys': selected_product_area_keys,
            'pages_product_area_filter_label': _product_area_filter_label(product_area_options),
            'pages_product_area_filter_has_selection': bool(selected_product_area_keys),
            'company_attribute_filter_state': company_attribute_filter_state,
            'pages_filters_hash': company_attribute_filter_state.filters_hash,
            **company_attribute_filter_context,
            'pages_overview_table_url': reverse('demo_pages_table_data') if is_demo_view else project_route(project, 'project_pages_table_data'),
            'is_demo_view': is_demo_view,
            'demo_project_id': project.id if is_demo_view else None,
            'demo_project_display_name': DEMO_PROJECT_DISPLAY_NAME,
        },
    )


def _pages_overview_table_response(request, project):
    range_key = _range_key(request)
    company_attribute_filter_state = parse_company_attribute_filters(
        project,
        request.GET,
    )
    cache, queued = filtered_overview.read_variant(
        filtered_overview.PAGES,
        project,
        range_key,
        company_attribute_filter_state,
        fetch=services.get_cached_overview_payload,
        schema_is_current=_is_current_payload_schema,
    )
    if not cache:
        if not company_attribute_filter_state.active:
            queued = _best_effort_queue_overview_rebuild(project.id, range_key)
        return JsonResponse({'pending': True, 'queued': queued, 'rows': [], 'pagination': {'page': 1, 'pageSize': PAGE_METRICS_TABLE_PAGE_SIZE, 'totalRows': 0, 'totalPages': 1}}, status=202)

    payload = services.normalize_overview_payload(cache.get('payload_json') or {})
    selected_product_area_keys = services.resolve_product_area_filter_keys(
        payload,
        _product_area_query_values(request),
    )
    if selected_product_area_keys:
        payload = services.filter_overview_payload_by_product_areas(payload, selected_product_area_keys)
    table_payload = _page_metrics_table_payload(payload, request)
    return JsonResponse({'table': 'pageMetrics', **table_payload}, json_dumps_params={'separators': (',', ':')})


@login_required
@require_project_member
def project_pages(request, project_id):
    project = get_accessible_project_or_404(request.user, project_id)
    return render_project_pages(request, project)


@login_required
@require_project_member
def project_pages_table_data(request, project_id):
    project = get_accessible_project_or_404(request.user, project_id)
    return _pages_overview_table_response(request, project)


def demo_project_pages(request):
    return render_project_pages(request, get_demo_project(), is_demo_view=True)


def demo_project_pages_table_data(request):
    return _pages_overview_table_response(request, get_demo_project())


def _page_selector_rows(rows):
    selector_rows = []
    seen_page_rule_ids = set()

    for row in rows or []:
        if not isinstance(row, dict):
            continue
        page_rule_id = str(
            row.get('page_rule_id')
            or row.get('pageRuleId')
            or row.get('pageId')
            or row.get('id')
            or ''
        ).strip()
        if not page_rule_id or page_rule_id in seen_page_rule_ids:
            continue

        page_name = (
            row.get('page_name')
            or row.get('displayName')
            or row.get('pageName')
            or row.get('route')
            or page_rule_id
        )
        product_area_name = (
            row.get('page_group')
            or row.get('productAreaName')
            or row.get('product_area_name')
            or row.get('product_area')
            or 'Unassigned'
        )
        product_area_key = (
            row.get('product_area_key')
            or row.get('productAreaKey')
            or row.get('product_area_id')
            or row.get('productAreaId')
            or ''
        )
        page_display_key = (
            row.get('page_display_key')
            or row.get('pageDisplayKey')
            or ''
        )

        seen_page_rule_ids.add(page_rule_id)
        selector_rows.append(
            {
                'page_rule_id': page_rule_id,
                'pageRuleId': page_rule_id,
                'page_name': page_name,
                'pageName': page_name,
                'displayName': page_name,
                'page_group': product_area_name,
                'productAreaName': product_area_name,
                'product_area_key': product_area_key,
                'productAreaKey': product_area_key,
                'page_display_key': page_display_key,
                'pageDisplayKey': page_display_key,
                'companies_count': row.get('companies_count') or 0,
                'visits_count': row.get('visits_count') or 0,
                'engaged_seconds': row.get('engaged_seconds') or 0,
            }
        )

    return selector_rows


def _detail_payload_bundle(request, project, page_rule_id, selected_range_key):
    cache = services.get_cached_detail_payload(project.id, page_rule_id, range_key=selected_range_key)
    selected_payload = None
    if cache and not cache.get('is_stale') and _is_current_payload_schema(cache.get('schema_version')):
        colored_payload = services.apply_page_detail_product_area_colors(
            project.id,
            cache.get('payload_json'),
        )
        selected_payload = _with_page_detail_table_payloads(colored_payload, request)
    selector_rows = _page_selector_rows(
        services.get_cached_overview_detail_rows(project.id, range_key=selected_range_key)
    )

    return {
        'selected_range_key': selected_range_key,
        'selected_period_days': selected_payload['period']['days'] if selected_payload else None,
        'payload': selected_payload,
        'period_payloads': {},
        'page_selector_rows': selector_rows,
    }


def render_project_page_detail(request, project, page_rule_id, *, is_demo_view=False):
    range_key = _detail_range_key(request)
    payload_bundle = _detail_payload_bundle(request, project, page_rule_id, range_key)
    payload = payload_bundle.get('payload')
    analytics_is_empty = payload is not None and is_page_detail_empty(payload)
    if payload is None:
        _best_effort_queue_overview_rebuild(project.id, range_key)
    overview_url = reverse('demo_pages') if is_demo_view else project_route(project, 'project_pages')
    detail_base_url = (
        reverse('demo_page_detail', kwargs={'page_rule_id': '__PAGE_RULE_ID__'})
        if is_demo_view
        else project_route(
            project,
            'project_page_detail',
            page_rule_id='__PAGE_RULE_ID__',
        )
    )
    selected_page_exists = any(
        str(row.get('page_rule_id') or row.get('pageRuleId') or '') == str(page_rule_id)
        for row in payload_bundle.get('page_selector_rows') or []
    )
    if payload is None and not selected_page_exists:
        alphabetical_pages = sorted(
            payload_bundle.get('page_selector_rows') or [],
            key=lambda row: (
                str(row.get('page_name') or row.get('pageName') or '').strip().lower(),
                str(row.get('page_rule_id') or row.get('pageRuleId') or ''),
            ),
        )
        if alphabetical_pages:
            fallback_page_id = str(
                alphabetical_pages[0].get('page_rule_id')
                or alphabetical_pages[0].get('pageRuleId')
                or ''
            )
            if fallback_page_id and fallback_page_id != str(page_rule_id):
                target = detail_base_url.replace('__PAGE_RULE_ID__', fallback_page_id)
                return redirect(f'{target}?{request.GET.urlencode()}' if request.GET else target)

    metric_dynamics_url = reverse('demo_page_metric_dynamics', kwargs={'page_rule_id': page_rule_id}) if is_demo_view else project_route(
        project,
        'project_page_metric_dynamics',
        page_rule_id=page_rule_id,
    )
    company_detail_base_url = reverse('demo_company_detail', kwargs={'company_id': 'detail'}) if is_demo_view else project_route(
        project,
        'project_company_detail',
        company_id='detail',
    )
    user_detail_base_url = reverse('demo_user_detail', kwargs={'user_id': 'detail'}) if is_demo_view else project_route(
        project,
        'project_user_detail',
        user_id='detail',
    )

    return render(
        request,
        'pages/detail.html',
        {
            'project': project,
            'page_rule_id': page_rule_id,
            'pages_detail_payload': payload,
            'pages_detail_payload_json': _payload_script_text(payload_bundle),
            'pages_range_key': range_key,
            'pages_range_label': PAGES_RANGE_LABELS.get(range_key, PAGES_RANGE_LABELS['last_30_days']),
            'pages_range_options': PAGES_RANGE_OPTIONS,
            'pages_period_query_suffix': preserved_period_query_suffix(request),
            'pages_overview_url': overview_url,
            'pages_detail_base_url': detail_base_url,
            'company_detail_base_url': company_detail_base_url,
            'user_detail_base_url': user_detail_base_url,
            'page_metric_dynamics_url': metric_dynamics_url,
            'page_detail_table_url': reverse('demo_page_detail_table_data', kwargs={'page_rule_id': page_rule_id}) if is_demo_view else project_route(
                project,
                'project_page_detail_table_data',
                page_rule_id=page_rule_id,
            ),
            'analytics_is_empty': analytics_is_empty,
            'analytics_empty_period_days': PAGES_RANGE_DAYS.get(range_key, 30),
            'page_detail_title': _page_detail_title(payload, page_rule_id),
            'is_demo_view': is_demo_view,
            'demo_project_id': project.id if is_demo_view else None,
            'demo_project_display_name': DEMO_PROJECT_DISPLAY_NAME,
        },
    )


@login_required
@require_project_member
def project_page_detail(request, project_id, page_rule_id):
    project = get_accessible_project_or_404(request.user, project_id)
    return render_project_page_detail(request, project, page_rule_id)


def demo_project_page_detail(request, page_rule_id):
    return render_project_page_detail(request, get_demo_project(), page_rule_id, is_demo_view=True)


def _page_detail_table_response(request, project, page_rule_id):
    range_key = _detail_range_key(request)
    table_name = request.GET.get('table') or ''
    cache = services.get_cached_detail_payload(project.id, page_rule_id, range_key=range_key)
    if not cache or cache.get('is_stale') or not _is_current_payload_schema(cache.get('schema_version')):
        queued = _best_effort_queue_overview_rebuild(project.id, range_key)
        return JsonResponse(
            {
                'pending': True,
                'queued': queued,
                'table': table_name,
                'rows': [],
                'pagination': {'page': 1, 'pageSize': PAGE_DETAIL_COMPANIES_TABLE_PAGE_SIZE, 'totalRows': 0, 'totalPages': 1},
            },
            status=202,
            json_dumps_params={'separators': (',', ':')},
        )

    table_payload = _page_detail_table_payload(cache.get('payload_json') or {}, request, table_name)
    if table_payload is None:
        return JsonResponse({'error': 'Unknown table'}, status=400)
    return JsonResponse({'table': table_name, **table_payload}, json_dumps_params={'separators': (',', ':')})


@login_required
@require_project_member
def project_page_detail_table_data(request, project_id, page_rule_id):
    project = get_accessible_project_or_404(request.user, project_id)
    return _page_detail_table_response(request, project, page_rule_id)


def demo_project_page_detail_table_data(request, page_rule_id):
    return _page_detail_table_response(request, get_demo_project(), page_rule_id)


def render_page_metric_dynamics(request, project, page_rule_id, *, is_demo_view=False):
    range_key = _detail_range_key(request)
    metric_dynamics_url = reverse('demo_page_metric_dynamics', kwargs={'page_rule_id': page_rule_id}) if is_demo_view else project_route(
        project,
        'project_page_metric_dynamics',
        page_rule_id=page_rule_id,
    )
    return render(
        request,
        'pages/partials/detail_metric_dynamics.html',
        {
            'project': project,
            'page_rule_id': page_rule_id,
            'pages_range_key': range_key,
            'page_metric_dynamics_url': metric_dynamics_url,
            'page_metric_dynamics_show_peers': _show_peers(request),
            'is_demo_view': is_demo_view,
            'demo_project_id': project.id if is_demo_view else None,
            'demo_project_display_name': DEMO_PROJECT_DISPLAY_NAME,
        },
    )


@login_required
@require_project_member
def project_page_metric_dynamics(request, project_id, page_rule_id):
    project = get_accessible_project_or_404(request.user, project_id)
    return render_page_metric_dynamics(request, project, page_rule_id)


def demo_project_page_metric_dynamics(request, page_rule_id):
    return render_page_metric_dynamics(request, get_demo_project(), page_rule_id, is_demo_view=True)


@login_required
@require_project_member
def scatter_tooltips(request, project_id):
    range_key = _range_key(request)
    cache = services.get_cached_scatter_tooltips(project_id, range_key=range_key)
    if cache:
        return JsonResponse(cache['payload_json'])

    queued = _best_effort_queue_tooltip_rebuild(project_id, range_key)
    return JsonResponse(
        {
            'pending': True,
            'queued': queued,
            'range_key': range_key,
            'items': [],
        },
        status=202,
    )
