import json
import math
from collections import OrderedDict, defaultdict
from statistics import median

from django.db.models import Count, Max, Min, Q, Sum
from django.utils import timezone as django_timezone

from apps.pages import services
from apps.pages.locks import project_advisory_lock
from apps.pages.models import PageDailyMetric, PageUserDailyMetric, PageVisit, UsersDetailCache
from apps.pages.product_area_colors import (
    build_product_area_color_lookup,
    product_area_color_from_lookup,
    resolve_product_area_colors,
)
from apps.projects.models import Project
from apps.tracker.models import ProjectPageRule


USER_DETAILS_PAYLOAD_SCHEMA_VERSION = 2
USER_DETAIL_USERS_LIMIT = 500
USER_DETAIL_SCATTER_LIMIT = 300


def _period_days(range_key):
    return {
        'last_7_days': 7,
        'last_30_days': 30,
        'last_90_days': 90,
        'last_180_days': 180,
    }.get(range_key, 30)


def _to_int(value):
    return int(value or 0)


def _to_float(value):
    return float(value or 0)


def _ratio(numerator, denominator):
    denominator = _to_float(denominator)
    return 0.0 if denominator <= 0 else _to_float(numerator) / denominator


def _pct(numerator, denominator):
    return round(_ratio(numerator, denominator) * 100, 1)


def _fraction(numerator, denominator):
    return round(_ratio(numerator, denominator), 4)


def _delta_pct_value(current, previous):
    delta = services._delta_pct(current, previous)
    value = delta.get('value') if isinstance(delta, dict) else 0
    return 0 if value is None else value


def _delta_pp_value(current_pct, previous_pct):
    return services._delta_pp(current_pct, previous_pct).get('value') or 0


def _format_duration(seconds):
    seconds = max(0, int(round(seconds or 0)))
    if seconds < 60:
        return f'{seconds}s'
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours:
        return f'{hours}h {minutes}m' if minutes else f'{hours}h'
    return f'{minutes}m'


def _format_percent(value):
    return f'{round(_to_float(value))}%'


def _format_number(value):
    return f'{int(round(_to_float(value))):,}'


def _safe_iso(value):
    return value.isoformat() if value else ''


def _safe_email(user_id):
    value = str(user_id or '').strip()
    return value if '@' in value else ''


def _email_for_user(user_id, *email_lookups):
    user_id = str(user_id or '')
    for lookup in email_lookups:
        email = (lookup or {}).get(user_id)
        if email:
            return email
    return _safe_email(user_id)


def _name_from_user_id(user_id):
    value = str(user_id or '').strip()
    if '@' in value:
        value = value.split('@', 1)[0]
    value = value.replace('.', ' ').replace('_', ' ').replace('-', ' ')
    return ' '.join(word.capitalize() for word in value.split()) or str(user_id or 'User')


def _base_user_queryset(project_id, start_date, end_date):
    return (
        PageUserDailyMetric.objects
        .filter(project_id=project_id, date__gte=start_date, date__lte=end_date)
        .exclude(user_id__isnull=True)
        .exclude(user_id='')
    )


def _aggregate_user_metrics(project_id, start_date, end_date, *, user_ids=None, company_id=None):
    queryset = _base_user_queryset(project_id, start_date, end_date)
    if user_ids is not None:
        queryset = queryset.filter(user_id__in=[str(user_id) for user_id in user_ids])
    if company_id:
        queryset = queryset.filter(company_id=company_id)

    rows = (
        queryset
        .values('user_id')
        .annotate(
            user_name=Max('user_name_sample'),
            company_id=Max('company_id'),
            visits=Sum('visits_count'),
            engaged_seconds_total=Sum('engaged_seconds'),
            click_count=Sum('click_count'),
            pages_used=Count('page_rule_id', filter=Q(visits_count__gt=0) | Q(engaged_seconds__gt=0), distinct=True),
            product_areas_used=Count('product_area_key', filter=Q(visits_count__gt=0) | Q(engaged_seconds__gt=0), distinct=True),
            active_days=Count('date', filter=Q(visits_count__gt=0) | Q(engaged_seconds__gt=0), distinct=True),
            first_seen_date=Min('date'),
            last_seen_date=Max('date'),
        )
    )

    return {
        str(row['user_id']): {
            'user_id': str(row['user_id']),
            'user_name': row.get('user_name') or '',
            'company_id': row.get('company_id') or '',
            'visits': _to_int(row.get('visits')),
            'engaged_seconds': _to_int(row.get('engaged_seconds_total')),
            'click_count': _to_int(row.get('click_count')),
            'pages_used': _to_int(row.get('pages_used')),
            'product_areas_used': _to_int(row.get('product_areas_used')),
            'active_days': _to_int(row.get('active_days')),
            'first_seen_date': row.get('first_seen_date'),
            'last_seen_date': row.get('last_seen_date'),
        }
        for row in rows
        if row.get('user_id')
    }


def _visit_queryset(project, start_date, end_date):
    start_ts, end_ts = services._utc_bounds_for_local_dates(start_date, end_date, project.timezone)
    return (
        PageVisit.objects
        .filter(project=project, visit_start_ts__gte=start_ts, visit_start_ts__lt=end_ts)
        .exclude(user_id__isnull=True)
        .exclude(user_id='')
    )


def _visit_metrics(project, start_date, end_date, *, user_ids=None, company_id=None):
    queryset = _visit_queryset(project, start_date, end_date)
    if user_ids is not None:
        queryset = queryset.filter(user_id__in=[str(user_id) for user_id in user_ids])
    if company_id:
        queryset = queryset.filter(company_id=company_id)

    rows = (
        queryset
        .values('user_id')
        .annotate(
            user_name=Max('user_name_sample'),
            company_id=Max('company_id'),
            company_name=Max('company_name_sample'),
            sessions_count=Count('session_id', distinct=True),
            visits_count=Count('id'),
            visits_with_click=Count('id', filter=Q(had_click=True)),
            first_visit_ts=Min('visit_start_ts'),
            last_visit_ts=Max('visit_start_ts'),
        )
    )

    return {
        str(row['user_id']): {
            'user_id': str(row['user_id']),
            'user_name': row.get('user_name') or '',
            'company_id': row.get('company_id') or '',
            'company_name': row.get('company_name') or '',
            'sessions_count': _to_int(row.get('sessions_count')),
            'visits_count': _to_int(row.get('visits_count')),
            'visits_with_click': _to_int(row.get('visits_with_click')),
            'first_visit_ts': row.get('first_visit_ts'),
            'last_visit_ts': row.get('last_visit_ts'),
        }
        for row in rows
        if row.get('user_id')
    }


def _selected_lifetime_identity(project, user_id):
    row = (
        PageVisit.objects
        .filter(project=project, user_id=user_id)
        .values('user_id')
        .annotate(
            user_name=Max('user_name_sample'),
            company_id=Max('company_id'),
            company_name=Max('company_name_sample'),
            first_seen_at=Min('visit_start_ts'),
            last_active_at=Max('visit_start_ts'),
        )
        .order_by('user_id')
        .first()
    )
    return row or {}


def _product_area_short_label(name):
    words = [word for word in str(name or '').split() if word]
    if len(words) > 1:
        return ''.join(word[0] for word in words).upper()[:7]
    text = str(name or 'Area')
    return text[:7] if len(text) <= 8 else f'{text[:6]}.'


