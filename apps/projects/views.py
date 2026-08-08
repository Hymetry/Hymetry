import json
import threading
from collections import defaultdict
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo, available_timezones

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_slug
from django.http import Http404
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Max, Sum
from django.http import HttpRequest, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_http_methods, require_POST

from apps.pages import (
    company_analytics,
    company_detail_analytics,
    filtered_overview,
    services as pages_services,
    user_analytics,
    user_detail_analytics,
)
from apps.pages.table_pagination import paginate_cached_rows
from apps.pages.tasks import (
    build_company_detail_cache_task,
    build_user_detail_cache_task,
)
from apps.pages.models import RawPageDailyMetric
from apps.tracker.models import AnalyticsEvent, Event, ProjectPageRule
from apps.users.forms import ProjectForm
from . import analytics_filter_state
from .company_attribute_filter_support import (
    build_company_attribute_filter_context,
    canonical_company_scope_redirect,
)
from .company_attribute_filters import parse_company_attribute_filters
from .company_segments import (
    company_segment_urls,
    demo_company_segment_urls,
    resolve_company_scope,
)
from .demo import DEMO_PROJECT_DISPLAY_NAME, ensure_project_writable, get_demo_project
from .access import (
    active_workspace_memberships,
    effective_workspace_role,
    get_accessible_project_or_404,
    get_accessible_workspace_or_404,
    get_workspace_membership,
    is_last_owner,
    require_project_settings_editor,
    user_can_assign_workspace_role,
    user_can_create_project,
    user_can_create_workspace,
    user_can_edit_project_settings,
    user_can_edit_workspace,
    user_can_invite_role,
    user_can_manage_workspace_openai_key,
    user_can_remove_workspace_member,
    workspace_role_label,
)
from .decorators import require_project_member
from .models import (
    Project,
    ProjectStatus,
    Workspace,
    WorkspaceOpenAICredential,
    WorkspaceMemberRole,
    WorkspaceMemberStatus,
    WorkspaceMembership,
)
from .services import (
    archive_project,
    archive_workspace,
    change_workspace_slug,
    create_first_workspace_project,
    create_project_in_workspace,
    create_workspace_for_user,
    add_local_workspace_member,
    change_workspace_member_role_safely,
    normalize_timezone,
    remove_workspace_member_safely,
    workspace_has_active_projects,
    rename_workspace,
)
from .statuses import (
    project_effective_status,
    project_status_badge_class,
    project_status_label,
)
from .ai_credentials import (
    WorkspaceOpenAIKeyError,
    delete_workspace_openai_key,
    set_workspace_openai_key,
    validate_workspace_openai_key,
)
from .domain_utils import normalize_allowed_domains, normalize_workspace_website_url
from .url_helpers import preserved_period_query_suffix, project_route, workspace_route
from .utils import (
    TRACKING_MODE_ANALYTICS_AND_RECORDING,
    TRACKING_MODE_ANALYTICS_ONLY,
    generate_identify_settings_snippet,
    generate_tracking_script,
    get_tracking_mode_label,
    normalize_capture_modes,
    normalize_tracking_mode_choice,
)


def homepage(request):
    from apps.users.services import initial_admin_is_required

    if initial_admin_is_required():
        return redirect('users:initial_admin_setup')
    if request.user.is_authenticated:
        return redirect('project_list')

    return redirect('sign_in')


def project_detail_redirect(request, project_id):
    project = get_object_or_404(
        Project.active.select_related('workspace'),
        pk=project_id,
        workspace__archived_at__isnull=True,
    )
    return redirect(project_route(project, 'project_pages'))


PRODUCT_AREAS_PER_PAGE = 10
PRODUCT_AREA_EXAMPLES_PER_RULE = 3
PRODUCT_AREA_EXAMPLE_FALLBACK_SCAN_LIMIT = 200
COMPANIES_RANGE_OPTIONS = (
    ('last_7_days', 'Last 7 complete days'),
    ('last_30_days', 'Last 30 complete days'),
    ('last_90_days', 'Last 90 complete days'),
    ('last_180_days', 'Last 180 complete days'),
)
COMPANIES_SUPPORTED_RANGES = {key for key, _ in COMPANIES_RANGE_OPTIONS}
COMPANIES_PERIOD_RANGE_KEYS = {
    7: 'last_7_days',
    30: 'last_30_days',
    90: 'last_90_days',
    180: 'last_180_days',
}
COMPANIES_RANGE_DAYS = {range_key: days for days, range_key in COMPANIES_PERIOD_RANGE_KEYS.items()}
COMPANIES_TABLE_PAGE_SIZE = 20
COMPANIES_AT_RISK_TABLE_PAGE_SIZE = 20
COMPANIES_NEW_REACTIVATED_TABLE_PAGE_SIZE = 20
COMPANIES_EXPANSION_TABLE_PAGE_SIZE = 20
COMPANY_DETAIL_TOP_PAGES_TABLE_PAGE_SIZE = 15
COMPANY_DETAIL_USERS_TABLE_PAGE_SIZE = 20
USER_DETAIL_PAGES_TABLE_PAGE_SIZE = 15

COMPANIES_TABLE_SORT_GETTERS = {
    'name': lambda row: row.get('name') or row.get('companyName') or '',
    'status': lambda row: row.get('status') or '',
    'activeUsers': lambda row: row.get('activeUsers') or 0,
    'pagesUsed': lambda row: row.get('pagesUsed') or 0,
    'visits': lambda row: row.get('visits') or 0,
    'engagedSeconds': lambda row: row.get('engagedSeconds') or 0,
    'avgEngagedSecondsPerUser': lambda row: row.get('avgEngagedSecondsPerUser') or 0,
    'interactionPct': lambda row: row.get('interactionPct') or 0,
}

COMPANIES_AT_RISK_TABLE_SORT_GETTERS = {
    'name': lambda row: row.get('name') or row.get('companyName') or '',
    # The rendered "Risk reason" column orders by severity, not by reason text:
    # the badge is only the first of several reasons the score already weighs.
    'riskScore': lambda row: row.get('riskScore') or 0,
    'activeUsers': lambda row: row.get('activeUsers') or 0,
    'engagedSeconds': lambda row: row.get('engagedSeconds') or 0,
    'productAreasUsed': lambda row: row.get('productAreasUsed') or 0,
    # The browser only recomputes this when the stored value is blank or one of
    # the retired wordings, and a payload old enough to hold one of those fails
    # the schema check before it can render. What is stored is what is shown.
    'suggestedAction': lambda row: row.get('suggestedAction') or '',
}

COMPANIES_NEW_REACTIVATED_TABLE_SORT_GETTERS = {
    'name': lambda row: row.get('name') or row.get('companyName') or '',
    # Ordered by progress, not by the label's spelling.
    'activationStage': lambda row: company_analytics.ACTIVATION_STAGE_ORDER.get(row.get('activationStage'), 0),
    'daysSinceStart': lambda row: row.get('daysSinceStart') or 0,
    'activeUsers': lambda row: row.get('activeUsers') or 0,
    'engagedSeconds': lambda row: row.get('engagedSeconds') or 0,
    'productAreasUsed': lambda row: row.get('productAreasUsed') or 0,
}

COMPANIES_EXPANSION_TABLE_SORT_GETTERS = {
    'name': lambda row: row.get('name') or row.get('companyName') or '',
    # The badge shows a band; the score behind it is what orders the rows.
    'potentialScore': lambda row: row.get('potentialScore') or 0,
    'reason': lambda row: row.get('reason') or '',
    'activeUsers': lambda row: row.get('activeUsers') or 0,
    'avgEngagedSecondsPerUser': lambda row: row.get('avgEngagedSecondsPerUser') or 0,
    'interactionPct': lambda row: row.get('interactionPct') or 0,
    'productAreasUsed': lambda row: row.get('productAreasUsed') or 0,
    'suggestedAction': lambda row: row.get('suggestedAction') or '',
}

COMPANY_DETAIL_TOP_PAGES_SORT_GETTERS = {
    'pageName': lambda row: row.get('pageName') or '',
    'productArea': lambda row: row.get('productArea') or '',
    'users': lambda row: row.get('users') or 0,
    'visits': lambda row: row.get('visits') or 0,
    'engagedSeconds': lambda row: row.get('engagedSeconds') or 0,
    'avgVisitSeconds': lambda row: row.get('avgVisitSeconds') or 0,
    'interactionPct': lambda row: row.get('interactionPct') or 0,
}

COMPANY_DETAIL_USERS_SORT_GETTERS = {
    'name': lambda row: row.get('name') or '',
    'status': lambda row: row.get('status') or '',
    'lastActiveDays': lambda row: row.get('lastActiveDays') or 0,
    'activeDays': lambda row: row.get('activeDays') or 0,
    'visits': lambda row: row.get('visits') or 0,
    'engagedSeconds': lambda row: row.get('engagedSeconds') or 0,
    'interactionPct': lambda row: row.get('interactionPct') or 0,
    'topArea': lambda row: row.get('topArea') or '',
}

