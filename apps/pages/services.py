import copy
import json
import math
import re
import zlib
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.db.models import Count, F, Max, Q, Sum
from django.db.models.fields.json import KeyTextTransform
from django.utils.text import slugify
from django.utils import timezone as django_timezone

from apps.pages import analytics_memo, queries
from apps.pages.analytics_memo import analytics_memo_scope
from apps.pages.locks import project_advisory_lock
from apps.pages.models import PageCompanyDailyMetric, PageDailyMetric, PageUserDailyMetric, ProductArea, RawPageActionDailyMetric
from apps.pages.product_area_colors import (
    build_product_area_color_lookup,
    explicit_product_area_color,
    product_area_color_from_lookup,
    resolve_product_area_colors,
)
from apps.tracker.models import ProjectPageRule


DEFAULT_FILTERS_HASH = 'default'
DEFAULT_SESSION_TIMEOUT_SECONDS = 30 * 60
DEFAULT_EVENT_GAP_CAP_SECONDS = 30
DEFAULT_OVERVIEW_RANGE_KEYS = ('last_7_days', 'last_30_days', 'last_90_days', 'last_180_days')
# 24: Product area summary sparklines carry per-day values instead of
# period-to-date totals. The keys are unchanged, so stored payloads stay
# readable and would keep serving the old cumulative series until the version
# forces them to be rebuilt.
# 25: The fastest-growing card compares two period totals instead of plotting an
# aligned growth sparkline, so the per-day aligned company prefixes are no
# longer built or stored.
OVERVIEW_PAYLOAD_SCHEMA_VERSION = 25
CACHE_TTL = timedelta(hours=1)
OVERVIEW_CACHE_BINARY_MAGIC = b'HPO\x01'
OVERVIEW_CACHE_COMPRESSION_LEVEL = 6
POWER_USER_VISITS_PER_WEEK = 3
POWER_USER_ENGAGED_SECONDS_PER_WEEK = 100
POWER_USER_ACTIVE_DAYS_SHARE = 0.13
POWER_USER_PRODUCT_AREAS = 2
POWER_USER_MIN_INTERACTION = 0.20
POWER_USER_DYNAMIC_MIN_COHORT_SIZE = 30
POWER_USER_DYNAMIC_PERCENTILE = 0.90
HEALTHY_USER_VISITS_PER_WEEK = 2
HEALTHY_USER_ENGAGED_SECONDS_PER_WEEK = 60
HEALTHY_USER_ACTIVE_DAYS_SHARE = 0.10
PASSIVE_USER_ENGAGED_SECONDS = 60
JSON_SCRIPT_ESCAPES = str.maketrans({
    '>': '\\u003E',
    '<': '\\u003C',
    '&': '\\u0026',
})
PRODUCT_AREA_SUMMARY_TREND_METRICS = ('companies', 'adoption', 'users', 'engaged')
OVERVIEW_ROW_TREND_METRICS = ('companies', 'adoption', 'engaged', 'visits')
PAGE_DETAIL_TREND_METRICS = (
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
SYNTHETIC_USER_ID_RE = re.compile(r'^user[_-](?P<company>.+)_(?P<suffix>\d+)$')


def _schedule_demo_project_cache_clear(project_id):
    from apps.projects.demo import clear_demo_project_cache_for_project

    transaction.on_commit(
        lambda: clear_demo_project_cache_for_project(project_id),
    )


def bump_filtered_analytics_revision(project_id):
    """Advance the revision shared by company-attribute overview variants."""

    from apps.projects.models import Project

    updated = Project.objects.filter(pk=project_id).update(
        filtered_analytics_revision=F('filtered_analytics_revision') + 1,
    )
    if not updated:
        raise ValueError(f'Project {project_id} does not exist.')
    _schedule_demo_project_cache_clear(project_id)
    return int(
        Project.objects.values_list('filtered_analytics_revision', flat=True).get(
            pk=project_id,
        )
    )


def bump_analytics_facts_revision(project_id):
    """Advance prepared-fact and filtered-payload revisions atomically."""

    from apps.projects.models import Project

    updated = Project.objects.filter(pk=project_id).update(
        analytics_facts_revision=F('analytics_facts_revision') + 1,
        filtered_analytics_revision=F('filtered_analytics_revision') + 1,
    )
    if not updated:
        raise ValueError(f'Project {project_id} does not exist.')
    _schedule_demo_project_cache_clear(project_id)
    analytics_revision, filtered_revision = (
        Project.objects
        .values_list(
            'analytics_facts_revision',
            'filtered_analytics_revision',
        )
        .get(pk=project_id)
    )
    return {
        'analytics_facts_revision': int(analytics_revision),
        'filtered_analytics_revision': int(filtered_revision),
    }


def resolve_project_company_cohort(project_id, state):
    """
    Resolve one active filter state to the project's matching company IDs.

    The universe is every company the project has ever recorded a daily fact
    for, not just the requested window. Companies outside the window contribute
    no facts either way, so the window cannot change the answer, and a
    window-independent cohort stays valid across every range a single build
    touches.
    """

    from apps.pages.models import PageCompanyDailyMetric
    from apps.projects.company_attribute_filters import resolve_company_cohort

    observed = (
        PageCompanyDailyMetric.objects
        .filter(project_id=project_id)
        .exclude(company_id='')
        .order_by()
        .values_list('company_id', flat=True)
        .distinct()
    )
    return frozenset(resolve_company_cohort(state, observed))


def _delete_superseded_filtered_variants(project_id):
    """
    Drop filtered variants whose period window can no longer be requested.

    Every range resolves against the project's current local day, so once that
    day advances a variant built for the previous window is unreachable: no
    request will ever match its dates again. Collecting them here keeps the
    table proportional to the filters in current use rather than to every
    filter ever applied.
    """

    from apps.pages.models import (
        CompaniesOverviewCache,
        PagesOverviewCache,
        PagesScatterTooltipCache,
        UsersOverviewCache,
    )

    project = get_project_info(project_id)
    timezone_name = (project or {}).get('timezone') or 'UTC'
    reachable = {
        resolve_period(timezone_name, range_key=range_key)
        for range_key in DEFAULT_OVERVIEW_RANGE_KEYS
    }
    reachable_ends = {end_date for _start, end_date in reachable}

    deleted = {}
    for name, cache_model in (
        ('pages_overview', PagesOverviewCache),
        ('pages_scatter_tooltips', PagesScatterTooltipCache),
        ('companies_overview', CompaniesOverviewCache),
        ('users_overview', UsersOverviewCache),
    ):
        count, _ = (
            cache_model.objects
            .filter(project_id=project_id)
            .exclude(filters_hash=DEFAULT_FILTERS_HASH)
            .exclude(end_date__in=reachable_ends)
            .delete()
        )
        deleted[name] = count
    return deleted


def purge_expired_filtered_overview_caches(project_id, *, now=None):
    """
    Collect filtered variants that no request can reach any more.

    Expiry deliberately does not decide this. A variant past its one-hour TTL is
    still a correct answer for the window it was built for, and readers serve it
    while a rebuild runs behind them; deleting on TTL would send every returning
    user back to a preparing state each hour. Reachability is the durable
    condition, and it turns over once per project-local day.
    """

    deleted = _delete_superseded_filtered_variants(project_id)
    return {
        'project_id': project_id,
        'deleted': deleted,
        'deleted_total': sum(deleted.values()),
    }


def weekly_scaled_threshold(base_value, period_days):
    scale = max(1.0, float(period_days or 1) / 7.0)
    return max(int(base_value), math.ceil(base_value * scale))


def active_days_threshold(period_days, share):
    days = max(1, int(period_days or 1))
    return min(days, max(1, math.ceil(days * share)))


def passive_visits_threshold(period_days):
    days = max(1, int(period_days or 1))
    return max(2, math.ceil(days / 14.0))


def _active_user_cohort_rows(rows):
    if isinstance(rows, dict):
        rows = rows.values()
    return [
        row
        for row in (rows or [])
        if row and any(
            int(row.get(key) or 0) > 0
            for key in ('visits', 'engaged_seconds', 'click_count', 'active_days')
        )
    ]


def _cohort_percentile(rows, key, percentile):
    values = sorted(max(0, int(row.get(key) or 0)) for row in rows)
    if not values:
        return 0
    index = min(len(values) - 1, int(round((len(values) - 1) * percentile)))
    return values[index]


def power_user_thresholds(period_days, cohort_rows=None):
    thresholds = {
        'visits': weekly_scaled_threshold(POWER_USER_VISITS_PER_WEEK, period_days),
        'engaged_seconds': weekly_scaled_threshold(POWER_USER_ENGAGED_SECONDS_PER_WEEK, period_days),
        'active_days': active_days_threshold(period_days, POWER_USER_ACTIVE_DAYS_SHARE),
        'product_areas': POWER_USER_PRODUCT_AREAS,
        'interaction': POWER_USER_MIN_INTERACTION,
    }
    cohort = _active_user_cohort_rows(cohort_rows)
    if len(cohort) < POWER_USER_DYNAMIC_MIN_COHORT_SIZE:
        return thresholds

    thresholds['visits'] = max(
        thresholds['visits'],
        _cohort_percentile(cohort, 'visits', POWER_USER_DYNAMIC_PERCENTILE),
    )
    thresholds['engaged_seconds'] = max(
        thresholds['engaged_seconds'],
        _cohort_percentile(cohort, 'engaged_seconds', POWER_USER_DYNAMIC_PERCENTILE),
    )
    thresholds['active_days'] = min(
        max(1, int(period_days or 1)),
        max(
            thresholds['active_days'],
            _cohort_percentile(cohort, 'active_days', POWER_USER_DYNAMIC_PERCENTILE),
        ),
    )
    return thresholds


def project_power_user_thresholds(project_id, start_date, end_date):
    period_days = (end_date - start_date).days + 1
    rows = (
        PageUserDailyMetric.objects
        .filter(project_id=project_id, date__gte=start_date, date__lte=end_date)
        .exclude(user_id__isnull=True)
        .exclude(user_id='')
        .values('user_id')
        .annotate(
            visits=Sum('visits_count'),
            engaged_seconds=Sum('engaged_seconds'),
            click_count=Sum('click_count'),
            active_days=Count('date', filter=Q(visits_count__gt=0), distinct=True),
        )
    )
    return power_user_thresholds(period_days, rows)


def healthy_user_thresholds(period_days):
    return {
        'visits': weekly_scaled_threshold(HEALTHY_USER_VISITS_PER_WEEK, period_days),
        'engaged_seconds': weekly_scaled_threshold(HEALTHY_USER_ENGAGED_SECONDS_PER_WEEK, period_days),
        'active_days': active_days_threshold(period_days, HEALTHY_USER_ACTIVE_DAYS_SHARE),
        'product_areas': 1,
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


def compress_overview_payload(payload):
    """Encode an overview payload for low-overhead database transport."""

    serialized = json.dumps(
        payload or {},
        default=_json_default,
        ensure_ascii=False,
        separators=(',', ':'),
    ).encode('utf-8')
    return OVERVIEW_CACHE_BINARY_MAGIC + zlib.compress(
        serialized,
        level=OVERVIEW_CACHE_COMPRESSION_LEVEL,
    )


def decompress_overview_payload(payload_compressed):
    """Decode a payload produced by :func:`compress_overview_payload`."""

    encoded = bytes(payload_compressed or b'')
    if not encoded.startswith(OVERVIEW_CACHE_BINARY_MAGIC):
        raise ValueError('Unsupported Pages overview cache payload.')
    try:
        serialized = zlib.decompress(
            encoded[len(OVERVIEW_CACHE_BINARY_MAGIC):],
        )
        payload = json.loads(serialized)
    except (UnicodeDecodeError, json.JSONDecodeError, zlib.error) as exc:
        raise ValueError('Invalid Pages overview cache payload.') from exc
    if not isinstance(payload, dict):
        raise ValueError('Pages overview cache payload must decode to an object.')
    return payload


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
    """Return the latest usable trait email per prepared user."""

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
        .annotate(trait_email=KeyTextTransform('email', 'user_traits'))
        # Narrowing to the rows _safe_trait_email would accept is what lets the
        # newest row per user be the answer: a user whose latest trait email is
        # malformed still resolves to the newest well-formed one behind it.
        .filter(trait_email__contains='@')
    )
    if normalized_user_ids is not None:
        queryset = queryset.filter(user_id__in=normalized_user_ids)

    # DISTINCT ON returns the one row per user this needs. Ordering by timestamp
    # and walking every matching event in Python instead made the cost scale
    # with the period's event count rather than with the number of users.
    rows = (
        queryset
        .order_by('user_id', '-timestamp')
        .distinct('user_id')
        .values_list('user_id', 'trait_email')
    )

    emails = {}
    for row_user_id, trait_email in rows.iterator(chunk_size=2000):
        row_user_id = str(row_user_id or '').strip()
        email = _safe_trait_email(trait_email)
        if row_user_id and email:
            emails[row_user_id] = email
    return emails


def company_trait_domain_lookup(project, start_date, end_date, *, company_ids=None):
    """Return the latest non-empty company domain per prepared company."""

    from apps.tracker.models import AnalyticsEvent

    project_id = getattr(project, 'id', None)
    timezone_name = getattr(project, 'timezone', None)
    if isinstance(project, dict):
        project_id = project.get('id') or project.get('project_id')
        timezone_name = project.get('timezone')
    if not project_id:
        return {}

    normalized_company_ids = None
    if company_ids is not None:
        normalized_company_ids = [
            str(company_id)
            for company_id in company_ids
            if company_id not in (None, '')
        ]
        if not normalized_company_ids:
            return {}

    start_ts, end_ts = _utc_bounds_for_local_dates(start_date, end_date, timezone_name or 'UTC')
    queryset = (
        AnalyticsEvent.objects
        .filter(session__project_id=project_id, timestamp__gte=start_ts, timestamp__lt=end_ts)
        .exclude(company_id__isnull=True)
        .exclude(company_id='')
        .filter(company_traits__domain__isnull=False)
        .exclude(company_traits__domain='')
        .order_by('-timestamp')
    )
    if normalized_company_ids is not None:
        queryset = queryset.filter(company_id__in=normalized_company_ids)

    domains = {}
    for row in queryset.values('company_id', 'company_traits').iterator(chunk_size=2000):
        company_id = str(row.get('company_id') or '').strip()
        if not company_id or company_id in domains:
            continue
        domain = str((row.get('company_traits') or {}).get('domain') or '').strip()
        if domain:
            domains[company_id] = domain
    return domains


def _safe_date(value):
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _today_for_project(timezone_name):
    return django_timezone.now().astimezone(_project_zone(timezone_name)).date()


PERIOD_DAYS_BY_RANGE_KEY = {
    'last_7_days': 7,
    'last_30_days': 30,
    'last_90_days': 90,
    'last_180_days': 180,
}
DEFAULT_PERIOD_DAYS = 30


def period_days_for_range(range_key):
    return PERIOD_DAYS_BY_RANGE_KEY.get(range_key, DEFAULT_PERIOD_DAYS)


def resolve_period(project_timezone, range_key='last_30_days', start_date=None, end_date=None):
    """
    Resolve a range key to whole days that have already finished.

    The window ends on the last complete project-local day, never on today.
    Including a day still in progress would make every figure drift upward
    through the day and make a period incomparable with the one before it: the
    same dashboard would answer differently in the morning and in the evening,
    and the newest point of every trend would sit in a permanent dip.

    Fact preparation is unaffected and still covers today, so today's events are
    already aggregated by the time that day closes and enters a window.
    """

    if start_date and end_date:
        return _safe_date(start_date), _safe_date(end_date)

    last_complete_day = _today_for_project(project_timezone) - timedelta(days=1)
    return (
        last_complete_day - timedelta(days=period_days_for_range(range_key) - 1),
        last_complete_day,
    )


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
    params = [project_id, range_key, filters_hash]
    row = queries.fetch_one(queries.FETCH_OVERVIEW_CACHE_SQL, params)
    if not row:
        return None
    if row.get('payload_compressed'):
        try:
            row['payload_json'] = decompress_overview_payload(
                row['payload_compressed'],
            )
        except (TypeError, ValueError):
            # Binary payloads are an optimization. Keep the canonical JSONB
            # value as a recovery path for partial deploys or corrupt rows,
            # without transferring it on healthy cache hits.
            fallback = queries.fetch_one(
                queries.FETCH_OVERVIEW_CACHE_JSON_FALLBACK_SQL,
                params,
            )
            if not fallback:
                return None
            row['payload_json'] = _coerce_json(fallback.get('payload_json'))
        row.pop('payload_compressed', None)
    else:
        row.pop('payload_compressed', None)
        row['payload_json'] = _coerce_json(row.get('payload_json'))
    # Pages stores its schema inside the payload rather than as a column. Lift
    # it so every overview fetcher hands back the same shape and callers can
    # check usability without knowing which surface they are on.
    if isinstance(row.get('payload_json'), dict):
        row['schema_version'] = row['payload_json'].get('schema_version')
    else:
        row['schema_version'] = None
    return row


def is_current_overview_payload_schema(schema_version):
    """Match the surface-level schema check Companies and Users already expose."""

    try:
        return int(schema_version) == OVERVIEW_PAYLOAD_SCHEMA_VERSION
    except (TypeError, ValueError):
        return False


def get_cached_overview_metadata(project_id, range_key='last_30_days', filters_hash=DEFAULT_FILTERS_HASH):
    """Freshness metadata for one Pages variant, without its payload."""

    from apps.pages import filtered_overview

    return filtered_overview.metadata_row(
        queries.FETCH_PAGES_OVERVIEW_METADATA_SQL,
        project_id,
        range_key,
        filters_hash,
    )


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

        aggregate_page_daily_metrics(
            project_id,
            start_date,
            end_date,
            timezone_name,
            use_lock=False,
            bump_revision=False,
        )
        revisions = bump_analytics_facts_revision(project_id)

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
        **revisions,
        'cache_results': cache_result['cache_results'],
        'companies_cache_results': cache_result['companies_cache_results'],
        'users_cache_results': cache_result['users_cache_results'],
    }