def _product_area_options(project_id, start_date, end_date, *, limit=9):
    rows = (
        PageDailyMetric.objects
        .filter(project_id=project_id, date__gte=start_date, date__lte=end_date)
        .values('product_area_key')
        .annotate(
            product_area_name=Max('product_area_name'),
            product_area_short_name=Max('product_area__short_name'),
            product_area_color=Max('product_area__color'),
            engaged_seconds=Sum('engaged_seconds'),
        )
        .order_by('-engaged_seconds', 'product_area_name')
    )
    options = []
    seen = set()
    for row in rows:
        key = row.get('product_area_key') or 'unassigned'
        name = row.get('product_area_name') or key or 'Unassigned'
        if key in seen:
            continue
        seen.add(key)
        options.append({
            'id': key,
            'key': key,
            'name': name,
            'shortName': row.get('product_area_short_name') or _product_area_short_label(name),
            'color': row.get('product_area_color') or '',
        })

    if options:
        resolved = resolve_product_area_colors(options, prefer_explicit=True)
        if limit is None:
            return services._project_product_area_options(
                project_id,
                resolved,
                include_unobserved=True,
            )
        return resolved[:limit]

    fallback_rows = (
        _base_user_queryset(project_id, start_date, end_date)
        .values('product_area_key')
        .annotate(
            product_area_name=Max('product_area_name'),
            product_area_short_name=Max('product_area__short_name'),
            product_area_color=Max('product_area__color'),
            engaged_seconds=Sum('engaged_seconds'),
        )
        .order_by('-engaged_seconds', 'product_area_name')
    )
    for row in fallback_rows:
        key = row.get('product_area_key') or 'unassigned'
        name = row.get('product_area_name') or key or 'Unassigned'
        if key in seen:
            continue
        seen.add(key)
        options.append({
            'id': key,
            'key': key,
            'name': name,
            'shortName': row.get('product_area_short_name') or _product_area_short_label(name),
            'color': row.get('product_area_color') or '',
        })
    resolved = resolve_product_area_colors(options, prefer_explicit=True)
    if limit is None:
        return services._project_product_area_options(
            project_id,
            resolved,
            include_unobserved=True,
        )
    return resolved[:limit]


def _page_rule_names(project_id, page_rule_ids):
    ids = []
    for value in page_rule_ids:
        if value is None:
            continue
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    if not ids:
        return {}
    return {
        row['id']: row
        for row in (
            ProjectPageRule.objects
            .filter(project_id=project_id, id__in=ids)
            .values('id', 'page_name', 'product_area')
        )
    }


def _status_key(row, previous_row=None, *, period_days=30, first_seen_at=None, end_date=None):
    previous_row = previous_row or {}
    visits = _to_int(row.get('visits'))
    engaged = _to_int(row.get('engaged_seconds'))
    active_days = _to_int(row.get('active_days'))
    pages = _to_int(row.get('pages_used'))
    areas = _to_int(row.get('product_areas_used'))
    clicks = _to_int(row.get('click_count'))
    previous_engaged = _to_int(previous_row.get('engaged_seconds'))
    engaged_delta = _delta_pct_value(engaged, previous_engaged)
    consistency = _fraction(active_days, period_days)
    interaction = _fraction(clicks, visits)

    if first_seen_at and end_date:
        first_seen_date = first_seen_at.date() if hasattr(first_seen_at, 'date') else first_seen_at
        if first_seen_date and (end_date - first_seen_date).days <= 14:
            return 'new'

    if visits <= 0 and engaged <= 0:
        return 'at_risk'
    if engaged_delta <= -50 or (previous_engaged >= 300 and active_days <= 2):
        return 'at_risk'

    thresholds = services.power_user_thresholds(period_days)
    if (
        visits >= thresholds['visits']
        and engaged >= thresholds['engaged_seconds']
        and active_days >= thresholds['active_days']
        and areas >= thresholds['product_areas']
        and interaction >= thresholds['interaction']
    ):
        return 'power_user'

    if consistency < 0.30 and engaged >= 600:
        return 'sporadic'
    if visits >= max(2, math.ceil(period_days / 14)) and (pages >= 2 or areas >= 1):
        return 'healthy'
    return 'sporadic'


def _metric_row(row, visit_row=None):
    visit_row = visit_row or {}
    visits = _to_int(row.get('visits'))
    engaged = _to_int(row.get('engaged_seconds'))
    active_days = _to_int(row.get('active_days'))
    pages = _to_int(row.get('pages_used'))
    sessions = _to_int(visit_row.get('sessions_count')) or (max(1, round(visits / 3)) if visits else 0)
    visits_with_click = _to_int(visit_row.get('visits_with_click'))
    if not visits_with_click and visits:
        visits_with_click = min(visits, _to_int(row.get('click_count')))
    return {
        'visits': visits,
        'engaged_seconds': engaged,
        'active_days': active_days,
        'pages_used': pages,
        'click_count': _to_int(row.get('click_count')),
        'sessions_count': sessions,
        'visits_with_click': visits_with_click,
        'avg_visit_seconds': round(_ratio(engaged, visits)),
        'intensity_seconds': round(_ratio(engaged, active_days)),
        'interaction_pct': _pct(visits_with_click, visits),
    }


def _daily_metric_rows(project_id, user_id, start_date, end_date):
    rows = (
        _base_user_queryset(project_id, start_date, end_date)
        .filter(user_id=user_id)
        .values('date')
        .annotate(
            visits=Sum('visits_count'),
            engaged_seconds_total=Sum('engaged_seconds'),
            click_count=Sum('click_count'),
            pages_used=Count('page_rule_id', filter=Q(visits_count__gt=0) | Q(engaged_seconds__gt=0), distinct=True),
        )
    )
    by_date = {
        row['date']: {
            'visits': _to_int(row.get('visits')),
            'engaged_seconds': _to_int(row.get('engaged_seconds_total')),
            'click_count': _to_int(row.get('click_count')),
            'pages_used': _to_int(row.get('pages_used')),
        }
        for row in rows
    }
    return by_date


def _metric_daily_series(project_id, user_id, start_date, end_date, period_days):
    by_date = _daily_metric_rows(project_id, user_id, start_date, end_date)
    days = list(services._date_range(start_date, end_date))
    active_flags = []
    series = {
        'engaged_time': [],
        'active_days': [],
        'consistency': [],
        'intensity': [],
        'visits': [],
        'avg_visit': [],
        'pages_used': [],
        'interaction_rate': [],
    }

    for index, day in enumerate(days):
        row = by_date.get(day, {})
        visits = _to_int(row.get('visits'))
        engaged = _to_int(row.get('engaged_seconds'))
        clicks = _to_int(row.get('click_count'))
        pages = _to_int(row.get('pages_used'))
        active = 1 if visits > 0 or engaged > 0 else 0
        active_flags.append(active)
        window = active_flags[max(0, index - 6):index + 1]
        rolling_active = sum(window)
        rolling_days = min(7, index + 1)
        date_value = day.isoformat()

        series['engaged_time'].append({'date': date_value, 'value': engaged})
        series['active_days'].append({'date': date_value, 'value': active})
        series['consistency'].append({'date': date_value, 'value': _pct(rolling_active, rolling_days)})
        series['intensity'].append({'date': date_value, 'value': round(_ratio(engaged, active)) if active else 0})
        series['visits'].append({'date': date_value, 'value': visits})
        series['avg_visit'].append({'date': date_value, 'value': round(_ratio(engaged, visits))})
        series['pages_used'].append({'date': date_value, 'value': pages})
        series['interaction_rate'].append({'date': date_value, 'value': _pct(clicks, visits)})

    return series