USER_DETAIL_PAGES_SORT_GETTERS = {
    'pageName': lambda row: row.get('pageName') or '',
    'productArea': lambda row: row.get('productArea') or row.get('productAreaName') or '',
    'visits': lambda row: row.get('visits') or 0,
    'shareOfUserTimePct': lambda row: row.get('shareOfUserTimePct') or 0,
    'engagedSeconds': lambda row: row.get('engagedSeconds') or 0,
    'avgVisitSeconds': lambda row: row.get('avgVisitSeconds') or 0,
    'interactionPct': lambda row: row.get('interactionPct') or row.get('interactionRate') or 0,
    'peerUsagePct': lambda row: row.get('peerUsagePct') or 0,
    'lastUsedAt': lambda row: row.get('lastUsedAt') or '',
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


def is_companies_overview_empty(payload):
    if not isinstance(payload, dict):
        return True
    scatter = payload.get('scatter') if isinstance(payload.get('scatter'), dict) else {}
    total_active_companies = _analytics_number(scatter.get('totalActiveCompanies'))
    return not (
        total_active_companies > 0
        or _analytics_metrics_have_activity(payload.get('kpis'))
        or _analytics_rows_have_activity(
            payload.get('companies'),
            ['activeUsers', 'visits', 'engagedSeconds', 'pagesUsed', 'productAreasUsed'],
        )
    )


def is_company_detail_empty(payload):
    if not isinstance(payload, dict):
        return True
    return not (
        _analytics_row_has_activity(payload.get('company'), ['activeUsers', 'visits', 'engagedSeconds', 'pagesUsed', 'productAreasUsed'])
        or _analytics_rows_have_activity(payload.get('topPages'), ['visits', 'engagedSeconds', 'users'])
        or _analytics_rows_have_activity(payload.get('users'), ['visits', 'engagedSeconds', 'activeDays'])
        or _analytics_rows_have_activity(payload.get('metricCards'), ['currentValue', 'rawValue', 'value'])
    )


def is_users_overview_empty(payload):
    if not isinstance(payload, dict):
        return True
    scatter_meta = payload.get('scatterMeta') if isinstance(payload.get('scatterMeta'), dict) else {}
    total_active_users = _analytics_number(scatter_meta.get('totalActiveUsers'))
    return not (
        total_active_users > 0
        or _analytics_metrics_have_activity(payload.get('kpis'))
        or _analytics_rows_have_activity(
            payload.get('users'),
            ['visitsCount', 'visits', 'engagedSeconds', 'activeDays', 'sessionsCount'],
        )
    )


def is_user_detail_empty(payload):
    if not isinstance(payload, dict):
        return True
    return not (
        _analytics_row_has_activity(payload.get('userMetrics'), ['engagedSeconds', 'visits', 'activeDays', 'pagesUsed', 'visitsWithClick'])
        or _analytics_rows_have_activity(payload.get('pagesUsed'), ['visits', 'engagedSeconds', 'clicks'])
        or _analytics_rows_have_activity(payload.get('dailyUsage'), ['visits', 'engagedSeconds', 'clicks'])
    )


def _companies_range_key(request):
    period = request.GET.get('period')
    try:
        period_days = int(str(period or '').rstrip('d')) if period is not None else None
    except (TypeError, ValueError):
        period_days = None
    if period_days in COMPANIES_PERIOD_RANGE_KEYS:
        return COMPANIES_PERIOD_RANGE_KEYS[period_days]

    value = request.GET.get('range', 'last_30_days')
    return value if value in COMPANIES_SUPPORTED_RANGES else 'last_30_days'


def _show_peers(request):
    return str(request.GET.get('show_peers', '')).lower() in {'1', 'true', 'yes', 'on'}


def _best_effort_queue_company_detail_rebuild(project_id, company_id, range_key):
    company_id = str(company_id or '').strip()
    if not company_id:
        return False
    if not getattr(settings, 'COMPANIES_QUEUE_REBUILDS_ON_REQUEST', getattr(settings, 'PAGES_QUEUE_REBUILDS_ON_REQUEST', True)):
        return False

    def enqueue():
        try:
            build_company_detail_cache_task.apply_async(
                args=[project_id, company_id, range_key],
                retry=False,
                ignore_result=True,
            )
        except Exception:
            return

    threading.Thread(target=enqueue, daemon=True).start()
    return True


def _best_effort_queue_user_detail_rebuild(project_id, user_id, range_key):
    user_id = str(user_id or '').strip()
    if not user_id:
        return False
    if not getattr(settings, 'USERS_QUEUE_REBUILDS_ON_REQUEST', getattr(settings, 'PAGES_QUEUE_REBUILDS_ON_REQUEST', True)):
        return False

    def enqueue():
        try:
            build_user_detail_cache_task.apply_async(
                args=[project_id, user_id, range_key],
                retry=False,
                ignore_result=True,
            )
        except Exception:
            return

    threading.Thread(target=enqueue, daemon=True).start()
    return True


def _pending_table_response(table_name, page_size, queued=False, status=202):
    return JsonResponse(
        {
            'pending': True,
            'queued': queued,
            'table': table_name,
            'rows': [],
            'pagination': {
                'page': 1,
                'pageSize': page_size,
                'totalRows': 0,
                'totalPages': 1,
            },
        },
        status=status,
        json_dumps_params={'separators': (',', ':')},
    )


def _table_request_for(request, table_name):
    """
    Scope paging parameters to the table that asked for them.

    The Companies overview embeds the first page of two independent tables in
    one document, so an unscoped `page` or `sort` would move both at once. Only
    the table named in the request keeps the parameters; the other one renders
    its defaults.
    """

    if (request.GET.get('table') or 'companies') == table_name:
        return request
    return HttpRequest()


def _companies_table_payload(payload, request):
    return paginate_cached_rows(
        payload.get('companies') or [],
        _table_request_for(request, 'companies'),
        default_page_size=COMPANIES_TABLE_PAGE_SIZE,
        default_sort_key='engagedSeconds',
        default_sort_direction='desc',
        sort_getters=COMPANIES_TABLE_SORT_GETTERS,
        fallback_getter=lambda row: row.get('name') or row.get('companyName') or '',
    )


def _companies_at_risk_table_payload(payload, request):
    return paginate_cached_rows(
        payload.get('atRiskCompanies') or [],
        _table_request_for(request, 'atRisk'),
        default_page_size=COMPANIES_AT_RISK_TABLE_PAGE_SIZE,
        default_sort_key='riskScore',
        default_sort_direction='desc',
        sort_getters=COMPANIES_AT_RISK_TABLE_SORT_GETTERS,
        fallback_getter=lambda row: row.get('name') or row.get('companyName') or '',
    )


def _companies_new_reactivated_table_payload(payload, request):
    return paginate_cached_rows(
        payload.get('newReactivatedCompanies') or [],
        _table_request_for(request, 'newReactivated'),
        default_page_size=COMPANIES_NEW_REACTIVATED_TABLE_PAGE_SIZE,
        default_sort_key='activationStage',
        default_sort_direction='asc',
        sort_getters=COMPANIES_NEW_REACTIVATED_TABLE_SORT_GETTERS,
        fallback_getter=lambda row: row.get('name') or row.get('companyName') or '',
    )


def _companies_expansion_table_payload(payload, request):
    return paginate_cached_rows(
        payload.get('expansionOpportunities') or [],
        _table_request_for(request, 'expansion'),
        default_page_size=COMPANIES_EXPANSION_TABLE_PAGE_SIZE,
        default_sort_key='potentialScore',
        default_sort_direction='desc',
        sort_getters=COMPANIES_EXPANSION_TABLE_SORT_GETTERS,
        fallback_getter=lambda row: row.get('name') or row.get('companyName') or '',
    )


COMPANIES_OVERVIEW_TABLE_PAYLOADS = {
    'companies': (_companies_table_payload, COMPANIES_TABLE_PAGE_SIZE),
    'atRisk': (_companies_at_risk_table_payload, COMPANIES_AT_RISK_TABLE_PAGE_SIZE),
    'newReactivated': (_companies_new_reactivated_table_payload, COMPANIES_NEW_REACTIVATED_TABLE_PAGE_SIZE),
    'expansion': (_companies_expansion_table_payload, COMPANIES_EXPANSION_TABLE_PAGE_SIZE),
}


def _users_table_identified_only(request):
    value = request.GET.get('identified')
    if value is None:
        return True
    return str(value).strip().lower() not in {'0', 'false', 'no', 'off', 'all', 'any'}


_VARIANT_STATUS_FETCHERS = {
    filtered_overview.PAGES: (
        lambda: pages_services.get_cached_overview_metadata,
        lambda: pages_services.is_current_overview_payload_schema,
    ),
    filtered_overview.COMPANIES: (
        lambda: company_analytics.get_cached_companies_overview_metadata,
        lambda: company_analytics.is_current_companies_payload_schema,
    ),
    filtered_overview.USERS: (
        lambda: user_analytics.get_cached_users_overview_metadata,
        lambda: user_analytics.is_current_users_payload_schema,
    ),
}


def _variant_status_response(request, project):
    """
    Report whether one filter variant is ready to render.

    The preparing state polls this instead of asking the user to refresh. It
    reads only variant metadata, so polling stays cheap no matter how large the
    payload being built is.
    """

    surface = str(request.GET.get('surface') or '').strip()
    if surface not in _VARIANT_STATUS_FETCHERS:
        return JsonResponse({'error': 'Unknown surface'}, status=400)

    range_key = _companies_range_key(request)
    state = parse_company_attribute_filters(project, request.GET)
    fetch_factory, schema_factory = _VARIANT_STATUS_FETCHERS[surface]
    cache, queued = filtered_overview.read_variant(
        surface,
        project,
        range_key,
        state,
        fetch=fetch_factory(),
        schema_is_current=schema_factory(),
    )
    return JsonResponse(
        {'surface': surface, 'range_key': range_key, 'ready': cache is not None, 'queued': queued},
        json_dumps_params={'separators': (',', ':')},
    )


@login_required
@require_project_member
@require_http_methods(["GET"])
def project_analytics_variant_status(request, project_id):
    project = get_accessible_project_or_404(request.user, project_id)
    return _variant_status_response(request, project)


@require_http_methods(["GET"])
def demo_analytics_variant_status(request):
    return _variant_status_response(request, get_demo_project())


def _users_overview_table_payload(project, request, *, range_key=None, filters_hash=None):
    state = parse_company_attribute_filters(project, request.GET)

    return user_analytics.get_cached_users_overview_table_page(
        project.id,
        range_key=range_key or _companies_range_key(request),
        filters_hash=filters_hash or state.filters_hash,
        page=request.GET.get('page', 1),
        page_size=request.GET.get('page_size') or request.GET.get('pageSize') or user_analytics.USERS_TABLE_PAGE_SIZE,
        sort_key=request.GET.get('sort') or user_analytics.USERS_TABLE_DEFAULT_SORT_KEY,
        sort_direction=request.GET.get('direction') or user_analytics.USERS_TABLE_DEFAULT_SORT_DIRECTION,
        company=request.GET.get('company'),
        status=request.GET.get('status'),
        query=request.GET.get('q'),
        role=request.GET.get('role'),
        identified_only=_users_table_identified_only(request),
        feature=request.GET.get('feature'),
    )


def _company_attribute_filter_context(project, scope, *, surface, is_demo_view):
    preview_url = (
        reverse('demo_company_attribute_filter_preview')
        if is_demo_view
        else project_route(project, 'project_company_attribute_filter_preview')
    )
    return build_company_attribute_filter_context(
        project,
        scope.state,
        surface=surface,
        preview_url=preview_url,
        scope=scope,
        segment_urls=(
            demo_company_segment_urls()
            if is_demo_view
            else company_segment_urls(project)
        ),
    )


def _company_attribute_filter_query_suffix(scope):
    query = urlencode(scope.canonical_pairs)
    return f'&{query}' if query else ''


def _with_companies_overview_table_payload(payload, request):
    table_payload = _companies_table_payload(payload, request)
    at_risk_payload = _companies_at_risk_table_payload(payload, request)
    new_reactivated_payload = _companies_new_reactivated_table_payload(payload, request)
    expansion_payload = _companies_expansion_table_payload(payload, request)
    client_payload = {**(payload or {})}
    client_payload['companies'] = table_payload['rows']
    client_payload['atRiskCompanies'] = at_risk_payload['rows']
    client_payload['newReactivatedCompanies'] = new_reactivated_payload['rows']
    client_payload['expansionOpportunities'] = expansion_payload['rows']
    table_data = client_payload.setdefault('tableData', {})
    table_data['companies'] = table_payload
    table_data['atRisk'] = at_risk_payload
    table_data['newReactivated'] = new_reactivated_payload
    table_data['expansion'] = expansion_payload
    return client_payload


def _company_detail_users_scatter_rows(users):
    rows = []
    for user in users or []:
        rows.append({
            'id': user.get('id') or user.get('userId'),
            'name': user.get('name'),
            'email': user.get('email'),
            'status': user.get('status'),
            'sessionsCount': user.get('sessionsCount'),
            'visits': user.get('visits'),
            'engagedSeconds': user.get('engagedSeconds'),
            'activeDays': user.get('activeDays'),
            'productAreaAdoption': user.get('productAreaAdoption') or [],
        })
    return rows


def _company_detail_table_payload(payload, request, table_name):
    if table_name == 'topPages':
        return paginate_cached_rows(
            payload.get('allTopPages') or payload.get('topPages') or [],
            request,
            default_page_size=COMPANY_DETAIL_TOP_PAGES_TABLE_PAGE_SIZE,
            default_sort_key='engagedSeconds',
            default_sort_direction='desc',
            sort_getters=COMPANY_DETAIL_TOP_PAGES_SORT_GETTERS,
            fallback_getter=lambda row: row.get('pageName') or '',
        )
    if table_name == 'users':
        return paginate_cached_rows(
            payload.get('users') or [],
            request,
            default_page_size=COMPANY_DETAIL_USERS_TABLE_PAGE_SIZE,
            default_sort_key='engagedSeconds',
            default_sort_direction='desc',
            sort_getters=COMPANY_DETAIL_USERS_SORT_GETTERS,
            fallback_getter=lambda row: row.get('name') or '',
        )
    return None


def _with_company_detail_table_payloads(payload, request):
    if not payload:
        return payload
    top_pages_table = _company_detail_table_payload(payload, request, 'topPages')
    users_table = _company_detail_table_payload(payload, request, 'users')
    client_payload = {**payload}
    full_users = payload.get('users') or []
    client_payload['topPages'] = top_pages_table['rows']
    client_payload.pop('allTopPages', None)
    client_payload['users'] = users_table['rows']
    client_payload['usersScatter'] = _company_detail_users_scatter_rows(full_users)
    client_payload.setdefault('tableData', {})['topPages'] = top_pages_table
    client_payload.setdefault('tableData', {})['users'] = users_table
    return client_payload


def _filter_user_detail_pages(rows, request):
    query = str(request.GET.get('q') or '').strip().lower()
    product_area_id = str(request.GET.get('product_area_id') or '').strip()
    filtered = []
    for row in rows or []:
        if product_area_id and str(row.get('productAreaId') or '') != product_area_id:
            continue
        if query:
            haystack = ' '.join([
                str(row.get('pageName') or ''),
                str(row.get('productArea') or ''),
                str(row.get('productAreaName') or ''),
            ]).lower()
            if query not in haystack:
                continue
        filtered.append(row)
    return filtered


def _user_detail_pages_table_payload(payload, request):
    rows = _filter_user_detail_pages(payload.get('pagesUsed') or [], request)
    return paginate_cached_rows(
        rows,
        request,
        default_page_size=USER_DETAIL_PAGES_TABLE_PAGE_SIZE,
        default_sort_key='engagedSeconds',
        default_sort_direction='desc',
        sort_getters=USER_DETAIL_PAGES_SORT_GETTERS,
        fallback_getter=lambda row: row.get('pageName') or '',
    )


def _with_user_detail_table_payloads(payload, request):
    if not payload:
        return payload
    pages_table = _user_detail_pages_table_payload(payload, request)
    client_payload = {**payload}
    client_payload['pagesUsed'] = pages_table['rows']
    client_payload.setdefault('tableData', {})['pagesUsed'] = pages_table
    return client_payload


@require_http_methods(["GET"])
def project_list(request):
    """View for the modern all projects page"""
    workspace_cards = []
    workspace_memberships = list(
        active_workspace_memberships()
        .filter(user=request.user)
        .select_related('workspace')
        .order_by('workspace__name', 'workspace__created_at')
    )
    workspace_ids = [membership.workspace_id for membership in workspace_memberships]
    projects = list(
        Project.active.filter(workspace_id__in=workspace_ids)
        .select_related('workspace')
        .order_by('workspace__name', 'name')
    )
    projects_by_workspace = defaultdict(list)
    for project in projects:
        projects_by_workspace[project.workspace_id].append(
            {
                'project': project,
                'status_label': project_status_label(project),
                'status_class': project_status_badge_class(project),
            }
        )
    project_names_by_workspace = defaultdict(list)
    for workspace_id, project_name in Project.objects.filter(workspace_id__in=workspace_ids).values_list('workspace_id', 'name'):
        project_names_by_workspace[workspace_id].append(project_name.strip().lower())
    for membership in workspace_memberships:
        project_rows = projects_by_workspace.get(membership.workspace_id, [])
        workspace_cards.append({
            'workspace': membership.workspace,
            'membership': membership,
            'projects': project_rows,
            'project_names_json': json.dumps(project_names_by_workspace.get(membership.workspace_id, [])),
            'role_label': workspace_role_label(membership.role),
            'can_create_project': user_can_create_project(request.user, membership.workspace),
            'can_invite_members': bool(
                user_can_invite_role(request.user, membership.workspace, WorkspaceMemberRole.OWNER)
                or user_can_invite_role(request.user, membership.workspace, WorkspaceMemberRole.ADMIN)
                or user_can_invite_role(request.user, membership.workspace, WorkspaceMemberRole.MEMBER)
                or user_can_invite_role(request.user, membership.workspace, WorkspaceMemberRole.VIEWER)
            ),
            'can_view_workspace_details': effective_workspace_role(membership.role) != WorkspaceMemberRole.VIEWER,
        })

    return render(
        request,
        'projects/project_list.html',
        {
            'workspace_cards': workspace_cards,
            'hosted_demo_url': getattr(settings, 'HOSTED_DEMO_URL', ''),
            'can_create_workspace': user_can_create_workspace(request.user),
        },
    )


def render_project_companies(request, project, *, is_demo_view=False):
    range_key = _companies_range_key(request)
    company_scope = resolve_company_scope(request, project, is_demo_view=is_demo_view)
    company_attribute_filter_state = company_scope.state
    canonical_redirect = canonical_company_scope_redirect(request, company_scope)
    if canonical_redirect is not None:
        return canonical_redirect
    restored = analytics_filter_state.restore_redirect(
        request,
        project,
        analytics_filter_state.COMPANIES_OVERVIEW,
        is_demo_view=is_demo_view,
    )
    if restored is not None:
        return restored

    cache, queued = filtered_overview.read_variant(
        filtered_overview.COMPANIES,
        project,
        range_key,
        company_attribute_filter_state,
        fetch=company_analytics.get_cached_companies_overview_payload,
        schema_is_current=company_analytics.is_current_companies_payload_schema,
    )
    payload = {}
    full_payload = {}
    payload_script_text = None
    cache_status = 'ready'

    if cache:
        if cache.get('is_stale'):
            cache_status = 'stale'
        full_payload = cache.get('payload_json') or {}
        payload = _with_companies_overview_table_payload(full_payload, request)
        payload_script_text = mark_safe(pages_services.to_json_script_text(payload))
    else:
        full_payload = company_analytics.empty_companies_overview_payload(project, range_key)
        payload = _with_companies_overview_table_payload(full_payload, request)
        payload_script_text = mark_safe(pages_services.to_json_script_text(payload))
        cache_status = 'preparing' if company_attribute_filter_state.active else 'missing'

    detail_base_url = reverse('demo_company_detail', kwargs={'company_id': 'detail'}) if is_demo_view else project_route(
        project,
        'project_company_detail',
        company_id='detail',
    )
    company_options_url = reverse('demo_company_options') if is_demo_view else project_route(project, 'project_company_options')
    table_url = reverse('demo_companies_table_data') if is_demo_view else project_route(project, 'project_companies_table_data')
    analytics_filter_state.remember(
        request,
        project,
        analytics_filter_state.COMPANIES_OVERVIEW,
        scope=company_scope,
        page_values={'range': range_key},
        is_demo_view=is_demo_view,
    )

    return render(
        request,
        'projects/companies.html',
        {
            'project': project,
            'companies_overview_payload': payload,
            'companies_overview_payload_json': payload_script_text,
            'companies_range_key': range_key,
            'companies_range_options': COMPANIES_RANGE_OPTIONS,
            'companies_cache_status': cache_status,
            'companies_variant_queued': queued,
            'companies_detail_base_url': detail_base_url,
            'companies_options_url': company_options_url,
            'companies_table_url': table_url,
            'company_attribute_filter_query_suffix': _company_attribute_filter_query_suffix(
                company_scope,
            ),
            'analytics_is_empty': is_companies_overview_empty(full_payload),
            'analytics_is_preparing': cache_status == 'preparing',
            'analytics_surface': 'companies',
            'analytics_variant_status_url': (
                reverse('demo_analytics_variant_status')
                if is_demo_view
                else project_route(project, 'project_analytics_variant_status')
            ),
            'analytics_empty_period_days': COMPANIES_RANGE_DAYS.get(range_key, 30),
            'is_demo_view': is_demo_view,
            'demo_project_id': project.id if is_demo_view else None,
            'demo_project_display_name': DEMO_PROJECT_DISPLAY_NAME,
            **_company_attribute_filter_context(
                project,
                company_scope,
                surface='companies',
                is_demo_view=is_demo_view,
            ),
        },
    )


@login_required
@require_project_member
def project_companies(request, project_id):
    project = get_accessible_project_or_404(request.user, project_id)
    return render_project_companies(request, project)


def demo_project_companies(request):
    return render_project_companies(request, get_demo_project(), is_demo_view=True)


def _companies_table_response(request, project):
    table_name = request.GET.get('table') or 'companies'
    if table_name not in COMPANIES_OVERVIEW_TABLE_PAYLOADS:
        return JsonResponse({'error': 'Unknown table'}, status=400)
    build_payload, page_size = COMPANIES_OVERVIEW_TABLE_PAYLOADS[table_name]
    range_key = _companies_range_key(request)
    company_attribute_filter_state = parse_company_attribute_filters(project, request.GET)
    cache, queued = filtered_overview.read_variant(
        filtered_overview.COMPANIES,
        project,
        range_key,
        company_attribute_filter_state,
        fetch=company_analytics.get_cached_companies_overview_payload,
        schema_is_current=company_analytics.is_current_companies_payload_schema,
    )
    if not cache:
        return _pending_table_response(table_name, page_size, queued=queued)
    table_payload = build_payload(cache.get('payload_json') or {}, request)
    return JsonResponse({'table': table_name, **table_payload}, json_dumps_params={'separators': (',', ':')})


@login_required
@require_project_member
@require_http_methods(["GET"])
def project_companies_table_data(request, project_id):
    project = get_accessible_project_or_404(request.user, project_id)
    return _companies_table_response(request, project)


@require_http_methods(["GET"])
def demo_project_companies_table_data(request):
    return _companies_table_response(request, get_demo_project())


def render_project_users(request, project, *, is_demo_view=False):
    range_key = _companies_range_key(request)
    company_scope = resolve_company_scope(request, project, is_demo_view=is_demo_view)
    company_attribute_filter_state = company_scope.state
    canonical_redirect = canonical_company_scope_redirect(request, company_scope)
    if canonical_redirect is not None:
        return canonical_redirect
    restored = analytics_filter_state.restore_redirect(
        request,
        project,
        analytics_filter_state.USERS_OVERVIEW,
        is_demo_view=is_demo_view,
    )
    if restored is not None:
        return restored

    cache, queued = filtered_overview.read_variant(
        filtered_overview.USERS,
        project,
        range_key,
        company_attribute_filter_state,
        fetch=user_analytics.get_cached_users_overview_client_payload,
        schema_is_current=user_analytics.is_current_users_payload_schema,
    )
    payload = {}
    full_payload = {}
    payload_script_text = None
    cache_status = 'ready'

    if cache:
        if cache.get('is_stale'):
            cache_status = 'stale'
        full_payload = cache.get('payload_json') or {}
        table_payload = user_analytics.get_cached_users_overview_table_page(
            project.id,
            range_key=range_key,
            filters_hash=company_attribute_filter_state.filters_hash,
            page=1,
            page_size=user_analytics.USERS_TABLE_PAGE_SIZE,
            sort_key=user_analytics.USERS_TABLE_DEFAULT_SORT_KEY,
            sort_direction=user_analytics.USERS_TABLE_DEFAULT_SORT_DIRECTION,
        )
        payload = user_analytics.initial_users_overview_payload(full_payload, table_payload=table_payload)
        payload_script_text = mark_safe(pages_services.to_json_script_text(payload))
    else:
        payload = user_analytics.empty_users_overview_payload(project, range_key)
        full_payload = payload
        payload_script_text = mark_safe(pages_services.to_json_script_text(payload))
        cache_status = 'preparing' if company_attribute_filter_state.active else 'missing'

    data_base_url = reverse('demo_users_data') if is_demo_view else project_route(project, 'project_users_data')
    data_query = [('range', range_key), *company_attribute_filter_state.canonical_pairs]
    data_url = f"{data_base_url}?{urlencode(data_query)}"
    detail_base_url = reverse('demo_user_detail', kwargs={'user_id': 'detail'}) if is_demo_view else project_route(
        project,
        'project_user_detail',
        user_id='detail',
    )
    company_detail_base_url = reverse('demo_company_detail', kwargs={'company_id': 'detail'}) if is_demo_view else project_route(
        project,
        'project_company_detail',
        company_id='detail',
    )
    user_options_url = reverse('demo_user_options') if is_demo_view else project_route(project, 'project_user_options')
    table_url = reverse('demo_users_table_data') if is_demo_view else project_route(project, 'project_users_table_data')
    analytics_filter_state.remember(
        request,
        project,
        analytics_filter_state.USERS_OVERVIEW,
        scope=company_scope,
        page_values={'range': range_key},
        is_demo_view=is_demo_view,
    )

    return render(
        request,
        'projects/users.html',
        {
            'project': project,
            'users_overview_payload': payload,
            'users_overview_payload_json': payload_script_text,
            'users_range_key': range_key,
            'users_range_options': COMPANIES_RANGE_OPTIONS,
            'users_cache_status': cache_status,
            'users_variant_queued': queued,
            'users_data_url': data_url,
            'users_detail_base_url': detail_base_url,
            'company_detail_base_url': company_detail_base_url,
            'users_options_url': user_options_url,
            'users_table_url': table_url,
            'company_attribute_filter_query_suffix': _company_attribute_filter_query_suffix(
                company_scope,
            ),
            'users_initial_limit': user_analytics.INITIAL_USERS_PAYLOAD_LIMIT,
            'analytics_is_empty': is_users_overview_empty(full_payload),
            'analytics_is_preparing': cache_status == 'preparing',
            'analytics_surface': 'users',
            'analytics_variant_status_url': (
                reverse('demo_analytics_variant_status')
                if is_demo_view
                else project_route(project, 'project_analytics_variant_status')
            ),
            'analytics_empty_period_days': COMPANIES_RANGE_DAYS.get(range_key, 30),
            'is_demo_view': is_demo_view,
            'demo_project_id': project.id if is_demo_view else None,
            'demo_project_display_name': DEMO_PROJECT_DISPLAY_NAME,
            **_company_attribute_filter_context(
                project,
                company_scope,
                surface='users',
                is_demo_view=is_demo_view,
            ),
        },
    )


@login_required
@require_project_member
def project_users(request, project_id):
    project = get_accessible_project_or_404(request.user, project_id)
    return render_project_users(request, project)


def demo_project_users(request):
    return render_project_users(request, get_demo_project(), is_demo_view=True)


def _users_overview_table_response(request, project):
    range_key = _companies_range_key(request)
    company_attribute_filter_state = parse_company_attribute_filters(project, request.GET)
    ready, queued = filtered_overview.gate_filtered_variant(
        filtered_overview.USERS,
        project,
        range_key,
        company_attribute_filter_state,
        fetch=user_analytics.get_cached_users_overview_metadata,
        schema_is_current=user_analytics.is_current_users_payload_schema,
    )
    if not ready:
        return _pending_table_response(
            'users',
            user_analytics.USERS_TABLE_PAGE_SIZE,
            queued=queued,
        )
    table_payload = _users_overview_table_payload(project, request, range_key=range_key)
    if table_payload is None:
        return _pending_table_response(
            'users',
            user_analytics.USERS_TABLE_PAGE_SIZE,
            queued=queued,
        )
    return JsonResponse(
        {'table': 'users', **table_payload},
        json_dumps_params={'separators': (',', ':')},
    )


@login_required
@require_project_member
@require_http_methods(["GET"])
def project_users_table_data(request, project_id):
    project = get_accessible_project_or_404(request.user, project_id)
    return _users_overview_table_response(request, project)


@require_http_methods(["GET"])
def demo_project_users_table_data(request):
    return _users_overview_table_response(request, get_demo_project())


def _user_absent_from_users_overview(project, user_id, range_key):
    """True only when the users overview can positively rule the user out.

    An overview that is missing or stored under an older schema cannot answer,
    and saying "not found" on that basis would bounce visitors off a user who
    does exist, so an unusable overview reports nothing.
    """
    cache = user_analytics.get_cached_users_overview_payload(project.id, range_key=range_key)
    if not cache or not user_analytics.is_current_users_payload_schema(cache.get('schema_version')):
        return False
    known_user_ids = {
        str(row.get('id') or row.get('userId') or '').strip()
        for row in (cache.get('payload_json') or {}).get('users') or []
    }
    return str(user_id or '').strip() not in known_user_ids


def _user_detail_payload_bundle(project, user_id, range_key, *, is_demo_view=False):
    overview_url = reverse('demo_users') if is_demo_view else project_route(project, 'project_users')
    user_options_url = reverse('demo_user_options') if is_demo_view else project_route(project, 'project_user_options')
    detail_base_url = reverse('demo_user_detail', kwargs={'user_id': 'detail'}) if is_demo_view else project_route(
        project,
        'project_user_detail',
        user_id='detail',
    )
    company_detail_base_url = reverse('demo_company_detail', kwargs={'company_id': 'detail'}) if is_demo_view else project_route(
        project,
        'project_company_detail',
        company_id='detail',
    )
    page_detail_base_url = reverse('demo_page_detail', kwargs={'page_rule_id': 'detail'}) if is_demo_view else project_route(
        project,
        'project_page_detail',
        page_rule_id='detail',
    )
    urls = {
        'usersOverviewUrl': overview_url,
        'userOptionsUrl': user_options_url,
        'userDetailBaseUrl': detail_base_url,
        'companyDetailBaseUrl': company_detail_base_url,
        'pageDetailBaseUrl': page_detail_base_url,
    }
    cache = user_detail_analytics.get_cached_user_detail_payload(project.id, user_id, range_key=range_key)
    if cache and not user_detail_analytics.is_current_user_details_payload_schema(cache.get('schema_version')):
        cache = None

    if not cache:
        # Building the payload here would run an uncached rebuild inside the
        # request. Without a bulk context that path costs tens of seconds and
        # has already outrun the gunicorn worker timeout, so the miss is queued
        # and the caller renders the preparing state instead.
        if _user_absent_from_users_overview(project, user_id, range_key):
            return {
                'status': 'not_found',
                'payload': None,
                'overviewUrl': overview_url,
                'detailBaseUrl': detail_base_url,
                'urls': urls,
                'period': {'range_key': range_key},
            }
        _best_effort_queue_user_detail_rebuild(project.id, user_id, range_key)
        return {
            'status': 'preparing',
            'payload': None,
            'overviewUrl': overview_url,
            'detailBaseUrl': detail_base_url,
            'urls': urls,
            'period': {'range_key': range_key},
        }

    if cache.get('is_stale'):
        _best_effort_queue_user_detail_rebuild(project.id, user_id, range_key)

    payload = {**(cache.get('payload_json') or {})}
    payload['urls'] = urls

    return {
        'status': 'ready',
        'payload': payload,
        'overviewUrl': overview_url,
        'detailBaseUrl': detail_base_url,
        'period': payload.get('period') or {'range_key': range_key},
        'urls': urls,
    }


def _user_detail_client_payload(payload, request):
    if not payload:
        return payload
    client_payload = _with_user_detail_table_payloads(payload, request)
    client_payload.pop('users', None)
    return client_payload


def _first_project_user_id(project, range_key):
    cache = user_analytics.get_cached_users_overview_payload(project.id, range_key=range_key)
    if not cache or not user_analytics.is_current_users_payload_schema(cache.get('schema_version')):
        return ''
    rows, _ = _user_selector_rows(
        (cache.get('payload_json') or {}).get('users') or [],
        '',
        1,
        alphabetical=True,
    )
    return rows[0]['id'] if rows else ''


def _detail_fallback_url(base_url, fallback_id, request):
    target = str(base_url or '').replace('detail', quote(str(fallback_id), safe=''), 1)
    query = request.GET.copy()
    query.pop('user_id', None)
    query.pop('company_id', None)
    return f'{target}?{query.urlencode()}' if query else target


def _is_detail_route_placeholder(value):
    return str(value or '').strip().lower() in {'detail', 'detail.html'}


def render_project_user_detail(request, project, user_id, *, is_demo_view=False):
    range_key = _companies_range_key(request)
    requested_user_id = request.GET.get('user_id') or user_id
    if requested_user_id in {'detail', 'detail.html'}:
        requested_user_id = request.GET.get('user_id') or ''

    bundle = _user_detail_payload_bundle(
        project,
        requested_user_id,
        range_key,
        is_demo_view=is_demo_view,
    )
    if bundle.get('status') == 'not_found':
        fallback_user_id = _first_project_user_id(project, range_key)
        if fallback_user_id and fallback_user_id != requested_user_id:
            return redirect(_detail_fallback_url(bundle.get('detailBaseUrl'), fallback_user_id, request))

    client_payload = _user_detail_client_payload(bundle.get('payload'), request)
    analytics_is_empty = bundle.get('status') == 'ready' and is_user_detail_empty(bundle.get('payload'))

    return render(
        request,
        'projects/user_detail.html',
        {
            'project': project,
            'user_id': requested_user_id,
            'user_detail_status': bundle.get('status'),
            'user_detail_payload': client_payload,
            'user_detail_payload_json': mark_safe(pages_services.to_json_script_text(client_payload or {})),
            'users_overview_url': bundle.get('overviewUrl'),
            'users_detail_base_url': bundle.get('detailBaseUrl'),
            'user_detail_table_url': reverse('demo_user_detail_table_data', kwargs={'user_id': requested_user_id}) if is_demo_view else project_route(
                project,
                'project_user_detail_table_data',
                user_id=requested_user_id,
            ),
            'users_range_key': range_key,
            'users_range_options': COMPANIES_RANGE_OPTIONS,
            'users_period_query_suffix': preserved_period_query_suffix(request),
            'analytics_is_empty': analytics_is_empty,
            'analytics_empty_period_days': COMPANIES_RANGE_DAYS.get(range_key, 30),
            'is_demo_view': is_demo_view,
            'demo_project_id': project.id if is_demo_view else None,
            'demo_project_display_name': DEMO_PROJECT_DISPLAY_NAME,
        },
    )


@login_required
@require_project_member
def project_user_detail(request, project_id, user_id):
    project = get_accessible_project_or_404(request.user, project_id)
    return render_project_user_detail(request, project, user_id)


def demo_project_user_detail(request, user_id):
    return render_project_user_detail(request, get_demo_project(), user_id, is_demo_view=True)


def _user_detail_table_response(request, project, user_id):
    range_key = _companies_range_key(request)
    table_name = request.GET.get('table') or 'pagesUsed'
    if table_name != 'pagesUsed':
        return JsonResponse({'error': 'Unknown table'}, status=400)
    cache = user_detail_analytics.get_cached_user_detail_payload(project.id, user_id, range_key=range_key)
    if not cache or cache.get('is_stale') or not user_detail_analytics.is_current_user_details_payload_schema(cache.get('schema_version')):
        queued = _best_effort_queue_user_detail_rebuild(project.id, user_id, range_key)
        return _pending_table_response('pagesUsed', USER_DETAIL_PAGES_TABLE_PAGE_SIZE, queued=queued)
    payload = cache.get('payload_json') or {}
    table_payload = _user_detail_pages_table_payload(payload, request)
    return JsonResponse({'table': 'pagesUsed', **table_payload}, json_dumps_params={'separators': (',', ':')})


@login_required
@require_project_member
@require_http_methods(["GET"])
def project_user_detail_table_data(request, project_id, user_id):
    project = get_accessible_project_or_404(request.user, project_id)
    return _user_detail_table_response(request, project, user_id)


@require_http_methods(["GET"])
def demo_project_user_detail_table_data(request, user_id):
    return _user_detail_table_response(request, get_demo_project(), user_id)


def _users_overview_data_response(request, project):
    range_key = _companies_range_key(request)
    company_attribute_filter_state = parse_company_attribute_filters(project, request.GET)
    cache, queued = filtered_overview.read_variant(
        filtered_overview.USERS,
        project,
        range_key,
        company_attribute_filter_state,
        fetch=user_analytics.get_cached_users_overview_client_payload,
        schema_is_current=user_analytics.is_current_users_payload_schema,
    )

    if cache:
        return JsonResponse(
            user_analytics.deferred_users_overview_payload(cache.get('payload_json')),
            json_dumps_params={'separators': (',', ':')},
        )

    return JsonResponse(
        {
            'pending': True,
            'queued': queued,
            'range_key': range_key,
            'users': [],
            'scatter': [],
        },
        status=202,
        json_dumps_params={'separators': (',', ':')},
    )


@login_required
@require_project_member
@require_http_methods(["GET"])
def project_users_data(request, project_id):
    project = get_accessible_project_or_404(request.user, project_id)
    return _users_overview_data_response(request, project)


@require_http_methods(["GET"])
def demo_project_users_data(request):
    return _users_overview_data_response(request, get_demo_project())


def _selector_limit(request, default=20, maximum=50):
    try:
        value = int(request.GET.get('limit') or default)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, maximum))


