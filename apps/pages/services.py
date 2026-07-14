import copy
import json
import math
import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import Max, Sum
from django.utils.text import slugify
from django.utils import timezone as django_timezone

from apps.pages import queries
from apps.pages.locks import project_advisory_lock
from apps.pages.models import PageCompanyDailyMetric, PageDailyMetric, PageUserDailyMetric, RawPageActionDailyMetric
from apps.tracker.models import ProjectPageRule


DEFAULT_FILTERS_HASH = 'default'
DEFAULT_SESSION_TIMEOUT_SECONDS = 30 * 60
DEFAULT_EVENT_GAP_CAP_SECONDS = 30
DEFAULT_OVERVIEW_RANGE_KEYS = ('last_7_days', 'last_30_days', 'last_90_days', 'last_180_days')
OVERVIEW_PAYLOAD_SCHEMA_VERSION = 16
CACHE_TTL = timedelta(hours=1)
POWER_USER_VISITS_PER_WEEK = 9
POWER_USER_ENGAGED_SECONDS_PER_WEEK = 1500
POWER_USER_ACTIVE_DAYS_SHARE = 0.30
POWER_USER_PRODUCT_AREAS = 2
POWER_USER_MIN_INTERACTION = 0.20
JSON_SCRIPT_ESCAPES = str.maketrans({
    '>': '\\u003E',
    '<': '\\u003C',
    '&': '\\u0026',
})
PRODUCT_AREA_SUMMARY_TREND_METRICS = ('companies', 'adoption', 'users', 'engaged')
OVERVIEW_ROW_TREND_METRICS = ('companies', 'adoption', 'engaged')
SYNTHETIC_USER_ID_RE = re.compile(r'^user[_-](?P<company>.+)_(?P<suffix>\d+)$')


def weekly_scaled_threshold(base_value, period_days):
    scale = max(1.0, float(period_days or 1) / 7.0)
    return max(int(base_value), math.ceil(base_value * scale))


def active_days_threshold(period_days, share):
    days = max(1, int(period_days or 1))
    return min(days, max(1, math.ceil(days * share)))


def passive_visits_threshold(period_days):
    days = max(1, int(period_days or 1))
    return max(2, math.ceil(days / 14.0))


def power_user_thresholds(period_days):
    return {
        'visits': weekly_scaled_threshold(POWER_USER_VISITS_PER_WEEK, period_days),
        'engaged_seconds': weekly_scaled_threshold(POWER_USER_ENGAGED_SECONDS_PER_WEEK, period_days),
        'active_days': active_days_threshold(period_days, POWER_USER_ACTIVE_DAYS_SHARE),
        'product_areas': POWER_USER_PRODUCT_AREAS,
        'interaction': POWER_USER_MIN_INTERACTION,
    }


PAGE_DETAIL_METRICS = (
    {
        'key': 'companies',
        'label': 'Companies',
        'source': 'companies_count',
        'delta_type': 'percent',
        'value_type': 'count',
    },
    {
        'key': 'adoption',
        'label': 'Adoption',
        'source': 'adoption_pct',
        'delta_type': 'percentage_point',
        'value_type': 'percent',
    },
    {
        'key': 'users',
        'label': 'Users',
        'source': 'users_count',
        'delta_type': 'percent',
        'value_type': 'count',
    },
    {
        'key': 'penetration',
        'label': 'Penetration',
        'source': 'penetration_pct',
        'delta_type': 'percentage_point',
        'value_type': 'percent',
    },
    {
        'key': 'visits',
        'label': 'Visits',
        'source': 'visits_count',
        'delta_type': 'percent',
        'value_type': 'count',
    },
    {
        'key': 'engaged',
        'label': 'Engaged',
        'source': 'engaged_seconds',
        'delta_type': 'percent',
        'value_type': 'duration',
    },
    {
        'key': 'avg_visit',
        'label': 'Avg / visit',
        'source': 'avg_visit_seconds',
        'delta_type': 'percent',
        'value_type': 'duration',
    },
    {
        'key': 'interaction',
        'label': 'Interaction',
        'source': 'interaction_pct',
        'delta_type': 'percentage_point',
        'value_type': 'percent',
    },
    {
        'key': 'clicks_per_visit',
        'label': 'Clicks / visit',
        'source': 'clicks_per_visit',
        'delta_type': 'percent',
        'value_type': 'ratio',
    },
)


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def to_json_script_text(payload):
    return json.dumps(payload, default=_json_default, separators=(',', ':')).translate(JSON_SCRIPT_ESCAPES)


def escape_json_script_text(value):
    return str(value or '{}').translate(JSON_SCRIPT_ESCAPES)


def _project_zone(timezone_name):
    try:
        return ZoneInfo(timezone_name or 'UTC')
    except ZoneInfoNotFoundError:
        return ZoneInfo('UTC')


def _utc_bounds_for_local_dates(start_date, end_date, timezone_name):
    zone = _project_zone(timezone_name)
    start_local = datetime.combine(start_date, time.min, tzinfo=zone)
    end_local = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=zone)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _safe_trait_email(value):
    text = str(value or '').strip()
    return text if '@' in text else ''


def user_trait_email_lookup(project, start_date, end_date, *, user_ids=None):
    from apps.tracker.models import AnalyticsEvent

    project_id = getattr(project, 'id', None)
    timezone_name = getattr(project, 'timezone', None)
    if isinstance(project, dict):
        project_id = project.get('id') or project.get('project_id')
        timezone_name = project.get('timezone')
    if not project_id:
        return {}

    normalized_user_ids = None
    if user_ids is not None:
        normalized_user_ids = [str(user_id) for user_id in user_ids if user_id not in (None, '')]
        if not normalized_user_ids:
            return {}

    start_ts, end_ts = _utc_bounds_for_local_dates(start_date, end_date, timezone_name or 'UTC')
    queryset = (
        AnalyticsEvent.objects
        .filter(session__project_id=project_id, timestamp__gte=start_ts, timestamp__lt=end_ts)
        .exclude(user_id__isnull=True)
        .exclude(user_id='')
        .filter(user_traits__email__isnull=False)
        .order_by('-timestamp')
    )
    if normalized_user_ids is not None:
        queryset = queryset.filter(user_id__in=normalized_user_ids)

    emails = {}
    for row in queryset.values('user_id', 'user_traits').iterator(chunk_size=2000):
        user_id = str(row.get('user_id') or '').strip()
        if not user_id or user_id in emails:
            continue
        email = _safe_trait_email((row.get('user_traits') or {}).get('email'))
        if email:
            emails[user_id] = email
    return emails


def _safe_date(value):
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _today_for_project(timezone_name):
    return django_timezone.now().astimezone(_project_zone(timezone_name)).date()


def resolve_period(project_timezone, range_key='last_30_days', start_date=None, end_date=None):
    if start_date and end_date:
        return _safe_date(start_date), _safe_date(end_date)

    today = _today_for_project(project_timezone)
    if range_key == 'last_7_days':
        return today - timedelta(days=6), today
    if range_key == 'last_90_days':
        return today - timedelta(days=89), today
    if range_key == 'last_180_days':
        return today - timedelta(days=179), today

    return today - timedelta(days=29), today


def previous_period(start_date, end_date):
    days = (end_date - start_date).days + 1
    previous_end = start_date - timedelta(days=1)
    previous_start = previous_end - timedelta(days=days - 1)
    return previous_start, previous_end


def get_project_info(project_id):
    return queries.fetch_one(queries.PROJECT_INFO_SQL, [project_id])


def get_recent_analytics_project_ids(since_ts):
    rows = queries.fetch_all(queries.RECENT_ANALYTICS_PROJECTS_SQL, [since_ts])
    return [row['project_id'] for row in rows]


def get_cached_overview_payload(project_id, range_key='last_30_days', filters_hash=DEFAULT_FILTERS_HASH):
    row = queries.fetch_one(queries.FETCH_OVERVIEW_CACHE_SQL, [project_id, range_key, filters_hash])
    if not row:
        return None
    row['payload_json'] = _coerce_json(row.get('payload_json'))
    return row


def get_cached_overview_payload_json(project_id, range_key='last_30_days', filters_hash=DEFAULT_FILTERS_HASH):
    return queries.fetch_one(queries.FETCH_OVERVIEW_CACHE_JSON_SQL, [project_id, range_key, filters_hash])


def get_cached_detail_payload(project_id, page_rule_id, range_key='last_30_days', filters_hash=DEFAULT_FILTERS_HASH):
    row = queries.fetch_one(
        queries.FETCH_DETAIL_CACHE_SQL,
        [project_id, range_key, str(page_rule_id or ''), filters_hash],
    )
    if not row:
        return None
    row['payload_json'] = _coerce_json(row.get('payload_json'))
    return row


def get_cached_scatter_tooltips(project_id, range_key='last_30_days', filters_hash=DEFAULT_FILTERS_HASH):
    row = queries.fetch_one(queries.FETCH_SCATTER_TOOLTIP_CACHE_SQL, [project_id, range_key, filters_hash])
    if not row:
        return None
    row['payload_json'] = _coerce_json(row.get('payload_json'))
    return row


def _coerce_json(value):
    if isinstance(value, str):
        return json.loads(value)
    return value or {}


def _run_daily_delete(project_id, start_date, end_date):
    for sql in queries.DELETE_DAILY_METRICS_SQL:
        queries.execute(sql, [project_id, start_date, end_date])


def rebuild_project_pages_analytics(
    project_id,
    start_date,
    end_date,
    *,
    range_keys=DEFAULT_OVERVIEW_RANGE_KEYS,
    session_timeout_seconds=DEFAULT_SESSION_TIMEOUT_SECONDS,
    include_user_details=False,
):
    project = get_project_info(project_id)
    if not project:
        raise ValueError(f'Project {project_id} does not exist.')

    start_date = _safe_date(start_date)
    end_date = _safe_date(end_date)
    timezone_name = project['timezone'] or 'UTC'
    window_start_utc, window_end_utc = _utc_bounds_for_local_dates(
        start_date - timedelta(days=1),
        end_date + timedelta(days=1),
        timezone_name,
    )
    strict_start_utc, strict_end_utc = _utc_bounds_for_local_dates(start_date, end_date, timezone_name)

    with project_advisory_lock(project_id, namespace='pages-rebuild') as acquired:
        if not acquired:
            return {'status': 'skipped', 'reason': 'lock_not_acquired', 'project_id': project_id}

        queries.execute(
            queries.ENSURE_PRODUCT_AREAS_SQL,
            [project_id, project_id, window_start_utc, window_end_utc],
        )
        queries.execute(
            queries.DELETE_TRANSITIONS_FOR_WINDOW_SQL,
            [
                project_id,
                strict_start_utc,
                strict_end_utc,
                project_id,
                strict_start_utc,
                strict_end_utc,
                project_id,
                strict_start_utc,
                strict_end_utc,
            ],
        )
        queries.execute(queries.DELETE_VISITS_FOR_WINDOW_SQL, [project_id, strict_start_utc, strict_end_utc])
        queries.execute(
            queries.INSERT_PAGE_VISITS_SQL,
            [
                project_id,
                window_start_utc,
                window_end_utc,
                session_timeout_seconds,
                strict_start_utc,
                strict_end_utc,
            ],
        )
        queries.execute(
            queries.INSERT_PAGE_TRANSITIONS_SQL,
            [project_id, strict_start_utc, strict_end_utc, session_timeout_seconds],
        )

        aggregate_page_daily_metrics(project_id, start_date, end_date, timezone_name, use_lock=False)

        cache_result = rebuild_project_analytics_caches(
            project_id,
            range_keys=range_keys,
            include_user_details=include_user_details,
        )

    return {
        'status': 'success',
        'project_id': project_id,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'cache_results': cache_result['cache_results'],
        'companies_cache_results': cache_result['companies_cache_results'],
        'users_cache_results': cache_result['users_cache_results'],
    }


def rebuild_project_analytics_caches(project_id, *, range_keys=DEFAULT_OVERVIEW_RANGE_KEYS, include_user_details=False):
    from apps.pages.company_analytics import build_companies_overview_cache
    from apps.pages.user_analytics import build_users_overview_cache

    selected_range_keys = DEFAULT_OVERVIEW_RANGE_KEYS if range_keys is None else tuple(range_keys)
    cache_results = []
    companies_cache_results = []
    users_cache_results = []

    for range_key in selected_range_keys:
        cache_results.append(build_pages_overview_cache(project_id, range_key=range_key))
        companies_cache_results.append(build_companies_overview_cache(project_id, range_key=range_key))
        users_cache_results.append(
            build_users_overview_cache(
                project_id,
                range_key=range_key,
                include_user_details=include_user_details,
            )
        )

    obsolete_cache_purge = (
        purge_obsolete_analytics_cache_rows(project_id, range_keys=selected_range_keys)
        if selected_range_keys
        else {
            'project_id': project_id,
            'range_keys': [],
            'deleted': {},
            'deleted_total': 0,
        }
    )

    return {
        'status': 'success',
        'project_id': project_id,
        'range_keys': list(selected_range_keys),
        'include_user_details': include_user_details,
        'cache_results': cache_results,
        'companies_cache_results': companies_cache_results,
        'users_cache_results': users_cache_results,
        'obsolete_cache_purge': obsolete_cache_purge,
    }


def purge_obsolete_analytics_cache_rows(project_id, *, range_keys=None):
    from apps.pages import company_analytics, company_detail_analytics, user_analytics, user_detail_analytics
    from apps.pages.models import (
        CompaniesDetailCache,
        CompaniesOverviewCache,
        PagesDetailCache,
        PagesOverviewCache,
        UsersDetailCache,
        UsersOverviewCache,
    )

    selected_range_keys = None if range_keys is None else tuple(range_keys)

    def purge_model(model, current_schema_version):
        queryset = model.objects.filter(project_id=project_id)
        if selected_range_keys is not None:
            queryset = queryset.filter(range_key__in=selected_range_keys)
        deleted_count, _deleted_by_model = queryset.exclude(
            payload_json__schema_version=current_schema_version,
        ).delete()
        return deleted_count

    deleted = {
        'pages_overview': purge_model(PagesOverviewCache, OVERVIEW_PAYLOAD_SCHEMA_VERSION),
        'pages_detail': purge_model(PagesDetailCache, OVERVIEW_PAYLOAD_SCHEMA_VERSION),
        'companies_overview': purge_model(CompaniesOverviewCache, company_analytics.COMPANIES_PAYLOAD_SCHEMA_VERSION),
        'companies_detail': purge_model(CompaniesDetailCache, company_detail_analytics.COMPANY_DETAIL_PAYLOAD_SCHEMA_VERSION),
        'users_overview': purge_model(UsersOverviewCache, user_analytics.USERS_PAYLOAD_SCHEMA_VERSION),
        'users_detail': purge_model(UsersDetailCache, user_detail_analytics.USER_DETAILS_PAYLOAD_SCHEMA_VERSION),
    }
    return {
        'project_id': project_id,
        'range_keys': list(selected_range_keys) if selected_range_keys is not None else None,
        'deleted': deleted,
        'deleted_total': sum(deleted.values()),
    }