def _metric_card(card_id, label, value, raw_value, previous_value, delta_type, daily_series):
    if delta_type == 'pp':
        delta_value = round((raw_value - previous_value) * 100, 1)
    elif delta_type == 'absolute':
        delta_value = round(raw_value - previous_value, 1)
    else:
        delta_value = _delta_pct_value(raw_value, previous_value)

    return {
        'id': card_id,
        'label': label,
        'value': value,
        'rawValue': raw_value,
        'previousValue': previous_value,
        'deltaValue': delta_value,
        'deltaType': delta_type,
        'dailySeries': daily_series,
        'trend': [point['value'] for point in daily_series],
    }


def _metric_cards(project_id, user_id, start_date, end_date, current, previous, period_days):
    current_metrics = _metric_row(current)
    previous_metrics = _metric_row(previous)
    current_consistency = _fraction(current_metrics['active_days'], period_days)
    previous_consistency = _fraction(previous_metrics['active_days'], period_days)
    current_interaction = _fraction(current_metrics['visits_with_click'], current_metrics['visits'])
    previous_interaction = _fraction(previous_metrics['visits_with_click'], previous_metrics['visits'])
    daily = _metric_daily_series(project_id, user_id, start_date, end_date, period_days)

    return [
        _metric_card(
            'engaged_time',
            'Engaged time',
            _format_duration(current_metrics['engaged_seconds']),
            current_metrics['engaged_seconds'],
            previous_metrics['engaged_seconds'],
            'percent',
            daily['engaged_time'],
        ),
        _metric_card(
            'active_days',
            'Active days',
            _format_number(current_metrics['active_days']),
            current_metrics['active_days'],
            previous_metrics['active_days'],
            'absolute',
            daily['active_days'],
        ),
        _metric_card(
            'consistency',
            'Consistency',
            _format_percent(current_consistency * 100),
            current_consistency,
            previous_consistency,
            'pp',
            daily['consistency'],
        ),
        _metric_card(
            'intensity',
            'Intensity',
            _format_duration(current_metrics['intensity_seconds']),
            current_metrics['intensity_seconds'],
            previous_metrics['intensity_seconds'],
            'percent',
            daily['intensity'],
        ),
        _metric_card(
            'visits',
            'Visits',
            _format_number(current_metrics['visits']),
            current_metrics['visits'],
            previous_metrics['visits'],
            'percent',
            daily['visits'],
        ),
        _metric_card(
            'avg_visit',
            'Avg / visit',
            _format_duration(current_metrics['avg_visit_seconds']),
            current_metrics['avg_visit_seconds'],
            previous_metrics['avg_visit_seconds'],
            'percent',
            daily['avg_visit'],
        ),
        _metric_card(
            'pages_used',
            'Pages used',
            _format_number(current_metrics['pages_used']),
            current_metrics['pages_used'],
            previous_metrics['pages_used'],
            'absolute',
            daily['pages_used'],
        ),
        _metric_card(
            'interaction_rate',
            'Interaction rate',
            _format_percent(current_interaction * 100),
            current_interaction,
            previous_interaction,
            'pp',
            daily['interaction_rate'],
        ),
    ]


def _daily_usage(project_id, user_id, start_date, end_date, product_areas):
    rows = (
        _base_user_queryset(project_id, start_date, end_date)
        .filter(user_id=user_id)
        .values('date', 'product_area_key')
        .annotate(
            product_area_name=Max('product_area_name'),
            visits=Sum('visits_count'),
            engaged_seconds=Sum('engaged_seconds'),
            clicks=Sum('click_count'),
        )
    )
    by_key = {
        (row['date'], row.get('product_area_key') or 'unassigned'): row
        for row in rows
    }
    output = []
    for day in services._date_range(start_date, end_date):
        for area in product_areas:
            key = area.get('id') or area.get('key') or 'unassigned'
            row = by_key.get((day, key), {})
            output.append({
                'date': day.isoformat(),
                'productAreaId': key,
                'productAreaName': row.get('product_area_name') or area.get('name') or key,
                'productAreaColor': area.get('color') or '',
                'engagedSeconds': _to_int(row.get('engaged_seconds')),
                'visits': _to_int(row.get('visits')),
                'clicks': _to_int(row.get('clicks')),
            })
    return output


def _area_usage(project_id, start_date, end_date, *, user_ids=None, company_id=None, color_lookup=None):
    queryset = _base_user_queryset(project_id, start_date, end_date)
    if user_ids is not None:
        queryset = queryset.filter(user_id__in=[str(user_id) for user_id in user_ids])
    if company_id:
        queryset = queryset.filter(company_id=company_id)
    rows = (
        queryset
        .values('user_id', 'product_area_key')
        .annotate(
            product_area_name=Max('product_area_name'),
            engaged_seconds_total=Sum('engaged_seconds'),
            visits=Sum('visits_count'),
            pages_used=Count('page_rule_id', filter=Q(visits_count__gt=0) | Q(engaged_seconds__gt=0), distinct=True),
        )
    )
    output = defaultdict(dict)
    for index, row in enumerate(rows):
        user_id = str(row.get('user_id') or '')
        area_key = row.get('product_area_key') or 'unassigned'
        if not user_id:
            continue
        area_name = row.get('product_area_name') or area_key
        color = product_area_color_from_lookup(
            color_lookup,
            {'key': area_key, 'name': area_name},
            index,
            prefer_explicit=True,
        )
        output[user_id][area_key] = {
            'productAreaId': area_key,
            'productAreaName': area_name,
            'productAreaColor': color,
            'color': color,
            'product_area_color': color,
            'engagedSeconds': _to_int(row.get('engaged_seconds_total')),
            'visits': _to_int(row.get('visits')),
            'pagesUsed': _to_int(row.get('pages_used')),
        }
    return output


class BulkUserDetailContext:
    def __init__(self, project, start_date, end_date, *, max_companies=50):
        self.project = project
        self.project_id = project.id
        self.start_date = start_date
        self.end_date = end_date
        self.max_companies = max(1, int(max_companies or 1))
        self._project_metrics = None
        self._project_visits = None
        self._project_emails = None
        self._product_areas = None
        self._product_area_catalog = None
        self._product_area_color_lookup = None
        self._company_metrics_cache = OrderedDict()
        self._company_area_usage_cache = OrderedDict()
        self._company_page_usage_cache = OrderedDict()

    def _remember_company_value(self, cache, company_id, value):
        key = str(company_id or '')
        cache[key] = value
        cache.move_to_end(key)
        if len(cache) > self.max_companies:
            cache.popitem(last=False)
        return value

    def _get_company_value(self, cache, company_id):
        key = str(company_id or '')
        if key not in cache:
            return None
        cache.move_to_end(key)
        return cache[key]

    def get_project_metrics(self):
        if self._project_metrics is None:
            self._project_metrics = _aggregate_user_metrics(self.project_id, self.start_date, self.end_date)
        return self._project_metrics

    def get_project_visits(self):
        if self._project_visits is None:
            self._project_visits = _visit_metrics(self.project, self.start_date, self.end_date)
        return self._project_visits

    def get_project_emails(self):
        if self._project_emails is None:
            user_ids = set(self.get_project_metrics()) | set(self.get_project_visits())
            self._project_emails = services.user_trait_email_lookup(
                self.project,
                self.start_date,
                self.end_date,
                user_ids=user_ids,
            )
        return self._project_emails

    def get_product_areas(self):
        if self._product_areas is None:
            self._product_areas = _product_area_options(
                self.project_id,
                self.start_date,
                self.end_date,
            )
        return self._product_areas

    def get_product_area_catalog(self):
        if self._product_area_catalog is None:
            self._product_area_catalog = services._project_product_area_options(
                self.project_id,
                self.get_product_areas(),
                include_unobserved=True,
            )
        return self._product_area_catalog

    def get_product_area_color_lookup(self):
        if self._product_area_color_lookup is None:
            self._product_area_color_lookup = build_product_area_color_lookup(
                self.get_product_area_catalog(),
                prefer_explicit=True,
            )
        return self._product_area_color_lookup

    def get_company_metrics(self, company_id):
        if not company_id:
            return {}
        cached = self._get_company_value(self._company_metrics_cache, company_id)
        if cached is not None:
            return cached
        value = _aggregate_user_metrics(self.project_id, self.start_date, self.end_date, company_id=company_id)
        return self._remember_company_value(self._company_metrics_cache, company_id, value)

    def get_company_area_usage(self, company_id):
        if not company_id:
            return {}
        cached = self._get_company_value(self._company_area_usage_cache, company_id)
        if cached is not None:
            return cached
        value = _area_usage(
            self.project_id,
            self.start_date,
            self.end_date,
            company_id=company_id,
            color_lookup=self.get_product_area_color_lookup(),
        )
        return self._remember_company_value(self._company_area_usage_cache, company_id, value)

    def get_company_page_usage(self, company_id):
        if not company_id:
            return []
        cached = self._get_company_value(self._company_page_usage_cache, company_id)
        if cached is not None:
            return cached
        value = list(
            _base_user_queryset(self.project_id, self.start_date, self.end_date)
            .filter(company_id=company_id)
            .values('user_id', 'page_rule_id')
            .annotate(
                visits=Sum('visits_count'),
                engaged_seconds=Sum('engaged_seconds'),
            )
        )
        return self._remember_company_value(self._company_page_usage_cache, company_id, value)