def _selector_query(request):
    return str(request.GET.get('q') or request.GET.get('query') or '').strip()


def _selector_text(value):
    return str(value or '').strip().lower()


def _selector_number(value, default=0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _selector_matches(query, *values):
    normalized_query = _selector_text(query)
    if not normalized_query:
        return True
    return normalized_query in _selector_text(' '.join(str(value or '') for value in values))


def _user_selector_rows(users, query, limit, *, alphabetical=False):
    rows = []
    for row in users or []:
        user_id = str(row.get('id') or row.get('userId') or '').strip()
        if not user_id:
            continue
        name = row.get('name') or user_id
        email = row.get('email') or ''
        company_name = row.get('companyName') or row.get('company') or ''
        if not _selector_matches(query, name, email, company_name, row.get('role'), row.get('seatType'), user_id):
            continue
        visits_count = row.get('visitsCount') or row.get('visits') or 0
        features_count = row.get('featuresCount') or len(row.get('topFeatures') or row.get('pageGroups') or [])
        rows.append({
            'id': user_id,
            'userId': user_id,
            'name': name,
            'email': email,
            'companyId': row.get('companyId') or row.get('company_id') or '',
            'companyName': company_name,
            'company': company_name,
            'role': row.get('role') or '',
            'seatType': row.get('seatType') or row.get('seat_type') or '',
            'status': row.get('status') or '',
            'engagedSeconds': row.get('engagedSeconds') or 0,
            'visitsCount': visits_count,
            'featuresCount': features_count,
            'lastActive': row.get('lastActive') or row.get('lastActiveAt') or '',
            'lastActiveSort': row.get('lastActiveSort') or 0,
        })
    if alphabetical:
        rows.sort(key=lambda item: (_selector_text(item.get('name')), item.get('id')))
    elif query:
        rows.sort(key=lambda item: (_selector_text(item.get('companyName')), _selector_text(item.get('name')), item.get('id')))
    else:
        rows.sort(key=lambda item: (
            _selector_number(item.get('lastActiveSort')),
            -_selector_number(item.get('engagedSeconds')),
            _selector_text(item.get('name')),
            item.get('id'),
        ))
    return rows[:limit], len(rows)


def _users_options_response(request, project):
    range_key = _companies_range_key(request)
    query = _selector_query(request)
    limit = _selector_limit(request)
    alphabetical = request.GET.get('sort') == 'alphabetical'
    company_attribute_filter_state = parse_company_attribute_filters(project, request.GET)
    ready, queued = filtered_overview.gate_filtered_variant(
        filtered_overview.USERS,
        project,
        range_key,
        company_attribute_filter_state,
        fetch=user_analytics.get_cached_users_overview_metadata,
        schema_is_current=user_analytics.is_current_users_payload_schema,
    )
    selector = (
        user_analytics.get_cached_users_overview_selector_rows(
            project.id,
            range_key=range_key,
            filters_hash=company_attribute_filter_state.filters_hash,
            query=query,
            limit=limit,
            alphabetical=alphabetical,
        )
        if ready
        else None
    )

    if selector is not None:
        rows, total = selector
        return JsonResponse(
            {
                'query': query,
                'range_key': range_key,
                'results': rows,
                'users': rows,
                'total': total,
                'hasMore': total > len(rows),
            },
            json_dumps_params={'separators': (',', ':')},
        )

    return JsonResponse(
        {
            'pending': True,
            'queued': queued,
            'query': query,
            'range_key': range_key,
            'results': [],
            'users': [],
            'total': 0,
            'hasMore': False,
        },
        status=202,
        json_dumps_params={'separators': (',', ':')},
    )


@login_required
@require_project_member
@require_http_methods(["GET"])
def project_user_options(request, project_id):
    project = get_accessible_project_or_404(request.user, project_id)
    return _users_options_response(request, project)


@require_http_methods(["GET"])
def demo_project_user_options(request):
    return _users_options_response(request, get_demo_project())


def _company_detail_selector_rows(company_rows):
    rows = []
    for row in company_rows or []:
        company_id = str(row.get('id') or row.get('companyId') or '')
        if not company_id:
            continue
        rows.append({
            'id': company_id,
            'companyId': company_id,
            'name': row.get('name') or row.get('companyName') or company_id,
            'companyName': row.get('companyName') or row.get('name') or company_id,
            'domain': row.get('domain') or '',
            'status': row.get('status') or 'healthy',
            'activeUsers': row.get('activeUsers') or 0,
            'productAreasUsed': row.get('productAreasUsed') or 0,
            'pagesUsed': row.get('pagesUsed') or 0,
            'lastSeen': row.get('lastSeen') or row.get('lastActiveAt') or '',
            'lastSeenDate': row.get('lastSeenDate') or row.get('last_seen_date') or '',
            'lastSeenDays': row.get('lastSeenDays') or 0,
        })
    return rows


def _company_detail_payload_bundle(project, company_id, range_key, *, is_demo_view=False):
    overview_url = reverse('demo_companies') if is_demo_view else project_route(project, 'project_companies')
    company_options_url = reverse('demo_company_options') if is_demo_view else project_route(project, 'project_company_options')
    detail_base_url = reverse('demo_company_detail', kwargs={'company_id': 'detail'}) if is_demo_view else project_route(
        project,
        'project_company_detail',
        company_id='detail',
    )
    user_detail_base_url = reverse('demo_user_detail', kwargs={'user_id': 'detail'}) if is_demo_view else project_route(
        project,
        'project_user_detail',
        user_id='detail',
    )
    pages_detail_base_url = reverse('demo_pages') if is_demo_view else f"{project_route(project, 'project_pages')}/"
    urls = {
        'companiesOverviewUrl': overview_url,
        'companyOptionsUrl': company_options_url,
        'companyDetailBaseUrl': detail_base_url,
        'userDetailBaseUrl': user_detail_base_url,
        'pagesDetailBaseUrl': pages_detail_base_url,
    }
    overview_payload = None
    cache = company_analytics.get_cached_companies_overview_payload(project.id, range_key=range_key)
    if cache and company_analytics.is_current_companies_payload_schema(cache.get('schema_version')):
        overview_payload = cache.get('payload_json') or {}
    else:
        return {
            'status': 'preparing',
            'selected_range_key': range_key,
            'selected_period': f"{company_detail_analytics._period_days(range_key)}d",
            'selected_period_days': company_detail_analytics._period_days(range_key),
            'payload': None,
            'companies': [],
            'productAreas': company_detail_analytics.product_area_options(project.id),
            'urls': urls,
        }

    overview_company_rows = overview_payload.get('companies') or []
    companies = _company_detail_selector_rows(overview_company_rows)
    requested_company_id = str(company_id or '').strip()
    company_exists = any(str(row.get('id') or row.get('companyId') or '') == requested_company_id for row in companies)
    product_areas = overview_payload.get('productAreas') or company_detail_analytics.product_area_options(project.id)

    payload = None
    detail_cache = company_analytics.get_cached_company_detail_payload(
        project.id,
        requested_company_id,
        range_key=range_key,
    )
    if detail_cache and company_analytics.is_current_company_detail_payload_schema(detail_cache.get('schema_version')):
        if detail_cache.get('is_stale'):
            _best_effort_queue_company_detail_rebuild(project.id, requested_company_id, range_key)
        payload = detail_cache.get('payload_json') or None
    elif company_exists:
        _best_effort_queue_company_detail_rebuild(project.id, requested_company_id, range_key)

    status = 'ready' if payload else ('preparing' if company_exists else 'not_found')

    return {
        'status': status,
        'selected_range_key': range_key,
        'selected_period': payload['period']['key'] if payload else f"{company_detail_analytics._period_days(range_key)}d",
        'selected_period_days': payload['period']['days'] if payload else company_detail_analytics._period_days(range_key),
        'payload': payload,
        'companies': companies,
        'productAreas': product_areas,
        'urls': urls,
    }


def _company_detail_client_bundle(bundle, request):
    client_bundle = {**(bundle or {})}
    if client_bundle.get('payload'):
        client_bundle['payload'] = _with_company_detail_table_payloads(client_bundle.get('payload'), request)
    client_bundle.pop('companies', None)
    return client_bundle


def render_project_company_detail(request, project, company_id, *, is_demo_view=False):
    range_key = _companies_range_key(request)
    requested_company_id = request.GET.get('company_id') or company_id
    if _is_detail_route_placeholder(requested_company_id):
        requested_company_id = ''

    payload_bundle = _company_detail_payload_bundle(
        project,
        requested_company_id,
        range_key,
        is_demo_view=is_demo_view,
    )
    if payload_bundle.get('status') == 'not_found':
        alphabetical_companies = sorted(
            payload_bundle.get('companies') or [],
            key=lambda row: (_selector_text(row.get('name') or row.get('companyName')), str(row.get('id') or '')),
        )
        fallback_company_id = str(alphabetical_companies[0].get('id') or '') if alphabetical_companies else ''
        if fallback_company_id and fallback_company_id != requested_company_id:
            return redirect(_detail_fallback_url(
                payload_bundle['urls']['companyDetailBaseUrl'],
                fallback_company_id,
                request,
            ))

    client_payload_bundle = _company_detail_client_bundle(payload_bundle, request)
    overview_url = payload_bundle['urls']['companiesOverviewUrl']
    analytics_is_empty = payload_bundle.get('status') == 'ready' and is_company_detail_empty(payload_bundle.get('payload'))
    metric_dynamics_url = reverse('demo_company_metric_dynamics', kwargs={'company_id': requested_company_id}) if is_demo_view else project_route(
        project,
        'project_company_metric_dynamics',
        company_id=requested_company_id,
    )

    return render(
        request,
        'projects/company_detail.html',
        {
            'project': project,
            'company_id': requested_company_id,
            'company_detail_payload': payload_bundle.get('payload'),
            'company_detail_payload_json': mark_safe(pages_services.to_json_script_text(client_payload_bundle)),
            'companies_range_key': range_key,
            'companies_range_options': COMPANIES_RANGE_OPTIONS,
            'companies_period_query_suffix': preserved_period_query_suffix(request),
            'companies_overview_url': overview_url,
            'company_detail_base_url': payload_bundle['urls']['companyDetailBaseUrl'],
            'user_detail_base_url': payload_bundle['urls']['userDetailBaseUrl'],
            'pages_detail_base_url': payload_bundle['urls']['pagesDetailBaseUrl'],
            'company_metric_dynamics_url': metric_dynamics_url,
            'company_detail_table_url': reverse('demo_company_detail_table_data', kwargs={'company_id': requested_company_id}) if is_demo_view else project_route(
                project,
                'project_company_detail_table_data',
                company_id=requested_company_id,
            ),
            'analytics_is_empty': analytics_is_empty,
            'analytics_empty_period_days': COMPANIES_RANGE_DAYS.get(range_key, 30),
            'is_demo_view': is_demo_view,
            'demo_project_id': project.id if is_demo_view else None,
            'demo_project_display_name': DEMO_PROJECT_DISPLAY_NAME,
        },
    )


@login_required
@require_project_member
def project_company_detail(request, project_id, company_id):
    project = get_accessible_project_or_404(request.user, project_id)
    return render_project_company_detail(request, project, company_id)


def demo_project_company_detail(request, company_id):
    return render_project_company_detail(request, get_demo_project(), company_id, is_demo_view=True)


def _company_detail_table_response(request, project, company_id):
    range_key = _companies_range_key(request)
    table_name = request.GET.get('table') or ''
    cache = company_analytics.get_cached_company_detail_payload(project.id, company_id, range_key=range_key)
    if not cache or cache.get('is_stale') or not company_analytics.is_current_company_detail_payload_schema(cache.get('schema_version')):
        queued = _best_effort_queue_company_detail_rebuild(project.id, company_id, range_key)
        page_size = COMPANY_DETAIL_TOP_PAGES_TABLE_PAGE_SIZE if table_name == 'topPages' else COMPANY_DETAIL_USERS_TABLE_PAGE_SIZE
        return _pending_table_response(table_name, page_size, queued=queued)
    table_payload = _company_detail_table_payload(cache.get('payload_json') or {}, request, table_name)
    if table_payload is None:
        return JsonResponse({'error': 'Unknown table'}, status=400)
    return JsonResponse({'table': table_name, **table_payload}, json_dumps_params={'separators': (',', ':')})


@login_required
@require_project_member
@require_http_methods(["GET"])
def project_company_detail_table_data(request, project_id, company_id):
    project = get_accessible_project_or_404(request.user, project_id)
    return _company_detail_table_response(request, project, company_id)


@require_http_methods(["GET"])
def demo_project_company_detail_table_data(request, company_id):
    return _company_detail_table_response(request, get_demo_project(), company_id)


def _company_selector_rows(rows, query, limit, *, alphabetical=False):
    filtered = []
    for row in rows or []:
        if not _selector_matches(query, row.get('name'), row.get('companyName'), row.get('domain'), row.get('status'), row.get('id')):
            continue
        filtered.append(row)
    if query or alphabetical:
        filtered.sort(key=lambda item: (_selector_text(item.get('name') or item.get('companyName')), item.get('id')))
    else:
        filtered.sort(key=lambda item: (
            _selector_number(item.get('lastSeenDays')),
            -_selector_number(item.get('activeUsers')),
            _selector_text(item.get('name') or item.get('companyName')),
            item.get('id'),
        ))
    return filtered[:limit], len(filtered)


def _company_options_response(request, project):
    range_key = _companies_range_key(request)
    query = _selector_query(request)
    limit = _selector_limit(request)
    alphabetical = request.GET.get('sort') == 'alphabetical'
    company_attribute_filter_state = parse_company_attribute_filters(project, request.GET)
    cache, queued = filtered_overview.read_variant(
        filtered_overview.COMPANIES,
        project,
        range_key,
        company_attribute_filter_state,
        fetch=company_analytics.get_cached_companies_overview_payload,
        schema_is_current=company_analytics.is_current_companies_payload_schema,
    )

    if cache:
        rows = _company_detail_selector_rows((cache.get('payload_json') or {}).get('companies') or [])
        results, total = _company_selector_rows(rows, query, limit, alphabetical=alphabetical)
        return JsonResponse(
            {
                'query': query,
                'range_key': range_key,
                'results': results,
                'companies': results,
                'total': total,
                'hasMore': total > len(results),
            },
            json_dumps_params={'separators': (',', ':')},
        )

    return JsonResponse(
        {
            'pending': True,
            'queued': queued,
            'query': query,
            'range_key': range_key,
            'results': [],
            'companies': [],
            'total': 0,
            'hasMore': False,
        },
        status=202,
        json_dumps_params={'separators': (',', ':')},
    )


@login_required
@require_project_member
@require_http_methods(["GET"])
def project_company_options(request, project_id):
    project = get_accessible_project_or_404(request.user, project_id)
    return _company_options_response(request, project)


@require_http_methods(["GET"])
def demo_project_company_options(request):
    return _company_options_response(request, get_demo_project())


def render_company_metric_dynamics(request, project, company_id, *, is_demo_view=False):
    range_key = _companies_range_key(request)
    requested_company_id = request.GET.get('company_id') or company_id
    if requested_company_id in {'detail', 'detail.html'}:
        requested_company_id = request.GET.get('company_id') or ''

    metric_dynamics_url = reverse('demo_company_metric_dynamics', kwargs={'company_id': requested_company_id}) if is_demo_view else project_route(
        project,
        'project_company_metric_dynamics',
        company_id=requested_company_id,
    )
    return render(
        request,
        'projects/partials/company_detail_metric_dynamics.html',
        {
            'project': project,
            'company_id': requested_company_id,
            'companies_range_key': range_key,
            'company_metric_dynamics_url': metric_dynamics_url,
            'company_metric_dynamics_show_peers': _show_peers(request),
            'is_demo_view': is_demo_view,
            'demo_project_id': project.id if is_demo_view else None,
            'demo_project_display_name': DEMO_PROJECT_DISPLAY_NAME,
        },
    )


@login_required
@require_project_member
def project_company_metric_dynamics(request, project_id, company_id):
    project = get_accessible_project_or_404(request.user, project_id)
    return render_company_metric_dynamics(request, project, company_id)


def demo_project_company_metric_dynamics(request, company_id):
    return render_company_metric_dynamics(request, get_demo_project(), company_id, is_demo_view=True)


@login_required
def project_create(request):
    if request.method == 'POST':
        workspace_id = request.POST.get('workspace_id')
        workspace = get_accessible_workspace_or_404(request.user, workspace_id)
        if not user_can_create_project(request.user, workspace):
            raise PermissionDenied('You do not have permission to create projects in this workspace.')

        project_name = request.POST.get('name', '').strip()
        product_url = request.POST.get('product_url', '').strip()
        if not project_name:
            messages.error(request, 'Project name cannot be empty.', extra_tags='create-project')
            return redirect('projects:project_list')

        if Project.objects.filter(workspace=workspace, name__iexact=project_name).exists():
            messages.error(
                request,
                'A project with this name already exists in this workspace.',
                extra_tags='create-project',
            )
            return redirect('projects:project_list')

        if product_url and not normalize_allowed_domains([product_url]):
            messages.error(request, 'Enter a valid product URL.', extra_tags='create-project')
            return redirect('projects:project_list')

        project = create_project_in_workspace(
            request.user,
            workspace,
            project_name,
            product_url=product_url,
            timezone_value=request.POST.get('timezone', 'UTC'),
        )
        return redirect(project_route(project, 'project_settings'))
    else:
        form = ProjectForm()
    workspaces = active_workspace_memberships().filter(
        user=request.user,
        role=WorkspaceMemberRole.OWNER,
    ).select_related('workspace')
    return render(request, 'projects/project_form.html', {'form': form, 'workspaces': workspaces})


@login_required
@require_POST
def workspace_create(request):
    if not user_can_create_workspace(request.user):
        raise PermissionDenied('Only an instance administrator or workspace owner can create a workspace.')
    name = request.POST.get('name', '').strip()
    website_url = request.POST.get('website_url', '').strip()
    normalized_website_url = normalize_workspace_website_url(website_url)
    if website_url and not normalized_website_url:
        messages.error(request, 'Enter a valid website domain.')
        return redirect('projects:project_list')
    if name:
        create_workspace_for_user(request.user, name, website_url=normalized_website_url)
    return redirect('projects:project_list')


@login_required
@require_POST
def onboarding_first_project(request):
    if not user_can_create_workspace(request.user):
        raise PermissionDenied('You do not have permission to create the first workspace.')
    workspace_name = request.POST.get('workspace_name', '').strip()
    project_name = request.POST.get('project_name', '').strip()
    product_url = request.POST.get('product_url', '').strip()
    if not (workspace_name and project_name):
        return redirect('welcome')
    if product_url and not normalize_allowed_domains([product_url]):
        messages.error(request, 'Enter a valid product URL.')
        return redirect('welcome')

    workspace, project = create_first_workspace_project(
        request.user,
        workspace_name,
        project_name,
        product_url,
        timezone_value=request.POST.get('timezone', 'UTC'),
    )
    return redirect(project_route(project, 'project_settings'))


def _workspace_settings_access(request, workspace_id):
    workspace = get_accessible_workspace_or_404(request.user, workspace_id)
    membership = get_workspace_membership(request.user, workspace)
    if membership and effective_workspace_role(membership.role) == WorkspaceMemberRole.VIEWER:
        raise PermissionDenied('Viewers do not have access to workspace settings.')
    return workspace, membership


def _workspace_projects(workspace):
    return Project.active.filter(workspace=workspace).order_by('name')


def _workspace_settings_project(request, workspace):
    try:
        project_id = int(request.GET.get('project', ''))
    except (TypeError, ValueError):
        return None
    return Project.active.select_related('workspace').filter(pk=project_id, workspace=workspace).first()


def _workspace_settings_route(request, workspace, route_name):
    url = workspace_route(workspace, route_name)
    project = _workspace_settings_project(request, workspace)
    if project:
        return f'{url}?{urlencode({"project": project.id})}'
    return url


@login_required
def workspace_details(request, workspace_id):
    workspace, membership = _workspace_settings_access(request, workspace_id)
    current_project = _workspace_settings_project(request, workspace)
    projects = _workspace_projects(workspace)
    has_active_workspace_projects = workspace_has_active_projects(workspace)
    context = {
        'workspace': workspace,
        'project': current_project,
        'workspace_membership': membership,
        'workspace_projects': projects,
        'can_edit_workspace': user_can_edit_workspace(request.user, workspace),
        'can_leave_workspace': bool(membership and not is_last_owner(membership)),
        'can_delete_workspace': bool(
            request.user.is_superuser
            or (membership and effective_workspace_role(membership.role) == WorkspaceMemberRole.OWNER)
        ),
        'can_manage_openai_key': user_can_manage_workspace_openai_key(request.user, workspace),
        'openai_credential': WorkspaceOpenAICredential.objects.filter(workspace=workspace).first(),
        'has_active_workspace_projects': has_active_workspace_projects,
        'active_settings_section': 'workspace_details',
    }
    return render(request, 'projects/workspace_details.html', context)


@login_required
@require_POST
def save_workspace_openai_key(request, workspace_id):
    workspace, membership = _workspace_settings_access(request, workspace_id)
    if not user_can_manage_workspace_openai_key(request.user, workspace):
        raise PermissionDenied('Only workspace owners can manage the OpenAI API key.')
    try:
        set_workspace_openai_key(
            workspace,
            request.POST.get('api_key', ''),
            updated_by=request.user,
        )
    except WorkspaceOpenAIKeyError as exc:
        messages.error(request, str(exc), extra_tags='workspace-openai-key')
    else:
        messages.success(request, 'OpenAI API key saved.', extra_tags='workspace-openai-key')
    return redirect(_workspace_settings_route(request, workspace, 'workspace_details'))


@login_required
@require_POST
def validate_workspace_openai_key_view(request, workspace_id):
    workspace, membership = _workspace_settings_access(request, workspace_id)
    if not user_can_manage_workspace_openai_key(request.user, workspace):
        raise PermissionDenied('Only workspace owners can validate the OpenAI API key.')
    try:
        credential = validate_workspace_openai_key(workspace)
    except WorkspaceOpenAICredential.DoesNotExist:
        messages.error(request, 'Add an OpenAI API key first.', extra_tags='workspace-openai-key')
    else:
        if credential.validation_status == 'valid':
            messages.success(request, 'OpenAI API key is valid.', extra_tags='workspace-openai-key')
        elif credential.validation_status == 'invalid':
            messages.error(request, 'OpenAI API key is invalid.', extra_tags='workspace-openai-key')
        else:
            messages.warning(
                request,
                'The OpenAI API could not be reached. Try validation again later.',
                extra_tags='workspace-openai-key',
            )
    return redirect(_workspace_settings_route(request, workspace, 'workspace_details'))


@login_required
@require_POST
def remove_workspace_openai_key(request, workspace_id):
    workspace, membership = _workspace_settings_access(request, workspace_id)
    if not user_can_manage_workspace_openai_key(request.user, workspace):
        raise PermissionDenied('Only workspace owners can remove the OpenAI API key.')
    delete_workspace_openai_key(workspace)
    messages.success(request, 'OpenAI API key removed.', extra_tags='workspace-openai-key')
    return redirect(_workspace_settings_route(request, workspace, 'workspace_details'))


@login_required
@require_POST
def update_workspace_name(request, workspace_id):
    workspace, membership = _workspace_settings_access(request, workspace_id)
    if not user_can_edit_workspace(request.user, workspace):
        raise PermissionDenied('You do not have permission to edit workspace details.')

    name = request.POST.get('name', '').strip()
    if not name:
        messages.error(request, 'Workspace name is required.', extra_tags='workspace-name')
        return redirect(_workspace_settings_route(request, workspace, 'workspace_details'))
    if len(name) > Workspace._meta.get_field('name').max_length:
        messages.error(request, 'Workspace name is too long.', extra_tags='workspace-name')
        return redirect(_workspace_settings_route(request, workspace, 'workspace_details'))

    rename_workspace(workspace, name)
    return redirect(_workspace_settings_route(request, workspace, 'workspace_details'))


@login_required
@require_POST
def update_workspace_slug(request, workspace_id):
    workspace, membership = _workspace_settings_access(request, workspace_id)
    if not user_can_edit_workspace(request.user, workspace):
        raise PermissionDenied('You do not have permission to edit workspace details.')

    wants_json = request.headers.get('x-requested-with') == 'XMLHttpRequest'

    def error_response(message):
        if wants_json:
            return JsonResponse({'ok': False, 'error': message}, status=400)
        messages.error(request, message, extra_tags='workspace-slug')
        return redirect(_workspace_settings_route(request, workspace, 'workspace_details'))

    slug = request.POST.get('slug', '').strip().lower()
    if not slug:
        return error_response('Workspace URL slug is required.')
    if len(slug) > Workspace._meta.get_field('slug').max_length:
        return error_response('Workspace URL slug is too long.')
    try:
        validate_slug(slug)
    except DjangoValidationError:
        return error_response('Enter a valid URL slug.')

    try:
        change_workspace_slug(workspace, slug)
    except ValueError as exc:
        return error_response(str(exc))

    redirect_url = _workspace_settings_route(request, workspace, 'workspace_details')
    if wants_json:
        return JsonResponse({'ok': True, 'redirect_url': redirect_url})
    return redirect(redirect_url)


@login_required
@require_POST
def update_workspace_website(request, workspace_id):
    workspace, membership = _workspace_settings_access(request, workspace_id)
    if not user_can_edit_workspace(request.user, workspace):
        raise PermissionDenied('You do not have permission to edit workspace details.')

    website_url = request.POST.get('website_url', '').strip()
    normalized_website_url = normalize_workspace_website_url(website_url)
    if website_url and not normalized_website_url:
        messages.error(request, 'Enter a valid website domain.', extra_tags='workspace-website')
        return redirect(_workspace_settings_route(request, workspace, 'workspace_details'))
    if len(normalized_website_url) > Workspace._meta.get_field('website_url').max_length:
        messages.error(request, 'Website domain is too long.', extra_tags='workspace-website')
        return redirect(_workspace_settings_route(request, workspace, 'workspace_details'))

    workspace.website_url = normalized_website_url
    workspace.save(update_fields=['website_url', 'updated_at'])
    return redirect(_workspace_settings_route(request, workspace, 'workspace_details'))


@login_required
@require_POST
def update_workspace_details(request, workspace_id):
    submitted_fields = {field for field in ('name', 'slug', 'website_url') if field in request.POST}
    if submitted_fields == {'name'}:
        return update_workspace_name(request, workspace_id)
    if submitted_fields == {'slug'}:
        return update_workspace_slug(request, workspace_id)
    if submitted_fields == {'website_url'}:
        return update_workspace_website(request, workspace_id)

    workspace, membership = _workspace_settings_access(request, workspace_id)
    if not user_can_edit_workspace(request.user, workspace):
        raise PermissionDenied('You do not have permission to edit workspace details.')
    messages.error(request, 'Update one workspace detail at a time.', extra_tags='workspace-details')
    return redirect(_workspace_settings_route(request, workspace, 'workspace_details'))


@login_required
@require_POST
def leave_workspace(request, workspace_id):
    workspace, membership = _workspace_settings_access(request, workspace_id)
    if is_last_owner(membership):
        messages.error(request, 'Transfer ownership before leaving this workspace.', extra_tags='workspace-leave')
        return redirect(_workspace_settings_route(request, workspace, 'workspace_details'))
    remove_workspace_member_safely(membership)
    return redirect('projects:project_list')


@login_required
@require_POST
def delete_workspace(request, workspace_id):
    workspace, membership = _workspace_settings_access(request, workspace_id)
    if not request.user.is_superuser and (
        not membership or effective_workspace_role(membership.role) != WorkspaceMemberRole.OWNER
    ):
        raise PermissionDenied('Only workspace owners can delete this workspace.')

    if workspace_has_active_projects(workspace):
        return redirect(_workspace_settings_route(request, workspace, 'workspace_details'))

    confirmation = request.POST.get('workspace_name', '').strip()
    if confirmation != workspace.name:
        messages.error(request, 'Workspace name does not match.', extra_tags='workspace-delete')
        return redirect(_workspace_settings_route(request, workspace, 'workspace_details'))

    archive_workspace(workspace)
    return redirect('projects:project_list')


def _workspace_member_role_options(user, workspace, membership):
    current_role = effective_workspace_role(membership.role)
    options = []
    has_role_change = False
    for role_value, role_label in WorkspaceMemberRole.choices:
        if user_can_assign_workspace_role(user, workspace, membership, role_value):
            options.append(
                {
                    'value': role_value,
                    'label': role_label,
                    'selected': role_value == current_role,
                }
            )
            if role_value != current_role:
                has_role_change = True
    return options, has_role_change


def _workspace_team_sort_key(row):
    sort_name = str(row.get('_sort_name') or '').casefold()
    sort_email = str(row.get('email') or '').casefold()
    return (0 if sort_name else 1, sort_name or sort_email, sort_email)


def _workspace_team_rows(workspace, user):
    rows = []
    memberships = (
        WorkspaceMembership.objects.filter(
            workspace=workspace,
            status=WorkspaceMemberStatus.ACTIVE,
            removed_at__isnull=True,
        )
        .select_related('user')
        .order_by('role', 'user__email')
    )
    for membership in memberships:
        person_name = membership.user.get_full_name().strip()
        can_remove = user_can_remove_workspace_member(user, workspace, membership)
        role_options, can_change_role = _workspace_member_role_options(user, workspace, membership)
        rows.append(
            {
                'kind': 'member',
                'id': membership.id,
                'name': person_name or membership.user.username,
                'email': membership.user.email,
                'role': effective_workspace_role(membership.role),
                'status': 'active',
                'membership': membership,
                'can_remove': can_remove,
                'can_change_role': can_change_role,
                'role_options': role_options,
                'has_actions': bool(can_remove or can_change_role),
                '_sort_name': person_name,
            }
        )

    rows.sort(key=_workspace_team_sort_key)
    return rows


@login_required
def workspace_team(request, workspace_id):
    workspace, membership = _workspace_settings_access(request, workspace_id)
    current_project = _workspace_settings_project(request, workspace)
    context = {
        'workspace': workspace,
        'project': current_project,
        'workspace_membership': membership,
        'workspace_projects': _workspace_projects(workspace),
        'team_members': _workspace_team_rows(workspace, request.user),
        'can_add_owner': user_can_invite_role(request.user, workspace, WorkspaceMemberRole.OWNER),
        'can_add_admin': user_can_invite_role(request.user, workspace, WorkspaceMemberRole.ADMIN),
        'can_add_member': user_can_invite_role(request.user, workspace, WorkspaceMemberRole.MEMBER),
        'can_add_viewer': user_can_invite_role(request.user, workspace, WorkspaceMemberRole.VIEWER),
        'active_settings_section': 'workspace_team',
    }
    return render(request, 'projects/workspace_team.html', context)


@login_required
@require_POST
def workspace_add_member(request, workspace_id):
    workspace, membership = _workspace_settings_access(request, workspace_id)
    role = request.POST.get('role', WorkspaceMemberRole.MEMBER)
    try:
        added_membership, user_created = add_local_workspace_member(
            actor=request.user,
            workspace=workspace,
            email=request.POST.get('email', ''),
            role=role,
            temporary_password=request.POST.get('temporary_password', ''),
        )
    except DjangoValidationError as exc:
        error_message = '; '.join(exc.messages) if hasattr(exc, 'messages') else 'Could not add this user.'
        messages.error(request, error_message, extra_tags='workspace-add-member')
    else:
        action = 'created and added' if user_created else 'added'
        messages.success(
            request,
            f'{added_membership.user.email} was {action}.',
            extra_tags='workspace-add-member',
        )
    return redirect(_workspace_settings_route(request, workspace, 'workspace_team'))


@login_required
@require_POST
def remove_workspace_member(request, workspace_id, membership_id):
    workspace, membership = _workspace_settings_access(request, workspace_id)
    target = get_object_or_404(WorkspaceMembership, pk=membership_id, workspace=workspace)
    if not user_can_remove_workspace_member(request.user, workspace, target):
        raise PermissionDenied('You do not have permission to remove workspace members.')
    remove_workspace_member_safely(target)
    if target.user_id == request.user.id:
        return redirect('projects:project_list')
    return redirect(_workspace_settings_route(request, workspace, 'workspace_team'))


@login_required
@require_POST
def update_workspace_member_role(request, workspace_id, membership_id):
    workspace, membership = _workspace_settings_access(request, workspace_id)
    target = get_object_or_404(WorkspaceMembership, pk=membership_id, workspace=workspace)
    new_role = request.POST.get('role', '').strip()
    if new_role not in WorkspaceMemberRole.values:
        return redirect(_workspace_settings_route(request, workspace, 'workspace_team'))
    if not user_can_assign_workspace_role(request.user, workspace, target, new_role):
        raise PermissionDenied('You do not have permission to update this member role.')
    change_workspace_member_role_safely(target, new_role)
    return redirect(_workspace_settings_route(request, workspace, 'workspace_team'))


@login_required
def project_delete(request, pk):
    project = get_accessible_project_or_404(request.user, pk)
    membership = get_workspace_membership(request.user, project.workspace)
    if not request.user.is_superuser and (
        not membership or effective_workspace_role(membership.role) != WorkspaceMemberRole.OWNER
    ):
        raise PermissionDenied('Only workspace owners can delete projects.')
    ensure_project_writable(project)
    if request.method == 'POST':
        archive_project(project)
    return redirect('projects:project_list')


@login_required
@require_project_settings_editor
def update_project_name(request, project_id):
    """Handle project name updates"""
    project = get_accessible_project_or_404(request.user, project_id)
    ensure_project_writable(project)

    if request.method == 'POST':
        new_name = request.POST.get('name', '').strip()

        if not new_name:
            return JsonResponse({'success': False, 'error': 'Project name cannot be empty.'})

        if Project.objects.filter(workspace=project.workspace, name__iexact=new_name).exclude(pk=project.pk).exists():
            return JsonResponse({
                'success': False,
                'error': 'A project with this name already exists in this workspace.',
            })

        project.name = new_name
        project.save()
        return JsonResponse({'success': True, 'new_name': new_name})

    return JsonResponse({'success': False, 'error': 'Invalid request method.'})


@login_required
@require_project_settings_editor
def update_project_timezone(request, project_id):
    """Handle project timezone change"""
    if request.method == 'POST':
        project = get_accessible_project_or_404(request.user, project_id)
        ensure_project_writable(project)
        new_timezone = request.POST.get('timezone', '').strip()

        # Validate timezone using zoneinfo
        try:
            project.timezone = normalize_timezone(new_timezone)
            project.save(update_fields=['timezone'])
            return redirect(project_route(project, 'project_settings'))
        except Exception:
            return JsonResponse({'success': False, 'error': 'Invalid timezone.'})

    return JsonResponse({'success': False, 'error': 'Invalid request method.'})


@login_required
@require_project_settings_editor
def update_project_product_url(request, project_id):
    project = get_accessible_project_or_404(request.user, project_id)
    ensure_project_writable(project)
    settings_url = project_route(project, 'project_settings')

    if request.method == 'POST':
        product_url = request.POST.get('product_url', '').strip()
        if not product_url:
            messages.error(request, 'Product URL cannot be empty.', extra_tags='product-url')
            return redirect(settings_url)
        allowed_domains = normalize_allowed_domains([product_url])
        if not allowed_domains:
            messages.error(request, 'Enter a valid product URL.', extra_tags='product-url')
            return redirect(settings_url)
        project.product_url = allowed_domains[0]
        project.allowed_domains = allowed_domains
        project.status = ProjectStatus.SETUP_REQUIRED if not project.first_production_event_at else project.status
        project.save(update_fields=['product_url', 'allowed_domains', 'status'])
        return redirect(settings_url)

    return JsonResponse({'success': False, 'error': 'Invalid request method.'})


@login_required
@require_project_settings_editor
def update_project_tracking(request, project_id):
    """Handle tracking mode updates for project settings."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method.'})

    project = get_accessible_project_or_404(request.user, project_id)
    ensure_project_writable(project)
    selected_mode = normalize_tracking_mode_choice(str(request.POST.get('tracking_mode', '')).strip().lower())

    if not selected_mode:
        selected_modules = {
            value.strip().lower()
            for value in request.POST.getlist('tracking_modules')
            if value and value.strip()
        }
        if selected_modules == {'analytics'}:
            selected_mode = TRACKING_MODE_ANALYTICS_ONLY
        elif selected_modules in ({'recording'}, {'analytics', 'recording'}):
            selected_mode = TRACKING_MODE_ANALYTICS_AND_RECORDING

    settings_url = project_route(project, 'project_settings')
    if selected_mode not in {TRACKING_MODE_ANALYTICS_AND_RECORDING, TRACKING_MODE_ANALYTICS_ONLY}:
        messages.error(request, 'Select at least one tracking option.', extra_tags='tracking')
        return redirect(settings_url)

    if project.tracking_capture != selected_mode:
        project.tracking_capture = selected_mode
        project.save(update_fields=['tracking_capture'])
        messages.success(
            request,
            'Update the script in your app to apply these changes.',
            extra_tags='tracking',
        )

    return redirect(settings_url)


def _build_product_area_rows(project, rules):
    rule_ids = [rule.id for rule in rules]
    if not rule_ids:
        return []

    seven_days_ago = timezone.now() - timezone.timedelta(days=7)
    prepared_metrics_available = RawPageDailyMetric.objects.filter(
        project=project,
        page_rule_id__in=rule_ids,
    ).exists()

    if prepared_metrics_available:
        volume_by_rule = _build_product_area_volume_from_metrics(
            project,
            rule_ids,
            seven_days_ago.date(),
        )
        examples_by_rule = _build_product_area_examples_from_metrics(project, rule_ids)
    else:
        volume_by_rule = _build_product_area_volume_from_events(project, rule_ids, seven_days_ago)
        examples_by_rule = _build_product_area_examples_from_events(project, rule_ids)

    rows = []
    for rule in rules:
        rows.append(
            {
                'rule': rule,
                'product_area': (rule.product_area or rule.page_name or 'Ungrouped').strip() or 'Ungrouped',
                'page_name': rule.page_name,
                'pattern': rule.pattern,
                'examples': examples_by_rule.get(rule.id, []),
                'volume_7d': volume_by_rule.get(rule.id, 0),
                'volume_7d_display': f"{volume_by_rule.get(rule.id, 0):,}",
            }
        )

    return rows


def _build_product_area_volume_from_metrics(project, rule_ids, start_date):
    return {
        row['page_rule_id']: row['volume_7d'] or 0
        for row in (
            RawPageDailyMetric.objects.filter(
                project=project,
                page_rule_id__in=rule_ids,
                date__gte=start_date,
            )
            .values('page_rule_id')
            .annotate(volume_7d=Sum('visits_count'))
        )
    }


def _build_product_area_examples_from_metrics(project, rule_ids):
    examples_by_rule = defaultdict(list)
    remaining_rule_ids = set(rule_ids)
    metric_rows = (
        RawPageDailyMetric.objects.filter(project=project, page_rule_id__in=rule_ids)
        .exclude(url_normalized='')
        .values('page_rule_id', 'url_normalized')
        .annotate(latest_date=Max('date'), visits_total=Sum('visits_count'))
        .order_by('page_rule_id', '-latest_date', '-visits_total', 'url_normalized')
    )

    for row in metric_rows.iterator(chunk_size=200):
        rule_id = row['page_rule_id']
        if rule_id not in remaining_rule_ids:
            continue

        url_normalized = (row.get('url_normalized') or '').strip()
        if not url_normalized:
            continue

        examples_by_rule[rule_id].append(url_normalized)

        if len(examples_by_rule[rule_id]) >= PRODUCT_AREA_EXAMPLES_PER_RULE:
            remaining_rule_ids.discard(rule_id)
            if not remaining_rule_ids:
                break

    return examples_by_rule


def _build_product_area_volume_from_events(project, rule_ids, seven_days_ago):
    volume_by_rule = {
        row['page_rule_id']: row['volume_7d']
        for row in (
            AnalyticsEvent.objects.filter(
                session__project=project,
                page_rule_id__in=rule_ids,
                timestamp__gte=seven_days_ago,
            )
            .values('page_rule_id')
            .annotate(volume_7d=Count('id'))
        )
    }
    return volume_by_rule


def _build_product_area_examples_from_events(project, rule_ids):
    examples_by_rule = defaultdict(list)
    for rule_id in rule_ids:
        seen_examples = set()
        urls = (
            AnalyticsEvent.objects.filter(session__project=project, page_rule_id=rule_id)
            .exclude(url_normalized='')
            .order_by('-timestamp', '-id')
            .values_list('url_normalized', flat=True)[:PRODUCT_AREA_EXAMPLE_FALLBACK_SCAN_LIMIT]
        )
        for url_normalized in urls:
            url_normalized = (url_normalized or '').strip()
            if not url_normalized or url_normalized in seen_examples:
                continue

            seen_examples.add(url_normalized)
            examples_by_rule[rule_id].append(url_normalized)

            if len(examples_by_rule[rule_id]) >= PRODUCT_AREA_EXAMPLES_PER_RULE:
                break

    return examples_by_rule


@login_required
@require_project_member
def project_settings(request, project_id):
    """View for project settings page"""
    project = get_accessible_project_or_404(request.user, project_id)
    if not user_can_edit_project_settings(request.user, project):
        raise PermissionDenied('You do not have access to project settings.')

    # Get all available timezones, excluding deprecated Kiev (use Kyiv instead)
    all_timezones = sorted([tz for tz in available_timezones() if tz != 'Europe/Kiev'])

    workspace = project.workspace
    memberships = WorkspaceMembership.objects.filter(
        workspace=workspace,
        status=WorkspaceMemberStatus.ACTIVE,
        removed_at__isnull=True,
    ).select_related('user')
    team_members = []
    for membership in memberships:
        role = effective_workspace_role(membership.role)
        team_members.append({
            'name': membership.user.get_full_name() or membership.user.username,
            'email': membership.user.email,
            'role': role,
            'status': 'active',
            'membership_id': membership.id,
            'is_owner': role == WorkspaceMemberRole.OWNER,
            'can_remove': role != WorkspaceMemberRole.OWNER,
        })

    tracking_capture = normalize_capture_modes(project.tracking_capture)
    tracking_mode = normalize_tracking_mode_choice(project.tracking_capture)
    tracking_mode_values = set(tracking_mode.split(','))
    tracking_uses_analytics = 'analytics' in tracking_mode_values
    allowed_domains = [domain for domain in (project.allowed_domains or []) if domain]
    if len(allowed_domains) == 1:
        allowed_domain = allowed_domains[0]
        allowed_domain_summary = f'{allowed_domain} and all subdomains'
        allowed_domain_helper = f'Includes {allowed_domain} and any subdomain, such as app.{allowed_domain} or acme.{allowed_domain}.'
    elif allowed_domains:
        allowed_domain_summary = f"{', '.join(allowed_domains)} and all subdomains"
        allowed_domain_helper = 'Includes these domains and any subdomain for each one.'
    else:
        allowed_domain_summary = 'Setup required'
        allowed_domain_helper = 'Add the product URL where you will install Hymetry.'
    tracking_mode_label = get_tracking_mode_label(project.tracking_capture)
    tracking_mode_summary = f'{tracking_mode_label}'
    if tracking_mode == TRACKING_MODE_ANALYTICS_ONLY:
        tracking_mode_helper = 'Tracks product usage without recording sessions.'
    else:
        tracking_mode_helper = 'Tracks product usage and records sessions for replay.'

    # Generate tracking script if project has API key
    tracking_script = None
    if project.api_key:
        tracking_script_tag = generate_tracking_script(
            project.api_key,
            {
                'capture': tracking_mode,
            }
        )
        if tracking_uses_analytics:
            tracking_script = f"{generate_identify_settings_snippet()}\n{tracking_script_tag}"
        else:
            tracking_script = tracking_script_tag

    recording_events = Event.objects.filter(session__visitor__project=project)
    analytics_events = AnalyticsEvent.objects.filter(session__project=project)
    latest_recording_event_at = recording_events.order_by('-timestamp').values_list('timestamp', flat=True).first()
    latest_analytics_event_at = analytics_events.order_by('-timestamp').values_list('timestamp', flat=True).first()
    event_timestamps = [
        event_at
        for event_at in (project.last_event_at, latest_recording_event_at, latest_analytics_event_at)
        if event_at
    ]
    last_installation_event_at = max(event_timestamps) if event_timestamps else None
    has_analytics_events = analytics_events.exists()
    has_recording_events = recording_events.exists()
    has_detected_user_id = (
        analytics_events.exclude(user_id__isnull=True)
        .exclude(user_id='')
        .exists()
    )
    has_detected_company_id = (
        analytics_events.exclude(company_id__isnull=True)
        .exclude(company_id='')
        .exists()
    )
    recording_enabled = 'recording' in tracking_mode_values
    analytics_enabled = 'analytics' in tracking_mode_values
    has_allowed_domains = bool(allowed_domains)
    has_installation_event = bool(project.first_production_event_at or last_installation_event_at)
    requires_setup = not has_allowed_domains
    # Fresh installation data means the product is still sending events, not just that setup happened once.
    recent_data_cutoff = timezone.now() - timezone.timedelta(hours=72)
    has_fresh_data = bool(last_installation_event_at and last_installation_event_at >= recent_data_cutoff)
    has_no_recent_data = has_installation_event and not has_fresh_data
    installation_status = {
        'is_active': has_installation_event and has_fresh_data and not requires_setup,
        'has_no_recent_data': has_no_recent_data,
        'requires_setup': requires_setup,
        'last_event_at': last_installation_event_at,
        'analytics_enabled': analytics_enabled,
        'analytics_active': has_analytics_events,
        'recording_enabled': recording_enabled,
        'recording_active': has_recording_events,
        'user_id_detected': has_detected_user_id,
        'company_id_detected': has_detected_company_id,
        'is_ready': (
            has_installation_event
            and has_fresh_data
            and not requires_setup
            and (not analytics_enabled or has_analytics_events)
            and (not recording_enabled or has_recording_events)
            and has_detected_user_id
            and has_detected_company_id
        ),
    }
    user_memberships = active_workspace_memberships().filter(user=request.user).select_related('workspace')
    workspace_membership = get_workspace_membership(request.user, workspace)
    context = {
        'project': project,
        'workspace': workspace,
        'team_members': team_members,
        'tracking_script': tracking_script,
        'tracking_capture': tracking_capture,
        'tracking_mode': tracking_mode,
        'tracking_mode_label': tracking_mode_label,
        'tracking_mode_summary': tracking_mode_summary,
        'tracking_mode_helper': tracking_mode_helper,
        'allowed_domain_summary': allowed_domain_summary,
        'allowed_domain_helper': allowed_domain_helper,
        'tracking_mode_options': (
            {
                'value': TRACKING_MODE_ANALYTICS_ONLY,
                'label': 'Analytics',
                'description': 'Track page views, activity, and usage patterns.',
            },
            {
                'value': TRACKING_MODE_ANALYTICS_AND_RECORDING,
                'label': 'Analytics and screen recording',
                'description': 'Track page views, activity, and usage patterns, and record user sessions for replay and troubleshooting.',
            },
        ),
        'tracking_capture_modes': {
            'recording': 'recording' in tracking_mode_values,
            'analytics': 'analytics' in tracking_mode_values,
        },
        'show_privacy_settings': recording_enabled,
        'can_edit_project_settings': user_can_edit_project_settings(request.user, project),
        'can_delete_project': bool(
            workspace_membership and effective_workspace_role(workspace_membership.role) == WorkspaceMemberRole.OWNER
        ),
        'has_fresh_data': has_fresh_data,
        'installation_status': installation_status,
        'memberships': user_memberships,
        'all_timezones': all_timezones,
        'workspace_project_names_json': json.dumps(list(
            Project.objects.filter(workspace=workspace)
            .exclude(pk=project.pk)
            .values_list('name', flat=True)
        )),
        'project_status_label': project_status_label(project),
        'project_status_key': project_effective_status(project),
    }

    return render(request, 'projects/project_settings.html', context)


@login_required
@require_project_member
def project_product_areas(request, project_id):
    project = get_accessible_project_or_404(request.user, project_id)
    if not user_can_edit_project_settings(request.user, project):
        raise PermissionDenied('You do not have access to project settings.')
    has_observed_pages = AnalyticsEvent.objects.filter(session__project=project).exclude(url_normalized='').exists()
    active_rules = list(
        ProjectPageRule.objects.filter(project=project, is_active=True).order_by('-priority', '-updated_at', 'id')
    )
    paginator = Paginator(active_rules, PRODUCT_AREAS_PER_PAGE)
    page_obj = paginator.get_page(request.GET.get('page'))
    product_area_rows = _build_product_area_rows(project, list(page_obj.object_list))

    context = {
        'project': project,
        'workspace': project.workspace,
        'product_area_rows': product_area_rows,
        'page_obj': page_obj,
        'total_pages': paginator.num_pages,
        'page_number': page_obj.number,
        'has_rules': bool(active_rules),
        'has_observed_pages': has_observed_pages,
    }
    return render(request, 'projects/product_areas.html', context)


@login_required
@require_project_member
def update_page_structure_guidance(request, project_id):
    project = get_accessible_project_or_404(request.user, project_id)
    if not user_can_edit_project_settings(request.user, project):
        raise PermissionDenied('You do not have access to project settings.')
    ensure_project_writable(project)
    redirect_url = project_route(project, 'project_product_areas')
    page_number = request.POST.get('page', '').strip()
    if page_number.isdigit() and int(page_number) > 1:
        redirect_url = f'{redirect_url}?page={page_number}'

    if request.method != 'POST':
        return redirect(redirect_url)

    guidance = request.POST.get('page_structure_guidance', '').strip()
    if len(guidance) > Project._meta.get_field('page_structure_guidance').max_length:
        messages.error(
            request,
            'Keep page structure guidance within 500 characters.',
            extra_tags='product-areas',
        )
        return redirect(redirect_url)

    if project.page_structure_guidance == guidance:
        messages.success(
            request,
            'Page structure guidance is already up to date.',
            extra_tags='product-areas',
        )
        return redirect(redirect_url)

    project.page_structure_guidance = guidance
    project.save(update_fields=['page_structure_guidance'])

    if guidance:
        message_text = 'Saved page structure guidance for the next rule update.'
    else:
        message_text = 'Cleared page structure guidance.'

    messages.success(request, message_text, extra_tags='product-areas')
    return redirect(redirect_url)


@login_required
@require_project_member
def project_intro(request, project_id):
    """View for project intro page after joining"""
    project = get_accessible_project_or_404(request.user, project_id)

    context = {
        'project': project,
    }
    return render(request, 'projects/project_intro.html', context)