def refresh_recent_projects_pages_analytics(
    *,
    lookback_days=2,
    active_since_days=2,
    range_keys=DEFAULT_OVERVIEW_RANGE_KEYS,
    project_ids=None,
    exclude_project_ids=None,
):
    active_since_ts = django_timezone.now() - timedelta(days=active_since_days)
    if project_ids is None:
        selected_project_ids = get_recent_analytics_project_ids(active_since_ts)
    else:
        selected_project_ids = list(project_ids)
    excluded_project_ids = {int(project_id) for project_id in (exclude_project_ids or [])}
    if excluded_project_ids:
        selected_project_ids = [
            project_id for project_id in selected_project_ids if int(project_id) not in excluded_project_ids
        ]
    results = []

    for project_id in selected_project_ids:
        project = get_project_info(project_id)
        if not project:
            results.append({'status': 'skipped', 'reason': 'missing_project', 'project_id': project_id})
            continue

        end_date = _today_for_project(project['timezone'] or 'UTC')
        start_date = end_date - timedelta(days=max(int(lookback_days), 1) - 1)

        try:
            results.append(
                rebuild_project_pages_analytics(
                    project_id,
                    start_date,
                    end_date,
                    range_keys=tuple(range_keys or DEFAULT_OVERVIEW_RANGE_KEYS),
                )
            )
        except Exception as exc:
            results.append({
                'status': 'failed',
                'project_id': project_id,
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat(),
                'error': str(exc),
            })

    return {
        'status': 'success',
        'projects_count': len(selected_project_ids),
        'lookback_days': lookback_days,
        'active_since_days': active_since_days,
        'range_keys': list(range_keys or DEFAULT_OVERVIEW_RANGE_KEYS),
        'excluded_project_ids': sorted(excluded_project_ids),
        'results': results,
    }


def aggregate_page_daily_metrics(project_id, start_date, end_date, timezone_name=None, *, use_lock=True):
    project = get_project_info(project_id)
    if not project:
        raise ValueError(f'Project {project_id} does not exist.')

    timezone_name = timezone_name or project['timezone'] or 'UTC'
    start_date = _safe_date(start_date)
    end_date = _safe_date(end_date)
    date_params = [project_id, start_date, end_date]

    if use_lock:
        with project_advisory_lock(project_id, namespace='pages-rebuild') as acquired:
            if not acquired:
                return {
                    'status': 'skipped',
                    'reason': 'lock_not_acquired',
                    'project_id': project_id,
                    'start_date': date_params[1].isoformat(),
                    'end_date': date_params[2].isoformat(),
                }

            return aggregate_page_daily_metrics(
                project_id,
                start_date,
                end_date,
                timezone_name,
                use_lock=False,
            )

    _run_daily_delete(project_id, start_date, end_date)

    common_params = [timezone_name, project_id, timezone_name, start_date, timezone_name, end_date]
    queries.execute(queries.INSERT_PAGE_DAILY_METRICS_SQL, common_params)
    queries.execute(queries.INSERT_PAGE_COMPANY_DAILY_METRICS_SQL, common_params)
    queries.execute(queries.INSERT_PAGE_USER_DAILY_METRICS_SQL, common_params)
    queries.execute(queries.INSERT_RAW_PAGE_DAILY_METRICS_SQL, common_params)
    queries.execute(queries.INSERT_RAW_PAGE_ACTION_DAILY_METRICS_SQL, common_params)
    queries.execute(queries.INSERT_PROJECT_DAILY_METRICS_SQL, common_params)

    return {
        'status': 'success',
        'project_id': project_id,
        'start_date': date_params[1].isoformat(),
        'end_date': date_params[2].isoformat(),
    }


def _to_int(value):
    return int(value or 0)


def _to_float(value):
    return float(value or 0)


def _pct(numerator, denominator):
    denominator = _to_float(denominator)
    if denominator <= 0:
        return 0.0
    return round(_to_float(numerator) / denominator * 100, 1)


def _bounded_pct(numerator, denominator):
    numerator = _to_float(numerator)
    denominator = max(_to_float(denominator), numerator)
    return _pct(numerator, denominator)


def _ratio(numerator, denominator):
    denominator = _to_float(denominator)
    if denominator <= 0:
        return 0.0
    return round(_to_float(numerator) / denominator, 2)


def _delta_pct(current, previous):
    current = _to_float(current)
    previous = _to_float(previous)
    if previous == 0 and current == 0:
        return {'value': 0, 'label': '0', 'direction': 'neutral'}
    if previous == 0:
        return {'value': None, 'label': 'New', 'direction': 'positive'}
    value = round((current - previous) / previous * 100, 1)
    return {'value': value, 'label': _format_signed(value, '%'), 'direction': _direction(value, 5)}


def _delta_pp(current, previous):
    value = round(_to_float(current) - _to_float(previous), 1)
    return {'value': value, 'label': _format_signed(value, ' pp'), 'direction': _direction(value, 1)}


def _direction(value, threshold):
    if value >= threshold:
        return 'positive'
    if value <= -threshold:
        return 'negative'
    return 'neutral'


def _format_signed(value, suffix):
    numeric = _to_float(value)
    rounded = int(numeric + 0.5) if numeric >= 0 else int(numeric - 0.5)
    prefix = '+' if rounded > 0 else ''
    return f'{prefix}{rounded}{suffix}'


def _format_duration(seconds):
    seconds = _to_int(seconds)
    hours = seconds // 3600
    minutes = round((seconds % 3600) / 60)
    if hours > 0:
        return f'{hours}h {minutes}m' if minutes else f'{hours}h'
    return f'{minutes}m'


def _format_duration_kpi(seconds):
    seconds = _to_int(seconds)
    hours = seconds // 3600
    if hours > 0:
        return f'{hours}h'
    minutes = round(seconds / 60)
    return f'{minutes}m'


def _page_rule_id(row):
    value = (
        row.get('page_rule_id')
        or row.get('product_area_key')
        or row.get('product_area_id')
        or row.get('page_name')
        or row.get('product_area_name')
        or ''
    )
    return str(value)


def _delta_value(row, metric):
    delta = row.get('deltas', {}).get(metric, {})
    if not isinstance(delta, dict):
        return 0
    value = delta.get('value')
    return 0 if value is None else _to_float(value)


def _trend_values(row, metric):
    return [
        _to_float(point.get('current'))
        for point in row.get('relative_change_series', {}).get(metric, [])
        if isinstance(point, dict)
    ]


def _weighted_percent_change(rows, value_key, delta_key):
    current_total = 0.0
    previous_total = 0.0
    for row in rows:
        current = _to_float(row.get(value_key))
        delta = _to_float(row.get(delta_key))
        previous = 0 if delta <= -100 else current / (1 + delta / 100)
        current_total += current
        previous_total += previous

    if previous_total <= 0:
        return 100 if current_total > 0 else 0
    return round((current_total - previous_total) / previous_total * 100, 1)


def _percent_change_value(current, previous):
    current = _to_float(current)
    previous = _to_float(previous)
    if previous <= 0:
        return 100 if current > 0 else 0
    return round((current - previous) / previous * 100, 1)


def _ensure_change_row_contract(row):
    page_name = row.get('page_name') or row.get('product_area_name') or row.get('product_area_key') or 'Untitled page'
    page_group = row.get('page_group') or row.get('product_area_name') or page_name or 'Unassigned'
    bars = row.get('bars') or {}

    row['page_rule_id'] = _page_rule_id(row)
    row['page_rule_ids'] = [str(value) for value in _page_rule_aliases(row)]
    row['page_name'] = page_name
    row['page_group'] = page_group
    row.setdefault('trend_values', _trend_values(row, 'companies'))

    delta_fields = {
        'companies_change_pct': 'companies',
        'adoption_change_pp': 'adoption',
        'users_change_pct': 'users',
        'penetration_change_pp': 'penetration',
        'visits_change_pct': 'visits',
        'engaged_change_pct': 'engaged',
        'avg_visit_change_pct': 'avg_visit',
        'interaction_change_pp': 'interaction',
        'clicks_per_visit_change_pct': 'clicks_per_visit',
    }
    for field_name, metric in delta_fields.items():
        if row.get(field_name) is None:
            row[field_name] = _delta_value(row, metric)

    for metric in (
        'companies',
        'adoption',
        'users',
        'penetration',
        'visits',
        'engaged',
        'avg_visit',
        'interaction',
        'clicks_per_visit',
    ):
        field_name = f'{metric}_bar_value'
        if row.get(field_name) is None:
            row[field_name] = _to_float(bars.get(metric))

    return row


def _strip_relative_change_series(row):
    slim_row = dict(row)
    slim_row.pop('relative_change_series', None)
    return slim_row


def _with_compact_trends(row, metrics=PRODUCT_AREA_SUMMARY_TREND_METRICS):
    row = dict(row)
    existing = row.get('trends')
    if isinstance(existing, dict) and all(isinstance(existing.get(metric), list) for metric in metrics):
        return row

    relative_change_series = row.get('relative_change_series')
    if not isinstance(relative_change_series, dict):
        return row

    trends = dict(existing) if isinstance(existing, dict) else {}
    for metric in metrics:
        if isinstance(trends.get(metric), list):
            continue
        points = relative_change_series.get(metric) or []
        values = [
            _to_float(point.get('current'))
            for point in points
            if isinstance(point, dict)
        ]
        if values:
            trends[metric] = values

    if trends:
        row['trends'] = trends
    return row


def _strip_for_product_area_summary(row):
    return _strip_relative_change_series(_with_compact_trends(row))


def _strip_for_overview_row(row):
    return _strip_relative_change_series(_with_compact_trends(row, OVERVIEW_ROW_TREND_METRICS))


def _median(values):
    values = sorted(value for value in values if value is not None)
    if not values:
        return 0
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2


def _date_range(start_date, end_date):
    day = start_date
    while day <= end_date:
        yield day
        day += timedelta(days=1)


def _summary_by_area(project_id, start_date, end_date):
    rows = queries.fetch_all(
        queries.AREA_SUMMARY_SQL,
        [
            project_id, start_date, end_date,
            project_id, start_date, end_date,
            project_id, start_date, end_date,
            project_id, start_date, end_date,
        ],
    )
    return {row['product_area_key']: row for row in rows}


def _page_metric_key(row):
    product_area_key = row.get('product_area_key') or 'unassigned'
    page_rule_id = row.get('page_rule_id')
    page_key = str(page_rule_id) if page_rule_id is not None else ''
    return f'{product_area_key}::{page_key}'


def _page_display_name(row):
    return (
        row.get('page_name')
        or row.get('pageName')
        or row.get('displayName')
        or row.get('product_area_name')
        or row.get('productAreaName')
        or row.get('page_group')
        or _page_rule_id(row)
        or 'Untitled page'
    )


def _page_display_group(row):
    return (
        row.get('page_group')
        or row.get('product_area_name')
        or row.get('productAreaName')
        or 'Unassigned'
    )


def _page_display_key(row):
    return str(_page_display_name(row) or '').strip().casefold()


def _page_rule_aliases(row):
    aliases = []
    values = [*(row.get('page_rule_ids') or []), row.get('page_rule_id')]
    for value in values:
        if value in (None, ''):
            continue
        normalized = str(value)
        if all(str(existing) != normalized for existing in aliases):
            aliases.append(value)
    return aliases


def _collapse_page_metric_representatives(rows):
    """Collapse legacy rule-grained cache rows without inventing aggregate metrics.

    Schema 16 caches contain exact display-page rows.  This conservative fallback
    keeps stale schema 15 caches usable while their asynchronous rebuild is queued.
    """
    groups = {}
    order = []
    for source_row in rows or []:
        if not isinstance(source_row, dict):
            continue
        row = dict(source_row)
        key = _page_display_key(row) or f"rule:{_page_rule_id(row)}"
        group = groups.get(key)
        if group is None:
            group = {'leader': row, 'aliases': []}
            groups[key] = group
            order.append(key)

        leader = group['leader']
        leader_rank = (_to_int(leader.get('visits_count')), _to_int(leader.get('engaged_seconds')))
        row_rank = (_to_int(row.get('visits_count')), _to_int(row.get('engaged_seconds')))
        if row_rank > leader_rank:
            group['leader'] = row

        for alias in _page_rule_aliases(row):
            if all(str(existing) != str(alias) for existing in group['aliases']):
                group['aliases'].append(alias)

    collapsed = []
    for key in order:
        group = groups[key]
        leader = dict(group['leader'])
        leader['page_rule_ids'] = group['aliases']
        collapsed.append(leader)
    return collapsed


def _summary_by_page(project_id, start_date, end_date):
    rows = queries.fetch_all(
        queries.PAGE_SUMMARY_SQL,
        [
            project_id, start_date, end_date,
            project_id, start_date, end_date,
            project_id, start_date, end_date,
            project_id, start_date, end_date,
        ],
    )
    return {_page_metric_key(row): row for row in rows}


def _summary_by_display_page(project_id, start_date, end_date):
    rows = queries.fetch_all(
        queries.PAGE_DISPLAY_SUMMARY_SQL,
        [
            project_id, start_date, end_date,
            project_id, start_date, end_date,
            project_id, start_date, end_date,
        ],
    )
    return {row['page_display_key']: row for row in rows}


def _treemap_page_rows(project_id, start_date, end_date, previous_start, previous_end):
    return queries.fetch_all(
        queries.TREEMAP_PAGE_ROWS_SQL,
        [
            project_id, start_date, end_date,
            project_id, start_date, end_date,
            project_id, start_date, end_date,
            project_id, previous_start, previous_end,
        ],
    )


def _project_distinct_counts(project_id, start_date, end_date):
    row = queries.fetch_one(
        queries.PROJECT_DISTINCT_COUNTS_SQL,
        [project_id, start_date, end_date, project_id, start_date, end_date],
    )
    return row or {'active_companies_count': 0, 'active_users_count': 0}


def _has_period_comparison_data(rows_by_key, counts):
    return (
        bool(rows_by_key)
        or _to_int(counts.get('active_companies_count')) > 0
        or _to_int(counts.get('active_users_count')) > 0
    )


def _penetration_denominators(project_id, start_date, end_date):
    rows = queries.fetch_all(
        queries.PENETRATION_DENOMINATOR_SQL,
        [project_id, start_date, end_date, project_id, start_date, end_date],
    )
    return {row['product_area_key']: _to_int(row['active_users_in_adopted_companies']) for row in rows}


def _page_penetration_denominators(project_id, start_date, end_date):
    rows = queries.fetch_all(
        queries.PAGE_PENETRATION_DENOMINATOR_SQL,
        [project_id, start_date, end_date, project_id, start_date, end_date],
    )
    return {_page_metric_key(row): _to_int(row['active_users_in_adopted_companies']) for row in rows}


def _display_page_penetration_denominators(project_id, start_date, end_date):
    rows = queries.fetch_all(
        queries.PAGE_DISPLAY_PENETRATION_DENOMINATOR_SQL,
        [project_id, start_date, end_date, project_id, start_date, end_date],
    )
    return {
        row['page_display_key']: _to_int(row['active_users_in_adopted_companies'])
        for row in rows
    }


def _daily_area_rows(project_id, start_date, end_date):
    rows = queries.fetch_all(
        queries.DAILY_AREA_METRICS_SQL,
        [
            project_id,
            start_date,
            end_date,
            project_id,
            start_date,
            end_date,
            project_id,
            start_date,
            end_date,
            project_id,
        ],
    )
    data = {}
    for row in rows:
        data[(row['date'], row['product_area_key'])] = row
    return data


def _daily_page_rows(project_id, start_date, end_date):
    rows = queries.fetch_all(queries.DAILY_PAGE_METRICS_SQL, [project_id, start_date, end_date])
    data = {}
    for row in rows:
        data[(row['date'], _page_metric_key(row))] = row
    return data


def _daily_display_page_rows(project_id, start_date, end_date):
    rows = queries.fetch_all(
        queries.DAILY_PAGE_DISPLAY_METRICS_SQL,
        [
            project_id, start_date, end_date,
            project_id, start_date, end_date,
            project_id, start_date, end_date,
            project_id,
        ],
    )
    return {
        (row['date'], row['page_display_key']): row
        for row in rows
    }