def _top_area_row(area_rows):
    rows = sorted(
        area_rows.values() if isinstance(area_rows, dict) else area_rows,
        key=lambda row: (-_to_int(row.get('engagedSeconds')), row.get('productAreaName') or ''),
    )
    return rows[0] if rows else {}


def _top_area(area_rows):
    return _top_area_row(area_rows).get('productAreaName') or ''


def _peer_comparison_rows(
    project,
    selected_user_id,
    company_id,
    company_name,
    start_date,
    end_date,
    previous_start,
    previous_end,
    product_areas,
    product_area_color_lookup=None,
    bulk_context=None,
    previous_bulk_context=None,
):
    if bulk_context and previous_bulk_context and company_id:
        current = dict(bulk_context.get_company_metrics(company_id))
        previous_project_metrics = previous_bulk_context.get_project_metrics()
        previous = {
            user_id: previous_project_metrics[user_id]
            for user_id in set(current) | {selected_user_id}
            if user_id in previous_project_metrics
        }
        visits = bulk_context.get_project_visits()
        email_lookup = {
            **previous_bulk_context.get_project_emails(),
            **bulk_context.get_project_emails(),
        }
        area_by_user = bulk_context.get_company_area_usage(company_id)
    else:
        current = _aggregate_user_metrics(project.id, start_date, end_date, company_id=company_id)
        previous = _aggregate_user_metrics(
            project.id,
            previous_start,
            previous_end,
            user_ids=set(current.keys()) | {selected_user_id},
        )
        user_ids = sorted(set(current) | {selected_user_id})
        visits = _visit_metrics(project, start_date, end_date, user_ids=user_ids)
        email_lookup = services.user_trait_email_lookup(project, previous_start, end_date, user_ids=user_ids)
        area_by_user = _area_usage(
            project.id,
            start_date,
            end_date,
            user_ids=user_ids,
            color_lookup=product_area_color_lookup,
        )

    if selected_user_id not in current:
        if bulk_context:
            selected_current = bulk_context.get_project_metrics().get(selected_user_id)
        else:
            selected_current = _aggregate_user_metrics(project.id, start_date, end_date, user_ids=[selected_user_id]).get(selected_user_id)
        if selected_current:
            current[selected_user_id] = selected_current
    if selected_user_id not in previous:
        if previous_bulk_context:
            selected_previous = previous_bulk_context.get_project_metrics().get(selected_user_id)
        else:
            selected_previous = _aggregate_user_metrics(project.id, previous_start, previous_end, user_ids=[selected_user_id]).get(selected_user_id)
        if selected_previous:
            previous[selected_user_id] = selected_previous
    user_ids = sorted(set(current) | {selected_user_id})

    rows = []
    period_days = (end_date - start_date).days + 1
    for user_id in user_ids:
        row = current.get(user_id, {})
        previous_row = previous.get(user_id, {})
        visit_row = visits.get(user_id, {})
        metrics = _metric_row(row, visit_row)
        resolved_company_id = row.get('company_id') or visit_row.get('company_id') or company_id or ''
        resolved_company_name = visit_row.get('company_name') or (company_name if resolved_company_id == company_id else resolved_company_id) or 'Unknown company'
        name = row.get('user_name') or visit_row.get('user_name') or _name_from_user_id(user_id)
        area_rows = area_by_user.get(user_id, {})
        adoption = []
        for area in product_areas:
            area_key = area.get('id') or area.get('key') or 'unassigned'
            area_row = area_rows.get(area_key, {})
            adoption.append({
                'productAreaId': area_key,
                'productAreaName': area.get('name') or area_key,
                'productAreaColor': area.get('color') or '',
                'engagedSeconds': _to_int(area_row.get('engagedSeconds')),
                'visits': _to_int(area_row.get('visits')),
                'pagesUsed': _to_int(area_row.get('pagesUsed')),
            })
        top_area = _top_area_row(area_rows)
        status = _status_key(row, previous_row, period_days=period_days, first_seen_at=visit_row.get('first_visit_ts'), end_date=end_date)
        rows.append({
            'userId': user_id,
            'id': user_id,
            'name': name,
            'email': _email_for_user(user_id, email_lookup),
            'companyId': resolved_company_id,
            'companyName': resolved_company_name,
            'role': '',
            'seatType': '',
            'status': status,
            'engagedSeconds': metrics['engaged_seconds'],
            'engagedDeltaPct': _delta_pct_value(metrics['engaged_seconds'], previous_row.get('engaged_seconds')),
            'activeDays': metrics['active_days'],
            'consistency': _fraction(metrics['active_days'], period_days),
            'intensitySecondsPerActiveDay': metrics['intensity_seconds'],
            'sessionsCount': metrics['sessions_count'],
            'visits': metrics['visits'],
            'visitsDeltaPct': _delta_pct_value(metrics['visits'], previous_row.get('visits')),
            'pagesUsed': metrics['pages_used'],
            'topArea': top_area.get('productAreaName') or '',
            'topAreaId': top_area.get('productAreaId') or '',
            'topAreaColor': top_area.get('productAreaColor') or '',
            'productAreaAdoption': adoption,
            'interactionRate': _fraction(metrics['visits_with_click'], metrics['visits']),
            'rank': 0,
            'isCurrentUser': user_id == selected_user_id,
        })

    rows.sort(key=lambda item: (-item['engagedSeconds'], -item['visits'], item['name']))
    for index, row in enumerate(rows, start=1):
        row['rank'] = index
    return rows