def _rebuild_memo_floors(project_id, range_keys):
    """
    Describe the span the planned at-risk reads will collectively cover.

    Each range is charted over its selected and its previous window, so the
    rebuild asks for eight spans that nest inside one another rather than
    sharing an edge. Their union is one span reaching from the oldest history
    the longest previous window needs up to the newest day charted, and one
    read over it answers all eight.

    Returns an empty plan when the project or its period cannot be resolved, in
    which case each read simply loads its own span as before.
    """

    from apps.pages.company_analytics import at_risk_history_floor

    if not range_keys:
        return {}
    project = get_project_info(project_id)
    if not project:
        return {}

    project_timezone = project.get('timezone') or 'UTC'
    starts = []
    ends = []
    for range_key in range_keys:
        start_date, end_date = resolve_period(project_timezone, range_key=range_key)
        previous_start, previous_end = previous_period(start_date, end_date)
        for window_start, window_end in (
            (start_date, end_date),
            (previous_start, previous_end),
        ):
            starts.append(at_risk_history_floor(window_start, window_end))
            ends.append(window_end)
    if not starts:
        return {}
    return {'at_risk_facts': (min(starts), max(ends))}


def rebuild_project_analytics_caches(project_id, *, range_keys=DEFAULT_OVERVIEW_RANGE_KEYS, include_user_details=False):
    from apps.pages.company_analytics import build_companies_overview_cache
    from apps.pages.models import (
        CompaniesOverviewCache,
        PagesOverviewCache,
        PagesScatterTooltipCache,
        UsersOverviewCache,
    )
    from apps.pages.user_analytics import build_users_overview_cache

    # Filtered variants deliberately survive a fact rebuild. Deleting them here
    # made every variant cold on each hourly refresh, and nothing rebuilds them
    # afterwards because a scheduled job cannot reconstruct a filter expression
    # from its hash. New facts are staleness, not incorrectness: readers compare
    # the stored facts revision and refresh such a row behind the response,
    # while the stored window still bounds how old a served payload can be.
    #
    # Variants for a window that has already rolled past are unreachable, so
    # they are collected here rather than left to accumulate.
    _delete_superseded_filtered_variants(project_id)

    selected_range_keys = DEFAULT_OVERVIEW_RANGE_KEYS if range_keys is None else tuple(range_keys)
    cache_results = []
    companies_cache_results = []
    users_cache_results = []

    # The ranges read the same facts, and some of those facts do not vary with
    # the range at all. Sharing them across the loop is safe because a rebuild
    # only writes cache rows, so no builder here can invalidate what an earlier
    # range read.
    #
    # The ranges arrive narrowest first, so a read that could have been shared
    # would otherwise be too narrow to reuse and be redone, wider, every range.
    # Declaring the widest bound up front lets the first read serve them all.
    with analytics_memo_scope(floors=_rebuild_memo_floors(project_id, selected_range_keys)):
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
            # Benchmark indexes hold sorted peer values and their positions for
            # every company and day of one range, so keeping all of them would
            # grow with companies x days x metrics x ranges. Nothing after this
            # range reads its own, unlike the fact reads that span the loop.
            analytics_memo.forget('benchmark_series_index')

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


def aggregate_page_daily_metrics(
    project_id,
    start_date,
    end_date,
    timezone_name=None,
    *,
    use_lock=True,
    bump_revision=True,
):
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
                bump_revision=bump_revision,
            )

    _run_daily_delete(project_id, start_date, end_date)

    common_params = [timezone_name, project_id, timezone_name, start_date, timezone_name, end_date]
    queries.execute(queries.INSERT_PAGE_DAILY_METRICS_SQL, common_params)
    queries.execute(queries.INSERT_PAGE_COMPANY_DAILY_METRICS_SQL, common_params)
    queries.execute(queries.INSERT_PAGE_USER_DAILY_METRICS_SQL, common_params)
    queries.execute(queries.INSERT_RAW_PAGE_DAILY_METRICS_SQL, common_params)
    queries.execute(queries.INSERT_RAW_PAGE_ACTION_DAILY_METRICS_SQL, common_params)
    queries.execute(queries.INSERT_PROJECT_DAILY_METRICS_SQL, common_params)
    revisions = (
        bump_analytics_facts_revision(project_id)
        if bump_revision
        else None
    )

    result = {
        'status': 'success',
        'project_id': project_id,
        'start_date': date_params[1].isoformat(),
        'end_date': date_params[2].isoformat(),
    }
    if revisions is not None:
        result.update(revisions)
    return result


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
    rounded = _round_integer_for_display(value)
    prefix = '+' if rounded > 0 else ''
    return f'{prefix}{rounded}{suffix}'


def _format_signed_decimal(value, suffix, decimal_places=1):
    rounded = _decimal_for_display(value, decimal_places)
    prefix = '+' if rounded > 0 else ''
    return f'{prefix}{rounded:.{decimal_places}f}{suffix}'


def _decimal_for_display(value, decimal_places=0):
    decimal_places = max(0, int(decimal_places or 0))
    quantum = Decimal('1').scaleb(-decimal_places)
    return Decimal(str(_to_float(value))).quantize(quantum, rounding=ROUND_HALF_UP)


def _round_integer_for_display(value):
    return int(_decimal_for_display(value))


def _format_decimal_for_display(value, decimal_places=0):
    decimal_places = max(0, int(decimal_places or 0))
    return f'{_decimal_for_display(value, decimal_places):.{decimal_places}f}'


def _format_duration(seconds):
    seconds = max(0, _round_integer_for_display(seconds))
    if seconds < 60:
        return f'{seconds}s'
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return f'{hours}h {minutes}m' if minutes else f'{hours}h'
    remaining_seconds = seconds % 60
    return f'{minutes}m {remaining_seconds:02d}s'


def _format_duration_kpi(seconds):
    return _format_duration(seconds)


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


def _daily_adoption_values_from_relative_series(row, period='current'):
    relative_change_series = (
        row.get('relative_change_series')
        if isinstance(row, dict)
        else None
    )
    if not isinstance(relative_change_series, dict):
        return []

    adoption_points = relative_change_series.get('adoption') or []
    visit_points = relative_change_series.get('visits') or []
    visit_points_by_date = {
        point.get('date'): point
        for point in visit_points
        if isinstance(point, dict) and point.get('date')
    }
    values = []
    for index, adoption_point in enumerate(adoption_points):
        if not isinstance(adoption_point, dict):
            continue
        point_date = adoption_point.get('date')
        visit_point = visit_points_by_date.get(point_date)
        if not isinstance(visit_point, dict) and index < len(visit_points):
            visit_point = visit_points[index]
        visits = (
            visit_point.get(period)
            if isinstance(visit_point, dict)
            else 0
        )
        values.append(
            _to_float(adoption_point.get(period))
            if _to_float(visits) > 0
            else None
        )
    return values


def _daily_metric_values_from_relative_series(row, metric, period='current'):
    relative_change_series = (
        row.get('relative_change_series')
        if isinstance(row, dict)
        else None
    )
    if not isinstance(relative_change_series, dict):
        return []
    return [
        _to_float(point.get(period))
        for point in relative_change_series.get(metric) or []
        if isinstance(point, dict)
    ]


def _with_compact_daily_kpi_trends(row):
    row = dict(row)
    existing = row.get('daily_kpi_trends')
    adoption = existing.get('adoption') if isinstance(existing, dict) else None
    companies = existing.get('companies') if isinstance(existing, dict) else None
    if (
        isinstance(adoption, dict)
        and isinstance(adoption.get('current'), list)
        and isinstance(adoption.get('previous'), list)
        and isinstance(companies, dict)
        and isinstance(companies.get('current'), list)
        and isinstance(companies.get('previous'), list)
    ):
        return row

    daily_kpi_trends = dict(existing) if isinstance(existing, dict) else {}
    current_adoption = _daily_adoption_values_from_relative_series(row, 'current')
    previous_adoption = _daily_adoption_values_from_relative_series(row, 'previous')
    if current_adoption or previous_adoption:
        daily_kpi_trends['adoption'] = {
            'current': current_adoption,
            'previous': previous_adoption,
        }

    current_companies = _daily_metric_values_from_relative_series(
        row,
        'companies',
        'current',
    )
    previous_companies = _daily_metric_values_from_relative_series(
        row,
        'companies',
        'previous',
    )
    if current_companies or previous_companies:
        daily_kpi_trends['companies'] = {
            'current': current_companies,
            'previous': previous_companies,
        }

    if daily_kpi_trends:
        row['daily_kpi_trends'] = daily_kpi_trends
    return row


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
    row['page_display_key'] = _page_display_key(row)
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
    slim_row.pop('_period_to_date_trends', None)
    slim_row.pop('_daily_trends', None)
    return slim_row