def _daily_page_rows_for_rows(project_id, start_date, end_date, rows):
    page_rule_ids = sorted({
        page_rule_id
        for page_rule_id in (_coerce_int_or_none(row.get('page_rule_id')) for row in rows or [])
        if page_rule_id is not None
    })
    if not page_rule_ids:
        return _daily_page_rows(project_id, start_date, end_date)

    daily_rows = queries.fetch_all(
        queries.DAILY_PAGE_METRICS_FOR_RULES_SQL,
        [project_id, start_date, end_date, page_rule_ids],
    )
    data = {}
    for row in daily_rows:
        data[(row['date'], _page_metric_key(row))] = row
    return data


class BulkPageDetailContext:
    def __init__(self, project_id, start_date, end_date):
        self.project_id = project_id
        self.start_date = start_date
        self.end_date = end_date
        self._daily_rows_cache = {}

    def daily_page_rows_for_rows(self, rows):
        page_rule_ids = tuple(sorted({
            page_rule_id
            for page_rule_id in (_coerce_int_or_none(row.get('page_rule_id')) for row in rows or [])
            if page_rule_id is not None
        }))
        key = page_rule_ids or ('__all__',)
        if key not in self._daily_rows_cache:
            self._daily_rows_cache[key] = _daily_page_rows_for_rows(
                self.project_id,
                self.start_date,
                self.end_date,
                rows,
            )
        return self._daily_rows_cache[key]


def _daily_metric_value(row, metric):
    if not row:
        return 0
    visits = _to_int(row.get('visits_count'))
    if metric == 'companies':
        return _to_int(row.get('companies_count_daily'))
    if metric == 'users':
        return _to_int(row.get('users_count_daily'))
    if metric == 'visits':
        return visits
    if metric == 'engaged':
        return _to_int(row.get('engaged_seconds'))
    if metric == 'avg_visit':
        return _ratio(row.get('engaged_seconds'), visits)
    if metric == 'clicks_per_visit':
        return _ratio(row.get('click_count'), visits)
    if metric == 'interaction':
        return _pct(row.get('visits_with_click_count'), visits)
    if metric == 'adoption':
        return _bounded_pct(row.get('companies_count_daily'), row.get('active_companies_count'))
    if metric == 'penetration':
        return _bounded_pct(row.get('users_count_daily'), row.get('active_users_count'))
    return 0


def _relative_change_series(row_key, current_start, current_end, previous_start, daily_current, daily_previous, metric):
    is_rate = metric in {'adoption', 'penetration', 'interaction'}
    series = []
    offset = 0
    for current_date in _date_range(current_start, current_end):
        previous_date = previous_start + timedelta(days=offset)
        current_row = daily_current.get((current_date, row_key))
        previous_row = daily_previous.get((previous_date, row_key))
        current_value = _daily_metric_value(current_row, metric)
        previous_value = _daily_metric_value(previous_row, metric)

        if is_rate:
            change = round(current_value - previous_value, 1)
            direction = _direction(change, 1)
            label = _format_signed(change, ' pp') if change else '0'
            unit = 'pp'
            magnitude = abs(change)
        else:
            delta = _delta_pct(current_value, previous_value)
            change = delta['value']
            direction = delta['direction']
            label = delta['label']
            unit = '%'
            magnitude = 100 if change is None else abs(change)

        series.append({
            'date': current_date.isoformat(),
            'current': current_value,
            'previous': previous_value,
            'change': change,
            'unit': unit,
            'direction': direction,
            'magnitude': min(magnitude, 100),
            'label': label,
        })
        offset += 1
    return series


def _build_change_rows(project_id, start_date, end_date, previous_start, previous_end, *, grain='page'):
    if grain == 'product_area':
        current = _summary_by_area(project_id, start_date, end_date)
        previous = _summary_by_area(project_id, previous_start, previous_end)
        current_penetration_denominators = _penetration_denominators(project_id, start_date, end_date)
        previous_penetration_denominators = _penetration_denominators(project_id, previous_start, previous_end)
        daily_current = _daily_area_rows(project_id, start_date, end_date)
        daily_previous = _daily_area_rows(project_id, previous_start, previous_end)
    elif grain == 'display_page':
        current = _summary_by_display_page(project_id, start_date, end_date)
        previous = _summary_by_display_page(project_id, previous_start, previous_end)
        current_penetration_denominators = _display_page_penetration_denominators(project_id, start_date, end_date)
        previous_penetration_denominators = _display_page_penetration_denominators(project_id, previous_start, previous_end)
        daily_current = _daily_display_page_rows(project_id, start_date, end_date)
        daily_previous = _daily_display_page_rows(project_id, previous_start, previous_end)
    else:
        current = _summary_by_page(project_id, start_date, end_date)
        previous = _summary_by_page(project_id, previous_start, previous_end)
        current_penetration_denominators = _page_penetration_denominators(project_id, start_date, end_date)
        previous_penetration_denominators = _page_penetration_denominators(project_id, previous_start, previous_end)
        daily_current = _daily_page_rows(project_id, start_date, end_date)
        daily_previous = _daily_page_rows(project_id, previous_start, previous_end)

    current_counts = _project_distinct_counts(project_id, start_date, end_date)
    previous_counts = _project_distinct_counts(project_id, previous_start, previous_end)
    comparison_available = _has_period_comparison_data(previous, previous_counts)

    max_values = defaultdict(int)
    prepared = []
    metric_names = (
        'companies',
        'adoption',
        'users',
        'penetration',
        'visits',
        'engaged',
        'avg_visit',
        'interaction',
        'clicks_per_visit',
    )

    for row_key, row in current.items():
        previous_row = previous.get(row_key, {})
        product_area_key = row.get('product_area_key') or row_key or 'unassigned'
        product_area_name = row.get('product_area_name') or product_area_key
        page_name = row.get('page_name') or product_area_name
        visits = _to_int(row.get('visits_count'))
        previous_visits = _to_int(previous_row.get('visits_count'))
        engaged = _to_int(row.get('engaged_seconds'))
        previous_engaged = _to_int(previous_row.get('engaged_seconds'))
        companies = _to_int(row.get('companies_count'))
        previous_companies = _to_int(previous_row.get('companies_count'))
        users = _to_int(row.get('users_count'))
        previous_users = _to_int(previous_row.get('users_count'))
        adoption = _bounded_pct(companies, current_counts.get('active_companies_count'))
        previous_adoption = _bounded_pct(previous_companies, previous_counts.get('active_companies_count'))
        penetration = _pct(users, current_penetration_denominators.get(row_key))
        previous_penetration = _pct(previous_users, previous_penetration_denominators.get(row_key))
        avg_visit = _ratio(engaged, visits)
        previous_avg_visit = _ratio(previous_engaged, previous_visits)
        interaction = _pct(row.get('visits_with_click_count'), visits)
        previous_interaction = _pct(previous_row.get('visits_with_click_count'), previous_visits)
        clicks_per_visit = _ratio(row.get('click_count'), visits)
        previous_clicks_per_visit = _ratio(previous_row.get('click_count'), previous_visits)

        values = {
            'companies': companies,
            'adoption': adoption,
            'users': users,
            'penetration': penetration,
            'visits': visits,
            'engaged': engaged,
            'avg_visit': avg_visit,
            'interaction': interaction,
            'clicks_per_visit': clicks_per_visit,
        }
        for metric_name, value in values.items():
            max_values[metric_name] = max(max_values[metric_name], value)

        prepared.append({
            'row_key': row_key,
            'product_area_id': row.get('product_area_id'),
            'product_area_key': product_area_key,
            'product_area_name': product_area_name,
            'page_rule_id': row.get('page_rule_id'),
            'page_rule_ids': row.get('page_rule_ids') or _page_rule_aliases(row),
            'page_name': page_name,
            'page_group': product_area_name,
            'page_count': _to_int(row.get('page_count') or 1),
            'comparison_available': comparison_available,
            'comparisonAvailable': comparison_available,
            'companies_count': companies,
            'adoption_pct': adoption,
            'users_count': users,
            'penetration_pct': penetration,
            'visits_count': visits,
            'engaged_seconds': engaged,
            'engaged_label': _format_duration(engaged),
            'avg_visit_seconds': avg_visit,
            'avg_visit_label': _format_duration(avg_visit),
            'interaction_pct': interaction,
            'clicks_per_visit': clicks_per_visit,
            'top_company_id': row.get('top_company_id'),
            'top_company_name': row.get('top_company_name') or '',
            'deltas': {
                'companies': _delta_pct(companies, previous_companies),
                'adoption': _delta_pp(adoption, previous_adoption),
                'users': _delta_pct(users, previous_users),
                'penetration': _delta_pp(penetration, previous_penetration),
                'visits': _delta_pct(visits, previous_visits),
                'engaged': _delta_pct(engaged, previous_engaged),
                'avg_visit': _delta_pct(avg_visit, previous_avg_visit),
                'interaction': _delta_pp(interaction, previous_interaction),
                'clicks_per_visit': _delta_pct(clicks_per_visit, previous_clicks_per_visit),
            },
            'relative_change_series': {
                metric_name: _relative_change_series(
                    row_key,
                    start_date,
                    end_date,
                    previous_start,
                    daily_current,
                    daily_previous,
                    metric_name,
                )
                for metric_name in metric_names
            },
        })

    for row in prepared:
        row['bars'] = {
            metric: _pct(row_value, max_values[metric])
            for metric, row_value in {
                'companies': row['companies_count'],
                'adoption': row['adoption_pct'],
                'users': row['users_count'],
                'penetration': row['penetration_pct'],
                'visits': row['visits_count'],
                'engaged': row['engaged_seconds'],
                'avg_visit': row['avg_visit_seconds'],
                'interaction': row['interaction_pct'],
                'clicks_per_visit': row['clicks_per_visit'],
            }.items()
        }
        _ensure_change_row_contract(row)

    prepared.sort(key=lambda item: (-item['visits_count'], item['page_name']))
    return prepared, current_counts, previous_counts


def _daily_adopted_pages_trend(rows):
    dates = []
    adopted_by_date = defaultdict(int)
    for row in rows:
        for point in row['relative_change_series'].get('companies', []):
            point_date = point.get('date')
            if not point_date:
                continue
            if point_date not in dates:
                dates.append(point_date)
            if _to_int(point.get('current')) > 0:
                adopted_by_date[point_date] += 1
    return [adopted_by_date[point_date] for point_date in dates]


def _daily_trend_dates(rows, metric):
    dates = []
    for row in rows:
        for point in row['relative_change_series'].get(metric, []):
            point_date = point.get('date')
            if point_date and point_date not in dates:
                dates.append(point_date)
    return dates


def _daily_median_adoption_trend(rows):
    dates = []
    adoption_by_date = defaultdict(list)
    for row in rows:
        for point in row['relative_change_series'].get('adoption', []):
            point_date = point.get('date')
            if not point_date:
                continue
            if point_date not in dates:
                dates.append(point_date)
            current_value = _to_float(point.get('current'))
            if current_value > 0:
                adoption_by_date[point_date].append(current_value)
    return [round(_median(adoption_by_date[point_date]), 1) for point_date in dates]


def _build_kpis(rows, previous_rows_by_key, current_active_companies, previous_active_companies, *, comparison_available=True):
    adopted_pages = sum(1 for row in rows if row['companies_count'] > 0)
    previous_adopted_pages = sum(1 for row in previous_rows_by_key.values() if _to_int(row.get('companies_count')) > 0)
    median_adoption = _median([row['adoption_pct'] for row in rows if row['visits_count'] > 0])
    previous_median_adoption = _median([
        _bounded_pct(row.get('companies_count'), previous_active_companies)
        for row in previous_rows_by_key.values()
        if _to_int(row.get('visits_count')) > 0
    ])
    most_used = max(rows, key=lambda row: row['engaged_seconds'], default=None)

    fastest = None
    fastest_growth = -math.inf
    fastest_is_new = False
    strongest_new = None
    for row in rows:
        previous_row = previous_rows_by_key.get(row.get('row_key') or row.get('product_area_key'), {})
        previous_companies = _to_int(previous_row.get('companies_count'))
        current_companies = row['companies_count']
        if previous_companies < 3 and current_companies < 5:
            continue
        if previous_companies == 0 and current_companies > 0:
            if strongest_new is None or current_companies > strongest_new['companies_count']:
                strongest_new = row
            continue
        growth = _delta_pct(current_companies, previous_companies)['value']
        if growth is not None and growth > fastest_growth:
            fastest = row
            fastest_growth = growth

    if fastest is None:
        fastest = strongest_new or (rows[0] if rows else None)
        fastest_growth = None if strongest_new else 0
        fastest_is_new = strongest_new is not None

    adopted_delta = adopted_pages - previous_adopted_pages
    median_delta = round(_to_float(median_adoption) - _to_float(previous_median_adoption), 1)
    comparison_delta_label = None if comparison_available else 'n/a'

    return [
        {
            'label': 'Adopted pages',
            'value': str(adopted_pages),
            'delta': comparison_delta_label or f'{_format_signed(adopted_delta, "")} vs previous',
            'delta_value': adopted_delta if comparison_available else 0,
            'trend_values': _daily_adopted_pages_trend(rows),
            'trend_labels': _daily_trend_dates(rows, 'companies'),
            'trend_format': 'number',
        },
        {
            'label': 'Median adoption',
            'value': f'{round(median_adoption)}%',
            'delta': comparison_delta_label or _format_signed(round(median_delta), ' pp'),
            'delta_value': round(median_delta) if comparison_available else 0,
            'trend_values': _daily_median_adoption_trend(rows),
            'trend_labels': _daily_trend_dates(rows, 'adoption'),
            'trend_format': 'percent',
        },
        {
            'label': 'Most used page',
            'value': most_used['page_name'] if most_used else 'No data',
            'delta': f"{_format_duration_kpi(most_used['engaged_seconds'])} engaged" if most_used else '',
            'delta_value': 0,
            'product_area_key': most_used['product_area_key'] if most_used else '',
            'page_rule_id': most_used.get('page_rule_id') if most_used else None,
            'trend_values': [point['current'] for point in most_used['relative_change_series'].get('engaged', [])] if most_used else [],
            'trend_labels': [point['date'] for point in most_used['relative_change_series'].get('engaged', [])] if most_used else [],
            'trend_format': 'duration',
        },
        {
            'label': 'Fastest-growing',
            'value': fastest['page_name'] if fastest else 'No data',
            'delta': comparison_delta_label or ('New companies' if fastest_is_new else (_format_signed(round(fastest_growth or 0), '%') + ' companies' if fastest else '')),
            'delta_value': 0 if not comparison_available else (1 if fastest_is_new else (round(fastest_growth or 0) if fastest else 0)),
            'product_area_key': fastest['product_area_key'] if fastest else '',
            'page_rule_id': fastest.get('page_rule_id') if fastest else None,
            'trend_values': [point['current'] for point in fastest['relative_change_series'].get('companies', [])] if fastest else [],
            'trend_labels': [point['date'] for point in fastest['relative_change_series'].get('companies', [])] if fastest else [],
            'trend_format': 'number',
        },
    ]