def _product_area_mix(selected_user_id, peer_rows, product_areas):
    current_row = next((row for row in peer_rows if row.get('userId') == selected_user_id), None)
    current_adoption = {
        item.get('productAreaId'): item
        for item in (current_row or {}).get('productAreaAdoption') or []
    }
    peer_adoptions = [
        {
            item.get('productAreaId'): item
            for item in row.get('productAreaAdoption') or []
        }
        for row in peer_rows
        if row.get('userId') != selected_user_id
    ]
    user_total = sum(_to_int(item.get('engagedSeconds')) for item in current_adoption.values())
    output = []
    peer_top_scores = defaultdict(list)

    for area in product_areas:
        area_key = area.get('id') or area.get('key') or 'unassigned'
        user_area = current_adoption.get(area_key, {})
        user_engaged = _to_int(user_area.get('engagedSeconds'))
        user_share = _pct(user_engaged, user_total)
        peer_shares = []
        peer_engaged_values = []
        for adoption in peer_adoptions:
            peer_area = adoption.get(area_key, {})
            peer_engaged = _to_int(peer_area.get('engagedSeconds'))
            peer_total = sum(_to_int(item.get('engagedSeconds')) for item in adoption.values())
            peer_shares.append(_pct(peer_engaged, peer_total))
            peer_engaged_values.append(peer_engaged)
            if peer_engaged:
                peer_top_scores[area.get('name') or area_key].append(peer_engaged)
        peer_median_share = round(median(peer_shares), 1) if peer_shares else 0
        peer_median_engaged = round(median(peer_engaged_values)) if peer_engaged_values else 0
        output.append({
            'productAreaId': area_key,
            'productAreaName': area.get('name') or area_key,
            'productAreaColor': area.get('color') or '',
            'userSharePct': user_share,
            'peerMedianSharePct': peer_median_share,
            'deltaPp': round(user_share - peer_median_share, 1),
            'userEngagedSeconds': user_engaged,
            'peerMedianEngagedSeconds': peer_median_engaged,
            'deltaPct': _delta_pct_value(user_engaged, peer_median_engaged),
        })

    peer_area_medians = [
        (area_name, median(values))
        for area_name, values in peer_top_scores.items()
        if values
    ]
    peer_area_medians.sort(key=lambda item: (-item[1], item[0]))
    return output, (peer_area_medians[0][0] if peer_area_medians else '')


def _selected_page_visit_metrics(project, user_id, start_date, end_date):
    rows = (
        _visit_queryset(project, start_date, end_date)
        .filter(user_id=user_id)
        .values('page_rule_id')
        .annotate(
            visits_with_click=Count('id', filter=Q(had_click=True)),
            first_used_at=Min('visit_start_ts'),
            last_used_at=Max('visit_start_ts'),
        )
    )
    return {
        row.get('page_rule_id'): {
            'visits_with_click': _to_int(row.get('visits_with_click')),
            'first_used_at': row.get('first_used_at'),
            'last_used_at': row.get('last_used_at'),
        }
        for row in rows
    }


def _page_usage_rows(
    project,
    user_id,
    company_id,
    start_date,
    end_date,
    previous_start,
    previous_end,
    product_areas,
    product_area_color_lookup=None,
    bulk_context=None,
):
    rows = list(
        _base_user_queryset(project.id, start_date, end_date)
        .filter(user_id=user_id)
        .values('page_rule_id', 'product_area_key')
        .annotate(
            product_area_name=Max('product_area_name'),
            visits=Sum('visits_count'),
            engaged_seconds=Sum('engaged_seconds'),
            clicks=Sum('click_count'),
            first_used_date=Min('date'),
            last_used_date=Max('date'),
        )
        .order_by('-engaged_seconds', '-visits')
    )
    previous_rows = (
        _base_user_queryset(project.id, previous_start, previous_end)
        .filter(user_id=user_id)
        .values('page_rule_id')
        .annotate(
            visits=Sum('visits_count'),
            engaged_seconds=Sum('engaged_seconds'),
            clicks=Sum('click_count'),
        )
    )
    previous_by_page = {row.get('page_rule_id'): row for row in previous_rows}
    rule_names = _page_rule_names(project.id, {row.get('page_rule_id') for row in rows})
    visit_metrics = _selected_page_visit_metrics(project, user_id, start_date, end_date)
    if bulk_context and company_id:
        active_peer_ids = set(bulk_context.get_company_metrics(company_id)) - {user_id}
        peer_page_rows = [
            row
            for row in bulk_context.get_company_page_usage(company_id)
            if str(row.get('user_id') or '') in active_peer_ids
        ]
    else:
        active_peer_ids = set(
            _base_user_queryset(project.id, start_date, end_date)
            .filter(company_id=company_id)
            .exclude(user_id=user_id)
            .values_list('user_id', flat=True)
            .distinct()
        ) if company_id else set()
        peer_page_rows = (
            _base_user_queryset(project.id, start_date, end_date)
            .filter(company_id=company_id, user_id__in=active_peer_ids)
            .values('page_rule_id', 'user_id')
            .annotate(visits=Sum('visits_count'))
        ) if active_peer_ids else []
    peer_page_users = defaultdict(set)
    peer_page_visits = defaultdict(list)
    for row in peer_page_rows:
        page_rule_id = row.get('page_rule_id')
        visits = _to_int(row.get('visits'))
        if visits <= 0:
            continue
        peer_page_users[page_rule_id].add(row.get('user_id'))
        peer_page_visits[page_rule_id].append(visits)
    missing_rule_ids = set(peer_page_users) - set(rule_names)
    if missing_rule_ids:
        rule_names = {**rule_names, **_page_rule_names(project.id, missing_rule_ids)}

    area_by_key = {area.get('id') or area.get('key'): area for area in product_areas}
    total_user_engaged = sum(_to_int(row.get('engaged_seconds')) for row in rows)
    output = []
    for row in rows:
        page_rule_id = row.get('page_rule_id')
        area_key = row.get('product_area_key') or 'unassigned'
        area = area_by_key.get(area_key, {})
        rule = rule_names.get(page_rule_id) or {}
        product_area_name = row.get('product_area_name') or area.get('name') or rule.get('product_area') or 'Unassigned'
        product_area_color = product_area_color_from_lookup(
            product_area_color_lookup,
            {'key': area_key, 'name': product_area_name},
            len(output),
            prefer_explicit=True,
        )
        page_name = rule.get('page_name') or product_area_name or str(page_rule_id or 'Page')
        visits = _to_int(row.get('visits'))
        engaged = _to_int(row.get('engaged_seconds'))
        clicks = _to_int(row.get('clicks'))
        previous = previous_by_page.get(page_rule_id, {})
        page_visits = visit_metrics.get(page_rule_id, {})
        visits_with_click = _to_int(page_visits.get('visits_with_click')) or min(visits, clicks)
        avg_visit = round(_ratio(engaged, visits))
        previous_avg_visit = round(_ratio(previous.get('engaged_seconds'), previous.get('visits')))
        interaction = _pct(visits_with_click, visits)
        previous_interaction = _pct(previous.get('clicks'), previous.get('visits'))
        first_used = page_visits.get('first_used_at') or row.get('first_used_date')
        last_used = page_visits.get('last_used_at') or row.get('last_used_date')
        peer_usage_pct = _pct(len(peer_page_users.get(page_rule_id, set())), len(active_peer_ids))

        output.append({
            'pageRuleId': str(page_rule_id or f'{area_key}:unmatched'),
            'pageName': page_name,
            'productAreaId': area_key,
            'productAreaName': product_area_name,
            'productArea': product_area_name,
            'productAreaColor': product_area_color,
            'color': product_area_color,
            'product_area_color': product_area_color,
            'visits': visits,
            'visitsDeltaPct': _delta_pct_value(visits, previous.get('visits')),
            'shareOfUserTimePct': _pct(engaged, total_user_engaged),
            'engagedSeconds': engaged,
            'engagedDeltaPct': _delta_pct_value(engaged, previous.get('engaged_seconds')),
            'avgVisitSeconds': avg_visit,
            'avgVisitDeltaPct': _delta_pct_value(avg_visit, previous_avg_visit),
            'interactionPct': interaction,
            'interactionRate': interaction / 100,
            'interactionDeltaPp': _delta_pp_value(interaction, previous_interaction),
            'firstUsedAt': _safe_iso(first_used),
            'lastUsedAt': _safe_iso(last_used),
            'peerUsagePct': peer_usage_pct,
            'peerMedianVisits': round(median(peer_page_visits.get(page_rule_id, [0]))),
            'trend': [],
        })

    output.sort(key=lambda item: (-item['engagedSeconds'], -item['visits'], item['pageName']))
    return output, _underused_pages(
        peer_page_users,
        peer_page_visits,
        active_peer_ids,
        rule_names,
        product_areas,
        output,
        product_area_color_lookup,
    )