def _with_compact_trends(row, metrics=PRODUCT_AREA_SUMMARY_TREND_METRICS, *, prefer_daily=False):
    row = dict(row)
    existing = row.get('trends')
    if isinstance(existing, dict) and all(isinstance(existing.get(metric), list) for metric in metrics):
        return row

    period_to_date_trends = row.get('_period_to_date_trends')
    daily_trends = row.get('_daily_trends') if prefer_daily else None
    relative_change_series = row.get('relative_change_series')
    if (
        not isinstance(period_to_date_trends, dict)
        and not isinstance(daily_trends, dict)
        and not isinstance(relative_change_series, dict)
    ):
        return row

    trends = dict(existing) if isinstance(existing, dict) else {}
    for metric in metrics:
        if isinstance(trends.get(metric), list):
            continue
        values = daily_trends.get(metric) if isinstance(daily_trends, dict) else None
        if not isinstance(values, list):
            values = period_to_date_trends.get(metric) if isinstance(period_to_date_trends, dict) else None
        if not isinstance(values, list):
            points = relative_change_series.get(metric) or []
            values = [
                _to_float(point.get('current'))
                for point in points
                if isinstance(point, dict)
            ]
        if values:
            trends[metric] = [_to_float(value) for value in values]

    if trends:
        row['trends'] = trends
    return row


def _strip_for_product_area_summary(row):
    # This table's sparklines read as activity over the period rather than
    # progress towards the headline, so they use the per-day series. The
    # period-to-date series stays available to the surfaces built around it.
    return _strip_relative_change_series(
        _with_compact_trends(row, prefer_daily=True),
    )


def _strip_for_overview_row(row):
    return _strip_relative_change_series(
        _with_compact_daily_kpi_trends(
            _with_compact_trends(row, OVERVIEW_ROW_TREND_METRICS),
        ),
    )


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


def _analytics_params(project_id, start_date, end_date, *, cohort=None, **extra):
    """Named bind parameters shared by the analytical Pages queries."""

    params = {
        'project_id': project_id,
        'start_date': start_date,
        'end_date': end_date,
        **extra,
    }
    if cohort is not None:
        params['cohort'] = list(cohort)
    return params


def _analytics_sql(unfiltered_sql, filtered_sql, cohort):
    return filtered_sql if cohort is not None else unfiltered_sql