def _build_series(rows, metric):
    source_metric = 'visits' if metric == 'visits_count' else 'engaged'
    grouped_rows = {}
    for row in rows or []:
        key = _page_display_key(row)
        current_total = _to_float(row.get(metric))
        group = grouped_rows.setdefault(
            key,
            {
                'page_rule_id': row.get('page_rule_id') or _page_rule_id(row),
                'page_rule_ids': [],
                'page_name': _page_display_name(row),
                'page_group': _page_display_group(row),
                'total': 0,
                'points': defaultdict(float),
                'point_dates': [],
                '_lead_total': -math.inf,
            },
        )

        page_rule_id = row.get('page_rule_id') or _page_rule_id(row)
        aliases = _page_rule_aliases(row) or [page_rule_id]
        for alias in aliases:
            if all(str(existing) != str(alias) for existing in group['page_rule_ids']):
                group['page_rule_ids'].append(alias)

        group['total'] += current_total
        if current_total > group['_lead_total']:
            group['_lead_total'] = current_total
            group['page_rule_id'] = page_rule_id
            group['page_group'] = _page_display_group(row)

        for point in row.get('relative_change_series', {}).get(source_metric, []):
            point_date = point.get('date')
            if not point_date:
                continue
            if point_date not in group['points']:
                group['point_dates'].append(point_date)
            group['points'][point_date] += _to_float(point.get('current'))

    top_rows = sorted(grouped_rows.values(), key=lambda row: _to_float(row.get('total')), reverse=True)[:10]
    labels = []
    for row in top_rows:
        for point_date in row.get('point_dates', []):
            if point_date and point_date not in labels:
                labels.append(point_date)

    series = []
    for row in top_rows:
        series.append({
            'page_rule_id': row.get('page_rule_id'),
            'page_rule_ids': row.get('page_rule_ids') or [],
            'page_name': row.get('page_name'),
            'page_group': row.get('page_group'),
            'total': _to_int(round(_to_float(row.get('total')))),
            'values': [_to_float(row.get('points', {}).get(label)) for label in labels],
        })
    return {'granularity': 'day', 'labels': labels, 'series': series}


def _build_treemap(rows, active_companies_total=None):
    groups = {}
    total = 0
    active_companies_total = _to_int(active_companies_total)
    for row in rows:
        engaged_seconds = _to_int(row.get('engaged_seconds'))
        if engaged_seconds <= 0:
            continue

        page_group = row.get('page_group') or row.get('product_area_name') or 'Unassigned'
        companies_count = _to_int(row.get('companies_count'))
        area_companies_count = _to_int(row.get('area_companies_count'))
        child_adoption_pct = (
            _to_float(row.get('adoption_pct'))
            if row.get('adoption_pct') is not None
            else _bounded_pct(companies_count, active_companies_total)
        )
        child_engaged_change_pct = (
            _to_float(row.get('engaged_change_pct'))
            if row.get('engaged_change_pct') is not None
            else _percent_change_value(engaged_seconds, row.get('previous_engaged_seconds'))
        )
        group = groups.setdefault(
            page_group,
            {
                'name': page_group,
                'page_group': page_group,
                'is_group': True,
                'value': 0,
                'engaged_seconds': 0,
                'visits_count': 0,
                'companies_count': 0,
                'adoption_pct': 0,
                'engaged_change_pct': 0,
                'children': [],
            },
        )
        child = {
            'name': row.get('page_name') or row.get('product_area_name') or page_group,
            'page_rule_id': row.get('page_rule_id') or _page_rule_id(row),
            'page_group': page_group,
            'value': engaged_seconds,
            'engaged_seconds': engaged_seconds,
            'engaged_label': row.get('engaged_label') or _format_duration(engaged_seconds),
            'visits_count': _to_int(row.get('visits_count')),
            'companies_count': companies_count,
            'adoption_pct': child_adoption_pct,
            'engaged_change_pct': child_engaged_change_pct,
        }
        group['children'].append(child)
        group['value'] += engaged_seconds
        group['engaged_seconds'] += engaged_seconds
        group['visits_count'] += child['visits_count']
        group['companies_count'] = max(
            group['companies_count'],
            area_companies_count or child['companies_count'],
        )
        group['adoption_pct'] = max(
            group['adoption_pct'],
            _bounded_pct(area_companies_count, active_companies_total) if area_companies_count else child['adoption_pct'],
        )
        total += engaged_seconds

    for group in groups.values():
        group['page_count'] = len(group['children'])
        group['engaged_label'] = _format_duration(group['engaged_seconds'])
        group['engaged_change_pct'] = _weighted_percent_change(
            group['children'],
            'engaged_seconds',
            'engaged_change_pct',
        )

    return {
        'total_engaged_seconds': total,
        'nodes': sorted(groups.values(), key=lambda group: group['engaged_seconds'], reverse=True),
    }


def _build_sankey(project_id, timezone_name, start_date, end_date):
    links = queries.fetch_all(queries.SANKEY_SQL, [project_id, timezone_name, start_date, timezone_name, end_date])
    nodes = {}
    payload_links = []
    for link in links:
        source = link['from_page_name'] or link['from_page_key']
        target = link['to_page_name'] or link['to_page_key']
        nodes[source] = {
            'name': source,
            'page_key': link.get('from_page_key'),
            'product_area_key': link.get('from_product_area_key'),
            'product_area_name': link.get('from_product_area_name'),
        }
        nodes[target] = {
            'name': target,
            'page_key': link.get('to_page_key'),
            'product_area_key': link.get('to_product_area_key'),
            'product_area_name': link.get('to_product_area_name'),
        }
        payload_links.append({
            'source': source,
            'target': target,
            'source_page_key': link.get('from_page_key'),
            'target_page_key': link.get('to_page_key'),
            'source_product_area': link.get('from_product_area_name') or link.get('from_product_area_key'),
            'target_product_area': link.get('to_product_area_name') or link.get('to_product_area_key'),
            'value': _to_int(link['transition_count']),
            'sessions_count': _to_int(link['sessions_count']),
            'companies_count': _to_int(link['companies_count']),
        })
    return {'nodes': list(nodes.values()), 'links': payload_links}


def _build_top_actions(project_id, start_date, end_date, previous_start, previous_end):
    rows = queries.fetch_all(
        queries.TOP_ACTIONS_SQL,
        [
            project_id, start_date, end_date,
            project_id, previous_start, previous_end,
            project_id, start_date, end_date,
            project_id, previous_start, previous_end,
        ],
    )
    pages = {}
    for row in rows:
        page_key = row.get('page_key') or row.get('url_normalized')
        page = pages.setdefault(
            page_key,
            {
                'page_key': page_key,
                'url_normalized': row.get('url_normalized') or '',
                'page_rule_id': row.get('page_rule_id'),
                'page_group': row.get('page_group') or '',
                'page_label': row.get('page_label') or row.get('url_normalized') or page_key,
                'visits_count': _to_int(row['visits_count']),
                'engaged_seconds': _to_int(row['engaged_seconds']),
                'actions': [],
            },
        )
        if row.get('element_key'):
            visits_pct = _pct(row.get('visits_with_action_count'), page['visits_count'])
            previous_visits_pct = _pct(
                row.get('previous_visits_with_action_count'),
                row.get('previous_page_visits_count'),
            )
            clicks_delta = _delta_pct(row.get('clicks_count'), row.get('previous_clicks_count'))
            visits_pct_delta = _delta_pp(visits_pct, previous_visits_pct)
            page['actions'].append({
                'element_key': row['element_key'],
                'clicks_count': _to_int(row['clicks_count']),
                'users_count': _to_int(row['users_count_daily']),
                'companies_count': _to_int(row['companies_count_daily']),
                'visits_pct': visits_pct,
                'clicks_delta_pct': clicks_delta['value'],
                'clicks_delta_label': clicks_delta['label'],
                'clicks_delta_direction': clicks_delta['direction'],
                'visits_pct_delta_pp': visits_pct_delta['value'],
                'visits_pct_delta_label': visits_pct_delta['label'],
                'visits_pct_delta_direction': visits_pct_delta['direction'],
            })
    return list(pages.values())


def _build_top_actions_by_page_group(pages):
    groups = []
    for page in sorted(pages, key=lambda item: _to_int(item.get('visits_count')), reverse=True):
        actions = [
            {
                'element_key': action.get('element_key') or 'Unknown action',
                'clicks': _to_int(action.get('clicks_count')),
                'clicks_change_pct': _to_float(action.get('clicks_delta_pct')),
                'visits_pct': _to_float(action.get('visits_pct')),
                'visits_change_pp': _to_float(action.get('visits_pct_delta_pp')),
            }
            for action in sorted(
                page.get('actions') or [],
                key=lambda item: _to_int(item.get('clicks_count')),
                reverse=True,
            )
        ]
        if not actions:
            continue
        groups.append({
            'page_group': page.get('page_label') or page.get('url_normalized') or 'Unassigned',
            'page_rule_id': str(page.get('page_rule_id') or page.get('page_key') or page.get('url_normalized') or ''),
            'actions': actions,
        })
    return groups


def _build_top_clicked_elements(pages, limit=20):
    elements = {}
    for page in pages:
        for action in page.get('actions') or []:
            element_key = action.get('element_key') or 'Unknown action'
            item = elements.setdefault(
                element_key,
                {
                    'element_key': element_key,
                    'clicks': 0,
                    'clicks_count': 0,
                    'pages_count': 0,
                },
            )
            item['clicks'] += _to_int(action.get('clicks_count'))
            item['clicks_count'] = item['clicks']
            item['pages_count'] += 1
    return sorted(elements.values(), key=lambda item: item['clicks'], reverse=True)[:limit]


def _build_scatter(project_id, start_date, end_date):
    rows = queries.fetch_all(
        queries.SCATTER_SQL,
        [
            project_id, start_date, end_date,
            project_id, start_date, end_date,
            project_id, start_date, end_date,
        ],
    )
    groups = {}
    for row in rows:
        active_users = round(_to_float(row['active_users']), 2)
        total_engaged = _to_int(row['total_engaged_seconds'])
        group = groups.setdefault(
            row['product_area_key'],
            {
                'product_area_key': row['product_area_key'],
                'product_area_name': row['product_area_name'],
                'points': [],
            },
        )
        group['points'].append({
            'company_id': row['company_id'],
            'company_name': row['company_name'],
            'active_users': active_users,
            'avg_engaged_seconds_per_user': _ratio(total_engaged, active_users),
            'total_engaged_seconds': total_engaged,
            'visits_count': _to_int(row['visits_count']),
            'clicks_count': _to_int(row['clicks_count']),
        })
    return list(groups.values())


def _build_company_engagement_by_page_group(groups):
    return [
        {
            'page_group': group.get('product_area_name') or group.get('product_area_key') or 'Unassigned',
            'points': [
                {
                    'company_id': point.get('company_id'),
                    'company_name': point.get('company_name') or str(point.get('company_id') or 'Unknown company'),
                    'active_users': round(_to_float(point.get('active_users')), 2),
                    'avg_engaged_seconds_per_user': _to_float(point.get('avg_engaged_seconds_per_user')),
                    'avg_engaged_label': _format_duration(point.get('avg_engaged_seconds_per_user')),
                    'total_engaged_seconds': _to_int(point.get('total_engaged_seconds')),
                    'total_engaged_label': _format_duration(point.get('total_engaged_seconds')),
                    'visits': _to_int(point.get('visits_count') or point.get('visits')),
                }
                for point in group.get('points') or []
            ],
        }
        for group in groups
    ]


def _empty_payload(project, range_key, start_date, end_date, previous_start, previous_end, generated_at, source_max_event_ts):
    return {
        'schema_version': OVERVIEW_PAYLOAD_SCHEMA_VERSION,
        'project': {'id': project['id'], 'name': project['name']},
        'period': {
            'range_key': range_key,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'previous_start_date': previous_start.isoformat(),
            'previous_end_date': previous_end.isoformat(),
        },
        'freshness': {
            'generated_at': generated_at.isoformat(),
            'source_max_event_ts': source_max_event_ts.isoformat() if source_max_event_ts else None,
            'is_stale': False,
        },
        'kpis': [],
        'rows': [],
        'change_aware_rows': [],
        'page_metrics_rows': [],
        'product_area_summary': [],
        'top_pages_by_visits_over_time': {'granularity': 'day', 'labels': [], 'series': []},
        'top_pages_by_engaged_time_over_time': {'granularity': 'day', 'labels': [], 'series': []},
        'engaged_time_treemap': {'total_engaged_seconds': 0, 'nodes': []},
        'sankey': {'nodes': [], 'links': []},
        'top_actions_by_page': [],
        'top_actions_by_page_group': [],
        'company_engagement_by_product_area': [],
        'company_engagement_by_page_group': [],
        'top_clicked_elements': [],
    }


def _empty_time_series():
    return {'granularity': 'day', 'labels': [], 'series': []}


def _product_area_filter_identity(item):
    if not isinstance(item, dict):
        return '', ''

    name = (
        item.get('product_area_name')
        or item.get('productAreaName')
        or item.get('product_area')
        or item.get('page_group')
        or item.get('name')
        or ''
    )
    key = (
        item.get('product_area_key')
        or item.get('productAreaKey')
        or item.get('key')
        or ''
    )
    key = str(key or '').strip()
    name = str(name or '').strip()
    if not key:
        key = slugify(name) or 'unassigned'
    if not name:
        name = key or 'Unassigned'
    return key, name


def _normalized_filter_token(value):
    return str(value or '').strip().lower()


def _add_product_area_filter_option(options_by_key, item):
    key, name = _product_area_filter_identity(item)
    if not key:
        return

    existing = options_by_key.get(key)
    if existing:
        if existing.get('name') == existing.get('key') and name:
            existing['name'] = name
        return

    options_by_key[key] = {'key': key, 'name': name or key}


def overview_product_area_filter_options(payload):
    options_by_key = {}
    payload = payload if isinstance(payload, dict) else {}

    for section_name in (
        'product_area_summary',
        'page_metrics_rows',
        'change_aware_rows',
        'rows',
        'company_engagement_by_product_area',
    ):
        rows = payload.get(section_name)
        if not isinstance(rows, list):
            continue
        for row in rows:
            _add_product_area_filter_option(options_by_key, row)

    treemap = payload.get('engaged_time_treemap')
    if isinstance(treemap, dict):
        for node in treemap.get('nodes') or []:
            _add_product_area_filter_option(options_by_key, node)

    sankey = payload.get('sankey')
    if isinstance(sankey, dict):
        for node in sankey.get('nodes') or []:
            _add_product_area_filter_option(options_by_key, node)

    return list(options_by_key.values())


def resolve_product_area_filter_keys(payload, requested_values):
    options = overview_product_area_filter_options(payload)
    option_by_token = {}
    for option in options:
        key = option.get('key')
        name = option.get('name')
        for value in (key, name):
            token = _normalized_filter_token(value)
            if token:
                option_by_token[token] = key

    selected_keys = []
    seen = set()
    for value in requested_values or []:
        key = option_by_token.get(_normalized_filter_token(value))
        if key and key not in seen:
            selected_keys.append(key)
            seen.add(key)
    return selected_keys


def _product_area_filter_selection(payload, selected_keys):
    options = overview_product_area_filter_options(payload)
    requested = {_normalized_filter_token(key) for key in (selected_keys or []) if str(key or '').strip()}
    selected_options = [
        option
        for option in options
        if _normalized_filter_token(option.get('key')) in requested
    ]
    return {
        'keys': {_normalized_filter_token(option.get('key')) for option in selected_options},
        'names': {_normalized_filter_token(option.get('name')) for option in selected_options},
        'options': selected_options,
    }


def _matches_product_area_filter(item, selection):
    if not isinstance(item, dict):
        return False

    key, name = _product_area_filter_identity(item)
    values = [
        key,
        name,
        item.get('product_area_key'),
        item.get('productAreaKey'),
        item.get('product_area_name'),
        item.get('productAreaName'),
        item.get('product_area'),
        item.get('page_group'),
    ]
    tokens = {_normalized_filter_token(value) for value in values if str(value or '').strip()}
    return bool(tokens & selection['keys'] or tokens & selection['names'])


def _filter_time_series_by_product_area(time_series, selection):
    if not isinstance(time_series, dict):
        return _empty_time_series()

    filtered = copy.deepcopy(time_series)
    series = filtered.get('series')
    filtered['series'] = [
        row
        for row in series
        if _matches_product_area_filter(row, selection)
    ] if isinstance(series, list) else []
    filtered.setdefault('labels', [])
    filtered.setdefault('granularity', 'day')
    return filtered