def _underused_pages(
    peer_page_users,
    peer_page_visits,
    active_peer_ids,
    rule_names,
    product_areas,
    pages_used,
    product_area_color_lookup=None,
):
    if not active_peer_ids:
        return []
    used_by_page = {row.get('pageRuleId'): row for row in pages_used}
    area_by_name = {area.get('name'): area for area in product_areas}
    rows = []
    for page_rule_id, peer_users in peer_page_users.items():
        peer_usage_pct = _pct(len(peer_users), len(active_peer_ids))
        if peer_usage_pct < 40:
            continue
        used = used_by_page.get(str(page_rule_id))
        visits = _to_int(used.get('visits')) if used else 0
        peer_median_visits = round(median(peer_page_visits.get(page_rule_id, [0])))
        if visits and (not peer_median_visits or visits >= peer_median_visits * 0.35):
            continue
        rule = rule_names.get(page_rule_id) or {}
        page_name = rule.get('page_name') or str(page_rule_id or 'Page')
        product_area_name = rule.get('product_area') or (used or {}).get('productAreaName') or 'Unassigned'
        area = area_by_name.get(product_area_name) or {}
        product_area_id = area.get('id') or area.get('key') or (used or {}).get('productAreaId') or ''
        product_area_color = product_area_color_from_lookup(
            product_area_color_lookup,
            {'key': product_area_id, 'name': product_area_name},
            len(rows),
            prefer_explicit=True,
        )
        rows.append({
            'pageRuleId': str(page_rule_id or ''),
            'pageName': page_name,
            'productAreaId': product_area_id,
            'productAreaName': product_area_name,
            'productAreaColor': product_area_color,
            'color': product_area_color,
            'product_area_color': product_area_color,
            'peerUsagePct': peer_usage_pct,
            'peerMedianVisits': peer_median_visits,
            'userUsageLabel': f'{visits} visits' if visits else '0 visits',
            'whyItMatters': 'Common among company peers',
        })
    rows.sort(key=lambda item: (-item['peerUsagePct'], item['pageName']))
    return rows[:6]


def _recommendation(priority, type_key, action, reason, evidence, related_label, owner='CSM', **extra):
    return {
        'id': extra.pop('id', f"{type_key}_{abs(hash((action, evidence))) % 100000}"),
        'priority': priority,
        'type': type_key,
        'action': action,
        'reason': reason,
        'evidence': evidence,
        'relatedLabel': related_label,
        'owner': owner,
        'status': 'open',
        **extra,
    }


def _recommended_actions(metric_cards, product_area_mix, pages_used, underused_pages, peer_rows, selected_user_id, user_metrics):
    actions = []
    engaged_card = next((card for card in metric_cards if card['id'] == 'engaged_time'), None)
    pages_card = next((card for card in metric_cards if card['id'] == 'pages_used'), None)
    current_rank = next((row.get('rank') for row in peer_rows if row.get('userId') == selected_user_id), None)
    rank_pct = round((current_rank or len(peer_rows) or 1) / max(len(peer_rows), 1) * 100)

    if engaged_card and engaged_card.get('deltaValue', 0) <= -30:
        delta = round(engaged_card['deltaValue'])
        actions.append(_recommendation(
            'high' if delta <= -40 else 'medium',
            'usage_drop',
            'Reach out about usage drop',
            'Activity dropped sharply',
            f'Engaged {delta}% vs previous period',
            'Overall usage',
            'CSM',
            sortScore=abs(delta),
        ))

    for page in underused_pages[:3]:
        priority = 'high' if page['peerUsagePct'] >= 75 else 'medium'
        actions.append(_recommendation(
            priority,
            'underused_page',
            f"Offer enablement on {page['pageName']}",
            'Peers commonly use this page, this user does not',
            f"{page['pageName']}: {round(page['peerUsagePct'])}% peer usage, {page['userUsageLabel']}",
            f"{page['pageName']} · {page['productAreaName']}",
            'CSM',
            relatedPageName=page['pageName'],
            relatedProductAreaName=page['productAreaName'],
            relatedProductAreaColor=page.get('productAreaColor') or '',
            sortScore=page['peerUsagePct'],
        ))

    unusual = sorted(product_area_mix, key=lambda row: abs(row.get('deltaPp') or 0), reverse=True)
    if unusual and abs(unusual[0].get('deltaPp') or 0) >= 18:
        area = unusual[0]
        delta = round(area['deltaPp'])
        owner = 'Sales' if area['productAreaName'] in {'Billing', 'Administration', 'Seats', 'Team', 'Plan'} else 'Product'
        actions.append(_recommendation(
            'medium',
            'unusual_usage',
            f"{'Validate' if delta > 0 else 'Review low'} {area['productAreaName']} usage",
            'Usage mix differs from peers',
            f'{services._format_signed(delta, " pp")} vs peer median share',
            area['productAreaName'],
            owner,
            relatedProductAreaName=area['productAreaName'],
            relatedProductAreaColor=area.get('productAreaColor') or '',
            sortScore=abs(delta),
        ))

    friction = sorted(
        [page for page in pages_used if page.get('visits', 0) >= 10 and page.get('interactionRate', 0) < 0.22],
        key=lambda page: -page.get('visits', 0),
    )
    if friction:
        page = friction[0]
        actions.append(_recommendation(
            'medium',
            'friction_signal',
            f"Investigate friction on {page['pageName']}",
            'High visits, low interaction',
            f"{page['visits']} visits, {round(page['interactionRate'] * 100)}% interaction",
            f"{page['pageName']} · {page['productAreaName']}",
            'Product',
            relatedPageName=page['pageName'],
            relatedProductAreaName=page['productAreaName'],
            relatedProductAreaColor=page.get('productAreaColor') or '',
            sortScore=page['visits'],
        ))

    if rank_pct <= 10 and user_metrics.get('consistency', 0) >= 0.5 and user_metrics.get('pagesUsed', 0) >= 3:
        actions.append(_recommendation(
            'low',
            'champion_signal',
            'Mark as potential champion',
            'High consistency and broad page usage',
            f"Top {max(1, rank_pct)}% by engaged time, {user_metrics.get('pagesUsed', 0)} pages used",
            'Overall',
            'CSM',
            sortScore=100 - rank_pct,
        ))

    if pages_card and pages_card.get('deltaValue', 0) <= -2:
        actions.append(_recommendation(
            'medium',
            'activation_gap',
            'Review activation gap',
            'Page breadth declined',
            f"Pages used {int(pages_card['deltaValue'])} vs previous period",
            'Overall activation',
            'CSM',
            sortScore=abs(pages_card['deltaValue']),
        ))

    if not actions and user_metrics.get('visits', 0) > 0:
        actions.append(_recommendation(
            'low',
            'activation_gap',
            'Monitor next period',
            'Usage is near peer baseline',
            f"{_format_duration(user_metrics.get('engagedSeconds', 0))} engaged, {user_metrics.get('activeDays', 0)} active days",
            'Overall',
            'CSM',
            sortScore=user_metrics.get('engagedSeconds', 0),
        ))

    order = {'high': 0, 'medium': 1, 'low': 2}
    type_order = {
        'usage_drop': 0,
        'underused_page': 1,
        'friction_signal': 2,
        'unusual_usage': 3,
        'activation_gap': 4,
        'champion_signal': 5,
    }
    seen = set()
    unique = []
    for action in actions:
        key = (action['type'], action.get('relatedPageName') or '', action.get('relatedProductAreaName') or action.get('relatedLabel') or '')
        if key in seen:
            continue
        seen.add(key)
        unique.append(action)

    unique.sort(key=lambda action: (order.get(action['priority'], 9), type_order.get(action['type'], 9), -_to_float(action.get('sortScore'))))
    return [{key: value for key, value in action.items() if key != 'sortScore'} for action in unique[:6]]