def _summary_by_area(project_id, start_date, end_date, *, cohort=None):
    rows = queries.fetch_all(
        _analytics_sql(queries.AREA_SUMMARY_SQL, queries.AREA_SUMMARY_FILTERED_SQL, cohort),
        _analytics_params(project_id, start_date, end_date, cohort=cohort),
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


def _page_product_area_identity(row):
    name = str(
        row.get('product_area_name')
        or row.get('productAreaName')
        or row.get('product_area')
        or row.get('productArea')
        or row.get('page_group')
        or ''
    ).strip()
    key = str(
        row.get('product_area_key')
        or row.get('productAreaKey')
        or row.get('product_area_id')
        or row.get('productAreaId')
        or ''
    ).strip()
    if not key:
        key = slugify(name) or 'unassigned'
    if not name:
        name = key or 'Unassigned'
    return key, name


def _page_display_key(row):
    product_area_key, _product_area_name = _page_product_area_identity(row)
    # Keep Python-generated/fallback keys aligned with PostgreSQL LOWER() in
    # PAGE_DISPLAY_* queries.  casefold() is broader (for example, ß -> ss)
    # and could otherwise merge rows which the SQL aggregates keep separate.
    normalized_area_key = str(product_area_key or 'unassigned').strip().lower() or 'unassigned'
    normalized_page_name = str(_page_display_name(row) or '').strip().lower()
    return f'{normalized_area_key}::{normalized_page_name}'


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


def _summary_by_page(project_id, start_date, end_date, *, cohort=None):
    rows = queries.fetch_all(
        _analytics_sql(queries.PAGE_SUMMARY_SQL, queries.PAGE_SUMMARY_FILTERED_SQL, cohort),
        _analytics_params(project_id, start_date, end_date, cohort=cohort),
    )
    return {_page_metric_key(row): row for row in rows}


def _summary_by_display_page(project_id, start_date, end_date, *, cohort=None):
    rows = queries.fetch_all(
        _analytics_sql(
            queries.PAGE_DISPLAY_SUMMARY_SQL,
            queries.PAGE_DISPLAY_SUMMARY_FILTERED_SQL,
            cohort,
        ),
        _analytics_params(project_id, start_date, end_date, cohort=cohort),
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


def _project_distinct_counts(project_id, start_date, end_date, *, cohort=None):
    row = queries.fetch_one(
        _analytics_sql(
            queries.PROJECT_DISTINCT_COUNTS_SQL,
            queries.PROJECT_DISTINCT_COUNTS_FILTERED_SQL,
            cohort,
        ),
        _analytics_params(project_id, start_date, end_date, cohort=cohort),
    )
    return row or {'active_companies_count': 0, 'active_users_count': 0}


def _has_period_comparison_data(rows_by_key, counts):
    return (
        bool(rows_by_key)
        or _to_int(counts.get('active_companies_count')) > 0
        or _to_int(counts.get('active_users_count')) > 0
    )


def _penetration_denominators(project_id, start_date, end_date, *, cohort=None):
    rows = queries.fetch_all(
        _analytics_sql(
            queries.PENETRATION_DENOMINATOR_SQL,
            queries.PENETRATION_DENOMINATOR_FILTERED_SQL,
            cohort,
        ),
        _analytics_params(project_id, start_date, end_date, cohort=cohort),
    )
    return {row['product_area_key']: _to_int(row['active_users_in_adopted_companies']) for row in rows}


def _page_penetration_denominators(project_id, start_date, end_date, *, cohort=None):
    rows = queries.fetch_all(
        _analytics_sql(
            queries.PAGE_PENETRATION_DENOMINATOR_SQL,
            queries.PAGE_PENETRATION_DENOMINATOR_FILTERED_SQL,
            cohort,
        ),
        _analytics_params(project_id, start_date, end_date, cohort=cohort),
    )
    return {_page_metric_key(row): _to_int(row['active_users_in_adopted_companies']) for row in rows}


def _display_page_penetration_denominators(project_id, start_date, end_date, *, cohort=None):
    rows = queries.fetch_all(
        _analytics_sql(
            queries.PAGE_DISPLAY_PENETRATION_DENOMINATOR_SQL,
            queries.PAGE_DISPLAY_PENETRATION_DENOMINATOR_FILTERED_SQL,
            cohort,
        ),
        _analytics_params(project_id, start_date, end_date, cohort=cohort),
    )
    return {
        row['page_display_key']: _to_int(row['active_users_in_adopted_companies'])
        for row in rows
    }


def _daily_area_rows(project_id, start_date, end_date, *, cohort=None):
    rows = queries.fetch_all(
        _analytics_sql(
            queries.DAILY_AREA_METRICS_SQL,
            queries.DAILY_AREA_METRICS_FILTERED_SQL,
            cohort,
        ),
        _analytics_params(project_id, start_date, end_date, cohort=cohort),
    )
    data = {}
    for row in rows:
        data[(row['date'], row['product_area_key'])] = row
    return data


def _daily_page_rows(project_id, start_date, end_date, *, cohort=None):
    rows = queries.fetch_all(
        _analytics_sql(
            queries.DAILY_PAGE_METRICS_SQL,
            queries.DAILY_PAGE_METRICS_FILTERED_SQL,
            cohort,
        ),
        _analytics_params(project_id, start_date, end_date, cohort=cohort),
    )
    data = {}
    for row in rows:
        data[(row['date'], _page_metric_key(row))] = row
    return data


def _daily_display_page_rows(project_id, start_date, end_date, *, cohort=None):
    rows = queries.fetch_all(
        _analytics_sql(
            queries.DAILY_PAGE_DISPLAY_METRICS_SQL,
            queries.DAILY_PAGE_DISPLAY_METRICS_FILTERED_SQL,
            cohort,
        ),
        _analytics_params(project_id, start_date, end_date, cohort=cohort),
    )
    return {
        (row['date'], row['page_display_key']): row
        for row in rows
    }


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


def _period_to_date_identity_events(project_id, start_date, end_date, grain, *, cohort=None):
    rows = queries.fetch_all(
        queries.cumulative_identity_first_seen_sql(grain, filtered=cohort is not None),
        _analytics_params(project_id, start_date, end_date, cohort=cohort),
    )
    events = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for row in rows:
        kind = str(row.get('kind') or '')
        row_key = str(row.get('row_key') or '')
        first_date = row.get('first_date')
        if isinstance(first_date, str):
            try:
                first_date = date.fromisoformat(first_date)
            except ValueError:
                continue
        if not kind or not isinstance(first_date, date):
            continue
        identities_count = row.get('identities_count')
        events[kind][row_key][first_date] += max(
            0,
            1 if identities_count is None else _to_int(identities_count),
        )
    return events


def _running_identity_counts(events_by_date, dates):
    total = 0
    values = []
    for current_date in dates:
        total += _to_int((events_by_date or {}).get(current_date))
        values.append(total)
    return values


def _attach_period_to_date_trends(
    rows,
    project_id,
    start_date,
    end_date,
    daily_rows,
    *,
    grain,
    cohort=None,
):
    rows = list(rows or [])
    if not rows:
        return rows

    dates = list(_date_range(start_date, end_date))
    identity_events = _period_to_date_identity_events(
        project_id,
        start_date,
        end_date,
        grain,
        cohort=cohort,
    )
    project_companies = _running_identity_counts(
        identity_events.get('project_company', {}).get('', {}),
        dates,
    )

    for row in rows:
        if grain == 'product_area':
            row_key = str(row.get('row_key') or row.get('product_area_key') or 'unassigned')
        elif grain == 'display_page':
            row_key = str(row.get('row_key') or row.get('page_display_key') or _page_display_key(row))
        else:
            row_key = str(row.get('row_key') or _page_metric_key(row))
        company_counts = _running_identity_counts(
            identity_events.get('company', {}).get(row_key, {}),
            dates,
        )
        user_counts = _running_identity_counts(
            identity_events.get('user', {}).get(row_key, {}),
            dates,
        )
        penetration_denominators = _running_identity_counts(
            identity_events.get('penetration', {}).get(row_key, {}),
            dates,
        )
        running_visits = 0
        running_engaged = 0
        running_clicks = 0
        running_visits_with_click = 0
        trends = {
            metric: []
            for metric in PAGE_DETAIL_TREND_METRICS
        }
        # Read straight off the daily rows rather than differencing the running
        # totals. A running distinct count only moves when an identity is seen
        # for the first time, so its day-over-day difference is "newly seen",
        # not "active that day" — the two disagree for every returning company.
        daily_trends = {
            metric: []
            for metric in PRODUCT_AREA_SUMMARY_TREND_METRICS
        }

        for index, current_date in enumerate(dates):
            daily_row = daily_rows.get((current_date, row_key), {}) if isinstance(daily_rows, dict) else {}
            running_visits += _to_int(daily_row.get('visits_count'))
            running_engaged += _to_int(daily_row.get('engaged_seconds'))
            running_clicks += _to_int(daily_row.get('click_count'))
            running_visits_with_click += _to_int(daily_row.get('visits_with_click_count'))
            companies = company_counts[index] if index < len(company_counts) else 0
            users = user_counts[index] if index < len(user_counts) else 0
            active_companies = project_companies[index] if index < len(project_companies) else 0
            penetration_denominator = (
                penetration_denominators[index]
                if index < len(penetration_denominators)
                else 0
            )

            trends['companies'].append(companies)
            trends['adoption'].append(_bounded_pct(companies, active_companies))
            trends['users'].append(users)
            trends['penetration'].append(_pct(users, penetration_denominator))
            trends['visits'].append(running_visits)
            trends['engaged'].append(running_engaged)
            trends['avg_visit'].append(_ratio(running_engaged, running_visits))
            trends['interaction'].append(_pct(running_visits_with_click, running_visits))
            trends['clicks_per_visit'].append(_ratio(running_clicks, running_visits))

            daily_companies = _to_int(daily_row.get('companies_count_daily'))
            daily_trends['companies'].append(daily_companies)
            daily_trends['adoption'].append(
                _bounded_pct(daily_companies, _to_int(daily_row.get('active_companies_count'))),
            )
            daily_trends['users'].append(_to_int(daily_row.get('users_count_daily')))
            daily_trends['engaged'].append(_to_int(daily_row.get('engaged_seconds')))

        row['_period_to_date_trends'] = trends
        row['_daily_trends'] = daily_trends
        row['trend_values'] = list(trends['companies'])

    return rows


def _build_change_rows(
    project_id,
    start_date,
    end_date,
    previous_start,
    previous_end,
    *,
    grain='page',
    cohort=None,
    include_previous_only=False,
):
    if grain == 'product_area':
        current = _summary_by_area(project_id, start_date, end_date, cohort=cohort)
        previous = _summary_by_area(project_id, previous_start, previous_end, cohort=cohort)
        current_penetration_denominators = _penetration_denominators(project_id, start_date, end_date, cohort=cohort)
        previous_penetration_denominators = _penetration_denominators(project_id, previous_start, previous_end, cohort=cohort)
        daily_current = _daily_area_rows(project_id, start_date, end_date, cohort=cohort)
        daily_previous = _daily_area_rows(project_id, previous_start, previous_end, cohort=cohort)
    elif grain == 'display_page':
        current = _summary_by_display_page(project_id, start_date, end_date, cohort=cohort)
        previous = _summary_by_display_page(project_id, previous_start, previous_end, cohort=cohort)
        current_penetration_denominators = _display_page_penetration_denominators(project_id, start_date, end_date, cohort=cohort)
        previous_penetration_denominators = _display_page_penetration_denominators(project_id, previous_start, previous_end, cohort=cohort)
        daily_current = _daily_display_page_rows(project_id, start_date, end_date, cohort=cohort)
        daily_previous = _daily_display_page_rows(project_id, previous_start, previous_end, cohort=cohort)
    else:
        current = _summary_by_page(project_id, start_date, end_date, cohort=cohort)
        previous = _summary_by_page(project_id, previous_start, previous_end, cohort=cohort)
        current_penetration_denominators = _page_penetration_denominators(project_id, start_date, end_date, cohort=cohort)
        previous_penetration_denominators = _page_penetration_denominators(project_id, previous_start, previous_end, cohort=cohort)
        daily_current = _daily_page_rows(project_id, start_date, end_date, cohort=cohort)
        daily_previous = _daily_page_rows(project_id, previous_start, previous_end, cohort=cohort)

    current_counts = _project_distinct_counts(project_id, start_date, end_date, cohort=cohort)
    previous_counts = _project_distinct_counts(project_id, previous_start, previous_end, cohort=cohort)
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

    row_keys = list(current)
    if include_previous_only:
        row_keys.extend(row_key for row_key in previous if row_key not in current)

    for row_key in row_keys:
        row = current.get(row_key, {})
        previous_row = previous.get(row_key, {})
        identity_row = row or previous_row
        product_area_key = identity_row.get('product_area_key') or row_key or 'unassigned'
        product_area_name = identity_row.get('product_area_name') or product_area_key
        page_name = identity_row.get('page_name') or product_area_name
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
            'product_area_id': identity_row.get('product_area_id'),
            'product_area_key': product_area_key,
            'product_area_name': product_area_name,
            'page_rule_id': identity_row.get('page_rule_id'),
            'page_rule_ids': identity_row.get('page_rule_ids') or _page_rule_aliases(identity_row),
            'page_name': page_name,
            'page_group': product_area_name,
            'page_count': _to_int(identity_row.get('page_count') or 1),
            'comparison_available': comparison_available,
            'comparisonAvailable': comparison_available,
            'companies_count': companies,
            'previous_companies_count': previous_companies,
            'adoption_pct': adoption,
            'previous_adoption_pct': previous_adoption,
            'users_count': users,
            'penetration_pct': penetration,
            'visits_count': visits,
            'previous_visits_count': previous_visits,
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
        if row_key not in current:
            prepared[-1]['_previous_only'] = True

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

    _attach_period_to_date_trends(
        prepared,
        project_id,
        start_date,
        end_date,
        daily_current,
        grain=grain,
        cohort=cohort,
    )
    prepared.sort(key=lambda item: (-item['visits_count'], item['page_name']))
    return prepared, current_counts, previous_counts


def _period_to_date_trend_values(row, metric):
    if not isinstance(row, dict):
        return []

    period_to_date = row.get('_period_to_date_trends')
    if isinstance(period_to_date, dict) and isinstance(period_to_date.get(metric), list):
        return list(period_to_date.get(metric) or [])

    compact = row.get('trends')
    if isinstance(compact, dict) and isinstance(compact.get(metric), list):
        return [_to_float(value) for value in compact.get(metric) or []]

    return _trend_values(row, metric)


def _daily_adopted_pages_trend(rows, period='current'):
    trends = [
        _compact_daily_metric_values(row, 'companies', period)
        for row in rows
    ]
    length = max((len(trend) for trend in trends), default=0)
    return [
        sum(
            1
            for trend in trends
            if index < len(trend) and _to_float(trend[index]) > 0
        )
        for index in range(length)
    ]


def _daily_trend_dates(rows, metric):
    dates = []
    for row in rows:
        for point in row['relative_change_series'].get(metric, []):
            point_date = point.get('date')
            if point_date and point_date not in dates:
                dates.append(point_date)
    return dates


def _compact_daily_adoption_values(row, period='current'):
    compact = row.get('daily_kpi_trends') if isinstance(row, dict) else None
    adoption = compact.get('adoption') if isinstance(compact, dict) else None
    values = adoption.get(period) if isinstance(adoption, dict) else None
    if isinstance(values, list):
        return [
            None if value is None else _to_float(value)
            for value in values
        ]
    return _daily_adoption_values_from_relative_series(row, period)


def _compact_daily_metric_values(row, metric, period='current'):
    compact = row.get('daily_kpi_trends') if isinstance(row, dict) else None
    metric_values = compact.get(metric) if isinstance(compact, dict) else None
    values = metric_values.get(period) if isinstance(metric_values, dict) else None
    if isinstance(values, list):
        return [_to_float(value) for value in values]
    return _daily_metric_values_from_relative_series(row, metric, period)


def _daily_average_adoption_trend(rows, period='current'):
    row_values = [
        _compact_daily_adoption_values(row, period)
        for row in rows or []
    ]
    length = max((len(values) for values in row_values), default=0)
    trend = []
    for index in range(length):
        eligible_values = [
            _to_float(values[index])
            for values in row_values
            if index < len(values) and values[index] is not None
        ]
        trend.append(
            round(sum(eligible_values) / len(eligible_values), 1)
            if eligible_values
            else 0
        )
    return trend


def _average_trend_value(values, decimal_places=1):
    values = [_to_float(value) for value in values or []]
    if not values:
        return 0
    return round(sum(values) / len(values), decimal_places)


def _daily_additive_trend_values(row, metric):
    cumulative_values = _period_to_date_trend_values(row, metric)
    daily_values = []
    previous_value = 0
    for cumulative_value in cumulative_values:
        cumulative_value = _to_float(cumulative_value)
        daily_values.append(max(0, cumulative_value - previous_value))
        previous_value = cumulative_value
    return daily_values


def _growth_pct(current_companies, previous_companies):
    previous_companies = _to_int(previous_companies)
    if previous_companies <= 0:
        return None
    return (
        (_to_int(current_companies) - previous_companies)
        / previous_companies
        * 100
    )


def _rounded_growth_pct(current_companies, previous_companies):
    growth = _growth_pct(current_companies, previous_companies)
    return None if growth is None else _round_integer_for_display(growth)


PREVIOUS_PERIOD_BAR_LABEL = 'Previous period'
SELECTED_PERIOD_BAR_LABEL = 'Selected period'


def _build_fastest_growing_kpi(
    fastest,
    fastest_is_new,
    previous_companies,
    *,
    comparison_available,
):
    kpi = {
        'label': 'Fastest-growing',
        'value': fastest['page_name'] if fastest else 'No data',
        'delta': '',
        'delta_value': 0,
        'product_area_key': fastest.get('product_area_key') if fastest else '',
        'page_rule_id': fastest.get('page_rule_id') if fastest else None,
    }
    if not fastest:
        if comparison_available:
            kpi['context_line'] = 'No qualifying page growth'
        else:
            kpi['delta'] = 'n/a'
            kpi['context_line'] = 'Previous-period comparison unavailable'
        return kpi

    current_companies = _to_int(fastest.get('companies_count'))
    previous_companies = _to_int(previous_companies)
    is_new = fastest_is_new or (
        previous_companies <= 0
        and current_companies > 0
    )
    if not comparison_available:
        kpi['delta'] = 'n/a'
        kpi['context_line'] = 'Previous-period comparison unavailable'
        return kpi

    if is_new:
        kpi['delta'] = 'New companies'
        kpi['delta_value'] = 1
        kpi['context_line'] = 'New in selected period; no previous-period baseline'
        return kpi

    displayed_growth = _rounded_growth_pct(
        current_companies,
        previous_companies,
    )
    # Two bars rather than a sparkline: the card answers "how many distinct
    # companies used this page, before and now", so the series is the pair of
    # period totals and nothing in between.
    kpi.update({
        'trend_values': [previous_companies, current_companies],
        'trend_labels': [PREVIOUS_PERIOD_BAR_LABEL, SELECTED_PERIOD_BAR_LABEL],
        'trend_format': 'number',
        'trend_label': 'Companies',
        'trend_scope': 'period_comparison',
        'trend_delta_value': displayed_growth,
    })
    kpi['delta'] = _format_signed(displayed_growth, '%') + ' companies'
    kpi['delta_value'] = displayed_growth
    return kpi


def _select_fastest_growing_row(rows, previous_companies_for_row):
    fastest = None
    fastest_growth = -math.inf
    strongest_new = None

    for row in rows or []:
        previous_companies = _to_int(previous_companies_for_row(row))
        current_companies = _to_int(row.get('companies_count'))
        if previous_companies < 3 and current_companies < 5:
            continue
        if previous_companies == 0 and current_companies > 0:
            if strongest_new is None or current_companies > _to_int(strongest_new.get('companies_count')):
                strongest_new = row
            continue

        growth = _growth_pct(current_companies, previous_companies)
        if growth is not None and growth > fastest_growth:
            fastest = row
            fastest_growth = growth

    if fastest is not None:
        return fastest, fastest_growth, False
    if strongest_new is not None:
        return strongest_new, None, True
    return None, None, False


def _build_kpis(rows, previous_rows_by_key, current_active_companies, previous_active_companies, *, comparison_available=True):
    current_rows = [
        row
        for row in rows
        if not row.get('_previous_only')
    ]
    daily_adopted_pages_trend = _daily_adopted_pages_trend(rows)
    previous_daily_adopted_pages_trend = _daily_adopted_pages_trend(
        rows,
        'previous',
    )
    average_daily_adopted_pages = _average_trend_value(
        daily_adopted_pages_trend,
    )
    previous_average_daily_adopted_pages = _average_trend_value(
        previous_daily_adopted_pages_trend,
    )
    daily_adoption_trend = _daily_average_adoption_trend(rows)
    previous_daily_adoption_trend = _daily_average_adoption_trend(rows, 'previous')
    average_daily_adoption = _average_trend_value(daily_adoption_trend)
    previous_average_daily_adoption = _average_trend_value(previous_daily_adoption_trend)
    most_used = max(current_rows, key=lambda row: row['engaged_seconds'], default=None)
    most_used_daily_engaged = (
        _daily_additive_trend_values(most_used, 'engaged')
        if most_used
        else []
    )
    most_used_average_daily_engaged = _average_trend_value(
        most_used_daily_engaged,
        decimal_places=2,
    )

    def previous_companies_for_row(row):
        previous_row = previous_rows_by_key.get(row.get('row_key') or row.get('product_area_key'), {})
        return previous_row.get('companies_count')

    fastest, _fastest_growth, fastest_is_new = _select_fastest_growing_row(
        current_rows,
        previous_companies_for_row,
    )
    fastest_kpi = _build_fastest_growing_kpi(
        fastest,
        fastest_is_new,
        previous_companies_for_row(fastest) if fastest else 0,
        comparison_available=comparison_available,
    )

    average_daily_adopted_pages_delta = round(
        average_daily_adopted_pages - previous_average_daily_adopted_pages,
        1,
    )
    average_daily_adoption_delta = round(
        average_daily_adoption - previous_average_daily_adoption,
        1,
    )
    comparison_delta_label = None if comparison_available else 'n/a'

    return [
        {
            'label': 'Avg daily adopted pages',
            'value': _format_decimal_for_display(average_daily_adopted_pages, 1),
            'delta': comparison_delta_label or (
                f'{_format_signed_decimal(average_daily_adopted_pages_delta, "", 1)} vs previous'
            ),
            'delta_value': average_daily_adopted_pages_delta if comparison_available else 0,
            'trend_values': daily_adopted_pages_trend,
            'trend_labels': _daily_trend_dates(rows, 'companies'),
            'trend_format': 'number',
            'trend_label': 'Adopted pages',
            'trend_scope': 'daily',
        },
        {
            'label': 'Avg daily adoption',
            'value': f'{_round_integer_for_display(average_daily_adoption)}%',
            'delta': comparison_delta_label or _format_signed(round(average_daily_adoption_delta), ' pp'),
            'delta_value': round(average_daily_adoption_delta) if comparison_available else 0,
            'trend_values': daily_adoption_trend,
            'trend_labels': _daily_trend_dates(rows, 'adoption'),
            'trend_format': 'percent',
            'trend_label': 'Average page adoption',
            'trend_scope': 'daily',
        },
        {
            'label': 'Most used page',
            'value': most_used['page_name'] if most_used else 'No data',
            'delta': f'{_format_duration_kpi(most_used_average_daily_engaged)} avg/day' if most_used else '',
            'delta_value': 0,
            'product_area_key': most_used['product_area_key'] if most_used else '',
            'page_rule_id': most_used.get('page_rule_id') if most_used else None,
            'trend_values': most_used_daily_engaged,
            'trend_labels': [point['date'] for point in most_used['relative_change_series'].get('engaged', [])] if most_used else [],
            'trend_format': 'duration',
            'trend_label': 'Daily engaged',
            'trend_scope': 'daily',
        },
        fastest_kpi,
    ]


def _build_series(rows, metric):
    source_metric = 'visits' if metric == 'visits_count' else 'engaged'
    grouped_rows = {}
    for row in rows or []:
        key = _page_display_key(row)
        product_area_key, product_area_name = _page_product_area_identity(row)
        current_total = _to_float(row.get(metric))
        group = grouped_rows.setdefault(
            key,
            {
                'page_display_key': key,
                'page_rule_id': row.get('page_rule_id') or _page_rule_id(row),
                'page_rule_ids': [],
                'page_name': _page_display_name(row),
                'page_group': _page_display_group(row),
                'product_area_key': product_area_key,
                'product_area_name': product_area_name,
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
            group['product_area_key'] = product_area_key
            group['product_area_name'] = product_area_name

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
            'page_display_key': row.get('page_display_key'),
            'page_rule_id': row.get('page_rule_id'),
            'page_rule_ids': row.get('page_rule_ids') or [],
            'page_name': row.get('page_name'),
            'page_group': row.get('page_group'),
            'product_area_key': row.get('product_area_key'),
            'product_area_name': row.get('product_area_name'),
            'total': _to_int(round(_to_float(row.get('total')))),
            'values': [_to_float(row.get('points', {}).get(label)) for label in labels],
        })
    return {'granularity': 'day', 'labels': labels, 'series': series}


def _product_area_identity(item):
    item = item if isinstance(item, dict) else {'name': item}
    name = (
        item.get('product_area_name')
        or item.get('productAreaName')
        or item.get('product_area')
        or item.get('productArea')
        or item.get('page_group')
        or item.get('name')
        or ''
    )
    key = (
        item.get('product_area_key')
        or item.get('productAreaKey')
        or item.get('product_area_id')
        or item.get('productAreaId')
        or item.get('key')
        or item.get('slug')
        or item.get('id')
        or ''
    )
    key = str(key or '').strip()
    name = str(name or '').strip()
    if not key:
        key = slugify(name) or 'unassigned'
    if not name:
        name = key or 'Unassigned'
    return key, name


def _product_area_payload_item(item, color_lookup=None, index=0):
    source = dict(item) if isinstance(item, dict) else {'name': item}
    key, name = _product_area_identity(source)
    color = product_area_color_from_lookup(
        color_lookup,
        {
            **source,
            'key': key,
            'name': name,
        },
        index,
        prefer_explicit=True,
    )
    return {
        **source,
        'key': key,
        'name': name,
        'product_area_key': key,
        'product_area_name': name,
        'color': color,
        'product_area_color': color,
        'productAreaColor': color,
    }


def _project_product_area_options(project_id, observed_areas=None, *, include_unobserved=False):
    """Resolve persisted colors without widening an observed-area option list by default."""
    database_areas = list(
        ProductArea.objects
        .filter(project_id=project_id)
        .values('id', 'slug', 'name', 'short_name', 'color')
        .order_by('id')
    )
    database_by_key = {
        str(area.get('slug') or '').strip().lower(): area
        for area in database_areas
        if str(area.get('slug') or '').strip()
    }
    database_by_name = {
        str(area.get('name') or '').strip().lower(): area
        for area in database_areas
        if str(area.get('name') or '').strip()
    }
    candidates = []
    seen_database_ids = set()
    seen_identities = set()

    def add(area, database_area=None):
        key, name = _product_area_identity(area)
        identity = (key.lower(), name.lower())
        if identity in seen_identities:
            return
        seen_identities.add(identity)

        database_area = database_area or database_by_key.get(key.lower()) or database_by_name.get(name.lower())
        if database_area:
            seen_database_ids.add(database_area.get('id'))
        candidates.append({
            'key': database_area.get('slug') if database_area else key,
            'name': database_area.get('name') if database_area else name,
            'shortName': (database_area.get('short_name') or database_area.get('name')) if database_area else name,
            # A persisted value wins over any serialized or computed color on the observed row.
            'color': (database_area.get('color') or '') if database_area else explicit_product_area_color(area),
        })

    for area in observed_areas or []:
        add(area)
    if include_unobserved:
        for database_area in database_areas:
            if database_area.get('id') not in seen_database_ids:
                add(database_area, database_area)

    resolved = resolve_product_area_colors(candidates, prefer_explicit=True)
    color_lookup = build_product_area_color_lookup(resolved, prefer_explicit=True)
    return [
        _product_area_payload_item(area, color_lookup, index)
        for index, area in enumerate(resolved)
    ]


def apply_page_detail_product_area_colors(project_id, payload):
    """Overlay live ProductArea colors onto a cached page-detail flow payload."""
    if not isinstance(payload, dict):
        return payload

    page = dict(payload.get('page') or {})
    flow = dict(payload.get('flow') or {})
    previous_pages = [dict(item) for item in flow.get('previousPages') or [] if isinstance(item, dict)]
    next_pages = [dict(item) for item in flow.get('nextPages') or [] if isinstance(item, dict)]
    flow_links = [dict(item) for item in flow.get('links') or [] if isinstance(item, dict)]
    sankey = dict(flow.get('sankey') or {})
    sankey_links = [dict(item) for item in sankey.get('links') or [] if isinstance(item, dict)]
    sankey_nodes = [dict(item) for item in sankey.get('nodes') or [] if isinstance(item, dict)]
    observed_areas = []

    def area_identity(key, name):
        return {
            'key': str(key or '').strip(),
            'name': str(name or '').strip() or 'Unassigned',
        }

    def page_area(item):
        return area_identity(
            item.get('productAreaKey')
            or item.get('product_area_key')
            or item.get('productAreaId'),
            item.get('productAreaName')
            or item.get('product_area_name')
            or item.get('productArea')
            or item.get('product_area'),
        )

    def link_area(link, prefix):
        camel_prefix = f'{prefix}ProductArea'
        return area_identity(
            link.get(f'{prefix}_product_area_key') or link.get(f'{camel_prefix}Key'),
            link.get(f'{prefix}_product_area_name')
            or link.get(f'{camel_prefix}Name')
            or link.get(f'{prefix}_product_area')
            or link.get(camel_prefix),
        )

    observed_areas.append(page_area(page))
    for item in [*previous_pages, *next_pages]:
        observed_areas.append(page_area(item))
    for link in [*flow_links, *sankey_links]:
        observed_areas.append(link_area(link, 'source'))
        observed_areas.append(link_area(link, 'target'))

    product_areas = _project_product_area_options(project_id, observed_areas)
    color_lookup = build_product_area_color_lookup(product_areas, prefer_explicit=True)
    area_by_page_name = {}

    def resolved_area(area, index):
        key, name = _product_area_identity(area)
        color = product_area_color_from_lookup(
            color_lookup,
            {'key': key, 'name': name},
            index,
            prefer_explicit=True,
        )
        return {'key': key, 'name': name, 'color': color}

    def decorate_link(link, index):
        decorated = dict(link)
        for offset, prefix in enumerate(('source', 'target')):
            area = resolved_area(link_area(link, prefix), index + offset)
            decorated[f'{prefix}_product_area_key'] = area['key']
            decorated[f'{prefix}_product_area_name'] = area['name']
            decorated[f'{prefix}_product_area'] = area['name']
            decorated[f'{prefix}_product_area_color'] = area['color']
            page_name = str(link.get(prefix) or '').strip()
            if page_name:
                area_by_page_name.setdefault(page_name.casefold(), area)
        return decorated

    flow_links = [decorate_link(link, index) for index, link in enumerate(flow_links)]
    sankey_links = [decorate_link(link, index) for index, link in enumerate(sankey_links)]

    current_area = resolved_area(page_area(page), 0)
    page.update({
        'productAreaId': current_area['key'],
        'productAreaName': current_area['name'],
        'productAreaColor': current_area['color'],
    })
    current_page_name = str(page.get('displayName') or page.get('pageName') or '').strip()
    if current_page_name:
        area_by_page_name[current_page_name.casefold()] = current_area

    def decorate_flow_page(item, index):
        decorated = dict(item)
        page_name = str(item.get('pageName') or item.get('name') or '').strip()
        item_area = page_area(item)
        if item_area['name'] == 'Unassigned' and page_name:
            item_area = area_by_page_name.get(page_name.casefold(), item_area)
        area = resolved_area(item_area, index)
        decorated.update({
            'productAreaKey': area['key'],
            'productAreaName': area['name'],
            'productAreaColor': area['color'],
        })
        return decorated

    previous_pages = [decorate_flow_page(item, index) for index, item in enumerate(previous_pages)]
    next_pages = [decorate_flow_page(item, index) for index, item in enumerate(next_pages)]

    decorated_nodes = []
    for index, node in enumerate(sankey_nodes):
        decorated = dict(node)
        node_name = str(node.get('name') or '').strip()
        node_area = page_area(node)
        if node_area['name'] == 'Unassigned' and node_name:
            node_area = area_by_page_name.get(node_name.casefold(), node_area)
        area = resolved_area(node_area, index)
        decorated.update({
            'product_area_key': area['key'],
            'product_area_name': area['name'],
            'product_area_color': area['color'],
            'color': area['color'],
        })
        decorated_nodes.append(decorated)

    flow.update({
        'previousPages': previous_pages,
        'nextPages': next_pages,
        'links': flow_links,
        'sankey': {
            **sankey,
            'nodes': decorated_nodes,
            'links': sankey_links,
        },
    })
    return {
        **payload,
        'page': page,
        'productAreas': product_areas,
        'flow': flow,
    }


def _build_treemap(rows, active_companies_total=None, color_lookup=None):
    groups = {}
    total = 0
    active_companies_total = _to_int(active_companies_total)
    for row_index, row in enumerate(rows):
        engaged_seconds = _to_int(row.get('engaged_seconds'))
        if engaged_seconds <= 0:
            continue

        product_area_key, product_area_name = _product_area_identity(row)
        page_group = row.get('page_group') or product_area_name or 'Unassigned'
        color = product_area_color_from_lookup(
            color_lookup,
            {
                **row,
                'key': product_area_key,
                'name': product_area_name,
            },
            row_index,
            prefer_explicit=True,
        )
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
            product_area_key,
            {
                'name': page_group,
                'page_group': page_group,
                'product_area_key': product_area_key,
                'product_area_name': product_area_name,
                'color': color,
                'product_area_color': color,
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
            'product_area_key': product_area_key,
            'product_area_name': product_area_name,
            'color': color,
            'product_area_color': color,
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


def _build_sankey(project_id, timezone_name, start_date, end_date, color_lookup=None, *, cohort=None):
    links = queries.fetch_all(
        _analytics_sql(queries.SANKEY_SQL, queries.SANKEY_FILTERED_SQL, cohort),
        _analytics_params(
            project_id,
            start_date,
            end_date,
            cohort=cohort,
            timezone=timezone_name,
        ),
    )
    nodes = {}
    payload_links = []
    for index, link in enumerate(links):
        source = link['from_page_key']
        target = link['to_page_key']
        source_label = link['from_page_name'] or source
        target_label = link['to_page_name'] or target
        source_area = {
            'key': link.get('from_product_area_key') or 'unassigned',
            'name': link.get('from_product_area_name') or link.get('from_product_area_key') or 'Unassigned',
        }
        target_area = {
            'key': link.get('to_product_area_key') or 'unassigned',
            'name': link.get('to_product_area_name') or link.get('to_product_area_key') or 'Unassigned',
        }
        source_color = product_area_color_from_lookup(
            color_lookup,
            source_area,
            index,
            prefer_explicit=True,
        )
        target_color = product_area_color_from_lookup(
            color_lookup,
            target_area,
            index + 1,
            prefer_explicit=True,
        )
        nodes[source] = {
            'name': source,
            'label': source_label,
            'page_key': link.get('from_page_key'),
            'product_area_key': link.get('from_product_area_key'),
            'product_area_name': link.get('from_product_area_name'),
            'color': source_color,
            'product_area_color': source_color,
        }
        nodes[target] = {
            'name': target,
            'label': target_label,
            'page_key': link.get('to_page_key'),
            'product_area_key': link.get('to_product_area_key'),
            'product_area_name': link.get('to_product_area_name'),
            'color': target_color,
            'product_area_color': target_color,
        }
        payload_links.append({
            'source': source,
            'target': target,
            'sourceLabel': source_label,
            'targetLabel': target_label,
            'source_page_key': link.get('from_page_key'),
            'target_page_key': link.get('to_page_key'),
            'source_product_area_key': source_area['key'],
            'source_product_area_name': source_area['name'],
            'source_product_area': link.get('from_product_area_name') or link.get('from_product_area_key'),
            'source_product_area_color': source_color,
            'target_product_area_key': target_area['key'],
            'target_product_area_name': target_area['name'],
            'target_product_area': link.get('to_product_area_name') or link.get('to_product_area_key'),
            'target_product_area_color': target_color,
            'value': _to_int(link['transition_count']),
            'sessions_count': _to_int(link['sessions_count']),
            'companies_count': _to_int(link['companies_count']),
        })
    return {'nodes': list(nodes.values()), 'links': payload_links}


def _build_two_way_movement(project_id, timezone_name, start_date, end_date, *, cohort=None):
    rows = queries.fetch_all(
        _analytics_sql(queries.TWO_WAY_MOVEMENT_SQL, queries.TWO_WAY_MOVEMENT_FILTERED_SQL, cohort),
        _analytics_params(
            project_id,
            start_date,
            end_date,
            cohort=cohort,
            timezone=timezone_name,
        ),
    )
    payload_rows = []
    for row in rows:
        low_to_high = _to_int(row.get('low_to_high'))
        high_to_low = _to_int(row.get('high_to_low'))
        low_first = low_to_high >= high_to_low
        page_a_prefix = 'page_low' if low_first else 'page_high'
        page_b_prefix = 'page_high' if low_first else 'page_low'
        reciprocity_pct = round(_to_float(row.get('reciprocity_pct')), 1)
        label = 'Strong' if reciprocity_pct >= 70 else ('Moderate' if reciprocity_pct >= 40 else 'Mostly one-way')
        payload_rows.append({
            'page_a_id': str(row.get(f'{page_a_prefix}_id')),
            'page_a_name': row.get(f'{page_a_prefix}_name') or 'Unnamed page',
            'page_a_product_area_name': row.get(f'{page_a_prefix}_product_area_name') or 'Unassigned',
            'page_b_id': str(row.get(f'{page_b_prefix}_id')),
            'page_b_name': row.get(f'{page_b_prefix}_name') or 'Unnamed page',
            'page_b_product_area_name': row.get(f'{page_b_prefix}_product_area_name') or 'Unassigned',
            'a_to_b': low_to_high if low_first else high_to_low,
            'b_to_a': high_to_low if low_first else low_to_high,
            'total_transitions': _to_int(row.get('total_transitions')),
            'reciprocal_volume': _to_int(row.get('reciprocal_volume')),
            'reciprocity_pct': reciprocity_pct,
            'direction_balance': round(_to_float(row.get('direction_balance')), 3),
            'sessions_count': _to_int(row.get('sessions_count')),
            'companies_count': _to_int(row.get('companies_count')),
            'users_count': _to_int(row.get('users_count')),
            'label': label,
        })
    return {'rows': payload_rows, 'limit': 10, 'total_pairs': len(payload_rows)}


def _build_top_actions(
    project_id,
    start_date,
    end_date,
    previous_start,
    previous_end,
    *,
    cohort=None,
    timezone_name='UTC',
):
    if cohort is None:
        rows = queries.fetch_all(
            queries.TOP_ACTIONS_SQL,
            [
                project_id, start_date, end_date,
                project_id, previous_start, previous_end,
                project_id, start_date, end_date,
                project_id, previous_start, previous_end,
            ],
        )
    else:
        rows = queries.fetch_all(
            queries.TOP_ACTIONS_FILTERED_SQL,
            _analytics_params(
                project_id,
                start_date,
                end_date,
                cohort=cohort,
                timezone=timezone_name,
                previous_start_date=previous_start,
                previous_end_date=previous_end,
            ),
        )
    pages = {}
    for row in rows:
        page_key = row.get('page_key') or row.get('url_normalized')
        page = pages.setdefault(
            page_key,
            {
                'page_key': page_key,
                'product_area_key': row.get('product_area_key') or '',
                'product_area_name': row.get('product_area_name') or row.get('page_group') or '',
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
                'clicks_change_label': action.get('clicks_delta_label'),
                'visits_pct': _to_float(action.get('visits_pct')),
                'visits_change_pp': _to_float(action.get('visits_pct_delta_pp')),
                'visits_change_label': action.get('visits_pct_delta_label'),
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
            'page_name': page.get('page_label') or page.get('url_normalized') or 'Unassigned',
            'product_area_key': page.get('product_area_key') or '',
            'product_area_name': page.get('product_area_name') or page.get('page_group') or 'Unassigned',
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


def _build_scatter(project_id, start_date, end_date, color_lookup=None, *, cohort=None):
    rows = queries.fetch_all(
        _analytics_sql(queries.SCATTER_SQL, queries.SCATTER_FILTERED_SQL, cohort),
        _analytics_params(project_id, start_date, end_date, cohort=cohort),
    )
    groups = {}
    for index, row in enumerate(rows):
        active_users = round(_to_float(row['active_users']), 2)
        total_engaged = _to_int(row['total_engaged_seconds'])
        color = product_area_color_from_lookup(
            color_lookup,
            {
                'key': row.get('product_area_key') or 'unassigned',
                'name': row.get('product_area_name') or row.get('product_area_key') or 'Unassigned',
            },
            index,
            prefer_explicit=True,
        )
        group = groups.setdefault(
            row['product_area_key'],
            {
                'product_area_key': row['product_area_key'],
                'product_area_name': row['product_area_name'],
                'color': color,
                'product_area_color': color,
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
            'product_area_key': group.get('product_area_key') or slugify(group.get('product_area_name') or '') or 'unassigned',
            'product_area_name': group.get('product_area_name') or group.get('product_area_key') or 'Unassigned',
            'color': group.get('color') or group.get('product_area_color') or '',
            'product_area_color': group.get('product_area_color') or group.get('color') or '',
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
        'kpi_daily_rows': [],
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


def _empty_time_series():
    return {'granularity': 'day', 'labels': [], 'series': []}


def _product_area_filter_identity(item):
    if not isinstance(item, dict):
        return '', ''
    return _product_area_identity(item)


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
        color = explicit_product_area_color(item)
        if color and not explicit_product_area_color(existing):
            existing.update({
                'color': color,
                'product_area_color': color,
                'productAreaColor': color,
            })
        return

    color = explicit_product_area_color(item)
    options_by_key[key] = {
        'key': key,
        'name': name or key,
        'product_area_key': key,
        'product_area_name': name or key,
        'color': color,
        'product_area_color': color,
        'productAreaColor': color,
    }


def overview_product_area_filter_options(payload):
    options_by_key = {}
    payload = payload if isinstance(payload, dict) else {}

    for section_name in (
        'productAreas',
        'product_area_summary',
        'page_metrics_rows',
        'change_aware_rows',
        'rows',
        'company_engagement_by_product_area',
        'company_engagement_by_page_group',
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


_PRODUCT_AREA_IDENTITY_FIELDS = (
    'product_area_key',
    'productAreaKey',
    'product_area_id',
    'productAreaId',
    'product_area_name',
    'productAreaName',
    'product_area',
    'productArea',
    'page_group',
)


def _has_product_area_identity(item, *, allow_name=False):
    if not isinstance(item, dict):
        return False
    if any(str(item.get(field) or '').strip() for field in _PRODUCT_AREA_IDENTITY_FIELDS):
        return True
    return allow_name and bool(str(item.get('name') or '').strip())


def _overview_product_area_candidates(payload):
    candidates = []
    candidate_by_key = {}
    candidate_indexes_by_name = defaultdict(set)

    def add(item, *, allow_name=False):
        if not _has_product_area_identity(item, allow_name=allow_name):
            return

        key, name = _product_area_identity(item)
        key_token = _normalized_filter_token(key)
        name_token = _normalized_filter_token(name)
        has_explicit_key = any(
            str(item.get(field) or '').strip()
            for field in (
                'product_area_key',
                'productAreaKey',
                'product_area_id',
                'productAreaId',
                'key',
                'slug',
            )
        )
        existing_index = candidate_by_key.get(key_token)
        if existing_index is None and not has_explicit_key and name_token:
            name_matches = candidate_indexes_by_name.get(name_token, set())
            if len(name_matches) == 1:
                existing_index = next(iter(name_matches))
            elif len(name_matches) > 1:
                # A name-only legacy item cannot be assigned safely when two
                # real Product Areas intentionally share that display name.
                return
        explicit_color = explicit_product_area_color(item)
        if existing_index is not None:
            candidate = candidates[existing_index]
            if explicit_color and not explicit_product_area_color(candidate):
                candidate['color'] = explicit_color
            if key_token:
                candidate_by_key[key_token] = existing_index
            if name_token:
                candidate_indexes_by_name[name_token].add(existing_index)
            return

        candidate = {
            'key': key,
            'name': name,
            'color': explicit_color,
        }
        for field in (
            'shortName',
            'short_name',
            'areaRole',
            'area_role',
            'isAdoptionRecommendable',
            'is_adoption_recommendable',
        ):
            if field in item:
                candidate[field] = item[field]
        candidate_index = len(candidates)
        candidates.append(candidate)
        if key_token:
            candidate_by_key[key_token] = candidate_index
        if name_token:
            candidate_indexes_by_name[name_token].add(candidate_index)

    for item in payload.get('productAreas') or []:
        add(item, allow_name=True)

    for section_name in (
        'product_area_summary',
        'page_metrics_rows',
        'change_aware_rows',
        'rows',
        'company_engagement_by_product_area',
        'company_engagement_by_page_group',
        'top_actions_by_page',
    ):
        for item in payload.get(section_name) or []:
            add(item)

    for section_name in (
        'top_pages_by_visits_over_time',
        'top_pages_by_engaged_time_over_time',
    ):
        time_series = payload.get(section_name)
        if isinstance(time_series, dict):
            for item in time_series.get('series') or []:
                add(item)

    treemap = payload.get('engaged_time_treemap')
    if isinstance(treemap, dict):
        for node in treemap.get('nodes') or []:
            add(node)
            if isinstance(node, dict):
                for child in node.get('children') or []:
                    add(child)

    sankey = payload.get('sankey')
    if isinstance(sankey, dict):
        for node in sankey.get('nodes') or []:
            add(node)
        for link in sankey.get('links') or []:
            if not isinstance(link, dict):
                continue
            for prefix in ('source', 'target'):
                generic_area = link.get(f'{prefix}_product_area')
                add({
                    'product_area_key': link.get(f'{prefix}_product_area_key'),
                    'product_area_name': link.get(f'{prefix}_product_area_name') or generic_area,
                    'product_area_color': link.get(f'{prefix}_product_area_color'),
                })

    return candidates


def _decorate_overview_product_area_item(item, color_lookup, index=0):
    if not isinstance(item, dict) or not _has_product_area_identity(item):
        return item

    key, name = _product_area_identity(item)
    color = product_area_color_from_lookup(
        color_lookup,
        {'key': key, 'name': name},
        index,
        prefer_explicit=True,
    )
    return {
        **item,
        'product_area_key': key,
        'product_area_name': name,
        'color': color,
        'product_area_color': color,
        'productAreaColor': color,
    }


def _normalize_overview_product_area_colors(payload):
    resolved_areas = resolve_product_area_colors(
        _overview_product_area_candidates(payload),
        prefer_explicit=True,
    )
    color_lookup = build_product_area_color_lookup(resolved_areas, prefer_explicit=True)
    payload['productAreas'] = [
        _product_area_payload_item(area, color_lookup, index)
        for index, area in enumerate(resolved_areas)
    ]

    for section_name in (
        'product_area_summary',
        'page_metrics_rows',
        'change_aware_rows',
        'rows',
        'company_engagement_by_product_area',
        'company_engagement_by_page_group',
        'top_actions_by_page',
    ):
        rows = payload.get(section_name)
        if isinstance(rows, list):
            payload[section_name] = [
                _decorate_overview_product_area_item(item, color_lookup, index)
                for index, item in enumerate(rows)
            ]

    for section_name in (
        'top_pages_by_visits_over_time',
        'top_pages_by_engaged_time_over_time',
    ):
        time_series = payload.get(section_name)
        if not isinstance(time_series, dict) or not isinstance(time_series.get('series'), list):
            continue
        time_series['series'] = [
            _decorate_overview_product_area_item(item, color_lookup, index)
            for index, item in enumerate(time_series['series'])
        ]

    treemap = payload.get('engaged_time_treemap')
    if isinstance(treemap, dict) and isinstance(treemap.get('nodes'), list):
        decorated_nodes = []
        for node_index, node in enumerate(treemap['nodes']):
            decorated_node = _decorate_overview_product_area_item(node, color_lookup, node_index)
            if isinstance(decorated_node, dict) and isinstance(decorated_node.get('children'), list):
                decorated_node['children'] = [
                    _decorate_overview_product_area_item(child, color_lookup, child_index)
                    for child_index, child in enumerate(decorated_node['children'])
                ]
            decorated_nodes.append(decorated_node)
        treemap['nodes'] = decorated_nodes

    sankey = payload.get('sankey')
    if isinstance(sankey, dict):
        nodes = sankey.get('nodes') if isinstance(sankey.get('nodes'), list) else []
        decorated_nodes = [
            _decorate_overview_product_area_item(node, color_lookup, index)
            for index, node in enumerate(nodes)
        ]
        sankey['nodes'] = decorated_nodes
        node_by_name = {
            str(node.get('name') or ''): node
            for node in decorated_nodes
            if isinstance(node, dict) and str(node.get('name') or '')
        }
        decorated_links = []
        for index, link in enumerate(sankey.get('links') or []):
            if not isinstance(link, dict):
                continue
            decorated_link = dict(link)
            for prefix, offset in (('source', 0), ('target', 1)):
                endpoint_node = node_by_name.get(str(link.get(prefix) or '')) or {}
                generic_area = link.get(f'{prefix}_product_area')
                endpoint = {
                    'product_area_key': (
                        link.get(f'{prefix}_product_area_key')
                        or endpoint_node.get('product_area_key')
                    ),
                    'product_area_name': (
                        link.get(f'{prefix}_product_area_name')
                        or generic_area
                        or endpoint_node.get('product_area_name')
                    ),
                }
                if not _has_product_area_identity(endpoint):
                    continue
                key, name = _product_area_identity(endpoint)
                color = product_area_color_from_lookup(
                    color_lookup,
                    {'key': key, 'name': name},
                    index + offset,
                    prefer_explicit=True,
                )
                decorated_link.update({
                    f'{prefix}_product_area_key': key,
                    f'{prefix}_product_area_name': name,
                    f'{prefix}_product_area': name,
                    f'{prefix}_product_area_color': color,
                })
            decorated_links.append(decorated_link)
        sankey['links'] = decorated_links

    return payload


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
    explicit_key_values = [
        item.get('product_area_key'),
        item.get('productAreaKey'),
        item.get('product_area_id'),
        item.get('productAreaId'),
        item.get('key'),
        item.get('slug'),
    ]
    explicit_key_tokens = {
        _normalized_filter_token(value)
        for value in explicit_key_values
        if str(value or '').strip()
    }
    if explicit_key_tokens:
        return bool(explicit_key_tokens & selection['keys'])

    legacy_values = [
        key,
        name,
        item.get('product_area_name'),
        item.get('productAreaName'),
        item.get('product_area'),
        item.get('page_group'),
    ]
    tokens = {_normalized_filter_token(value) for value in legacy_values if str(value or '').strip()}
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
    return {
        **copy.deepcopy(sankey),
        'nodes': nodes,
        'links': links,
    }


def _filter_two_way_movement_by_product_area(movement, selection):
    if not isinstance(movement, dict):
        return {'rows': [], 'limit': 10, 'total_pairs': 0}
    rows = [
        copy.deepcopy(row)
        for row in movement.get('rows') or []
        if isinstance(row, dict)
        and _matches_product_area_filter(
            {'product_area_name': row.get('page_a_product_area_name')}, selection,
        )
        and _matches_product_area_filter(
            {'product_area_name': row.get('page_b_product_area_name')}, selection,
        )
    ]
    return {**copy.deepcopy(movement), 'rows': rows, 'total_pairs': len(rows)}


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


def _build_filtered_kpis(payload, rows):
    if not rows:
        return []

    current_rows = [
        row
        for row in rows
        if not row.get('_previous_only')
    ]
    comparison_available = any(
        row.get('comparison_available') is not False and row.get('comparisonAvailable') is not False
        for row in rows
    )
    daily_adopted_pages_trend = _daily_adopted_pages_trend(rows)
    previous_daily_adopted_pages_trend = _daily_adopted_pages_trend(
        rows,
        'previous',
    )
    average_daily_adopted_pages = _average_trend_value(
        daily_adopted_pages_trend,
    )
    previous_average_daily_adopted_pages = _average_trend_value(
        previous_daily_adopted_pages_trend,
    )
    daily_adoption_trend = _daily_average_adoption_trend(rows)
    previous_daily_adoption_trend = _daily_average_adoption_trend(rows, 'previous')
    average_daily_adoption = _average_trend_value(daily_adoption_trend)
    previous_average_daily_adoption = _average_trend_value(previous_daily_adoption_trend)
    most_used = max(
        current_rows,
        key=lambda row: _to_int(row.get('engaged_seconds')),
        default=None,
    )
    most_used_daily_engaged = (
        _daily_additive_trend_values(most_used, 'engaged')
        if most_used
        else []
    )
    most_used_average_daily_engaged = _average_trend_value(
        most_used_daily_engaged,
        decimal_places=2,
    )

    def previous_companies_for_row(row):
        if row.get('previous_companies_count') is not None:
            return row.get('previous_companies_count')
        return _previous_metric_value(
            row.get('companies_count'),
            {'value': row.get('companies_change_pct'), 'label': '%'},
        )

    fastest, _fastest_growth, fastest_is_new = _select_fastest_growing_row(
        current_rows,
        previous_companies_for_row,
    )
    trend_labels = (payload.get('top_pages_by_visits_over_time') or {}).get('labels') or []
    comparison_delta_label = None if comparison_available else 'n/a'
    fastest_kpi = _build_fastest_growing_kpi(
        fastest,
        fastest_is_new,
        previous_companies_for_row(fastest) if fastest else 0,
        comparison_available=comparison_available,
    )

    average_daily_adopted_pages_delta = round(
        average_daily_adopted_pages - previous_average_daily_adopted_pages,
        1,
    )
    average_daily_adoption_delta = round(
        average_daily_adoption - previous_average_daily_adoption,
        1,
    )
    engaged_time_series = payload.get('top_pages_by_engaged_time_over_time') or {}

    return [
        {
            'label': 'Avg daily adopted pages',
            'value': _format_decimal_for_display(average_daily_adopted_pages, 1),
            'delta': comparison_delta_label or (
                f'{_format_signed_decimal(average_daily_adopted_pages_delta, "", 1)} vs previous'
            ),
            'delta_value': average_daily_adopted_pages_delta if comparison_available else 0,
            'trend_values': daily_adopted_pages_trend,
            'trend_labels': trend_labels,
            'trend_format': 'number',
            'trend_label': 'Adopted pages',
            'trend_scope': 'daily',
        },
        {
            'label': 'Avg daily adoption',
            'value': f'{_round_integer_for_display(average_daily_adoption)}%',
            'delta': comparison_delta_label or _format_signed(round(average_daily_adoption_delta), ' pp'),
            'delta_value': round(average_daily_adoption_delta) if comparison_available else 0,
            'trend_values': daily_adoption_trend,
            'trend_labels': trend_labels,
            'trend_format': 'percent',
            'trend_label': 'Average page adoption',
            'trend_scope': 'daily',
        },
        {
            'label': 'Most used page',
            'value': most_used['page_name'] if most_used else 'No data',
            'delta': f'{_format_duration_kpi(most_used_average_daily_engaged)} avg/day' if most_used else '',
            'delta_value': 0,
            'product_area_key': most_used.get('product_area_key') if most_used else '',
            'page_rule_id': most_used.get('page_rule_id') if most_used else None,
            'trend_values': most_used_daily_engaged,
            'trend_labels': (engaged_time_series or {}).get('labels') or [],
            'trend_format': 'duration',
            'trend_label': 'Daily engaged',
            'trend_scope': 'daily',
        },
        fastest_kpi,
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
    kpi_daily_rows = [
        copy.deepcopy(row)
        for row in payload.get('kpi_daily_rows') or page_metrics_rows
        if _matches_product_area_filter(row, selection)
    ]
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
    payload['kpi_daily_rows'] = kpi_daily_rows
    payload['product_area_summary'] = product_area_summary
    payload['productAreas'] = [
        copy.deepcopy(area)
        for area in payload.get('productAreas') or []
        if _matches_product_area_filter(area, selection)
    ]
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
    payload['two_way_movement'] = _filter_two_way_movement_by_product_area(
        payload.get('two_way_movement'), selection,
    )
    payload['top_actions_by_page'] = top_actions
    payload['top_actions_by_page_group'] = _build_top_actions_by_page_group(top_actions)
    payload['company_engagement_by_product_area'] = company_engagement
    payload['company_engagement_by_page_group'] = _build_company_engagement_by_page_group(company_engagement)
    payload['top_clicked_elements'] = _build_top_clicked_elements(top_actions)
    payload['kpis'] = _build_filtered_kpis(
        payload,
        kpi_daily_rows or page_metrics_rows or change_rows,
    )
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
    if not isinstance(change_rows, list):
        change_rows = payload.get('rows')
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
    kpi_daily_rows = payload.get('kpi_daily_rows')
    kpi_daily_rows = (
        kpi_daily_rows
        if isinstance(kpi_daily_rows, list)
        else full_page_metrics_rows
    )
    payload['kpi_daily_rows'] = [
        _strip_for_overview_row(_ensure_change_row_contract(dict(row)))
        for row in kpi_daily_rows
        if isinstance(row, dict)
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
    payload.setdefault('two_way_movement', {'rows': [], 'limit': 10, 'total_pairs': 0})

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

    return _normalize_overview_product_area_colors(payload)


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
        return f'{_round_integer_for_display(value)}%'
    if value_type == 'duration':
        return _format_duration(_to_float(value))
    if value_type == 'ratio':
        return _format_decimal_for_display(value, 1)
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
        'previous_companies_count': previous_companies,
        'previous_adoption_pct': previous_adoption,
        'previous_visits_count': previous_visits,
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
        '_period_to_date_trends': {
            metric: [0 for _current_date in _date_range(start_date, end_date)]
            for metric in PAGE_DETAIL_TREND_METRICS
        },
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


def _period_to_date_detail_series(row, metric_key, start_date, end_date):
    dates = list(_date_range(start_date, end_date))
    values = _period_to_date_trend_values(row, metric_key)
    return [
        {
            'date': current_date.isoformat(),
            'value': values[index] if index < len(values) else 0,
        }
        for index, current_date in enumerate(dates)
    ]


def _detail_benchmark_series(rows, metric_key, start_date, end_date):
    source_series = [
        _period_to_date_detail_series(row, metric_key, start_date, end_date)
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


def _detail_metric_payload(row, peers, benchmark_rows, metric_config, start_date, end_date):
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
        'dailySeries': _period_to_date_detail_series(row, metric_key, start_date, end_date),
        'peerSeries': [
            {
                'pageId': peer.get('page_rule_id'),
                'pageName': peer.get('page_name') or peer.get('page_rule_id'),
                'productAreaName': peer.get('product_area_name') or peer.get('page_group'),
                'dailySeries': _period_to_date_detail_series(peer, metric_key, start_date, end_date),
            }
            for peer in peers
        ],
        'benchmarkSeries': _detail_benchmark_series(benchmark_rows, metric_key, start_date, end_date),
        'benchmarkEligiblePeerCount': len(benchmark_rows or []),
    }


def _detail_related_page_payload(row, current_page_id):
    comparison_available = row.get('comparison_available', row.get('comparisonAvailable', True)) is not False
    deltas = row.get('deltas') or {}

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
        'companiesChangeLabel': (deltas.get('companies') or {}).get('label'),
        'adoption': _to_float(row.get('adoption_pct')),
        'adoptionChange': _to_float(row.get('adoption_change_pp')),
        'adoptionChangeLabel': (deltas.get('adoption') or {}).get('label'),
        'users': _to_int(row.get('users_count')),
        'usersChange': _to_float(row.get('users_change_pct')),
        'usersChangeLabel': (deltas.get('users') or {}).get('label'),
        'visits': _to_int(row.get('visits_count')),
        'visitsChange': _to_float(row.get('visits_change_pct')),
        'visitsChangeLabel': (deltas.get('visits') or {}).get('label'),
        'engaged': _to_int(row.get('engaged_seconds')),
        'engagedChange': _to_float(row.get('engaged_change_pct')),
        'engagedChangeLabel': (deltas.get('engaged') or {}).get('label'),
        'interaction': _to_float(row.get('interaction_pct')),
        'interactionChange': _to_float(row.get('interaction_change_pp')),
        'interactionChangeLabel': (deltas.get('interaction') or {}).get('label'),
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
        group['_previous_visits'] += 0 if row.get('visitsChangeLabel') == 'New' else _previous_from_percent_change(visits, row.get('visitsChange'))
        group['_previous_engaged'] += 0 if row.get('engagedChangeLabel') == 'New' else _previous_from_percent_change(engaged, row.get('engagedChange'))

        companies = _to_int(row.get('companies'))
        if companies > group['_companies_value']:
            group['_companies_value'] = companies
            group['companies'] = companies
            group['companiesChange'] = _to_float(row.get('companiesChange'))
            group['companiesChangeLabel'] = row.get('companiesChangeLabel')

        adoption = _to_float(row.get('adoption'))
        if adoption > group['_adoption_value']:
            group['_adoption_value'] = adoption
            group['adoption'] = adoption
            group['adoptionChange'] = _to_float(row.get('adoptionChange'))
            group['adoptionChangeLabel'] = row.get('adoptionChangeLabel')

        users = _to_int(row.get('users'))
        if users > group['_users_value']:
            group['_users_value'] = users
            group['users'] = users
            group['usersChange'] = _to_float(row.get('usersChange'))
            group['usersChangeLabel'] = row.get('usersChangeLabel')

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

        previous_visits = group.pop('_previous_visits', 0)
        visits_delta = _delta_pct(group.get('visits'), previous_visits)
        group['visitsChange'] = _to_float(visits_delta.get('value'))
        group['visitsChangeLabel'] = visits_delta.get('label')
        previous_engaged = group.pop('_previous_engaged', 0)
        engaged_delta = _delta_pct(group.get('engaged'), previous_engaged)
        group['engagedChange'] = _to_float(engaged_delta.get('value'))
        group['engagedChangeLabel'] = engaged_delta.get('label')
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
    comparison_available = row.get('comparison_available', row.get('comparisonAvailable', True)) is not False
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
        users_delta = _delta_pct(users, previous_item.get('users'))
        visits_delta = _delta_pct(visits, previous_item.get('visits'))
        engaged_delta = _delta_pct(engaged, previous_item.get('engaged'))
        avg_user_delta = _delta_pct(avg_user, previous_avg_user)
        interaction_delta = _delta_pp(interaction, previous_interaction)

        companies.append({
            'id': company_id,
            'companyId': company_id,
            'company': item.get('company_name_sample') or company_id or 'Unknown company',
            'comparisonAvailable': comparison_available,
            'comparison_available': comparison_available,
            'users': users,
            'usersChange': _to_float(users_delta.get('value')),
            'usersChangeLabel': users_delta.get('label'),
            'pagePenetration': 0,
            'pagePenetrationChange': 0,
            'visits': visits,
            'visitsChange': _to_float(visits_delta.get('value')),
            'visitsChangeLabel': visits_delta.get('label'),
            'engagedSeconds': engaged,
            'engagedChange': _to_float(engaged_delta.get('value')),
            'engagedChangeLabel': engaged_delta.get('label'),
            'engaged': _format_duration(engaged),
            'avgUser': _format_duration(avg_user),
            'avgUserChange': _to_float(avg_user_delta.get('value')),
            'avgUserChangeLabel': avg_user_delta.get('label'),
            'interaction': interaction,
            'interactionChange': _to_float(interaction_delta.get('value')),
            'interactionChangeLabel': interaction_delta.get('label'),
            'clicks': clicks,
            'lastSeen': '-',
        })

    companies.sort(key=lambda item: (-item['engagedSeconds'], -item['visits'], item['company']))
    return companies[:limit] if limit else companies


def _build_detail_champions(project_id, row, start_date, end_date, previous_start, previous_end, limit=None):
    comparison_available = row.get('comparison_available', row.get('comparisonAvailable', True)) is not False
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
        previous_item = previous_by_user.get(user_id, {})
        engaged_delta = _delta_pct(engaged, previous_item.get('engaged'))
        visits_delta = _delta_pct(visits, previous_item.get('visits'))
        clicks_delta = _delta_pct(clicks, previous_item.get('clicks'))

        champions.append({
            'id': user_id,
            'userId': user_id,
            'companyId': company_id,
            'user': _detail_user_name(item.get('user_name_sample'), user_id, company_name if company_name != company_id else ''),
            'company': company_name,
            'comparisonAvailable': comparison_available,
            'comparison_available': comparison_available,
            'engagedSeconds': engaged,
            'engagedChange': _to_float(engaged_delta.get('value')),
            'engagedChangeLabel': engaged_delta.get('label'),
            'engaged': _format_duration(engaged),
            'visits': visits,
            'visitsChange': _to_float(visits_delta.get('value')),
            'visitsChangeLabel': visits_delta.get('label'),
            'avgVisit': _format_duration(_ratio(engaged, visits)),
            'clicks': clicks,
            'clicksChange': _to_float(clicks_delta.get('value')),
            'clicksChangeLabel': clicks_delta.get('label'),
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
    comparison_available = row.get('comparison_available', row.get('comparisonAvailable', True)) is not False
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
        clicks_delta = _delta_pct(clicks, previous_item.get('clicks'))
        visits_pct_delta = _delta_pp(visits_pct, previous_visits_pct)
        users_delta = _delta_pct(users, previous_item.get('users'))
        companies_delta = _delta_pct(companies, previous_item.get('companies'))

        actions.append({
            'action': action,
            'comparisonAvailable': comparison_available,
            'comparison_available': comparison_available,
            'clicks': clicks,
            'clicksChange': _to_float(clicks_delta.get('value')),
            'clicksChangeLabel': clicks_delta.get('label'),
            'visitsPct': visits_pct,
            'visitsPctChange': _to_float(visits_pct_delta.get('value')),
            'visitsPctChangeLabel': visits_pct_delta.get('label'),
            'users': users,
            'usersChange': _to_float(users_delta.get('value')),
            'usersChangeLabel': users_delta.get('label'),
            'companies': companies,
            'companiesChange': _to_float(companies_delta.get('value')),
            'companiesChangeLabel': companies_delta.get('label'),
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
        _attach_period_to_date_trends(
            rows,
            project_id,
            start_date,
            end_date,
            _daily_page_rows(project_id, start_date, end_date),
            grain='page',
        )
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
    detail_metrics = [
        _detail_metric_payload(current_row, peers, benchmark_rows, metric, start_date, end_date)
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


def build_pages_overview_cache(
    project_id,
    *,
    range_key='last_30_days',
    start_date=None,
    end_date=None,
    company_attribute_filter_state=None,
    use_lock=True,
):
    filters_active = (
        company_attribute_filter_state is not None
        and company_attribute_filter_state.active
    )
    if use_lock:
        with project_advisory_lock(project_id, namespace='pages-rebuild') as acquired:
            if not acquired:
                return {
                    'status': 'skipped',
                    'reason': 'lock_not_acquired',
                    'project_id': project_id,
                    'range_key': range_key,
                }
            return build_pages_overview_cache(
                project_id,
                range_key=range_key,
                start_date=start_date,
                end_date=end_date,
                company_attribute_filter_state=company_attribute_filter_state,
                use_lock=False,
            )

    project = get_project_info(project_id)
    if not project:
        raise ValueError(f'Project {project_id} does not exist.')

    from apps.projects.models import Project

    expected_filtered_revision, expected_facts_revision = (
        int(value)
        for value in Project.objects
        .values_list('filtered_analytics_revision', 'analytics_facts_revision')
        .get(pk=project_id)
    )
    cohort = (
        resolve_project_company_cohort(project_id, company_attribute_filter_state)
        if filters_active
        else None
    )
    filters_hash = (
        company_attribute_filter_state.filters_hash
        if filters_active
        else DEFAULT_FILTERS_HASH
    )

    timezone_name = project['timezone'] or 'UTC'
    start_date, end_date = resolve_period(timezone_name, range_key=range_key, start_date=start_date, end_date=end_date)
    previous_start, previous_end = previous_period(start_date, end_date)
    generated_at = django_timezone.now()
    expires_at = generated_at + CACHE_TTL
    source = queries.fetch_one(queries.SOURCE_MAX_EVENT_TS_SQL, [project_id]) or {}
    source_max_event_ts = source.get('source_max_event_ts')

    rows, current_counts, previous_counts = _build_change_rows(
        project_id,
        start_date,
        end_date,
        previous_start,
        previous_end,
        cohort=cohort,
    )
    page_kpi_rows, _, _ = _build_change_rows(
        project_id,
        start_date,
        end_date,
        previous_start,
        previous_end,
        grain='display_page',
        cohort=cohort,
        include_previous_only=True,
    )
    page_metrics_rows = [
        row
        for row in page_kpi_rows
        if not row.get('_previous_only')
    ]
    product_area_rows, _, _ = _build_change_rows(
        project_id,
        start_date,
        end_date,
        previous_start,
        previous_end,
        grain='product_area',
        cohort=cohort,
    )
    previous_rows = _summary_by_display_page(project_id, previous_start, previous_end, cohort=cohort)
    product_areas = _project_product_area_options(project_id, product_area_rows)
    product_area_color_lookup = build_product_area_color_lookup(product_areas, prefer_explicit=True)
    payload = _empty_payload(project, range_key, start_date, end_date, previous_start, previous_end, generated_at, source_max_event_ts)
    payload['productAreas'] = product_areas
    payload['project'].update({
        'active_companies_total': _to_int(current_counts.get('active_companies_count')),
        'active_users_total': _to_int(current_counts.get('active_users_count')),
    })

    if rows:
        top_actions = _build_top_actions(
            project_id,
            start_date,
            end_date,
            previous_start,
            previous_end,
            cohort=cohort,
            timezone_name=timezone_name,
        )
        company_engagement = _build_scatter(
            project_id,
            start_date,
            end_date,
            product_area_color_lookup,
            cohort=cohort,
        )
        overview_rows = [_strip_for_overview_row(row) for row in rows]
        overview_page_metrics_rows = [_strip_for_overview_row(row) for row in page_metrics_rows]
        overview_page_kpi_rows = [_strip_for_overview_row(row) for row in page_kpi_rows]
        payload.update({
            'kpis': _build_kpis(
                page_kpi_rows,
                previous_rows,
                _to_int(current_counts.get('active_companies_count')),
                _to_int(previous_counts.get('active_companies_count')),
                comparison_available=_has_period_comparison_data(previous_rows, previous_counts),
            ),
            'rows': overview_rows,
            'change_aware_rows': overview_rows,
            'page_metrics_rows': overview_page_metrics_rows,
            'kpi_daily_rows': overview_page_kpi_rows,
            'product_area_summary': [_strip_for_product_area_summary(row) for row in product_area_rows],
            'top_pages_by_visits_over_time': _build_series(page_metrics_rows, 'visits_count'),
            'top_pages_by_engaged_time_over_time': _build_series(page_metrics_rows, 'engaged_seconds'),
            'engaged_time_treemap': _build_treemap(
                page_metrics_rows,
                active_companies_total=current_counts.get('active_companies_count'),
                color_lookup=product_area_color_lookup,
            ),
            'sankey': _build_sankey(
                project_id,
                timezone_name,
                start_date,
                end_date,
                product_area_color_lookup,
                cohort=cohort,
            ),
            'two_way_movement': _build_two_way_movement(
                project_id,
                timezone_name,
                start_date,
                end_date,
                cohort=cohort,
            ),
            'top_actions_by_page': top_actions,
            'top_actions_by_page_group': _build_top_actions_by_page_group(top_actions),
            'company_engagement_by_product_area': company_engagement,
            'company_engagement_by_page_group': _build_company_engagement_by_page_group(company_engagement),
            'top_clicked_elements': _build_top_clicked_elements(top_actions),
        })

    payload = normalize_overview_payload(payload)
    if filters_active:
        # Both revisions are stored so a reader can tell an attribute edit,
        # which invalidates the cohort, from a fact rebuild, which only ages it.
        payload.setdefault('freshness', {}).update({
            'filtered_analytics_revision': expected_filtered_revision,
            'analytics_facts_revision': expected_facts_revision,
        })
        payload['company_attribute_filter'] = {
            'filters_hash': filters_hash,
            'active_count': company_attribute_filter_state.active_count,
        }

    # Page, Company and User detail caches are an unfiltered-only feature, so a
    # filtered variant publishes its overview row and nothing else.
    if filters_active:
        cache_params = [
            project_id,
            range_key,
            start_date,
            end_date,
            filters_hash,
            json.dumps(payload, default=_json_default),
            compress_overview_payload(payload),
            source_max_event_ts,
            generated_at,
            expires_at,
        ]
        with transaction.atomic():
            current_revision = int(
                Project.objects.select_for_update()
                .values_list('filtered_analytics_revision', flat=True)
                .get(pk=project_id)
            )
            if current_revision != expected_filtered_revision:
                return {
                    'status': 'skipped',
                    'reason': 'revision_changed',
                    'project_id': project_id,
                    'range_key': range_key,
                }
            queries.execute(queries.UPSERT_OVERVIEW_CACHE_SQL, cache_params)
        purge_expired_filtered_overview_caches(project_id)
        return {
            'status': 'success',
            'project_id': project_id,
            'range_key': range_key,
            'filters_hash': filters_hash,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'rows_count': len(page_metrics_rows),
        }

    detail_cache_result = hydrate_pages_detail_cache(
        project_id,
        range_key=range_key,
        start_date=start_date,
        end_date=end_date,
        project=project,
        rows=rows,
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
            compress_overview_payload(payload),
            source_max_event_ts,
            generated_at,
            expires_at,
        ],
    )
    hydrate_pages_scatter_tooltips_cache(
        project_id,
        range_key=range_key,
        start_date=start_date,
        end_date=end_date,
        use_lock=False,
    )
    return {
        'status': 'success',
        'project_id': project_id,
        'range_key': range_key,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'rows_count': len(page_metrics_rows),
        'detail_cache_count': detail_cache_result['items_count'],
    }


def hydrate_pages_scatter_tooltips_cache(
    project_id,
    *,
    range_key='last_30_days',
    start_date=None,
    end_date=None,
    use_lock=True,
):
    if use_lock:
        with project_advisory_lock(project_id, namespace='pages-rebuild') as acquired:
            if not acquired:
                return {
                    'status': 'skipped',
                    'reason': 'lock_not_acquired',
                    'project_id': project_id,
                    'range_key': range_key,
                    'items_count': 0,
                }
            return hydrate_pages_scatter_tooltips_cache(
                project_id,
                range_key=range_key,
                start_date=start_date,
                end_date=end_date,
                use_lock=False,
            )

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