def _filter_treemap_by_product_area(treemap, selection):
    if not isinstance(treemap, dict):
        return {'total_engaged_seconds': 0, 'nodes': []}

    nodes = []
    total = 0
    for node in treemap.get('nodes') or []:
        if not isinstance(node, dict):
            continue

        node_matches = _matches_product_area_filter(node, selection)
        filtered_node = copy.deepcopy(node)
        children = filtered_node.get('children')
        if isinstance(children, list) and not node_matches:
            filtered_node['children'] = [
                child
                for child in children
                if _matches_product_area_filter(child, selection)
            ]

        if not node_matches and not filtered_node.get('children'):
            continue

        if isinstance(filtered_node.get('children'), list) and filtered_node['children']:
            engaged_seconds = sum(_to_int(child.get('engaged_seconds') or child.get('value')) for child in filtered_node['children'])
            filtered_node['engaged_seconds'] = engaged_seconds
            filtered_node['value'] = engaged_seconds
            filtered_node['page_count'] = len(filtered_node['children'])

        total += _to_int(filtered_node.get('engaged_seconds') or filtered_node.get('value'))
        nodes.append(filtered_node)

    return {
        **copy.deepcopy(treemap),
        'total_engaged_seconds': total,
        'nodes': nodes,
    }


def _link_endpoint_matches_product_area(link, prefix, selection):
    item = {
        'product_area_key': link.get(f'{prefix}_product_area_key') or link.get(f'{prefix}_product_area'),
        'product_area_name': link.get(f'{prefix}_product_area_name') or link.get(f'{prefix}_product_area'),
    }
    return _matches_product_area_filter(item, selection)


def _filter_sankey_by_product_area(sankey, selection):
    if not isinstance(sankey, dict):
        return {'nodes': [], 'links': []}

    links = []
    node_names = set()
    for link in sankey.get('links') or []:
        if not isinstance(link, dict):
            continue
        if not (
            _link_endpoint_matches_product_area(link, 'source', selection)
            and _link_endpoint_matches_product_area(link, 'target', selection)
        ):
            continue
        links.append(copy.deepcopy(link))
        node_names.add(link.get('source'))
        node_names.add(link.get('target'))

    nodes = [
        copy.deepcopy(node)
        for node in sankey.get('nodes') or []
        if isinstance(node, dict)
        and (
            _matches_product_area_filter(node, selection)
            or node.get('name') in node_names
        )
    ]
    return {'nodes': nodes, 'links': links}


def _rescale_change_row_bars(rows):
    prepared = [
        _ensure_change_row_contract(dict(row))
        for row in rows or []
        if isinstance(row, dict)
    ]
    metric_value_fields = {
        'companies': 'companies_count',
        'adoption': 'adoption_pct',
        'users': 'users_count',
        'penetration': 'penetration_pct',
        'visits': 'visits_count',
        'engaged': 'engaged_seconds',
        'avg_visit': 'avg_visit_seconds',
        'interaction': 'interaction_pct',
        'clicks_per_visit': 'clicks_per_visit',
    }
    max_values = {
        metric: max((_to_float(row.get(field_name)) for row in prepared), default=0)
        for metric, field_name in metric_value_fields.items()
    }

    for row in prepared:
        bars = dict(row.get('bars') or {})
        for metric, field_name in metric_value_fields.items():
            bar_value = _pct(row.get(field_name), max_values.get(metric))
            bars[metric] = bar_value
            row[f'{metric}_bar_value'] = bar_value
        row['bars'] = bars

    return [_strip_relative_change_series(row) for row in prepared]


def _filter_kpi_series_value(time_series, row):
    if not isinstance(time_series, dict):
        return []

    page_rule_id = str(row.get('page_rule_id') or '')
    page_name = str(row.get('page_name') or '')
    for series in time_series.get('series') or []:
        rule_ids = [str(value) for value in series.get('page_rule_ids') or []]
        if (
            page_rule_id
            and (
                str(series.get('page_rule_id') or '') == page_rule_id
                or page_rule_id in rule_ids
            )
        ):
            return series.get('values') or []
        if page_name and str(series.get('page_name') or '') == page_name:
            return series.get('values') or []
    return []


def _compact_trend_values(row, metric):
    if not isinstance(row, dict):
        return []

    trends = row.get('trends')
    if isinstance(trends, dict) and isinstance(trends.get(metric), list):
        return [_to_float(value) for value in trends.get(metric) or []]

    if metric == 'companies' and isinstance(row.get('trend_values'), list):
        return [_to_float(value) for value in row.get('trend_values') or []]

    return _trend_values(row, metric)


def _adopted_pages_trend_from_rows(rows):
    trends = [_compact_trend_values(row, 'companies') for row in rows]
    trend_lengths = [len(trend) for trend in trends]
    if not trend_lengths:
        return []

    length = max(trend_lengths)
    values = []
    for index in range(length):
        values.append(sum(
            1
            for trend in trends
            if _to_float(trend[index] if index < len(trend) else 0) > 0
        ))
    return values


def _median_compact_trend_from_rows(rows, metric):
    trends = [_compact_trend_values(row, metric) for row in rows]
    trend_lengths = [len(trend) for trend in trends]
    if not trend_lengths:
        return []

    values = []
    for index in range(max(trend_lengths)):
        point_values = []
        for trend in trends:
            if index >= len(trend):
                continue
            current_value = _to_float(trend[index])
            if current_value > 0:
                point_values.append(current_value)
        values.append(round(_median(point_values), 1))
    return values


def _filtered_kpi_trend_values(row, metric, fallback_time_series=None):
    values = _compact_trend_values(row, metric)
    if values:
        return values
    if fallback_time_series:
        return _filter_kpi_series_value(fallback_time_series, row)
    return []


def _build_filtered_kpis(payload, rows):
    if not rows:
        return []

    comparison_available = any(
        row.get('comparison_available') is not False and row.get('comparisonAvailable') is not False
        for row in rows
    )
    adopted_pages = sum(1 for row in rows if _to_int(row.get('companies_count')) > 0)
    previous_adopted_pages = sum(
        1
        for row in rows
        if _previous_metric_value(row.get('companies_count'), {'value': row.get('companies_change_pct'), 'label': '%'}) > 0
    )
    median_adoption = _median([_to_float(row.get('adoption_pct')) for row in rows if _to_int(row.get('visits_count')) > 0])
    previous_median_adoption = _median([
        max(0, _to_float(row.get('adoption_pct')) - _to_float(row.get('adoption_change_pp')))
        for row in rows
        if _to_int(row.get('visits_count')) > 0
    ])
    most_used = max(rows, key=lambda row: _to_int(row.get('engaged_seconds')), default=None)
    fastest = max(rows, key=lambda row: _to_float(row.get('companies_change_pct')), default=None)
    trend_labels = (payload.get('top_pages_by_visits_over_time') or {}).get('labels') or []
    comparison_delta_label = None if comparison_available else 'n/a'

    adopted_delta = adopted_pages - previous_adopted_pages
    median_delta = round(_to_float(median_adoption) - _to_float(previous_median_adoption), 1)
    engaged_time_series = payload.get('top_pages_by_engaged_time_over_time') or {}
    product_area_summary = payload.get('product_area_summary') or []
    median_adoption_trend = (
        _median_compact_trend_from_rows(rows, 'adoption')
        or _median_compact_trend_from_rows(product_area_summary, 'adoption')
    )

    return [
        {
            'label': 'Adopted pages',
            'value': str(adopted_pages),
            'delta': comparison_delta_label or f'{_format_signed(adopted_delta, "")} vs previous',
            'delta_value': adopted_delta if comparison_available else 0,
            'trend_values': _adopted_pages_trend_from_rows(rows),
            'trend_labels': trend_labels,
            'trend_format': 'number',
        },
        {
            'label': 'Median adoption',
            'value': f'{round(median_adoption)}%',
            'delta': comparison_delta_label or _format_signed(round(median_delta), ' pp'),
            'delta_value': round(median_delta) if comparison_available else 0,
            'trend_values': median_adoption_trend,
            'trend_labels': trend_labels,
            'trend_format': 'percent',
        },
        {
            'label': 'Most used page',
            'value': most_used['page_name'] if most_used else 'No data',
            'delta': f"{_format_duration_kpi(most_used['engaged_seconds'])} engaged" if most_used else '',
            'delta_value': 0,
            'product_area_key': most_used.get('product_area_key') if most_used else '',
            'page_rule_id': most_used.get('page_rule_id') if most_used else None,
            'trend_values': _filtered_kpi_trend_values(most_used, 'engaged', engaged_time_series) if most_used else [],
            'trend_labels': (engaged_time_series or {}).get('labels') or [],
            'trend_format': 'duration',
        },
        {
            'label': 'Fastest-growing',
            'value': fastest['page_name'] if fastest else 'No data',
            'delta': comparison_delta_label or (_format_signed(round(_to_float(fastest.get('companies_change_pct'))), '%') + ' companies' if fastest else ''),
            'delta_value': round(_to_float(fastest.get('companies_change_pct'))) if comparison_available and fastest else 0,
            'product_area_key': fastest.get('product_area_key') if fastest else '',
            'page_rule_id': fastest.get('page_rule_id') if fastest else None,
            'trend_values': _filtered_kpi_trend_values(fastest, 'companies') if fastest else [],
            'trend_labels': trend_labels,
            'trend_format': 'number',
        },
    ]


def filter_overview_payload_by_product_areas(payload, selected_keys):
    payload = normalize_overview_payload(copy.deepcopy(payload or {}))
    selection = _product_area_filter_selection(payload, selected_keys)
    if not selection['options']:
        return payload

    rows = _rescale_change_row_bars([
        row
        for row in payload.get('rows') or []
        if _matches_product_area_filter(row, selection)
    ])
    change_rows = _rescale_change_row_bars([
        row
        for row in payload.get('change_aware_rows') or []
        if _matches_product_area_filter(row, selection)
    ])
    page_metrics_rows = _rescale_change_row_bars([
        row
        for row in payload.get('page_metrics_rows') or []
        if _matches_product_area_filter(row, selection)
    ])
    product_area_summary = _rescale_change_row_bars([
        row
        for row in payload.get('product_area_summary') or []
        if _matches_product_area_filter(row, selection)
    ])
    top_actions = [
        copy.deepcopy(row)
        for row in payload.get('top_actions_by_page') or []
        if _matches_product_area_filter(row, selection)
    ]
    company_engagement = [
        copy.deepcopy(row)
        for row in payload.get('company_engagement_by_product_area') or []
        if _matches_product_area_filter(row, selection)
    ]

    payload['rows'] = rows
    payload['change_aware_rows'] = change_rows
    payload['page_metrics_rows'] = page_metrics_rows
    payload['product_area_summary'] = product_area_summary
    payload['top_pages_by_visits_over_time'] = _filter_time_series_by_product_area(
        payload.get('top_pages_by_visits_over_time'),
        selection,
    )
    payload['top_pages_by_engaged_time_over_time'] = _filter_time_series_by_product_area(
        payload.get('top_pages_by_engaged_time_over_time'),
        selection,
    )
    payload['engaged_time_treemap'] = _filter_treemap_by_product_area(
        payload.get('engaged_time_treemap'),
        selection,
    )
    payload['sankey'] = _filter_sankey_by_product_area(payload.get('sankey'), selection)
    payload['top_actions_by_page'] = top_actions
    payload['top_actions_by_page_group'] = _build_top_actions_by_page_group(top_actions)
    payload['company_engagement_by_product_area'] = company_engagement
    payload['company_engagement_by_page_group'] = _build_company_engagement_by_page_group(company_engagement)
    payload['top_clicked_elements'] = _build_top_clicked_elements(top_actions)
    payload['kpis'] = _build_filtered_kpis(payload, page_metrics_rows or change_rows)
    payload['product_area_filter'] = {
        'selected_keys': [option['key'] for option in selection['options']],
        'selected_names': [option['name'] for option in selection['options']],
    }
    return payload


def _has_time_series_contract(payload):
    if not isinstance(payload, dict):
        return False
    series = payload.get('series')
    return isinstance(payload.get('labels'), list) and isinstance(series, list) and all(
        isinstance(row, dict) and isinstance(row.get('values'), list)
        for row in series
    )


def normalize_overview_payload(payload):
    payload = payload or {}
    payload.setdefault('schema_version', 1)
    project = payload.setdefault('project', {})

    change_rows = payload.get('change_aware_rows')
    change_rows = change_rows if isinstance(change_rows, list) else []
    full_change_rows = [
        _ensure_change_row_contract(dict(row))
        for row in change_rows
        if isinstance(row, dict)
    ]
    payload['change_aware_rows'] = [_strip_for_overview_row(row) for row in full_change_rows]

    page_metrics_rows = payload.get('page_metrics_rows')
    page_metrics_rows = page_metrics_rows if isinstance(page_metrics_rows, list) else []
    full_page_metrics_rows = [
        _ensure_change_row_contract(dict(row))
        for row in page_metrics_rows
        if isinstance(row, dict)
    ]
    if not full_page_metrics_rows and full_change_rows:
        full_page_metrics_rows = _collapse_page_metric_representatives(full_change_rows)
    payload['page_metrics_rows'] = [
        _strip_for_overview_row(row)
        for row in full_page_metrics_rows
    ]

    rows = payload.get('rows')
    rows = rows if isinstance(rows, list) and rows else full_change_rows
    full_rows = [
        _ensure_change_row_contract(dict(row))
        for row in rows
        if isinstance(row, dict)
    ]
    payload['rows'] = [_strip_for_overview_row(row) for row in full_rows]

    product_area_summary = payload.get('product_area_summary')
    product_area_summary = product_area_summary if isinstance(product_area_summary, list) else []
    payload['product_area_summary'] = [
        _strip_for_product_area_summary(_ensure_change_row_contract(dict(row)))
        for row in product_area_summary
        if isinstance(row, dict)
    ]

    if full_rows:
        project.setdefault('active_companies_total', max(_to_int(row.get('companies_count')) for row in full_rows))
        project.setdefault('active_users_total', max(_to_int(row.get('users_count')) for row in full_rows))

    overview_page_rows = full_page_metrics_rows or full_rows
    if not _has_time_series_contract(payload.get('top_pages_by_visits_over_time')):
        payload['top_pages_by_visits_over_time'] = _build_series(overview_page_rows, 'visits_count') if overview_page_rows else _empty_time_series()
    if not _has_time_series_contract(payload.get('top_pages_by_engaged_time_over_time')):
        payload['top_pages_by_engaged_time_over_time'] = _build_series(overview_page_rows, 'engaged_seconds') if overview_page_rows else _empty_time_series()
    treemap = payload.get('engaged_time_treemap')
    if overview_page_rows and not (isinstance(treemap, dict) and treemap.get('nodes')):
        payload['engaged_time_treemap'] = _build_treemap(overview_page_rows)
    else:
        payload.setdefault('engaged_time_treemap', {'total_engaged_seconds': 0, 'nodes': []})

    payload.setdefault('sankey', {'nodes': [], 'links': []})

    top_actions = payload.get('top_actions_by_page')
    top_actions = top_actions if isinstance(top_actions, list) else []
    payload['top_actions_by_page'] = top_actions
    if not payload.get('top_actions_by_page_group'):
        payload['top_actions_by_page_group'] = _build_top_actions_by_page_group(top_actions)

    company_groups = payload.get('company_engagement_by_product_area')
    company_groups = company_groups if isinstance(company_groups, list) else []
    payload['company_engagement_by_product_area'] = company_groups
    if not payload.get('company_engagement_by_page_group'):
        payload['company_engagement_by_page_group'] = _build_company_engagement_by_page_group(company_groups)

    if not payload.get('top_clicked_elements'):
        payload['top_clicked_elements'] = _build_top_clicked_elements(top_actions)

    return payload