def _insights(selected_user_id, metric_cards, product_area_mix, underused_pages, peer_rows, peer_area_median_top):
    output = []
    current_rank = next((row.get('rank') for row in peer_rows if row.get('userId') == selected_user_id), None)
    if current_rank and peer_rows:
        rank_pct = round(current_rank / len(peer_rows) * 100)
        if rank_pct <= 15:
            output.append(f'This user is in the top {max(1, rank_pct)}% by engaged time among company peers.')
        elif rank_pct >= 65:
            output.append('This user is below the engaged-time median for company peers.')
    engaged_card = next((card for card in metric_cards if card['id'] == 'engaged_time'), None)
    if engaged_card and engaged_card.get('deltaValue', 0) <= -25:
        output.append(f"Usage dropped {abs(round(engaged_card['deltaValue']))}% versus the previous period.")
    unusual = sorted(product_area_mix, key=lambda row: abs(row.get('deltaPp') or 0), reverse=True)
    if unusual and abs(unusual[0].get('deltaPp') or 0) >= 12:
        area = unusual[0]
        direction = 'more' if area['deltaPp'] > 0 else 'less'
        contrast = f', while peers lean toward {peer_area_median_top}' if peer_area_median_top and peer_area_median_top != area['productAreaName'] else ''
        output.append(f"Usage is unusually weighted toward {area['productAreaName']}: {abs(round(area['deltaPp']))}pp {direction} than peers{contrast}.")
    if underused_pages:
        page = underused_pages[0]
        output.append(f"{page['pageName']} is common among peers, but this user has {page['userUsageLabel'].lower()}.")
    return output[:4] or ['Usage is close to the company peer baseline across engagement, breadth, and interaction.']


def _users_for_switcher(
    project,
    start_date,
    end_date,
    previous_start,
    previous_end,
    selected_user_id,
    bulk_context=None,
    previous_bulk_context=None,
):
    if bulk_context and previous_bulk_context:
        current = bulk_context.get_project_metrics()
        previous = previous_bulk_context.get_project_metrics()
        visits = bulk_context.get_project_visits()
        email_lookup = {
            **previous_bulk_context.get_project_emails(),
            **bulk_context.get_project_emails(),
        }
    else:
        current = _aggregate_user_metrics(project.id, start_date, end_date)
        previous = _aggregate_user_metrics(project.id, previous_start, previous_end)
        user_ids = list((set(current) | set(previous) | {selected_user_id}))
        visits = _visit_metrics(project, start_date, end_date, user_ids=user_ids)
        email_lookup = services.user_trait_email_lookup(project, previous_start, end_date, user_ids=user_ids)
    user_ids = list((set(current) | set(previous) | {selected_user_id}))
    rows = []
    period_days = (end_date - start_date).days + 1

    for user_id in user_ids:
        row = current.get(user_id) or previous.get(user_id) or {}
        visit_row = visits.get(user_id, {})
        company_id = row.get('company_id') or visit_row.get('company_id') or ''
        company_name = visit_row.get('company_name') or company_id or 'Unknown company'
        name = row.get('user_name') or visit_row.get('user_name') or _name_from_user_id(user_id)
        metrics = _metric_row(current.get(user_id, {}), visit_row)
        rows.append({
            'id': user_id,
            'name': name,
            'email': _email_for_user(user_id, email_lookup),
            'companyId': company_id,
            'companyName': company_name,
            'role': '',
            'seatType': '',
            'firstSeenAt': _safe_iso(visit_row.get('first_visit_ts') or row.get('first_seen_date')),
            'lastActiveAt': _safe_iso(visit_row.get('last_visit_ts') or row.get('last_seen_date')),
            'status': _status_key(current.get(user_id, {}), previous.get(user_id, {}), period_days=period_days, first_seen_at=visit_row.get('first_visit_ts'), end_date=end_date),
            'engagedSeconds': metrics['engaged_seconds'],
        })

    rows.sort(key=lambda item: (item['companyName'], item['name']))
    selected = [row for row in rows if row['id'] == selected_user_id]
    others = [row for row in rows if row['id'] != selected_user_id]
    return (selected + others)[:USER_DETAIL_USERS_LIMIT]