def _period_days(start_date, end_date):
    return max((end_date - start_date).days + 1, 1)


def _detail_period_payload(range_key, start_date, end_date, previous_start, previous_end):
    return {
        'range_key': range_key,
        'days': _period_days(start_date, end_date),
        'currentStart': start_date.isoformat(),
        'currentEnd': end_date.isoformat(),
        'previousStart': previous_start.isoformat(),
        'previousEnd': previous_end.isoformat(),
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'previous_start_date': previous_start.isoformat(),
        'previous_end_date': previous_end.isoformat(),
    }


def _detail_route(row):
    page_rule_id = row.get('page_rule_id') or row.get('row_key') or row.get('page_name') or 'page'
    return f'/pages/{page_rule_id}'


def _detail_format_value(value, value_type):
    if value_type == 'percent':
        return f'{round(_to_float(value))}%'
    if value_type == 'duration':
        return _format_duration(_to_float(value))
    if value_type == 'ratio':
        value = _to_float(value)
        return f'{value:.1f}'
    return f'{_to_int(round(_to_float(value))):,}'


def _previous_metric_value(current_value, delta):
    current = _to_float(current_value)
    if not isinstance(delta, dict):
        return 0

    delta_value = delta.get('value')
    if delta_value is None:
        return 0

    delta_value = _to_float(delta_value)
    label = str(delta.get('label') or '')
    if label.endswith(' pp') or delta.get('unit') == 'pp':
        return max(0, current - delta_value)

    divisor = 1 + delta_value / 100
    return max(0, current / divisor) if divisor > 0 else 0


def _detail_identifier_tokens(value):
    raw_value = str(value or '').strip().strip('/')
    if not raw_value:
        return set()

    tokens = {raw_value}
    slug_value = slugify(raw_value)
    if slug_value:
        tokens.add(slug_value)

    for separator in ('::', '/'):
        if separator in raw_value:
            tail_value = raw_value.rsplit(separator, 1)[-1].strip()
            if tail_value:
                tokens.add(tail_value)
                tail_slug = slugify(tail_value)
                if tail_slug:
                    tokens.add(tail_slug)

    return tokens


def _detail_row_tokens(row, *, include_group=True):
    values = [
        row.get('page_rule_id'),
        row.get('row_key'),
        row.get('page_name'),
    ]
    if include_group:
        values.extend([
            row.get('product_area_key'),
            row.get('product_area_name'),
            row.get('page_group'),
        ])
    tokens = set()
    for value in values:
        tokens.update(_detail_identifier_tokens(value))
    return tokens


def _detail_identifier_pk(value):
    for token in _detail_identifier_tokens(value):
        page_rule_pk = _coerce_int_or_none(token)
        if page_rule_pk is not None:
            return page_rule_pk
    return None


def _find_detail_row(rows, page_rule_id):
    requested_tokens = _detail_identifier_tokens(page_rule_id)
    if not requested_tokens:
        return None

    direct_match = next((row for row in rows if requested_tokens & _detail_row_tokens(row, include_group=False)), None)
    if direct_match:
        return direct_match

    return next((row for row in rows if requested_tokens & _detail_row_tokens(row)), None)


def _find_detail_rule(project_id, page_rule_id):
    page_rule_pk = _detail_identifier_pk(page_rule_id)
    if page_rule_pk is not None:
        return (
            ProjectPageRule.objects
            .filter(project_id=project_id, pk=page_rule_pk)
            .values('id', 'page_name', 'product_area')
            .first()
        )

    requested_tokens = _detail_identifier_tokens(page_rule_id)
    if not requested_tokens:
        return None

    for rule in (
        ProjectPageRule.objects
        .filter(project_id=project_id)
        .values('id', 'page_name', 'product_area')
        .order_by('-priority', '-updated_at', 'id')
    ):
        rule_tokens = _detail_identifier_tokens(rule.get('id'))
        rule_tokens.update(_detail_identifier_tokens(rule.get('page_name')))
        if requested_tokens & rule_tokens:
            return rule

    for rule in (
        ProjectPageRule.objects
        .filter(project_id=project_id)
        .values('id', 'page_name', 'product_area')
        .order_by('-priority', '-updated_at', 'id')
    ):
        rule_tokens = _detail_identifier_tokens(rule.get('id'))
        rule_tokens.update(_detail_identifier_tokens(rule.get('page_name')))
        rule_tokens.update(_detail_identifier_tokens(rule.get('product_area')))
        if requested_tokens & rule_tokens:
            return rule

    return None


def _detail_baseline_row(project_id, page_rule_id):
    rule = _find_detail_rule(project_id, page_rule_id)
    page_rule_pk = rule.get('id') if rule else _detail_identifier_pk(page_rule_id)
    latest_metric = None
    if page_rule_pk is not None:
        latest_metric = (
            PageDailyMetric.objects
            .filter(project_id=project_id, page_rule_id=page_rule_pk)
            .order_by('-date')
            .values('page_rule_id', 'product_area_id', 'product_area_key', 'product_area_name')
            .first()
        )

    if not latest_metric and not rule:
        return None

    product_area_name = (
        (latest_metric or {}).get('product_area_name')
        or (rule or {}).get('product_area')
        or 'Unassigned'
    )
    product_area_key = (
        (latest_metric or {}).get('product_area_key')
        or slugify(product_area_name)
        or 'unassigned'
    )

    return {
        'row_key': f'{product_area_key}::{page_rule_pk if page_rule_pk is not None else page_rule_id}',
        'product_area_id': (latest_metric or {}).get('product_area_id'),
        'product_area_key': product_area_key,
        'product_area_name': product_area_name,
        'page_rule_id': page_rule_pk if page_rule_pk is not None else page_rule_id,
        'page_name': (rule or {}).get('page_name') or product_area_name,
        'page_group': product_area_name,
        'page_count': 1,
    }


def _zero_detail_change_row(
    project_id,
    page_rule_id,
    start_date,
    end_date,
    previous_start,
    previous_end,
    current_counts,
    previous_counts,
):
    baseline = _detail_baseline_row(project_id, page_rule_id)
    if not baseline:
        return None

    row_key = _page_metric_key(baseline)
    previous_row = _summary_by_page(project_id, previous_start, previous_end).get(row_key, {})
    previous_penetration_denominators = _page_penetration_denominators(project_id, previous_start, previous_end)
    previous_visits = _to_int(previous_row.get('visits_count'))
    previous_engaged = _to_int(previous_row.get('engaged_seconds'))
    previous_companies = _to_int(previous_row.get('companies_count'))
    previous_users = _to_int(previous_row.get('users_count'))
    previous_adoption = _bounded_pct(previous_companies, previous_counts.get('active_companies_count'))
    previous_penetration = _pct(previous_users, previous_penetration_denominators.get(row_key))
    previous_avg_visit = _ratio(previous_engaged, previous_visits)
    previous_interaction = _pct(previous_row.get('visits_with_click_count'), previous_visits)
    previous_clicks_per_visit = _ratio(previous_row.get('click_count'), previous_visits)

    row = {
        **baseline,
        'companies_count': 0,
        'adoption_pct': _bounded_pct(0, current_counts.get('active_companies_count')),
        'users_count': 0,
        'penetration_pct': 0,
        'visits_count': 0,
        'engaged_seconds': 0,
        'engaged_label': _format_duration(0),
        'avg_visit_seconds': 0,
        'avg_visit_label': _format_duration(0),
        'interaction_pct': 0,
        'clicks_per_visit': 0,
        'top_company_id': previous_row.get('top_company_id'),
        'top_company_name': previous_row.get('top_company_name') or '',
        'deltas': {
            'companies': _delta_pct(0, previous_companies),
            'adoption': _delta_pp(0, previous_adoption),
            'users': _delta_pct(0, previous_users),
            'penetration': _delta_pp(0, previous_penetration),
            'visits': _delta_pct(0, previous_visits),
            'engaged': _delta_pct(0, previous_engaged),
            'avg_visit': _delta_pct(0, previous_avg_visit),
            'interaction': _delta_pp(0, previous_interaction),
            'clicks_per_visit': _delta_pct(0, previous_clicks_per_visit),
        },
        'relative_change_series': {},
    }
    row['bars'] = {
        'companies': 0,
        'adoption': 0,
        'users': 0,
        'penetration': 0,
        'visits': 0,
        'engaged': 0,
        'avg_visit': 0,
        'interaction': 0,
        'clicks_per_visit': 0,
    }
    _ensure_change_row_contract(row)
    return row


def _select_detail_peer_rows(rows, current_row, limit=10):
    peer_limit = max(0, int(limit or 10))
    current_id = str(current_row.get('page_rule_id') or '')
    current_area_key = current_row.get('product_area_key') or ''
    selected = []
    selected_ids = {current_id}

    def add_page(row):
        page_id = str(row.get('page_rule_id') or '')
        if not page_id or page_id in selected_ids or len(selected) >= peer_limit:
            return
        selected.append(row)
        selected_ids.add(page_id)

    same_area = [
        row for row in rows
        if (row.get('product_area_key') or '') == current_area_key
        and str(row.get('page_rule_id') or '') != current_id
    ]
    project_pages = [
        row for row in rows
        if str(row.get('page_rule_id') or '') != current_id
    ]

    for row in sorted(same_area, key=lambda item: (-_to_int(item.get('visits_count')), item.get('page_name') or '')):
        add_page(row)
    for row in sorted(project_pages, key=lambda item: (-_to_int(item.get('visits_count')), item.get('page_name') or '')):
        add_page(row)

    return selected


def _daily_detail_metric_value(row, metric_key):
    if not row:
        return None if metric_key in {'avg_visit', 'clicks_per_visit', 'interaction'} else 0

    visits = _to_int(row.get('visits_count'))
    if metric_key == 'companies':
        return _to_int(row.get('companies_count_daily'))
    if metric_key == 'users':
        return _to_int(row.get('users_count_daily'))
    if metric_key == 'visits':
        return visits
    if metric_key == 'engaged':
        return _to_int(row.get('engaged_seconds'))
    if metric_key == 'avg_visit':
        return None if visits <= 0 else _ratio(row.get('engaged_seconds'), visits)
    if metric_key == 'clicks_per_visit':
        return None if visits <= 0 else _ratio(row.get('click_count'), visits)
    if metric_key == 'interaction':
        return None if visits <= 0 else _pct(row.get('visits_with_click_count'), visits)
    if metric_key == 'adoption':
        denominator = _to_int(row.get('active_companies_count'))
        return _bounded_pct(row.get('companies_count_daily'), denominator)
    if metric_key == 'penetration':
        denominator = _to_int(row.get('active_users_count'))
        return _bounded_pct(row.get('users_count_daily'), denominator)
    return 0


def _daily_detail_series(row, metric_key, start_date, end_date, daily_rows):
    row_key = row.get('row_key') or _page_metric_key(row)
    return [
        {
            'date': current_date.isoformat(),
            'value': _daily_detail_metric_value(daily_rows.get((current_date, row_key)), metric_key),
        }
        for current_date in _date_range(start_date, end_date)
    ]


def _detail_benchmark_series(rows, metric_key, start_date, end_date, daily_rows):
    source_series = [
        _daily_detail_series(row, metric_key, start_date, end_date, daily_rows)
        for row in rows or []
    ]
    if not source_series:
        return []

    dates = list(_date_range(start_date, end_date))
    result = []
    for index, current_date in enumerate(dates):
        values = [
            series[index].get('value')
            for series in source_series
            if index < len(series) and series[index].get('value') is not None
        ]
        result.append({
            'date': current_date.isoformat(),
            'value': _median(values) if values else None,
        })

    return result


def _detail_metric_payload(row, peers, benchmark_rows, metric_config, start_date, end_date, daily_rows):
    metric_key = metric_config['key']
    value = row.get(metric_config['source'])
    delta = row.get('deltas', {}).get(metric_key, {})
    comparison_available = row.get('comparison_available', row.get('comparisonAvailable', True)) is not False
    previous_value = _previous_metric_value(value, delta) if comparison_available else None
    delta_value = delta.get('value') if isinstance(delta, dict) else 0
    delta_direction = delta.get('direction') if isinstance(delta, dict) else 'neutral'
    formatted_delta = delta.get('label') if isinstance(delta, dict) else '0%'

    if not comparison_available:
        delta_value = None
        delta_direction = 'neutral'
        formatted_delta = 'n/a'

    return {
        'key': metric_key,
        'label': metric_config['label'],
        'value': value,
        'previousValue': previous_value,
        'formattedValue': _detail_format_value(value, metric_config['value_type']),
        'deltaValue': delta_value,
        'deltaDirection': delta_direction,
        'deltaType': metric_config['delta_type'],
        'formattedDelta': formatted_delta,
        'comparisonAvailable': comparison_available,
        'comparison_available': comparison_available,
        'valueType': metric_config['value_type'],
        'dailySeries': _daily_detail_series(row, metric_key, start_date, end_date, daily_rows),
        'peerSeries': [
            {
                'pageId': peer.get('page_rule_id'),
                'pageName': peer.get('page_name') or peer.get('page_rule_id'),
                'productAreaName': peer.get('product_area_name') or peer.get('page_group'),
                'dailySeries': _daily_detail_series(peer, metric_key, start_date, end_date, daily_rows),
            }
            for peer in peers
        ],
        'benchmarkSeries': _detail_benchmark_series(benchmark_rows, metric_key, start_date, end_date, daily_rows),
        'benchmarkEligiblePeerCount': len(benchmark_rows or []),
    }


def _detail_related_page_payload(row, current_page_id):
    comparison_available = row.get('comparison_available', row.get('comparisonAvailable', True)) is not False

    return {
        'id': row.get('page_rule_id'),
        'pageId': row.get('page_rule_id'),
        'page_rule_id': row.get('page_rule_id'),
        'route': _detail_route(row),
        'pageName': row.get('page_name') or row.get('page_rule_id'),
        'productAreaName': row.get('product_area_name') or row.get('page_group'),
        'isCurrent': str(row.get('page_rule_id') or '') == str(current_page_id or ''),
        'comparisonAvailable': comparison_available,
        'comparison_available': comparison_available,
        'companies': _to_int(row.get('companies_count')),
        'companiesChange': _to_float(row.get('companies_change_pct')),
        'adoption': _to_float(row.get('adoption_pct')),
        'adoptionChange': _to_float(row.get('adoption_change_pp')),
        'users': _to_int(row.get('users_count')),
        'usersChange': _to_float(row.get('users_change_pct')),
        'visits': _to_int(row.get('visits_count')),
        'visitsChange': _to_float(row.get('visits_change_pct')),
        'engaged': _to_int(row.get('engaged_seconds')),
        'engagedChange': _to_float(row.get('engaged_change_pct')),
        'interaction': _to_float(row.get('interaction_pct')),
        'interactionChange': _to_float(row.get('interaction_change_pp')),
        'engagedLabel': row.get('engaged_label') or _format_duration(row.get('engaged_seconds')),
    }


def _previous_from_percent_change(current, change_pct):
    divisor = 1 + (_to_float(change_pct) / 100)
    return _to_float(current) / divisor if divisor > 0 else 0


def _dedupe_detail_related_pages(rows, current_page_id):
    groups = {}
    for row in rows or []:
        key = str(row.get('pageName') or row.get('route') or row.get('pageId') or '').strip().casefold()
        if not key:
            key = str(row.get('pageId') or row.get('id') or '').strip().casefold()

        visits = _to_int(row.get('visits'))
        engaged = _to_int(row.get('engaged'))
        group = groups.setdefault(
            key,
            {
                **row,
                'pageIds': [],
                'visits': 0,
                'engaged': 0,
                '_leader_visits': -1,
                '_previous_visits': 0,
                '_previous_engaged': 0,
                '_interaction_weight': 0,
                '_interaction_total': 0,
                '_interaction_change_total': 0,
                '_companies_value': -1,
                '_adoption_value': -1,
                '_users_value': -1,
            },
        )

        page_id = row.get('pageId') or row.get('page_rule_id') or row.get('id')
        if page_id not in group['pageIds']:
            group['pageIds'].append(page_id)

        if row.get('isCurrent') or (not group.get('isCurrent') and visits > group['_leader_visits']):
            group['_leader_visits'] = visits
            for field_name in ('id', 'pageId', 'page_rule_id', 'route'):
                group[field_name] = row.get(field_name)

        group['isCurrent'] = group.get('isCurrent') or str(page_id or '') == str(current_page_id or '')
        group['visits'] += visits
        group['engaged'] += engaged
        group['_previous_visits'] += _previous_from_percent_change(visits, row.get('visitsChange'))
        group['_previous_engaged'] += _previous_from_percent_change(engaged, row.get('engagedChange'))

        companies = _to_int(row.get('companies'))
        if companies > group['_companies_value']:
            group['_companies_value'] = companies
            group['companies'] = companies
            group['companiesChange'] = _to_float(row.get('companiesChange'))

        adoption = _to_float(row.get('adoption'))
        if adoption > group['_adoption_value']:
            group['_adoption_value'] = adoption
            group['adoption'] = adoption
            group['adoptionChange'] = _to_float(row.get('adoptionChange'))

        users = _to_int(row.get('users'))
        if users > group['_users_value']:
            group['_users_value'] = users
            group['users'] = users
            group['usersChange'] = _to_float(row.get('usersChange'))

        weight = max(visits, 1)
        group['_interaction_weight'] += weight
        group['_interaction_total'] += _to_float(row.get('interaction')) * weight
        group['_interaction_change_total'] += _to_float(row.get('interactionChange')) * weight

    result = []
    for group in groups.values():
        interaction_weight = group.pop('_interaction_weight', 0)
        if interaction_weight:
            group['interaction'] = round(group.pop('_interaction_total', 0) / interaction_weight, 1)
            group['interactionChange'] = round(group.pop('_interaction_change_total', 0) / interaction_weight, 1)
        else:
            group.pop('_interaction_total', None)
            group.pop('_interaction_change_total', None)

        group['visitsChange'] = _percent_change_value(group.get('visits'), group.pop('_previous_visits', 0))
        group['engagedChange'] = _percent_change_value(group.get('engaged'), group.pop('_previous_engaged', 0))
        group['engagedLabel'] = _format_duration(group.get('engaged'))
        for field_name in ('_leader_visits', '_companies_value', '_adoption_value', '_users_value'):
            group.pop(field_name, None)
        result.append(group)

    return sorted(result, key=lambda row: (-_to_int(row.get('visits')), row.get('pageName') or ''))


def _coerce_int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _page_detail_queryset(queryset, row):
    page_rule_id = _coerce_int_or_none(row.get('page_rule_id'))
    if page_rule_id is not None:
        return queryset.filter(page_rule_id=page_rule_id)
    return queryset.filter(page_rule_id__isnull=True, product_area_key=row.get('product_area_key') or '')


def _aggregate_company_detail_rows(project_id, row, start_date, end_date, *, company_ids=None, limit=None):
    queryset = PageCompanyDailyMetric.objects.filter(project_id=project_id, date__gte=start_date, date__lte=end_date)
    queryset = _page_detail_queryset(queryset, row)
    if company_ids is not None:
        queryset = queryset.filter(company_id__in=company_ids)
    queryset = queryset.values('company_id').annotate(
        company_name_sample=Max('company_name_sample'),
        visits=Sum('visits_count'),
        engaged=Sum('engaged_seconds'),
        clicks=Sum('click_count'),
        visits_with_click=Sum('visits_with_click_count'),
        users=Sum('active_users_count_daily'),
    )
    if limit:
        queryset = queryset.order_by('-engaged', '-visits', 'company_name_sample', 'company_id')[:limit]
    return list(queryset)


def _aggregate_user_detail_rows(project_id, row, start_date, end_date, *, user_ids=None, limit=None):
    queryset = PageUserDailyMetric.objects.filter(project_id=project_id, date__gte=start_date, date__lte=end_date)
    queryset = _page_detail_queryset(queryset, row)
    if user_ids is not None:
        queryset = queryset.filter(user_id__in=user_ids)
    queryset = queryset.values('user_id', 'company_id').annotate(
        user_name_sample=Max('user_name_sample'),
        visits=Sum('visits_count'),
        engaged=Sum('engaged_seconds'),
        clicks=Sum('click_count'),
    )
    if limit:
        queryset = queryset.order_by('-engaged', '-visits', 'user_name_sample', 'user_id')[:limit]
    return list(queryset)


def _percent_delta_from_lookup(current_value, previous_lookup, lookup_key, field_name):
    previous = previous_lookup.get(lookup_key, {}).get(field_name, 0)
    return _to_float(_delta_pct(current_value, previous)['value'])


def _detail_company_name_lookup(project_id, row, start_date, end_date, *, company_ids=None):
    lookup = {}
    for item in _aggregate_company_detail_rows(project_id, row, start_date, end_date, company_ids=company_ids):
        company_id = item.get('company_id') or ''
        company_name = item.get('company_name_sample') or ''
        if company_id and company_name:
            lookup.setdefault(company_id, company_name)
    return lookup


def _format_synthetic_user_name(user_id, company_name=''):
    match = SYNTHETIC_USER_ID_RE.match(str(user_id or ''))
    if not match:
        return ''

    company_label = company_name or match.group('company').replace('-', ' ').replace('_', ' ').title()
    suffix = match.group('suffix').lstrip('0') or match.group('suffix')
    return f'{company_label} user {suffix}'


def _detail_user_name(user_name, user_id, company_name=''):
    return (
        user_name
        or _format_synthetic_user_name(user_id, company_name)
        or user_id
        or 'Unknown user'
    )


def _build_detail_companies(project_id, row, start_date, end_date, previous_start, previous_end, limit=None):
    current_rows = _aggregate_company_detail_rows(project_id, row, start_date, end_date, limit=limit)
    company_ids = [item.get('company_id') for item in current_rows if item.get('company_id')]
    previous_rows = _aggregate_company_detail_rows(
        project_id,
        row,
        previous_start,
        previous_end,
        company_ids=company_ids,
    ) if company_ids else []
    previous_by_company = {item['company_id']: item for item in previous_rows}
    companies = []

    for item in current_rows:
        company_id = item.get('company_id') or ''
        visits = _to_int(item.get('visits'))
        users = _to_int(item.get('users'))
        engaged = _to_int(item.get('engaged'))
        clicks = _to_int(item.get('clicks'))
        interaction = _pct(item.get('visits_with_click'), visits)
        previous_item = previous_by_company.get(company_id, {})
        previous_interaction = _pct(previous_item.get('visits_with_click'), previous_item.get('visits'))
        avg_user = _ratio(engaged, users)
        previous_avg_user = _ratio(previous_item.get('engaged'), previous_item.get('users'))

        companies.append({
            'id': company_id,
            'companyId': company_id,
            'company': item.get('company_name_sample') or company_id or 'Unknown company',
            'users': users,
            'usersChange': _percent_delta_from_lookup(users, previous_by_company, company_id, 'users'),
            'pagePenetration': 0,
            'pagePenetrationChange': 0,
            'visits': visits,
            'visitsChange': _percent_delta_from_lookup(visits, previous_by_company, company_id, 'visits'),
            'engagedSeconds': engaged,
            'engagedChange': _percent_delta_from_lookup(engaged, previous_by_company, company_id, 'engaged'),
            'engaged': _format_duration(engaged),
            'avgUser': _format_duration(avg_user),
            'avgUserChange': _to_float(_delta_pct(avg_user, previous_avg_user)['value']),
            'interaction': interaction,
            'interactionChange': _to_float(_delta_pp(interaction, previous_interaction)['value']),
            'clicks': clicks,
            'lastSeen': '-',
        })

    companies.sort(key=lambda item: (-item['engagedSeconds'], -item['visits'], item['company']))
    return companies[:limit] if limit else companies


def _build_detail_champions(project_id, row, start_date, end_date, previous_start, previous_end, limit=None):
    current_rows = _aggregate_user_detail_rows(project_id, row, start_date, end_date, limit=limit)
    user_ids = [item.get('user_id') for item in current_rows if item.get('user_id')]
    company_ids = [item.get('company_id') for item in current_rows if item.get('company_id')]
    previous_rows = _aggregate_user_detail_rows(
        project_id,
        row,
        previous_start,
        previous_end,
        user_ids=user_ids,
    ) if user_ids else []
    previous_by_user = {item['user_id']: item for item in previous_rows}
    company_names = _detail_company_name_lookup(project_id, row, start_date, end_date, company_ids=company_ids)
    champions = []

    for item in current_rows:
        user_id = item.get('user_id') or ''
        company_id = item.get('company_id') or ''
        company_name = company_names.get(company_id) or company_id or '-'
        visits = _to_int(item.get('visits'))
        engaged = _to_int(item.get('engaged'))
        clicks = _to_int(item.get('clicks'))

        champions.append({
            'id': user_id,
            'userId': user_id,
            'companyId': company_id,
            'user': _detail_user_name(item.get('user_name_sample'), user_id, company_name if company_name != company_id else ''),
            'company': company_name,
            'engagedSeconds': engaged,
            'engagedChange': _percent_delta_from_lookup(engaged, previous_by_user, user_id, 'engaged'),
            'engaged': _format_duration(engaged),
            'visits': visits,
            'visitsChange': _percent_delta_from_lookup(visits, previous_by_user, user_id, 'visits'),
            'avgVisit': _format_duration(_ratio(engaged, visits)),
            'clicks': clicks,
            'clicksChange': _percent_delta_from_lookup(clicks, previous_by_user, user_id, 'clicks'),
            'lastSeen': '-',
        })

    champions.sort(key=lambda item: (-item['engagedSeconds'], -item['visits'], item['user']))
    return champions[:limit] if limit else champions


def _aggregate_action_detail_rows(project_id, row, start_date, end_date, *, element_keys=None, limit=None):
    queryset = RawPageActionDailyMetric.objects.filter(project_id=project_id, date__gte=start_date, date__lte=end_date)
    queryset = _page_detail_queryset(queryset, row)
    if element_keys is not None:
        queryset = queryset.filter(element_key__in=element_keys)
    queryset = queryset.values('element_key').annotate(
        clicks=Sum('clicks_count'),
        users=Sum('users_count_daily'),
        companies=Sum('companies_count_daily'),
        visits_with_action=Sum('visits_with_action_count'),
    )
    if limit:
        queryset = queryset.order_by('-clicks', 'element_key')[:limit]
    return list(queryset)


def _build_detail_actions(project_id, row, start_date, end_date, previous_start, previous_end, limit=20):
    current_rows = _aggregate_action_detail_rows(project_id, row, start_date, end_date, limit=limit)
    element_keys = [item.get('element_key') for item in current_rows if item.get('element_key')]
    previous_rows = _aggregate_action_detail_rows(
        project_id,
        row,
        previous_start,
        previous_end,
        element_keys=element_keys,
    ) if element_keys else []
    previous_by_action = {item.get('element_key') or 'Unknown action': item for item in previous_rows}
    current_visits = _to_int(row.get('visits_count'))
    previous_visits = _previous_metric_value(row.get('visits_count'), row.get('deltas', {}).get('visits', {}))
    actions = []

    for item in current_rows:
        action = item.get('element_key') or 'Unknown action'
        visits_pct = _pct(item.get('visits_with_action'), current_visits)
        previous_item = previous_by_action.get(action, {})
        previous_visits_pct = _pct(previous_item.get('visits_with_action'), previous_visits)
        clicks = _to_int(item.get('clicks'))
        users = _to_int(item.get('users'))
        companies = _to_int(item.get('companies'))

        actions.append({
            'action': action,
            'clicks': clicks,
            'clicksChange': _to_float(_delta_pct(clicks, previous_item.get('clicks'))['value']),
            'visitsPct': visits_pct,
            'visitsPctChange': _to_float(_delta_pp(visits_pct, previous_visits_pct)['value']),
            'users': users,
            'usersChange': _to_float(_delta_pct(users, previous_item.get('users'))['value']),
            'companies': companies,
            'companiesChange': _to_float(_delta_pct(companies, previous_item.get('companies'))['value']),
            'trendValues': [],
        })

    actions.sort(key=lambda item: (-item['clicks'], item['action']))
    return actions[:limit]


def _aggregate_detail_flow_pages(pages):
    aggregated = {}
    for page in pages:
        page_name = page.get('pageName') or ''
        if not page_name:
            continue
        item = aggregated.setdefault(page_name, {'pageName': page_name, 'visits': 0, 'route': page.get('route') or ''})
        item['visits'] += _to_int(page.get('visits'))
        item['route'] = item.get('route') or page.get('route') or ''
    return sorted(aggregated.values(), key=lambda item: (-item['visits'], item['pageName'] or ''))


def _overview_cache_detail_rows(project_id, range_key):
    cached = queries.fetch_one(
        queries.FETCH_OVERVIEW_CACHE_DETAIL_ROWS_SQL,
        [project_id, range_key, DEFAULT_FILTERS_HASH],
    )
    if not cached:
        return None

    try:
        schema_version = int(cached.get('schema_version'))
    except (TypeError, ValueError):
        return None

    if schema_version != OVERVIEW_PAYLOAD_SCHEMA_VERSION:
        return None

    rows = [
        _ensure_change_row_contract(dict(row))
        for row in _coerce_json(cached.get('change_aware_rows')) or []
        if isinstance(row, dict)
    ]
    if not rows:
        return None

    project = _coerce_json(cached.get('project')) or {}
    current_counts = {
        'active_companies_count': _to_int(project.get('active_companies_total')),
        'active_users_count': _to_int(project.get('active_users_total')),
    }
    return rows, current_counts


def get_cached_overview_detail_rows(project_id, range_key='last_30_days'):
    cached_rows = _overview_cache_detail_rows(project_id, range_key)
    if not cached_rows:
        return []

    rows, _current_counts = cached_rows
    return rows


def _resolve_page_detail_context(project_id, page_rule_id, *, range_key='last_30_days', start_date=None, end_date=None):
    project = get_project_info(project_id)
    if not project:
        raise ValueError(f'Project {project_id} does not exist.')

    timezone_name = project['timezone'] or 'UTC'
    has_explicit_period = start_date is not None or end_date is not None
    start_date, end_date = resolve_period(timezone_name, range_key=range_key, start_date=start_date, end_date=end_date)
    previous_start, previous_end = previous_period(start_date, end_date)
    cached_rows = None if has_explicit_period else _overview_cache_detail_rows(project_id, range_key)
    if cached_rows:
        rows, current_counts = cached_rows
        if not current_counts.get('active_companies_count') and not current_counts.get('active_users_count'):
            current_counts = _project_distinct_counts(project_id, start_date, end_date)
        previous_counts = _project_distinct_counts(project_id, previous_start, previous_end)
    else:
        rows, current_counts, previous_counts = _build_change_rows(
            project_id,
            start_date,
            end_date,
            previous_start,
            previous_end,
        )

    current_row = _find_detail_row(rows, page_rule_id)
    if not current_row:
        current_row = _zero_detail_change_row(
            project_id,
            page_rule_id,
            start_date,
            end_date,
            previous_start,
            previous_end,
            current_counts,
            previous_counts,
        )

    return {
        'project': project,
        'timezone_name': timezone_name,
        'start_date': start_date,
        'end_date': end_date,
        'previous_start': previous_start,
        'previous_end': previous_end,
        'rows': rows,
        'current_counts': current_counts,
        'previous_counts': previous_counts,
        'current_row': current_row,
    }