def build_user_detail_payload(project, user_id, *, range_key='last_30_days', bulk_context=None, previous_bulk_context=None):
    user_id = str(user_id or '').strip()
    if not user_id:
        return None

    start_date, end_date = services.resolve_period(project.timezone, range_key=range_key)
    previous_start, previous_end = services.previous_period(start_date, end_date)
    period_days = (end_date - start_date).days + 1
    if bulk_context and previous_bulk_context:
        current = bulk_context.get_project_metrics().get(user_id, {})
        previous = previous_bulk_context.get_project_metrics().get(user_id, {})
        current_visits = bulk_context.get_project_visits().get(user_id, {})
        previous_visits = previous_bulk_context.get_project_visits().get(user_id, {})
        email_lookup = {
            **previous_bulk_context.get_project_emails(),
            **bulk_context.get_project_emails(),
        }
        product_areas = bulk_context.get_product_areas()
        product_area_color_lookup = bulk_context.get_product_area_color_lookup()
    else:
        current = _aggregate_user_metrics(project.id, start_date, end_date, user_ids=[user_id]).get(user_id, {})
        previous = _aggregate_user_metrics(project.id, previous_start, previous_end, user_ids=[user_id]).get(user_id, {})
        current_visits = _visit_metrics(project, start_date, end_date, user_ids=[user_id]).get(user_id, {})
        previous_visits = _visit_metrics(project, previous_start, previous_end, user_ids=[user_id]).get(user_id, {})
        email_lookup = services.user_trait_email_lookup(project, previous_start, end_date, user_ids=[user_id])
        product_areas = _product_area_options(
            project.id,
            start_date,
            end_date,
        )
        product_area_catalog = services._project_product_area_options(
            project.id,
            product_areas,
            include_unobserved=True,
        )
        product_area_color_lookup = build_product_area_color_lookup(
            product_area_catalog,
            prefer_explicit=True,
        )
    lifetime = _selected_lifetime_identity(project, user_id)

    if not current and not previous and not lifetime:
        return None

    company_id = current.get('company_id') or previous.get('company_id') or current_visits.get('company_id') or previous_visits.get('company_id') or lifetime.get('company_id') or ''
    company_name = current_visits.get('company_name') or previous_visits.get('company_name') or lifetime.get('company_name') or company_id or 'Unknown company'
    name = current.get('user_name') or previous.get('user_name') or current_visits.get('user_name') or previous_visits.get('user_name') or lifetime.get('user_name') or _name_from_user_id(user_id)
    metric_cards = _metric_cards(project.id, user_id, start_date, end_date, current, previous, period_days)
    selected_metrics = _metric_row(current, current_visits)
    previous_metrics = _metric_row(previous, previous_visits)
    peer_rows = _peer_comparison_rows(
        project,
        user_id,
        company_id,
        company_name,
        start_date,
        end_date,
        previous_start,
        previous_end,
        product_areas,
        product_area_color_lookup=product_area_color_lookup,
        bulk_context=bulk_context,
        previous_bulk_context=previous_bulk_context,
    )
    product_area_mix, peer_area_median_top = _product_area_mix(user_id, peer_rows, product_areas)
    pages_used, underused_pages = _page_usage_rows(
        project,
        user_id,
        company_id,
        start_date,
        end_date,
        previous_start,
        previous_end,
        product_areas,
        product_area_color_lookup=product_area_color_lookup,
        bulk_context=bulk_context,
    )
    consistency = _fraction(selected_metrics['active_days'], period_days)
    interaction_rate = _fraction(selected_metrics['visits_with_click'], selected_metrics['visits'])
    user_metrics = {
        'engagedSeconds': selected_metrics['engaged_seconds'],
        'activeDays': selected_metrics['active_days'],
        'periodDays': period_days,
        'consistency': consistency,
        'intensitySecondsPerActiveDay': selected_metrics['intensity_seconds'],
        'visits': selected_metrics['visits'],
        'avgVisitSeconds': selected_metrics['avg_visit_seconds'],
        'pagesUsed': selected_metrics['pages_used'],
        'interactionRate': interaction_rate,
        'visitsWithClick': selected_metrics['visits_with_click'],
    }
    selected_user = {
        'id': user_id,
        'name': name,
        'email': _email_for_user(user_id, email_lookup),
        'companyId': company_id,
        'companyName': company_name,
        'role': '',
        'seatType': '',
        'firstSeenAt': _safe_iso(lifetime.get('first_seen_at') or current_visits.get('first_visit_ts') or current.get('first_seen_date') or previous.get('first_seen_date')),
        'lastActiveAt': _safe_iso(lifetime.get('last_active_at') or current_visits.get('last_visit_ts') or current.get('last_seen_date') or previous.get('last_seen_date')),
        'status': _status_key(current, previous, period_days=period_days, first_seen_at=lifetime.get('first_seen_at') or current_visits.get('first_visit_ts'), end_date=end_date),
    }
    recommended_actions = _recommended_actions(metric_cards, product_area_mix, pages_used, underused_pages, peer_rows, user_id, user_metrics)

    return {
        'schema_version': USER_DETAILS_PAYLOAD_SCHEMA_VERSION,
        'project': {'id': project.id, 'name': project.name},
        'period': {
            'range_key': range_key,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'previous_start_date': previous_start.isoformat(),
            'previous_end_date': previous_end.isoformat(),
            'days': period_days,
        },
        'periodDays': period_days,
        'peerGroup': 'company',
        'peerGroupLabel': 'company peers',
        'selectedUser': selected_user,
        'users': _users_for_switcher(
            project,
            start_date,
            end_date,
            previous_start,
            previous_end,
            user_id,
            bulk_context=bulk_context,
            previous_bulk_context=previous_bulk_context,
        ),
        'productAreas': product_areas,
        'metricCards': metric_cards,
        'userMetrics': user_metrics,
        'previousUserMetrics': {
            'engagedSeconds': previous_metrics['engaged_seconds'],
            'activeDays': previous_metrics['active_days'],
            'visits': previous_metrics['visits'],
            'pagesUsed': previous_metrics['pages_used'],
            'interactionRate': _fraction(previous_metrics['visits_with_click'], previous_metrics['visits']),
        },
        'dailyUsage': _daily_usage(project.id, user_id, start_date, end_date, product_areas),
        'productAreaMix': product_area_mix,
        'peerComparison': peer_rows,
        'companyPeerComparison': [row for row in peer_rows if row.get('companyId') == company_id],
        'peerAreaMedianTop': peer_area_median_top,
        'pagesUsed': pages_used,
        'underusedPages': underused_pages,
        'recommendedActions': recommended_actions,
        'insights': _insights(user_id, metric_cards, product_area_mix, underused_pages, peer_rows, peer_area_median_top),
        'recentActivity': [],
        'emptyState': {
            'peers': 'No peers available. There are no active users in this peer group during the selected period.',
            'pages': 'No pages used. This user did not use any grouped pages/features during the selected period.',
            'actions': 'No recommended next steps. This user does not currently show usage drops, peer gaps, or unusual activity patterns.',
        },
    }


def is_current_user_details_payload_schema(schema_version):
    try:
        return int(schema_version) == USER_DETAILS_PAYLOAD_SCHEMA_VERSION
    except (TypeError, ValueError):
        return False


def get_cached_user_detail_payload(project_id, user_id, range_key='last_30_days', filters_hash=services.DEFAULT_FILTERS_HASH):
    row = (
        UsersDetailCache.objects
        .filter(project_id=project_id, range_key=range_key, user_id=str(user_id or '').strip(), filters_hash=filters_hash)
        .values('payload_json', 'is_stale', 'generated_at', 'expires_at', 'start_date', 'end_date')
        .first()
    )
    if not row:
        return None
    payload = services._coerce_json(row.get('payload_json'))
    row['payload_json'] = payload
    row['schema_version'] = payload.get('schema_version') if isinstance(payload, dict) else None
    return row


def build_user_detail_cache(
    project_id,
    user_id,
    *,
    range_key='last_30_days',
    project=None,
    generated_at=None,
    expires_at=None,
    bulk_context=None,
    previous_bulk_context=None,
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
                    'user_id': str(user_id or '').strip(),
                }
            return build_user_detail_cache(
                project_id,
                user_id,
                range_key=range_key,
                project=project,
                generated_at=generated_at,
                expires_at=expires_at,
                bulk_context=bulk_context,
                previous_bulk_context=previous_bulk_context,
                use_lock=False,
            )

    project = project or Project.active.filter(pk=project_id).first()
    if project is None:
        raise ValueError(f'Project {project_id} does not exist.')

    payload = build_user_detail_payload(
        project,
        user_id,
        range_key=range_key,
        bulk_context=bulk_context,
        previous_bulk_context=previous_bulk_context,
    )
    if not payload:
        return {
            'status': 'not_found',
            'project_id': project_id,
            'range_key': range_key,
            'user_id': str(user_id or '').strip(),
        }

    period = payload.get('period') or {}
    start_date = services._safe_date(period.get('start_date'))
    end_date = services._safe_date(period.get('end_date'))
    generated_at = generated_at or django_timezone.now()
    expires_at = expires_at or generated_at + services.CACHE_TTL
    payload['freshness'] = {
        'generated_at': generated_at.isoformat(),
        'is_stale': False,
        'pending_rebuild': False,
    }

    UsersDetailCache.objects.update_or_create(
        project_id=project_id,
        range_key=range_key,
        user_id=str(user_id or '').strip(),
        filters_hash=services.DEFAULT_FILTERS_HASH,
        defaults={
            'start_date': start_date,
            'end_date': end_date,
            'payload_json': json.loads(json.dumps(payload, default=services._json_default)),
            'generated_at': generated_at,
            'expires_at': expires_at,
            'is_stale': False,
        },
    )
    return {
        'status': 'success',
        'project_id': project_id,
        'range_key': range_key,
        'user_id': str(user_id or '').strip(),
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'peer_rows_count': len(payload.get('peerComparison') or []),
        'pages_count': len(payload.get('pagesUsed') or []),
        'actions_count': len(payload.get('recommendedActions') or []),
    }