def _page_detail_context_for_row(
    project,
    timezone_name,
    start_date,
    end_date,
    previous_start,
    previous_end,
    rows,
    current_counts,
    previous_counts,
    current_row,
    bulk_context=None,
):
    return {
        'project': project,
        'timezone_name': timezone_name,
        'start_date': start_date,
        'end_date': end_date,
        'previous_start': previous_start,
        'previous_end': previous_end,
        'rows': rows,
        'current_counts': current_counts,
        'previous_counts': previous_counts,
        'current_row': current_row,
        'bulk_context': bulk_context,
    }


def _detail_cache_page_rule_id(row):
    value = _page_rule_id(row or {})
    return str(value or '').strip()


def _build_detail_flow(project_id, timezone_name, row, visits, start_date, end_date):
    page_name = row.get('page_name') or ''
    page_rule_pk = _coerce_int_or_none(row.get('page_rule_id'))
    window_start_utc, window_end_utc = _utc_bounds_for_local_dates(start_date, end_date, timezone_name)
    if page_rule_pk is not None:
        transition_rows = queries.fetch_all(
            queries.DETAIL_FLOW_BY_RULE_SQL,
            [
                project_id,
                window_start_utc,
                window_end_utc,
                page_rule_pk,
                project_id,
                window_start_utc,
                window_end_utc,
                page_rule_pk,
            ],
        )
    else:
        transition_rows = queries.fetch_all(
            queries.DETAIL_FLOW_SQL,
            [
                project_id,
                window_start_utc,
                window_end_utc,
                page_rule_pk,
                page_rule_pk,
                page_rule_pk,
                page_rule_pk,
                page_name,
                page_name,
            ],
        )
    links = [
        {
            'source': link.get('from_page_name') or link.get('from_page_key'),
            'target': link.get('to_page_name') or link.get('to_page_key'),
            'value': _to_int(link.get('transition_count')),
            'sessions_count': _to_int(link.get('sessions_count')),
            'companies_count': _to_int(link.get('companies_count')),
            'source_product_area': link.get('from_product_area_name') or link.get('from_product_area_key'),
            'target_product_area': link.get('to_product_area_name') or link.get('to_product_area_key'),
        }
        for link in transition_rows
    ]
    previous_pages = sorted(
        [
            {'pageName': link.get('source'), 'visits': _to_int(link.get('value')), 'route': ''}
            for link in links
            if link.get('target') == page_name
        ],
        key=lambda item: (-item['visits'], item['pageName'] or ''),
    )
    next_pages = sorted(
        [
            {'pageName': link.get('target'), 'visits': _to_int(link.get('value')), 'route': ''}
            for link in links
            if link.get('source') == page_name
        ],
        key=lambda item: (-item['visits'], item['pageName'] or ''),
    )
    previous_pages = _aggregate_detail_flow_pages(previous_pages)
    next_pages = _aggregate_detail_flow_pages(next_pages)
    previous_visits = sum(item['visits'] for item in previous_pages)
    next_visits = sum(item['visits'] for item in next_pages)
    visits = max(_to_int(visits), 1)
    nodes = []
    node_names = set()
    for link in links:
        for name in (link.get('source'), link.get('target')):
            if name and name not in node_names:
                node_names.add(name)
                nodes.append({'name': name})

    return {
        'entryRate': max(0, min(100, round(((visits - min(visits, previous_visits)) / visits) * 100))),
        'exitRate': max(0, min(100, round(((visits - min(visits, next_visits)) / visits) * 100))),
        'mostCommonPreviousPage': previous_pages[0]['pageName'] if previous_pages else '-',
        'mostCommonNextPage': next_pages[0]['pageName'] if next_pages else '-',
        'previousPages': previous_pages,
        'nextPages': next_pages,
        'links': links,
        'sankey': {'nodes': nodes, 'links': links},
    }


def _build_page_detail_payload_from_context(project_id, range_key, context):
    project = context['project']
    timezone_name = context['timezone_name']
    start_date = context['start_date']
    end_date = context['end_date']
    previous_start = context['previous_start']
    previous_end = context['previous_end']
    rows = context['rows']
    current_counts = context['current_counts']
    previous_counts = context['previous_counts']
    current_row = context['current_row']

    if not current_row:
        return None

    selection_rows = rows
    current_page_id = current_row.get('page_rule_id')
    if not any(str(row.get('page_rule_id') or '') == str(current_page_id or '') for row in selection_rows):
        selection_rows = [current_row, *selection_rows]

    peers = _select_detail_peer_rows(selection_rows, current_row, 10)
    benchmark_rows = [
        row for row in selection_rows
        if str(row.get('page_rule_id') or '') != str(current_page_id or '')
    ]
    same_area_rows = sorted(
        [
            row for row in selection_rows
            if (row.get('product_area_key') or '') == (current_row.get('product_area_key') or '')
        ],
        key=lambda item: (-_to_int(item.get('visits_count')), item.get('page_name') or ''),
    )
    daily_source_rows = [current_row, *peers, *benchmark_rows]
    bulk_context = context.get('bulk_context')
    daily_rows = (
        bulk_context.daily_page_rows_for_rows(daily_source_rows)
        if bulk_context
        else _daily_page_rows_for_rows(project_id, start_date, end_date, daily_source_rows)
    )
    detail_metrics = [
        _detail_metric_payload(current_row, peers, benchmark_rows, metric, start_date, end_date, daily_rows)
        for metric in PAGE_DETAIL_METRICS
    ]
    metrics = [
        metric for metric in detail_metrics
        if metric['key'] not in {'interaction', 'clicks_per_visit'}
    ]
    interaction_metric = next(metric for metric in detail_metrics if metric['key'] == 'interaction')
    clicks_per_visit_metric = next(metric for metric in detail_metrics if metric['key'] == 'clicks_per_visit')
    clicks_per_visit_metric = {**clicks_per_visit_metric, 'peerSeries': []}

    return {
        'schema_version': OVERVIEW_PAYLOAD_SCHEMA_VERSION,
        'project': {
            'id': project_id,
            'name': project['name'],
            'active_companies_total': _to_int(current_counts.get('active_companies_count')),
            'active_users_total': _to_int(current_counts.get('active_users_count')),
        },
        'page': {
            'id': current_page_id,
            'pageRuleId': current_page_id,
            'route': _detail_route(current_row),
            'displayName': current_row.get('page_name') or current_page_id,
            'productAreaId': current_row.get('product_area_key') or 'unassigned',
            'productAreaName': current_row.get('product_area_name') or current_row.get('page_group') or 'Unassigned',
            'routeType': 'Page',
            'lastSeenAt': '-',
        },
        'period': _detail_period_payload(range_key, start_date, end_date, previous_start, previous_end),
        'metrics': metrics,
        'combinedInteractionClicksMetric': {
            'interaction': interaction_metric,
            'clicksPerVisit': clicks_per_visit_metric,
        },
        'relatedPages': _dedupe_detail_related_pages(
            [
                _detail_related_page_payload(row, current_page_id)
                for row in same_area_rows
            ],
            current_page_id,
        ),
        'champions': _build_detail_champions(project_id, current_row, start_date, end_date, previous_start, previous_end),
        'companies': _build_detail_companies(project_id, current_row, start_date, end_date, previous_start, previous_end),
        'actions': _build_detail_actions(project_id, current_row, start_date, end_date, previous_start, previous_end),
        'flow': _build_detail_flow(
            project_id,
            timezone_name,
            current_row,
            current_row.get('visits_count'),
            start_date,
            end_date,
        ),
        'previousProjectCounts': {
            'active_companies_total': _to_int(previous_counts.get('active_companies_count')),
            'active_users_total': _to_int(previous_counts.get('active_users_count')),
        },
    }


def build_page_detail_payload(project_id, page_rule_id, *, range_key='last_30_days', start_date=None, end_date=None):
    context = _resolve_page_detail_context(
        project_id,
        page_rule_id,
        range_key=range_key,
        start_date=start_date,
        end_date=end_date,
    )
    return _build_page_detail_payload_from_context(project_id, range_key, context)


def hydrate_pages_detail_cache(
    project_id,
    *,
    range_key='last_30_days',
    start_date=None,
    end_date=None,
    project=None,
    rows=None,
    current_counts=None,
    previous_counts=None,
    generated_at=None,
    expires_at=None,
):
    project = project or get_project_info(project_id)
    if not project:
        raise ValueError(f'Project {project_id} does not exist.')

    timezone_name = project['timezone'] or 'UTC'
    start_date, end_date = resolve_period(timezone_name, range_key=range_key, start_date=start_date, end_date=end_date)
    previous_start, previous_end = previous_period(start_date, end_date)
    generated_at = generated_at or django_timezone.now()
    expires_at = expires_at or generated_at + CACHE_TTL

    if rows is None or current_counts is None or previous_counts is None:
        rows, current_counts, previous_counts = _build_change_rows(
            project_id,
            start_date,
            end_date,
            previous_start,
            previous_end,
        )

    cached_count = 0
    seen_page_ids = set()
    bulk_context = BulkPageDetailContext(project_id, start_date, end_date)
    for row in rows or []:
        if not isinstance(row, dict):
            continue

        page_rule_id = _detail_cache_page_rule_id(row)
        if not page_rule_id or page_rule_id in seen_page_ids:
            continue

        seen_page_ids.add(page_rule_id)
        context = _page_detail_context_for_row(
            project,
            timezone_name,
            start_date,
            end_date,
            previous_start,
            previous_end,
            rows,
            current_counts,
            previous_counts,
            row,
            bulk_context=bulk_context,
        )
        payload = _build_page_detail_payload_from_context(project_id, range_key, context)
        if not payload:
            continue

        queries.execute(
            queries.UPSERT_DETAIL_CACHE_SQL,
            [
                project_id,
                range_key,
                page_rule_id,
                start_date,
                end_date,
                DEFAULT_FILTERS_HASH,
                json.dumps(payload, default=_json_default),
                generated_at,
                expires_at,
            ],
        )
        cached_count += 1

    return {'status': 'success', 'items_count': cached_count}


def build_pages_overview_cache(project_id, *, range_key='last_30_days', start_date=None, end_date=None):
    project = get_project_info(project_id)
    if not project:
        raise ValueError(f'Project {project_id} does not exist.')

    timezone_name = project['timezone'] or 'UTC'
    start_date, end_date = resolve_period(timezone_name, range_key=range_key, start_date=start_date, end_date=end_date)
    previous_start, previous_end = previous_period(start_date, end_date)
    generated_at = django_timezone.now()
    expires_at = generated_at + CACHE_TTL
    source = queries.fetch_one(queries.SOURCE_MAX_EVENT_TS_SQL, [project_id]) or {}
    source_max_event_ts = source.get('source_max_event_ts')

    rows, current_counts, previous_counts = _build_change_rows(project_id, start_date, end_date, previous_start, previous_end)
    page_metrics_rows, _, _ = _build_change_rows(
        project_id,
        start_date,
        end_date,
        previous_start,
        previous_end,
        grain='display_page',
    )
    product_area_rows, _, _ = _build_change_rows(
        project_id,
        start_date,
        end_date,
        previous_start,
        previous_end,
        grain='product_area',
    )
    previous_rows = _summary_by_display_page(project_id, previous_start, previous_end)
    payload = _empty_payload(project, range_key, start_date, end_date, previous_start, previous_end, generated_at, source_max_event_ts)
    payload['project'].update({
        'active_companies_total': _to_int(current_counts.get('active_companies_count')),
        'active_users_total': _to_int(current_counts.get('active_users_count')),
    })

    if rows:
        top_actions = _build_top_actions(project_id, start_date, end_date, previous_start, previous_end)
        company_engagement = _build_scatter(project_id, start_date, end_date)
        overview_rows = [_strip_for_overview_row(row) for row in rows]
        overview_page_metrics_rows = [_strip_for_overview_row(row) for row in page_metrics_rows]
        payload.update({
            'kpis': _build_kpis(
                page_metrics_rows,
                previous_rows,
                _to_int(current_counts.get('active_companies_count')),
                _to_int(previous_counts.get('active_companies_count')),
                comparison_available=_has_period_comparison_data(previous_rows, previous_counts),
            ),
            'rows': overview_rows,
            'change_aware_rows': overview_rows,
            'page_metrics_rows': overview_page_metrics_rows,
            'product_area_summary': [_strip_for_product_area_summary(row) for row in product_area_rows],
            'top_pages_by_visits_over_time': _build_series(page_metrics_rows, 'visits_count'),
            'top_pages_by_engaged_time_over_time': _build_series(page_metrics_rows, 'engaged_seconds'),
            'engaged_time_treemap': _build_treemap(
                page_metrics_rows,
                active_companies_total=current_counts.get('active_companies_count'),
            ),
            'sankey': _build_sankey(project_id, timezone_name, start_date, end_date),
            'top_actions_by_page': top_actions,
            'top_actions_by_page_group': _build_top_actions_by_page_group(top_actions),
            'company_engagement_by_product_area': company_engagement,
            'company_engagement_by_page_group': _build_company_engagement_by_page_group(company_engagement),
            'top_clicked_elements': _build_top_clicked_elements(top_actions),
        })

    payload = normalize_overview_payload(payload)
    detail_cache_result = hydrate_pages_detail_cache(
        project_id,
        range_key=range_key,
        start_date=start_date,
        end_date=end_date,
        project=project,
        rows=payload.get('change_aware_rows') or [],
        current_counts=current_counts,
        previous_counts=previous_counts,
        generated_at=generated_at,
        expires_at=expires_at,
    )

    queries.execute(
        queries.UPSERT_OVERVIEW_CACHE_SQL,
        [
            project_id,
            range_key,
            start_date,
            end_date,
            DEFAULT_FILTERS_HASH,
            json.dumps(payload, default=_json_default),
            source_max_event_ts,
            generated_at,
            expires_at,
        ],
    )
    hydrate_pages_scatter_tooltips_cache(project_id, range_key=range_key, start_date=start_date, end_date=end_date)
    return {
        'status': 'success',
        'project_id': project_id,
        'range_key': range_key,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'rows_count': len(page_metrics_rows),
        'detail_cache_count': detail_cache_result['items_count'],
    }


def hydrate_pages_scatter_tooltips_cache(project_id, *, range_key='last_30_days', start_date=None, end_date=None):
    project = get_project_info(project_id)
    if not project:
        raise ValueError(f'Project {project_id} does not exist.')

    start_date, end_date = resolve_period(project['timezone'], range_key=range_key, start_date=start_date, end_date=end_date)
    generated_at = django_timezone.now()
    expires_at = generated_at + CACHE_TTL
    groups = _build_scatter(project_id, start_date, end_date)
    items = []
    for group in groups:
        for point in group['points']:
            items.append({
                'product_area_key': group['product_area_key'],
                'product_area_name': group['product_area_name'],
                **point,
            })
    payload = {
        'generated_at': generated_at.isoformat(),
        'range_key': range_key,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'items': items,
    }
    queries.execute(
        queries.UPSERT_SCATTER_TOOLTIP_CACHE_SQL,
        [
            project_id,
            range_key,
            start_date,
            end_date,
            DEFAULT_FILTERS_HASH,
            json.dumps(payload, default=_json_default),
            generated_at,
            expires_at,
        ],
    )
    return {'status': 'success', 'items_count': len(items)}
