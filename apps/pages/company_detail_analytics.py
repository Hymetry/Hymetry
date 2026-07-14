import re
from collections import Counter, defaultdict
from datetime import date, timedelta

from django.db.models import Count, Max, Min, Q, Sum

from apps.pages import services
from apps.pages.models import PageCompanyDailyMetric, PageUserDailyMetric, PageVisit, ProductArea
from apps.pages.product_area_colors import (
    apply_product_area_metadata_colors,
    build_product_area_color_lookup,
    resolve_product_area_colors,
)
from apps.tracker.models import ProjectPageRule


COMPANY_DETAIL_PAYLOAD_SCHEMA_VERSION = 14
AT_RISK_USER_LOOKBACK_DAYS = 90
PEER_OPTIONAL_METADATA_CANDIDATE_LIMIT = 80
USER_HEALTH_STATUSES = (
    ('power', 'Power'),
    ('healthy', 'Healthy'),
    ('light', 'Light'),
    ('passive', 'Passive'),
    ('dropped', 'Dropped'),
)
PRODUCT_AREA_ROLE_ORDER = {
    ProductArea.AREA_ROLE_PRODUCT: 0,
    ProductArea.AREA_ROLE_SETUP: 1,
    ProductArea.AREA_ROLE_ADMIN: 2,
    ProductArea.AREA_ROLE_SUPPORT: 3,
    ProductArea.AREA_ROLE_SYSTEM: 4,
    ProductArea.AREA_ROLE_UNKNOWN: 5,
}


def _area_slug(value):
    slug = re.sub(r'[^0-9a-z]+', '-', str(value or '').strip().lower()).strip('-')
    return slug or 'unassigned'


def _period_days(range_key):
    return {
        'last_7_days': 7,
        'last_30_days': 30,
        'last_90_days': 90,
        'last_180_days': 180,
    }.get(range_key, 30)


def _detail_period_key(range_key):
    return f'{_period_days(range_key)}d'


def _to_int(value):
    return int(value or 0)


def _safe_pct(numerator, denominator):
    denominator = float(denominator or 0)
    if denominator <= 0:
        return 0
    return round((float(numerator or 0) / denominator) * 100)


def _avg(numerator, denominator):
    denominator = int(denominator or 0)
    if denominator <= 0:
        return 0
    return round(int(numerator or 0) / denominator)


def _delta_pct(current, previous):
    previous = float(previous or 0)
    current = float(current or 0)
    if previous == 0:
        return 0 if current == 0 else 100
    return round(((current - previous) / abs(previous)) * 100)


def _delta_pp(current, previous):
    return round(float(current or 0) - float(previous or 0))


def _formatted_delta(value, unit='%'):
    value = round(float(value or 0))
    prefix = '+' if value > 0 else ''
    suffix = '%' if unit == '%' else f' {unit}'
    return f'{prefix}{value}{suffix}'


def _delta_direction(value, invert=False):
    value = float(value or 0)
    if value == 0:
        return 'neutral'
    positive = value < 0 if invert else value > 0
    return 'positive' if positive else 'negative'


def _date_series(start_date, end_date):
    return list(services._date_range(start_date, end_date))


def _risk_comparison_periods(start_date, end_date):
    period_days = (end_date - start_date).days + 1
    risk_days = min(period_days, AT_RISK_USER_LOOKBACK_DAYS)
    current_end = end_date
    current_start = current_end - timedelta(days=risk_days - 1)
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=risk_days - 1)
    return current_start, current_end, previous_start, previous_end


def _relative_date_label(value, end_date):
    if not value:
        return '-'
    days = max(0, (end_date - value).days)
    if days <= 0:
        return 'Today'
    if days == 1:
        return '1d ago'
    return f'{days}d ago'


def _area_metadata(project_id):
    rows = ProductArea.objects.filter(project_id=project_id).values(
        'slug',
        'name',
        'short_name',
        'color',
        'area_role',
        'is_adoption_recommendable',
    )
    metadata = {}
    for row in rows:
        slug = row.get('slug') or 'unassigned'
        metadata[slug] = {
            'slug': slug,
            'name': row.get('name') or slug,
            'shortName': row.get('short_name') or row.get('name') or slug,
            'color': row.get('color') or '',
            'areaRole': row.get('area_role') or ProductArea.AREA_ROLE_UNKNOWN,
            'isAdoptionRecommendable': bool(row.get('is_adoption_recommendable')),
        }
    slug_by_name = {
        str(info.get('name') or '').strip().lower(): slug
        for slug, info in metadata.items()
        if str(info.get('name') or '').strip()
    }
    rule_rows = ProjectPageRule.objects.filter(project_id=project_id, is_active=True).exclude(product_area='').values(
        'product_area',
        'product_area_short_name',
        'area_role',
        'is_adoption_recommendable',
    )
    for row in rule_rows:
        area_name = row.get('product_area') or 'Unassigned'
        slug = slug_by_name.get(str(area_name).strip().lower()) or _area_slug(area_name)
        info = metadata.setdefault(
            slug,
            {
                'slug': slug,
                'name': area_name,
                'shortName': row.get('product_area_short_name') or area_name,
                'color': '',
                'areaRole': ProductArea.AREA_ROLE_UNKNOWN,
                'isAdoptionRecommendable': False,
            },
        )
        if row.get('product_area_short_name') and (not info.get('shortName') or info.get('shortName') == info.get('name')):
            info['shortName'] = row.get('product_area_short_name')
        area_role = row.get('area_role') or ProductArea.AREA_ROLE_UNKNOWN
        if area_role != ProductArea.AREA_ROLE_UNKNOWN:
            info['areaRole'] = area_role
        info['isAdoptionRecommendable'] = bool(info.get('isAdoptionRecommendable') or row.get('is_adoption_recommendable'))
    return metadata


def _area_info(area_key, area_name, metadata):
    key = area_key or 'unassigned'
    info = metadata.get(key) or {}
    if not info and area_name:
        normalized_name = str(area_name).strip().lower()
        info = next(
            (
                candidate
                for candidate in (metadata or {}).values()
                if str(candidate.get('name') or '').strip().lower() == normalized_name
            ),
            {},
        )
    name = area_name or info.get('name') or 'Unassigned'
    return {
        'slug': info.get('slug') or key,
        'name': name,
        'shortName': info.get('shortName') or name,
        'color': info.get('color') or '',
        'areaRole': info.get('areaRole') or ProductArea.AREA_ROLE_UNKNOWN,
        'isAdoptionRecommendable': bool(info.get('isAdoptionRecommendable')),
    }


def product_area_options(project_id, metadata=None):
    metadata = metadata or _area_metadata(project_id)
    return resolve_product_area_colors(
        sorted(
            metadata.values(),
            key=lambda item: (
                PRODUCT_AREA_ROLE_ORDER.get(item.get('areaRole'), 9),
                0 if item.get('isAdoptionRecommendable') else 1,
                item.get('name') or '',
            ),
        ),
        prefer_explicit=True,
    )


def _copy_company_detail_row(row):
    if not row:
        return {}
    copied = dict(row)
    copied['riskReasons'] = list(row.get('riskReasons') or [])
    copied['productAreas'] = list(row.get('productAreas') or [])
    copied['productAreaDistribution'] = [
        dict(item)
        for item in row.get('productAreaDistribution') or []
        if isinstance(item, dict)
    ]
    return copied


class BulkCompanyDetailContext:
    def __init__(self, project, *, range_key='last_30_days', overview_payload=None):
        self.project = project
        self.project_id = project.id
        self.range_key = range_key
        self.start_date, self.end_date = services.resolve_period(project.timezone, range_key=range_key)
        self.previous_start, self.previous_end = services.previous_period(self.start_date, self.end_date)
        self.overview_payload = overview_payload or {}
        self._metadata = None
        self._product_areas = None
        self._company_rows = None
        self._summary_cache = defaultdict(dict)
        self._daily_company_values_cache = {}
        self._new_reactivated_cache = {}

    def metadata(self):
        if self._metadata is None:
            metadata = _area_metadata(self.project_id)
            product_areas = product_area_options(self.project_id, metadata)
            color_lookup = build_product_area_color_lookup(product_areas, prefer_explicit=True)
            self._metadata = apply_product_area_metadata_colors(
                metadata,
                color_lookup,
                prefer_explicit=True,
            )
            self._product_areas = product_area_options(self.project_id, self._metadata)
        return self._metadata

    def product_areas(self):
        self.metadata()
        return self._product_areas

    def company_rows(self):
        if self._company_rows is None:
            if self.overview_payload.get('companies'):
                self._company_rows = _company_rows_from_overview_payload(
                    self.overview_payload,
                    self.metadata(),
                    self.end_date,
                )
            else:
                self._company_rows = _company_rows(
                    self.project_id,
                    self.start_date,
                    self.end_date,
                    self.previous_start,
                    self.previous_end,
                    self.metadata(),
                )
        return self._company_rows

    def company_summaries(self, company_ids, *, period='current', include_active_users=False):
        company_ids = [str(company_id) for company_id in company_ids or [] if company_id not in (None, '')]
        if not company_ids:
            return {}

        key = (period, bool(include_active_users))
        cache = self._summary_cache[key]
        missing = [company_id for company_id in dict.fromkeys(company_ids) if company_id not in cache]
        if missing:
            if period == 'previous':
                start_date, end_date = self.previous_start, self.previous_end
            else:
                start_date, end_date = self.start_date, self.end_date
            fetched = _company_summaries(
                self.project_id,
                start_date,
                end_date,
                company_ids=missing,
                include_active_users=include_active_users,
                metadata=self.metadata(),
            )
            for company_id in missing:
                cache[company_id] = fetched.get(company_id, {})

        return {company_id: cache.get(company_id, {}) for company_id in company_ids}

    def daily_company_values(self, company_ids, *, active_user_company_ids=None):
        company_key = tuple(sorted({str(company_id) for company_id in company_ids or [] if company_id not in (None, '')}))
        active_user_key = tuple(sorted({
            str(company_id)
            for company_id in (company_key if active_user_company_ids is None else active_user_company_ids)
            if company_id not in (None, '')
        }))
        key = (company_key, active_user_key)
        if key not in self._daily_company_values_cache:
            self._daily_company_values_cache[key] = _daily_company_values_for_companies(
                self.project_id,
                company_key,
                self.start_date,
                self.end_date,
                self.metadata(),
                active_user_company_ids=active_user_key,
            )
        return self._daily_company_values_cache[key]

    def new_reactivated_users(self, company_id, start_date, end_date, previous_start):
        key = (str(company_id or ''), start_date, end_date, previous_start)
        if key not in self._new_reactivated_cache:
            self._new_reactivated_cache[key] = _new_reactivated_users(
                self.project_id,
                company_id,
                start_date,
                end_date,
                previous_start,
            )
        return self._new_reactivated_cache[key]


def _company_base_queryset(project_id, start_date, end_date):
    return (
        PageCompanyDailyMetric.objects
        .filter(project_id=project_id, date__gte=start_date, date__lte=end_date)
        .exclude(company_id='')
    )


def _user_base_queryset(project_id, start_date, end_date):
    return (
        PageUserDailyMetric.objects
        .filter(project_id=project_id, date__gte=start_date, date__lte=end_date)
        .exclude(company_id__isnull=True)
        .exclude(company_id='')
    )


def _recommendable_product_area_keys(metadata):
    return [
        key
        for key, info in (metadata or {}).items()
        if info.get('areaRole') == ProductArea.AREA_ROLE_PRODUCT and info.get('isAdoptionRecommendable')
    ]


def _recommendable_product_area_names(metadata):
    return [
        info.get('name')
        for info in (metadata or {}).values()
        if info.get('name')
        and info.get('areaRole') == ProductArea.AREA_ROLE_PRODUCT
        and info.get('isAdoptionRecommendable')
    ]


def _recommendable_product_page_rule_ids(project_id):
    return list(
        ProjectPageRule.objects
        .filter(
            project_id=project_id,
            area_role=ProductArea.AREA_ROLE_PRODUCT,
            is_adoption_recommendable=True,
        )
        .values_list('id', flat=True)
    )


def _recommendable_product_usage_filter(project_id, metadata):
    recommendable_keys = _recommendable_product_area_keys(metadata)
    recommendable_names = _recommendable_product_area_names(metadata)
    recommendable_page_rule_ids = _recommendable_product_page_rule_ids(project_id)
    usage_filter = Q(visits_count__gt=0)
    recommendable_filter = Q()

    if recommendable_keys:
        recommendable_filter |= Q(product_area_key__in=recommendable_keys)
    if recommendable_names:
        recommendable_filter |= Q(product_area_name__in=recommendable_names)
    if recommendable_page_rule_ids:
        recommendable_filter |= Q(page_rule_id__in=recommendable_page_rule_ids)

    if recommendable_filter:
        return usage_filter & recommendable_filter

    # Older projects may not have adoption metadata populated yet. In that case,
    # keep the card useful instead of showing a misleading global zero.
    return usage_filter


def _company_summaries(project_id, start_date, end_date, company_ids=None, *, include_active_users=True, metadata=None):
    company_ids = [str(company_id) for company_id in company_ids or [] if str(company_id)]
    metadata = metadata if metadata is not None else _area_metadata(project_id)
    recommendable_filter = _recommendable_product_usage_filter(project_id, metadata)
    queryset = _company_base_queryset(project_id, start_date, end_date)
    if company_ids:
        queryset = queryset.filter(company_id__in=company_ids)
    rows = (
        queryset
        .values('company_id')
        .annotate(
            company_name=Max('company_name_sample'),
            visits=Sum('visits_count'),
            engaged_seconds=Sum('engaged_seconds'),
            click_count=Sum('click_count'),
            visits_with_click_count=Sum('visits_with_click_count'),
            pages_used=Count('page_rule_id', filter=recommendable_filter, distinct=True),
            product_areas_used=Count('product_area_key', filter=recommendable_filter, distinct=True),
            raw_pages_used=Count('page_rule_id', filter=Q(visits_count__gt=0), distinct=True),
            raw_product_areas_used=Count('product_area_key', filter=Q(visits_count__gt=0), distinct=True),
            last_seen_date=Max('date'),
        )
    )
    summaries = {}
    for row in rows:
        company_id = row['company_id']
        visits = _to_int(row.get('visits'))
        engaged_seconds = _to_int(row.get('engaged_seconds'))
        summary = {
            'company_id': company_id,
            'company_name': row.get('company_name') or company_id,
            'visits': visits,
            'engaged_seconds': engaged_seconds,
            'click_count': _to_int(row.get('click_count')),
            'visits_with_click_count': _to_int(row.get('visits_with_click_count')),
            'pages_used': _to_int(row.get('pages_used')),
            'product_areas_used': _to_int(row.get('product_areas_used')),
            'raw_pages_used': _to_int(row.get('raw_pages_used')),
            'raw_product_areas_used': _to_int(row.get('raw_product_areas_used')),
            'last_seen_date': row.get('last_seen_date'),
        }
        if include_active_users:
            summary['active_users'] = 0
        summaries[company_id] = summary

    if include_active_users:
        user_queryset = _user_base_queryset(project_id, start_date, end_date)
        if company_ids:
            user_queryset = user_queryset.filter(company_id__in=company_ids)
        for row in (
            user_queryset
            .values('company_id')
            .annotate(active_users=Count('user_id', distinct=True))
        ):
            summaries.setdefault(row['company_id'], {'company_id': row['company_id'], 'company_name': row['company_id']})
            summaries[row['company_id']]['active_users'] = _to_int(row.get('active_users'))

    return summaries


def _first_seen_companies(project_id, company_ids=None):
    company_ids = [str(company_id) for company_id in company_ids or [] if str(company_id)]
    queryset = PageCompanyDailyMetric.objects.filter(project_id=project_id).exclude(company_id='')
    if company_ids:
        queryset = queryset.filter(company_id__in=company_ids)
    return {
        row['company_id']: row.get('first_seen_date')
        for row in (
            queryset
            .values('company_id')
            .annotate(first_seen_date=Min('date'))
        )
    }


def _companies_active_before(project_id, before_date):
    return set(
        PageCompanyDailyMetric.objects
        .filter(project_id=project_id, date__lt=before_date)
        .exclude(company_id='')
        .values_list('company_id', flat=True)
        .distinct()
    )


def _known_user_counts(project_id, company_ids=None):
    company_ids = [str(company_id) for company_id in company_ids or [] if str(company_id)]
    queryset = (
        PageUserDailyMetric.objects
        .filter(project_id=project_id)
        .exclude(company_id__isnull=True)
        .exclude(company_id='')
    )
    if company_ids:
        queryset = queryset.filter(company_id__in=company_ids)
    return {
        row['company_id']: _to_int(row.get('known_users'))
        for row in (
            queryset
            .values('company_id')
            .annotate(known_users=Count('user_id', distinct=True))
        )
    }


def _company_area_usage(project_id, start_date, end_date, metadata, company_ids=None):
    company_ids = [str(company_id) for company_id in company_ids or [] if str(company_id)]
    usage = defaultdict(list)
    queryset = _company_base_queryset(project_id, start_date, end_date)
    if company_ids:
        queryset = queryset.filter(company_id__in=company_ids)
    rows = (
        queryset
        .values('company_id', 'product_area_key', 'product_area_name')
        .annotate(
            engaged_seconds=Sum('engaged_seconds'),
            visits=Sum('visits_count'),
            page_count=Count('page_rule_id', filter=Q(visits_count__gt=0), distinct=True),
        )
        .order_by('company_id', '-engaged_seconds')
    )
    totals = defaultdict(int)
    for row in rows:
        totals[row['company_id']] += _to_int(row.get('engaged_seconds'))
    for row in rows:
        company_id = row['company_id']
        info = _area_info(row.get('product_area_key'), row.get('product_area_name'), metadata)
        engaged_seconds = _to_int(row.get('engaged_seconds'))
        usage[company_id].append({
            'productArea': info['name'],
            'product_area_name': info['name'],
            'productAreaKey': info['slug'],
            'color': info['color'],
            'areaRole': info['areaRole'],
            'isAdoptionRecommendable': info['isAdoptionRecommendable'],
            'engagedSeconds': engaged_seconds,
            'engaged_seconds': engaged_seconds,
            'visits': _to_int(row.get('visits')),
            'pagesUsed': _to_int(row.get('page_count')),
            'percent': round((engaged_seconds / max(totals[company_id], 1)) * 100),
        })
    return usage


def _status_for_detail_company(row, previous, first_seen_date, previous_active, active_before_previous, start_date, end_date, thresholds):
    company_id = row['company_id']
    is_new = first_seen_date is not None and start_date <= first_seen_date <= end_date
    is_reactivated = company_id not in previous_active and company_id in active_before_previous
    period_days = (end_date - start_date).days + 1
    reasons = []

    if not is_new and not is_reactivated:
        if _to_int(previous.get('engaged_seconds')) >= 1800 and _to_int(row.get('engaged_seconds')) <= _to_int(previous.get('engaged_seconds')) * 0.5:
            reasons.append('Engaged drop')
        if _to_int(previous.get('active_users')) >= 2 and _to_int(row.get('active_users')) <= _to_int(previous.get('active_users')) * 0.5:
            reasons.append('Users dropped')
        if _to_int(previous.get('product_areas_used')) >= 2 and _to_int(row.get('product_areas_used')) < _to_int(previous.get('product_areas_used')):
            reasons.append('Product areas dropped')
        if period_days >= 14 and row.get('last_seen_date') and (end_date - row['last_seen_date']).days >= (7 if period_days <= 30 else 14):
            reasons.append('Stale activity')

    if is_new:
        status = 'new'
    elif is_reactivated:
        status = 'reactivated'
    elif reasons:
        status = 'at_risk'
    elif (
        _to_int(row.get('active_users')) >= thresholds['p75_active_users']
        and _avg(row.get('engaged_seconds'), row.get('active_users')) >= thresholds['p75_avg_engaged']
        and _to_int(row.get('product_areas_used')) >= thresholds['median_product_areas']
    ):
        status = 'power'
    elif _to_int(row.get('active_users')) >= 2 and _to_int(row.get('engaged_seconds')) >= 1800:
        status = 'activated'
    else:
        status = 'healthy'

    return status, reasons, is_new, is_reactivated


def _thresholds(rows):
    active_users = sorted(_to_int(row.get('active_users')) for row in rows)
    avg_engaged = sorted(_avg(row.get('engaged_seconds'), row.get('active_users')) for row in rows)
    product_areas = sorted(_to_int(row.get('product_areas_used')) for row in rows)

    return {
        'p75_active_users': _percentile(active_users, 0.75),
        'p75_avg_engaged': _percentile(avg_engaged, 0.75),
        'median_product_areas': max(1, _percentile(product_areas, 0.5)),
    }


def _percentile(values, pct):
    values = [value for value in values if value is not None]
    if not values:
        return 0
    index = min(len(values) - 1, round((len(values) - 1) * pct))
    return values[index]


def _company_rows(project_id, start_date, end_date, previous_start, previous_end, metadata):
    current = _company_summaries(project_id, start_date, end_date, metadata=metadata)
    previous = _company_summaries(project_id, previous_start, previous_end, metadata=metadata)
    area_usage = _company_area_usage(project_id, start_date, end_date, metadata)
    first_seen = _first_seen_companies(project_id)
    previous_active = set(previous.keys())
    active_before_previous = _companies_active_before(project_id, previous_start)
    known_users = _known_user_counts(project_id)
    thresholds = _thresholds(current.values())
    rows = []

    for company_id, row in current.items():
        previous_row = previous.get(company_id, {})
        status, reasons, is_new, is_reactivated = _status_for_detail_company(
            row,
            previous_row,
            first_seen.get(company_id),
            previous_active,
            active_before_previous,
            start_date,
            end_date,
            thresholds,
        )
        active_users = _to_int(row.get('active_users'))
        engaged_seconds = _to_int(row.get('engaged_seconds'))
        visits = _to_int(row.get('visits'))
        interaction_pct = _safe_pct(row.get('visits_with_click_count'), visits)
        previous_interaction_pct = _safe_pct(previous_row.get('visits_with_click_count'), previous_row.get('visits'))
        distribution = area_usage.get(company_id, [])
        top_area = distribution[0]['productArea'] if distribution else ''

        rows.append({
            'id': company_id,
            'companyId': company_id,
            'name': row.get('company_name') or company_id,
            'companyName': row.get('company_name') or company_id,
            'domain': '',
            'status': status,
            'riskReasons': reasons,
            'isNew': is_new,
            'isReactivated': is_reactivated,
            'activeUsers': active_users,
            'activeUsersDeltaPct': _delta_pct(active_users, previous_row.get('active_users')),
            'totalKnownUsers': max(active_users, known_users.get(company_id, active_users)),
            'productAreasUsed': _to_int(row.get('product_areas_used')),
            'productAreasDelta': _to_int(row.get('product_areas_used')) - _to_int(previous_row.get('product_areas_used')),
            'pagesUsed': _to_int(row.get('pages_used')),
            'rawProductAreasUsed': _to_int(row.get('raw_product_areas_used')),
            'rawPagesUsed': _to_int(row.get('raw_pages_used')),
            'visits': visits,
            'visitsDeltaPct': _delta_pct(visits, previous_row.get('visits')),
            'engagedSeconds': engaged_seconds,
            'engagedDeltaPct': _delta_pct(engaged_seconds, previous_row.get('engaged_seconds')),
            'avgEngagedSecondsPerUser': _avg(engaged_seconds, active_users),
            'avgEngagedSecondsPerUserDeltaPct': _delta_pct(_avg(engaged_seconds, active_users), _avg(previous_row.get('engaged_seconds'), previous_row.get('active_users'))),
            'interactionPct': interaction_pct,
            'interactionDeltaPp': _delta_pp(interaction_pct, previous_interaction_pct),
            'lastActiveAt': _relative_date_label(row.get('last_seen_date'), end_date),
            'lastSeen': _relative_date_label(row.get('last_seen_date'), end_date),
            'lastSeenDate': row.get('last_seen_date').isoformat() if row.get('last_seen_date') else None,
            'lastSeenDays': (end_date - row['last_seen_date']).days if row.get('last_seen_date') else 0,
            'firstSeenDate': first_seen.get(company_id).isoformat() if first_seen.get(company_id) else None,
            'topProductArea': top_area,
            'productAreas': [item['productArea'] for item in distribution if item['engagedSeconds'] > 0],
            'productAreaDistribution': distribution,
        })

    return sorted(rows, key=lambda item: (-item['engagedSeconds'], item['name']))


def _normalize_overview_area_distribution(distribution, metadata):
    rows = []
    total = sum(_to_int(item.get('engagedSeconds') or item.get('engaged_seconds')) for item in distribution) or 1
    for item in distribution or []:
        info = _area_info(
            item.get('productAreaKey') or item.get('product_area_key'),
            item.get('productArea') or item.get('product_area_name') or item.get('name'),
            metadata,
        )
        engaged_seconds = _to_int(item.get('engagedSeconds') or item.get('engaged_seconds'))
        percent = item.get('percent')
        rows.append({
            'productArea': info['name'],
            'product_area_name': info['name'],
            'productAreaKey': info['slug'],
            'product_area_key': info['slug'],
            'color': info['color'],
            'areaRole': info['areaRole'],
            'isAdoptionRecommendable': info['isAdoptionRecommendable'],
            'engagedSeconds': engaged_seconds,
            'engaged_seconds': engaged_seconds,
            'visits': _to_int(item.get('visits')),
            'pagesUsed': _to_int(item.get('pagesUsed') or item.get('pages_used')),
            'percent': percent if percent is not None else round((engaged_seconds / total) * 100),
        })
    return sorted(rows, key=lambda item: (-item['engagedSeconds'], item['productArea']))


def _company_rows_from_overview_payload(overview_payload, metadata, end_date):
    rows = []
    for source in overview_payload.get('companies') or []:
        company_id = str(source.get('companyId') or source.get('id') or '')
        if not company_id:
            continue

        last_seen_date = services._safe_date(source.get('lastSeenDate'))
        first_seen_date = services._safe_date(source.get('firstSeenDate'))
        active_users = _to_int(source.get('activeUsers'))
        distribution = _normalize_overview_area_distribution(source.get('productAreaDistribution') or [], metadata)

        rows.append({
            'id': company_id,
            'companyId': company_id,
            'name': source.get('companyName') or source.get('name') or company_id,
            'companyName': source.get('companyName') or source.get('name') or company_id,
            'domain': source.get('domain') or '',
            'status': source.get('status') or 'healthy',
            'riskReasons': source.get('riskReasons') or [],
            'isNew': bool(source.get('isNew')),
            'isReactivated': bool(source.get('isReactivated')),
            'activeUsers': active_users,
            'activeUsersDeltaPct': source.get('activeUsersDeltaPct') or 0,
            'totalKnownUsers': max(active_users, _to_int(source.get('totalKnownUsers') or source.get('totalIdentifiedUsers') or active_users)),
            'productAreasUsed': _to_int(source.get('productAreasUsed')),
            'productAreasDelta': _to_int(source.get('productAreasDelta')),
            'pagesUsed': _to_int(source.get('pagesUsed')),
            'rawProductAreasUsed': _to_int(source.get('rawProductAreasUsed') or source.get('productAreasUsed')),
            'rawPagesUsed': _to_int(source.get('rawPagesUsed') or source.get('pagesUsed')),
            'visits': _to_int(source.get('visits')),
            'visitsDeltaPct': source.get('visitsDeltaPct') or 0,
            'engagedSeconds': _to_int(source.get('engagedSeconds')),
            'engagedDeltaPct': source.get('engagedDeltaPct') or 0,
            'avgEngagedSecondsPerUser': _to_int(source.get('avgEngagedSecondsPerUser')),
            'avgEngagedSecondsPerUserDeltaPct': source.get('avgEngagedSecondsPerUserDeltaPct') or 0,
            'interactionPct': source.get('interactionPct') or 0,
            'interactionDeltaPp': source.get('interactionDeltaPp') or 0,
            'lastActiveAt': _relative_date_label(last_seen_date, end_date),
            'lastSeen': _relative_date_label(last_seen_date, end_date),
            'lastSeenDate': last_seen_date.isoformat() if last_seen_date else None,
            'lastSeenDays': (end_date - last_seen_date).days if last_seen_date else 0,
            'firstSeenDate': first_seen_date.isoformat() if first_seen_date else None,
            'topProductArea': distribution[0]['productArea'] if distribution else '',
            'productAreas': source.get('productAreas') or [item['productArea'] for item in distribution if item['engagedSeconds'] > 0],
            'productAreaDistribution': distribution,
        })

    return sorted(rows, key=lambda item: (-item['engagedSeconds'], item['name']))


def _hydrate_peer_optional_metadata(project_id, current_company, company_rows):
    candidate_rows = [current_company] + sorted(
        [row for row in company_rows if row['id'] != current_company['id'] and _peer_active_users(row) > 0],
        key=lambda row: _peer_active_users_key(row, current_company),
    )[:PEER_OPTIONAL_METADATA_CANDIDATE_LIMIT]
    missing_first_seen_ids = [row['id'] for row in candidate_rows if not row.get('firstSeenDate')]
    first_seen = _first_seen_companies(project_id, missing_first_seen_ids) if missing_first_seen_ids else {}

    for row in candidate_rows:
        if not row.get('firstSeenDate') and first_seen.get(row['id']):
            row['firstSeenDate'] = first_seen[row['id']].isoformat()


def _apply_company_summary_to_detail_row(row, summary, previous_summary=None, end_date=None):
    if not summary:
        return

    previous_summary = previous_summary or None
    active_users = _to_int(summary.get('active_users')) if 'active_users' in summary else _to_int(row.get('activeUsers'))
    visits = _to_int(summary.get('visits'))
    engaged_seconds = _to_int(summary.get('engaged_seconds'))
    interaction_pct = _safe_pct(summary.get('visits_with_click_count'), visits)

    row['activeUsers'] = active_users
    row['totalKnownUsers'] = max(active_users, _to_int(row.get('totalKnownUsers')))
    row['productAreasUsed'] = _to_int(summary.get('product_areas_used'))
    row['pagesUsed'] = _to_int(summary.get('pages_used'))
    row['rawProductAreasUsed'] = _to_int(summary.get('raw_product_areas_used'))
    row['rawPagesUsed'] = _to_int(summary.get('raw_pages_used'))
    row['visits'] = visits
    row['engagedSeconds'] = engaged_seconds
    row['avgEngagedSecondsPerUser'] = _avg(engaged_seconds, active_users)
    row['interactionPct'] = interaction_pct

    if previous_summary is not None:
        if 'active_users' in previous_summary:
            row['activeUsersDeltaPct'] = _delta_pct(active_users, previous_summary.get('active_users'))
        row['productAreasDelta'] = _to_int(summary.get('product_areas_used')) - _to_int(previous_summary.get('product_areas_used'))
        row['visitsDeltaPct'] = _delta_pct(visits, previous_summary.get('visits'))
        row['engagedDeltaPct'] = _delta_pct(engaged_seconds, previous_summary.get('engaged_seconds'))
        if 'active_users' in previous_summary:
            row['avgEngagedSecondsPerUserDeltaPct'] = _delta_pct(
                _avg(engaged_seconds, active_users),
                _avg(previous_summary.get('engaged_seconds'), previous_summary.get('active_users')),
            )
        row['interactionDeltaPp'] = _delta_pp(
            interaction_pct,
            _safe_pct(previous_summary.get('visits_with_click_count'), previous_summary.get('visits')),
        )

    last_seen_date = summary.get('last_seen_date')
    if last_seen_date:
        row['lastSeenDate'] = last_seen_date.isoformat()
        if end_date:
            row['lastActiveAt'] = _relative_date_label(last_seen_date, end_date)
            row['lastSeen'] = _relative_date_label(last_seen_date, end_date)
            row['lastSeenDays'] = (end_date - last_seen_date).days


def _empty_daily_company_values(dates):
    return {day: {'visits': 0, 'engaged': 0, 'clickVisits': 0, 'productPageCount': 0} for day in dates}


def _daily_company_values_for_companies(project_id, company_ids, start_date, end_date, metadata, active_user_company_ids=None):
    dates = _date_series(start_date, end_date)
    company_ids = [str(company_id) for company_id in company_ids or [] if company_id not in (None, '')]
    active_user_company_ids = [
        str(company_id)
        for company_id in (company_ids if active_user_company_ids is None else active_user_company_ids)
        if company_id not in (None, '')
    ]
    daily_by_company = {company_id: _empty_daily_company_values(dates) for company_id in company_ids}

    if not company_ids:
        return {}

    for row in (
        _company_base_queryset(project_id, start_date, end_date)
        .filter(company_id__in=company_ids)
        .values('company_id', 'date')
        .annotate(
            visits=Sum('visits_count'),
            engaged=Sum('engaged_seconds'),
            click_visits=Sum('visits_with_click_count'),
        )
    ):
        company_id = str(row['company_id'])
        daily_by_company[company_id][row['date']].update({
            'visits': _to_int(row.get('visits')),
            'engaged': _to_int(row.get('engaged')),
            'clickVisits': _to_int(row.get('click_visits')),
        })

    for row in (
        _company_base_queryset(project_id, start_date, end_date)
        .filter(
            company_id__in=company_ids,
        )
        .filter(_recommendable_product_usage_filter(project_id, metadata))
        .values('company_id', 'date')
        .annotate(product_pages=Count('page_rule_id', distinct=True))
    ):
        company_id = str(row['company_id'])
        if company_id in daily_by_company and row['date'] in daily_by_company[company_id]:
            daily_by_company[company_id][row['date']]['productPageCount'] = _to_int(row.get('product_pages'))

    active_users_by_company_day = defaultdict(dict)
    if active_user_company_ids:
        for row in (
            _user_base_queryset(project_id, start_date, end_date)
            .filter(company_id__in=active_user_company_ids)
            .values('company_id', 'date')
            .annotate(active_users=Count('user_id', distinct=True))
        ):
            active_users_by_company_day[str(row['company_id'])][row['date']] = _to_int(row.get('active_users'))

    results = {}
    for company_id in company_ids:
        base_values = daily_by_company[company_id]
        active_users_by_day = active_users_by_company_day.get(company_id, {})
        results[company_id] = {
            'dates': dates,
            'activeUsers': [{'date': day.isoformat(), 'value': active_users_by_day.get(day, 0)} for day in dates],
            'visits': [{'date': day.isoformat(), 'value': base_values[day]['visits']} for day in dates],
            'engaged': [{'date': day.isoformat(), 'value': base_values[day]['engaged']} for day in dates],
            'avgPerUser': [
                {'date': day.isoformat(), 'value': _avg(base_values[day]['engaged'], active_users_by_day.get(day, 0))}
                for day in dates
            ],
            'interaction': [
                {'date': day.isoformat(), 'value': _safe_pct(base_values[day]['clickVisits'], base_values[day]['visits'])}
                for day in dates
            ],
            'adoptionBreadth': [{'date': day.isoformat(), 'value': base_values[day]['productPageCount']} for day in dates],
        }

    return results


def _new_reactivated_users(project_id, company_id, start_date, end_date, previous_start):
    current_users = set(
        _user_base_queryset(project_id, start_date, end_date)
        .filter(company_id=company_id)
        .values_list('user_id', flat=True)
        .distinct()
    )
    first_seen = {
        row['user_id']: row['first_seen_date']
        for row in (
            PageUserDailyMetric.objects
            .filter(project_id=project_id, company_id=company_id, user_id__in=current_users)
            .values('user_id')
            .annotate(first_seen_date=Min('date'))
        )
    }
    previous_active = set(
        _user_base_queryset(project_id, previous_start, start_date - timedelta(days=1))
        .filter(company_id=company_id, user_id__in=current_users)
        .values_list('user_id', flat=True)
        .distinct()
    )
    active_before_previous = set(
        PageUserDailyMetric.objects
        .filter(project_id=project_id, company_id=company_id, user_id__in=current_users, date__lt=previous_start)
        .values_list('user_id', flat=True)
        .distinct()
    )
    new_users = {user_id for user_id in current_users if first_seen.get(user_id) and start_date <= first_seen[user_id] <= end_date}
    reactivated_users = {user_id for user_id in current_users if user_id not in previous_active and user_id in active_before_previous}
    daily = {day: 0 for day in _date_series(start_date, end_date)}
    first_current_dates = (
        _user_base_queryset(project_id, start_date, end_date)
        .filter(company_id=company_id, user_id__in=new_users | reactivated_users)
        .values('user_id')
        .annotate(first_current_date=Min('date'))
    )
    for row in first_current_dates:
        if row['first_current_date'] in daily:
            daily[row['first_current_date']] += 1

    return {
        'new': len(new_users),
        'reactivated': len(reactivated_users - new_users),
        'daily': [{'date': day.isoformat(), 'value': daily[day]} for day in _date_series(start_date, end_date)],
    }


def _daily_active_user_count_series(project_id, company_id, user_ids, start_date, end_date):
    dates = _date_series(start_date, end_date)
    user_ids = [str(user_id) for user_id in user_ids or [] if user_id not in (None, '')]
    if not user_ids:
        return [{'date': day.isoformat(), 'value': 0} for day in dates]

    values = {
        row['date']: _to_int(row.get('users'))
        for row in (
            _user_base_queryset(project_id, start_date, end_date)
            .filter(company_id=company_id, user_id__in=user_ids)
            .filter(Q(visits_count__gt=0) | Q(engaged_seconds__gt=0) | Q(click_count__gt=0))
            .values('date')
            .annotate(users=Count('user_id', distinct=True))
        )
    }
    return [{'date': day.isoformat(), 'value': values.get(day, 0)} for day in dates]


def _at_risk_user_ids_for_period(project_id, company_id, start_date, end_date, previous_start, previous_end, user_ids=None):
    user_ids = [str(user_id) for user_id in user_ids or [] if user_id not in (None, '')]
    current_queryset = _user_base_queryset(project_id, start_date, end_date).filter(company_id=company_id)
    if user_ids:
        current_queryset = current_queryset.filter(user_id__in=user_ids)
    current = {
        row['user_id']: row
        for row in (
            current_queryset
            .values('user_id')
            .annotate(engaged_seconds=Sum('engaged_seconds'), visits=Sum('visits_count'))
        )
    }
    if not current:
        return set()

    previous = {
        row['user_id']: row
        for row in (
            _user_base_queryset(project_id, previous_start, previous_end)
            .filter(company_id=company_id, user_id__in=current.keys())
            .values('user_id')
            .annotate(engaged_seconds=Sum('engaged_seconds'), visits=Sum('visits_count'))
        )
    }

    at_risk = set()
    for user_id, current_row in current.items():
        previous_row = previous.get(user_id, {})
        previous_engaged = _to_int(previous_row.get('engaged_seconds'))
        current_engaged = _to_int(current_row.get('engaged_seconds'))
        previous_visits = _to_int(previous_row.get('visits'))
        current_visits = _to_int(current_row.get('visits'))
        engaged_drop = previous_engaged >= 600 and current_engaged <= previous_engaged * 0.5
        visits_drop = previous_visits >= 4 and current_visits <= previous_visits * 0.5
        if engaged_drop or visits_drop:
            at_risk.add(user_id)

    return at_risk


def _daily_at_risk_user_count_series(project_id, company_id, users, start_date, end_date, previous_start, previous_end):
    dates = _date_series(start_date, end_date)
    user_ids = [
        str(user.get('id'))
        for user in users or []
        if user.get('id') not in (None, '') and user.get('riskStatus') != 'dropped'
    ]
    if not user_ids:
        return [{'date': day.isoformat(), 'value': 0} for day in dates]

    risk_days = min(len(dates), AT_RISK_USER_LOOKBACK_DAYS)
    history_start = start_date - timedelta(days=(risk_days * 2) - 1)
    history_dates = _date_series(history_start, end_date)
    date_index = {day: index for index, day in enumerate(history_dates)}
    daily_by_user = {
        user_id: {
            'engaged': [0] * len(history_dates),
            'visits': [0] * len(history_dates),
        }
        for user_id in user_ids
    }

    for row in (
        _user_base_queryset(project_id, history_start, end_date)
        .filter(company_id=company_id, user_id__in=user_ids)
        .values('user_id', 'date')
        .annotate(engaged_seconds=Sum('engaged_seconds'), visits=Sum('visits_count'))
    ):
        day_index = date_index.get(row['date'])
        if day_index is None:
            continue
        user_values = daily_by_user.setdefault(row['user_id'], {
            'engaged': [0] * len(history_dates),
            'visits': [0] * len(history_dates),
        })
        user_values['engaged'][day_index] += _to_int(row.get('engaged_seconds'))
        user_values['visits'][day_index] += _to_int(row.get('visits'))

    prefixes_by_user = {}
    for user_id, values in daily_by_user.items():
        engaged_prefix = [0]
        visits_prefix = [0]
        for engaged, visits in zip(values['engaged'], values['visits']):
            engaged_prefix.append(engaged_prefix[-1] + engaged)
            visits_prefix.append(visits_prefix[-1] + visits)
        prefixes_by_user[user_id] = {
            'engaged': engaged_prefix,
            'visits': visits_prefix,
        }

    def range_sum(prefix, range_start, range_end):
        range_start = max(range_start, history_start)
        range_end = min(range_end, end_date)
        if range_start > range_end:
            return 0
        return prefix[date_index[range_end] + 1] - prefix[date_index[range_start]]

    series = []

    for day in dates:
        current_start = day - timedelta(days=risk_days - 1)
        previous_end = current_start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=risk_days - 1)
        count = 0
        for user_id in user_ids:
            prefixes = prefixes_by_user[user_id]
            current_engaged = range_sum(prefixes['engaged'], current_start, day)
            current_visits = range_sum(prefixes['visits'], current_start, day)
            previous_engaged = range_sum(prefixes['engaged'], previous_start, previous_end)
            previous_visits = range_sum(prefixes['visits'], previous_start, previous_end)
            engaged_drop = previous_engaged >= 600 and current_engaged <= previous_engaged * 0.5
            visits_drop = previous_visits >= 4 and current_visits <= previous_visits * 0.5
            if engaged_drop or visits_drop:
                count += 1

        series.append({'date': day.isoformat(), 'value': count})

    return series


def _peer_metric_series(peer_companies, daily_by_company, key):
    series = []
    for peer in peer_companies or []:
        company_id = str(peer.get('id') or peer.get('companyId') or '')
        daily_series = daily_by_company.get(company_id, {}).get(key) or []
        if not company_id or not daily_series:
            continue
        series.append({
            'companyId': company_id,
            'companyName': peer.get('name') or peer.get('companyName') or company_id,
            'dailySeries': daily_series,
        })
    return series


def _peer_new_reactivated_metric_series(project_id, peer_companies, start_date, end_date, previous_start, bulk_context=None):
    series = []
    for peer in peer_companies or []:
        company_id = str(peer.get('id') or peer.get('companyId') or '')
        if not company_id:
            continue

        new_reactivated = (
            bulk_context.new_reactivated_users(company_id, start_date, end_date, previous_start)
            if bulk_context
            else _new_reactivated_users(project_id, company_id, start_date, end_date, previous_start)
        )
        series.append({
            'companyId': company_id,
            'companyName': peer.get('name') or peer.get('companyName') or company_id,
            'dailySeries': new_reactivated['daily'],
        })

    return series


def _peer_at_risk_user_metric_series(project_id, peer_companies, start_date, end_date, previous_start, previous_end):
    series = []
    for peer in peer_companies or []:
        company_id = str(peer.get('id') or peer.get('companyId') or '')
        if not company_id:
            continue

        peer_user_ids = (
            _user_base_queryset(project_id, start_date, end_date)
            .filter(company_id=company_id)
            .values_list('user_id', flat=True)
            .distinct()
        )
        peer_users = [{'id': user_id, 'riskStatus': 'active'} for user_id in peer_user_ids if user_id not in (None, '')]
        series.append({
            'companyId': company_id,
            'companyName': peer.get('name') or peer.get('companyName') or company_id,
            'dailySeries': _daily_at_risk_user_count_series(
                project_id,
                company_id,
                peer_users,
                start_date,
                end_date,
                previous_start,
                previous_end,
            ),
        })

    return series


def _benchmark_metric_series(benchmark_companies, daily_by_company, key):
    source_series = []
    for peer in benchmark_companies or []:
        company_id = str(peer.get('id') or peer.get('companyId') or '')
        daily_series = daily_by_company.get(company_id, {}).get(key) or []
        if daily_series:
            source_series.append(daily_series)

    if not source_series:
        return []

    length = max(len(series) for series in source_series)
    result = []
    for index in range(length):
        point_date = next(
            (series[index].get('date') for series in source_series if index < len(series) and series[index].get('date')),
            '',
        )
        values = [
            series[index].get('value')
            for series in source_series
            if index < len(series) and series[index].get('value') is not None
        ]
        result.append({
            'date': point_date,
            'value': services._median(values) if values else None,
        })

    return result


def _metric_card(key, label, value_type, value, previous_value, daily_series, *, secondary_text='', delta_unit='%', peer_series=None, benchmark_series=None, benchmark_peer_count=0):
    delta_value = _delta_pp(value, previous_value) if delta_unit == 'pp' else _delta_pct(value, previous_value)
    return {
        'key': key,
        'label': label,
        'valueType': value_type,
        'value': value,
        'previousValue': previous_value,
        'deltaValue': delta_value,
        'deltaDirection': _delta_direction(delta_value),
        'formattedDelta': _formatted_delta(delta_value, delta_unit),
        'secondaryText': secondary_text,
        'dailySeries': daily_series,
        'peerSeries': peer_series or [],
        'benchmarkSeries': benchmark_series or [],
        'benchmarkEligiblePeerCount': benchmark_peer_count,
    }


def _apply_metric_delta(card, delta_value, delta_unit='%'):
    if delta_value is None:
        return card

    card['deltaValue'] = delta_value
    card['deltaDirection'] = _delta_direction(delta_value)
    card['formattedDelta'] = _formatted_delta(delta_value, delta_unit)
    return card


def _metric_cards(
    project_id,
    company_id,
    start_date,
    end_date,
    previous_start,
    previous_end,
    company,
    previous_company,
    users,
    metadata,
    peer_companies=None,
    benchmark_companies=None,
    bulk_context=None,
):
    company_id = str(company_id)
    peer_companies = list(peer_companies or [])
    benchmark_companies = list(benchmark_companies or [])
    peer_ids = [peer.get('id') or peer.get('companyId') for peer in peer_companies]
    benchmark_ids = [peer.get('id') or peer.get('companyId') for peer in benchmark_companies]
    metric_company_ids = list(dict.fromkeys([company_id, *peer_ids, *benchmark_ids]))
    daily_by_company = (
        bulk_context.daily_company_values(metric_company_ids, active_user_company_ids=metric_company_ids)
        if bulk_context
        else _daily_company_values_for_companies(
            project_id,
            metric_company_ids,
            start_date,
            end_date,
            metadata,
            active_user_company_ids=metric_company_ids,
        )
    )
    daily = daily_by_company[company_id]
    new_reactivated = (
        bulk_context.new_reactivated_users(company_id, start_date, end_date, previous_start)
        if bulk_context
        else _new_reactivated_users(project_id, company_id, start_date, end_date, previous_start)
    )
    previous_new_reactivated = (
        bulk_context.new_reactivated_users(
            company_id,
            previous_start,
            previous_end,
            previous_start - (end_date - start_date + timedelta(days=1)),
        )
        if bulk_context
        else _new_reactivated_users(
            project_id,
            company_id,
            previous_start,
            previous_end,
            previous_start - (end_date - start_date + timedelta(days=1)),
        )
    )
    active_users = company.get('activeUsers', 0)
    previous_active_users = previous_company.get('active_users', 0)
    engaged = company.get('engagedSeconds', 0)
    previous_engaged = previous_company.get('engaged_seconds', 0)
    visits = company.get('visits', 0)
    previous_visits = previous_company.get('visits', 0)
    interaction = company.get('interactionPct', 0)
    previous_interaction = _safe_pct(previous_company.get('visits_with_click_count'), previous_company.get('visits'))
    benchmark_peer_count = len(benchmark_companies)
    at_risk_users = [user for user in users if user.get('riskStatus') == 'at_risk']
    risk_start, risk_end, risk_previous_start, risk_previous_end = _risk_comparison_periods(start_date, end_date)
    previous_risk_start, previous_risk_end, before_previous_start, before_previous_end = _risk_comparison_periods(risk_previous_start, risk_previous_end)
    previous_at_risk_count = len(_at_risk_user_ids_for_period(
        project_id,
        company_id,
        previous_risk_start,
        previous_risk_end,
        before_previous_start,
        before_previous_end,
    ))
    at_risk_daily = _daily_at_risk_user_count_series(
        project_id,
        company_id,
        users,
        start_date,
        end_date,
        previous_start,
        previous_end,
    )

    active_users_card = _apply_metric_delta(
        _metric_card(
            'activeUsers',
            'ACTIVE USERS',
            'number',
            active_users,
            previous_active_users,
            daily['activeUsers'],
            peer_series=_peer_metric_series(peer_companies, daily_by_company, 'activeUsers'),
            benchmark_series=_benchmark_metric_series(benchmark_companies, daily_by_company, 'activeUsers'),
            benchmark_peer_count=benchmark_peer_count,
        ),
        company.get('activeUsersDeltaPct'),
    )
    avg_per_user_card = _apply_metric_delta(
        _metric_card(
            'avgPerUser',
            'AVG / USER',
            'duration',
            _avg(engaged, active_users),
            _avg(previous_engaged, previous_active_users),
            daily['avgPerUser'],
            peer_series=_peer_metric_series(peer_companies, daily_by_company, 'avgPerUser'),
            benchmark_series=_benchmark_metric_series(benchmark_companies, daily_by_company, 'avgPerUser'),
            benchmark_peer_count=benchmark_peer_count,
        ),
        company.get('avgEngagedSecondsPerUserDeltaPct'),
    )
    peer_new_reactivated_series = _peer_new_reactivated_metric_series(
        project_id,
        peer_companies,
        start_date,
        end_date,
        previous_start,
        bulk_context=bulk_context,
    )
    peer_at_risk_series = _peer_at_risk_user_metric_series(
        project_id,
        peer_companies,
        start_date,
        end_date,
        previous_start,
        previous_end,
    )

    return [
        active_users_card,
        _metric_card(
            'newReactivatedUsers',
            'NEW / REACTIVATED',
            'number',
            new_reactivated['new'] + new_reactivated['reactivated'],
            previous_new_reactivated['new'] + previous_new_reactivated['reactivated'],
            new_reactivated['daily'],
            secondary_text=f"{new_reactivated['new']} new · {new_reactivated['reactivated']} reactivated",
            peer_series=peer_new_reactivated_series,
            benchmark_peer_count=len(peer_new_reactivated_series),
        ),
        _metric_card(
            'visits',
            'VISITS',
            'number',
            visits,
            previous_visits,
            daily['visits'],
            peer_series=_peer_metric_series(peer_companies, daily_by_company, 'visits'),
            benchmark_series=_benchmark_metric_series(benchmark_companies, daily_by_company, 'visits'),
            benchmark_peer_count=benchmark_peer_count,
        ),
        _metric_card(
            'engaged',
            'ENGAGED',
            'duration',
            engaged,
            previous_engaged,
            daily['engaged'],
            peer_series=_peer_metric_series(peer_companies, daily_by_company, 'engaged'),
            benchmark_series=_benchmark_metric_series(benchmark_companies, daily_by_company, 'engaged'),
            benchmark_peer_count=benchmark_peer_count,
        ),
        avg_per_user_card,
        _metric_card(
            'interaction',
            'INTERACTION',
            'percent',
            interaction,
            previous_interaction,
            daily['interaction'],
            delta_unit='pp',
            peer_series=_peer_metric_series(peer_companies, daily_by_company, 'interaction'),
            benchmark_series=_benchmark_metric_series(benchmark_companies, daily_by_company, 'interaction'),
            benchmark_peer_count=benchmark_peer_count,
        ),
        {
            **_metric_card(
                'adoptionBreadth',
                'ADOPTION BREADTH',
                'number',
                company.get('productAreasUsed', 0),
                previous_company.get('product_areas_used', 0),
                daily['adoptionBreadth'],
                secondary_text=f"{company.get('productAreasUsed', 0)} areas · {company.get('pagesUsed', 0)} pages",
                peer_series=_peer_metric_series(peer_companies, daily_by_company, 'adoptionBreadth'),
                benchmark_series=_benchmark_metric_series(benchmark_companies, daily_by_company, 'adoptionBreadth'),
                benchmark_peer_count=benchmark_peer_count,
            ),
            'formattedDelta': _formatted_delta(company.get('productAreasDelta', 0), 'area'),
        },
        _metric_card(
            'atRiskUsers',
            'AT-RISK USERS',
            'number',
            len(at_risk_users),
            previous_at_risk_count,
            at_risk_daily,
            peer_series=peer_at_risk_series,
            benchmark_peer_count=len(peer_at_risk_series),
        ),
    ]


def _page_names(project_id, page_rule_ids):
    ids = [page_rule_id for page_rule_id in page_rule_ids if page_rule_id is not None]
    return {
        str(row['id']): row['page_name']
        for row in ProjectPageRule.objects.filter(project_id=project_id, id__in=ids).values('id', 'page_name')
    }


def _top_pages(project_id, company_id, start_date, end_date, previous_start, previous_end, metadata):
    current_rows = list(
        _company_base_queryset(project_id, start_date, end_date)
        .filter(company_id=company_id, page_rule_id__isnull=False)
        .values('page_rule_id', 'product_area_key', 'product_area_name')
        .annotate(
            visits=Sum('visits_count'),
            engaged_seconds=Sum('engaged_seconds'),
            click_visits=Sum('visits_with_click_count'),
        )
    )
    previous_rows = {
        row['page_rule_id']: row
        for row in (
            _company_base_queryset(project_id, previous_start, previous_end)
            .filter(company_id=company_id, page_rule_id__isnull=False)
            .values('page_rule_id')
            .annotate(
                visits=Sum('visits_count'),
                engaged_seconds=Sum('engaged_seconds'),
                click_visits=Sum('visits_with_click_count'),
            )
        )
    }
    users_current = {
        row['page_rule_id']: _to_int(row.get('users'))
        for row in (
            _user_base_queryset(project_id, start_date, end_date)
            .filter(company_id=company_id, page_rule_id__isnull=False)
            .values('page_rule_id')
            .annotate(users=Count('user_id', distinct=True))
        )
    }
    users_previous = {
        row['page_rule_id']: _to_int(row.get('users'))
        for row in (
            _user_base_queryset(project_id, previous_start, previous_end)
            .filter(company_id=company_id, page_rule_id__isnull=False)
            .values('page_rule_id')
            .annotate(users=Count('user_id', distinct=True))
        )
    }
    page_names = _page_names(project_id, [row['page_rule_id'] for row in current_rows])
    daily = defaultdict(dict)
    for row in (
        _company_base_queryset(project_id, start_date, end_date)
        .filter(company_id=company_id, page_rule_id__isnull=False)
        .values('page_rule_id', 'date')
        .annotate(engaged=Sum('engaged_seconds'))
    ):
        daily[row['page_rule_id']][row['date']] = _to_int(row.get('engaged'))

    dates = _date_series(start_date, end_date)
    rows = []
    for row in current_rows:
        page_rule_id = row['page_rule_id']
        previous = previous_rows.get(page_rule_id, {})
        visits = _to_int(row.get('visits'))
        previous_visits = _to_int(previous.get('visits'))
        engaged = _to_int(row.get('engaged_seconds'))
        previous_engaged = _to_int(previous.get('engaged_seconds'))
        interaction = _safe_pct(row.get('click_visits'), visits)
        previous_interaction = _safe_pct(previous.get('click_visits'), previous_visits)
        info = _area_info(row.get('product_area_key'), row.get('product_area_name'), metadata)

        rows.append({
            'pageRuleId': str(page_rule_id),
            'pageName': page_names.get(str(page_rule_id)) or f"Page {page_rule_id}",
            'productArea': info['name'],
            'productAreaKey': info['slug'],
            'color': info['color'],
            'areaRole': info['areaRole'],
            'isAdoptionRecommendable': info['isAdoptionRecommendable'],
            'users': users_current.get(page_rule_id, 0),
            'usersDeltaPct': _delta_pct(users_current.get(page_rule_id, 0), users_previous.get(page_rule_id, 0)),
            'visits': visits,
            'visitsDeltaPct': _delta_pct(visits, previous_visits),
            'engagedSeconds': engaged,
            'engagedDeltaPct': _delta_pct(engaged, previous_engaged),
            'avgVisitSeconds': _avg(engaged, visits),
            'avgVisitDeltaPct': _delta_pct(_avg(engaged, visits), _avg(previous_engaged, previous_visits)),
            'interactionPct': interaction,
            'interactionDeltaPp': _delta_pp(interaction, previous_interaction),
            'dailySeries': [{'date': day.isoformat(), 'value': daily[page_rule_id].get(day, 0)} for day in dates],
        })

    return sorted(rows, key=lambda item: (-item['engagedSeconds'], -item['visits'], item['pageName']))


def _area_treemap(top_pages):
    total = sum(row['engagedSeconds'] for row in top_pages)
    by_area = defaultdict(list)
    for row in top_pages:
        by_area[row['productArea']].append(row)

    return {
        'totalEngagedSeconds': total,
        'nodes': [
            {
                'name': area,
                'page_group': area,
                'productArea': area,
                'color': rows[0].get('color') or '',
                'areaRole': rows[0].get('areaRole'),
                'isAdoptionRecommendable': rows[0].get('isAdoptionRecommendable'),
                'value': sum(row['engagedSeconds'] for row in rows),
                'engagedSeconds': sum(row['engagedSeconds'] for row in rows),
                'visits': sum(row['visits'] for row in rows),
                'activeUsers': max((row['users'] for row in rows), default=0),
                'pageCount': len(rows),
                'isGroup': True,
                'children': [
                    {
                        'name': row['pageName'],
                        'pageRuleId': row['pageRuleId'],
                        'page_group': area,
                        'productArea': area,
                        'color': row.get('color') or rows[0].get('color') or '',
                        'areaRole': row.get('areaRole'),
                        'isAdoptionRecommendable': row.get('isAdoptionRecommendable'),
                        'value': row['engagedSeconds'],
                        'engagedSeconds': row['engagedSeconds'],
                        'visits': row['visits'],
                        'activeUsers': row['users'],
                        'shareOfCompanyEngaged': (row['engagedSeconds'] / max(total, 1)) * 100,
                    }
                    for row in rows
                ],
            }
            for area, rows in sorted(by_area.items(), key=lambda item: -sum(row['engagedSeconds'] for row in item[1]))
        ],
    }


def _area_usage_over_time(project_id, company_id, start_date, end_date, metadata):
    dates = _date_series(start_date, end_date)
    values = defaultdict(lambda: {day: 0 for day in dates})
    area_info = {}

    for row in (
        _company_base_queryset(project_id, start_date, end_date)
        .filter(company_id=company_id)
        .values('date', 'product_area_key', 'product_area_name')
        .annotate(engaged=Sum('engaged_seconds'))
    ):
        info = _area_info(row.get('product_area_key'), row.get('product_area_name'), metadata)
        area_info[info['name']] = info
        values[info['name']][row['date']] = _to_int(row.get('engaged'))

    series = [
        {
            'productArea': area,
            'color': area_info[area]['color'],
            'areaRole': area_info[area]['areaRole'],
            'isAdoptionRecommendable': area_info[area]['isAdoptionRecommendable'],
            'values': [day_values[day] for day in dates],
            'topPagesByDate': [{'date': day.isoformat(), 'pageNames': []} for day in dates],
        }
        for area, day_values in values.items()
        if any(value > 0 for value in day_values.values())
    ]
    series.sort(key=lambda row: (PRODUCT_AREA_ROLE_ORDER.get(row['areaRole'], 9), -sum(row['values']), row['productArea']))

    return {
        'dates': [day.isoformat() for day in dates],
        'productAreas': [row['productArea'] for row in series],
        'series': series,
        'finalAreaCount': len(series),
        'finalPageCount': 0,
    }


def _peer_active_users(company):
    return _to_int(company.get('activeUsers'))


def _peer_identified_or_seats(company):
    for key in ('seats', 'seatCount', 'totalSeats', 'licensedSeats', 'accountSeats', 'totalIdentifiedUsers', 'totalKnownUsers'):
        if key not in company:
            continue
        value = company.get(key)
        if value in (None, ''):
            continue
        value = _to_int(value)
        if value > 0:
            return value
    return None


def _peer_first_seen_ordinal(company):
    value = company.get('firstSeenDate') or company.get('first_seen_date') or company.get('accountCreatedDate')
    if not value:
        return None
    if hasattr(value, 'toordinal'):
        return value.toordinal()
    try:
        return date.fromisoformat(str(value)[:10]).toordinal()
    except ValueError:
        return None


def _peer_similarity_key(row, current):
    key = [abs(_peer_active_users(row) - _peer_active_users(current))]
    current_identified_or_seats = _peer_identified_or_seats(current)
    current_first_seen = _peer_first_seen_ordinal(current)

    if current_identified_or_seats is not None:
        row_identified_or_seats = _peer_identified_or_seats(row)
        key.extend((
            1 if row_identified_or_seats is None else 0,
            abs(row_identified_or_seats - current_identified_or_seats) if row_identified_or_seats is not None else 0,
        ))
    if current_first_seen is not None:
        row_first_seen = _peer_first_seen_ordinal(row)
        key.extend((
            1 if row_first_seen is None else 0,
            abs(row_first_seen - current_first_seen) if row_first_seen is not None else 0,
        ))

    key.append(row.get('name') or row.get('companyName') or row.get('id') or '')
    return tuple(key)


def _peer_active_users_key(row, current):
    return (
        abs(_peer_active_users(row) - _peer_active_users(current)),
        row.get('name') or row.get('companyName') or row.get('id') or '',
    )


def _select_peer_companies(current_company, company_rows, limit=10):
    candidates = [
        row
        for row in company_rows
        if row['id'] != current_company['id'] and _peer_active_users(row) > 0
    ]
    return sorted(candidates, key=lambda row: _peer_similarity_key(row, current_company))[:limit]


def _product_area_cells(company, product_area_names):
    distribution = {item['productArea']: item for item in company.get('productAreaDistribution', [])}
    return [
        {
            'productArea': area,
            'color': distribution.get(area, {}).get('color', ''),
            'used': (distribution.get(area, {}).get('engagedSeconds') or 0) > 0,
            'engagedSeconds': distribution.get(area, {}).get('engagedSeconds', 0),
            'visits': distribution.get(area, {}).get('visits', 0),
            'activeUsers': company.get('activeUsers', 0) if distribution.get(area, {}).get('engagedSeconds') else 0,
            'pagesUsed': distribution.get(area, {}).get('pagesUsed', 0),
        }
        for area in product_area_names
    ]


def _distribution_item_for_area(company, area_name):
    normalized_area = str(area_name or '').strip().lower()
    for item in company.get('productAreaDistribution', []) or []:
        item_area = item.get('productArea') or item.get('product_area_name') or item.get('name')
        if str(item_area or '').strip().lower() == normalized_area:
            return item
    return {}


def _peer_median_product_area_distribution(peers, product_area_names):
    area_names = list(product_area_names or [])
    if not area_names:
        seen = set()
        for peer in peers:
            for item in peer.get('productAreaDistribution', []) or []:
                area_name = item.get('productArea') or item.get('product_area_name') or item.get('name')
                if area_name and area_name not in seen:
                    seen.add(area_name)
                    area_names.append(area_name)

    rows = []
    for area_name in area_names:
        items = [_distribution_item_for_area(peer, area_name) for peer in peers]
        engaged_seconds = round(services._median([
            _to_int(item.get('engagedSeconds') or item.get('engaged_seconds'))
            for item in items
        ]))
        visits = round(services._median([
            _to_int(item.get('visits') or item.get('visits_count'))
            for item in items
        ]))
        pages_used = round(services._median([
            _to_int(item.get('pagesUsed') or item.get('pages_used'))
            for item in items
        ]))
        if engaged_seconds <= 0 and visits <= 0 and pages_used <= 0:
            continue

        sample = next((item for item in items if item), {})
        rows.append({
            'productArea': area_name,
            'product_area_name': area_name,
            'productAreaKey': sample.get('productAreaKey') or sample.get('product_area_key') or '',
            'product_area_key': sample.get('product_area_key') or sample.get('productAreaKey') or '',
            'color': sample.get('color') or '',
            'areaRole': sample.get('areaRole') or ProductArea.AREA_ROLE_UNKNOWN,
            'isAdoptionRecommendable': bool(sample.get('isAdoptionRecommendable')),
            'engagedSeconds': engaged_seconds,
            'engaged_seconds': engaged_seconds,
            'visits': visits,
            'pagesUsed': pages_used,
            'pages_used': pages_used,
        })

    total_engaged = sum(row['engagedSeconds'] for row in rows)
    for row in rows:
        row['percent'] = round((row['engagedSeconds'] / max(total_engaged, 1)) * 100) if total_engaged else 0

    return sorted(rows, key=lambda item: (-item['engagedSeconds'], item['productArea']))


def _peer_comparison(current_company, company_rows, product_area_names, peers=None):
    peers = peers if peers is not None else _select_peer_companies(current_company, company_rows, limit=10)

    rows = [{
        **current_company,
        'rowType': 'current',
        'keyDifference': 'This company',
        'productAreaAdoption': _product_area_cells(current_company, product_area_names),
    }]
    if peers:
        median_row = {
            'id': 'peer-median',
            'name': 'Peer median',
            'companyName': 'Peer median',
            'status': 'healthy',
            'activeUsers': round(services._median([peer['activeUsers'] for peer in peers])),
            'avgEngagedSecondsPerUser': round(services._median([peer['avgEngagedSecondsPerUser'] for peer in peers])),
            'avgEngagedSecondsPerUserDeltaPct': round(services._median([peer['avgEngagedSecondsPerUserDeltaPct'] for peer in peers])),
            'productAreasUsed': round(services._median([peer['productAreasUsed'] for peer in peers])),
            'pagesUsed': round(services._median([peer['pagesUsed'] for peer in peers])),
            'interactionPct': round(services._median([peer['interactionPct'] for peer in peers])),
            'productAreaDistribution': _peer_median_product_area_distribution(peers, product_area_names),
            'rowType': 'median',
            'keyDifference': 'Median of similar companies',
        }
        median_row['productAreaAdoption'] = _product_area_cells(median_row, product_area_names)
        rows.append(median_row)

    for peer in peers:
        rows.append({
            **peer,
            'rowType': 'peer',
            'keyDifference': _peer_key_difference(peer, current_company),
            'productAreaAdoption': _product_area_cells(peer, product_area_names),
        })

    insights = []
    median = rows[1] if len(rows) > 1 and rows[1].get('rowType') == 'median' else None
    if median:
        if current_company['avgEngagedSecondsPerUser'] > median['avgEngagedSecondsPerUser'] * 1.12:
            insights.append('Above peer median in engagement')
        elif current_company['avgEngagedSecondsPerUser'] < median['avgEngagedSecondsPerUser'] * 0.88:
            insights.append('Below peer median in engagement')
        if current_company['productAreasUsed'] > median['productAreasUsed']:
            insights.append('Above peer median in product adoption breadth')
        elif current_company['productAreasUsed'] < median['productAreasUsed']:
            insights.append('Below peer median in product adoption breadth')

    return {'insights': insights[:3], 'rows': rows}


def _peer_key_difference(peer, current):
    if peer.get('productAreasUsed', 0) >= current.get('productAreasUsed', 0) + 2:
        return 'Higher product adoption breadth'
    if peer.get('productAreasUsed', 0) <= current.get('productAreasUsed', 0) - 2:
        return 'Lower product adoption breadth'
    if peer.get('avgEngagedSecondsPerUser', 0) > current.get('avgEngagedSecondsPerUser', 0) * 1.18:
        return 'Higher engaged/user'
    if peer.get('avgEngagedSecondsPerUser', 0) < current.get('avgEngagedSecondsPerUser', 0) * 0.82:
        return 'Lower engaged/user'
    return 'Similar adoption breadth'


def _company_user_health_status(visits, engaged_seconds, product_areas_used, click_count, active_days=None, *, period_days=30):
    visits = _to_int(visits)
    engaged_seconds = _to_int(engaged_seconds)
    product_areas_used = _to_int(product_areas_used)
    click_count = _to_int(click_count)
    active_days = min(visits, int(period_days or 1)) if active_days is None else _to_int(active_days)
    interaction = click_count / max(visits, 1)
    power_thresholds = services.power_user_thresholds(period_days)
    healthy_visits = services.weekly_scaled_threshold(3, period_days)
    healthy_engaged = services.weekly_scaled_threshold(300, period_days)
    healthy_active_days = services.active_days_threshold(period_days, 0.10)
    passive_visits = services.passive_visits_threshold(period_days)
    passive_engaged = services.weekly_scaled_threshold(60, period_days)

    if visits <= 0 and engaged_seconds <= 0:
        return 'dropped'
    if (
        visits >= power_thresholds['visits']
        and engaged_seconds >= power_thresholds['engaged_seconds']
        and product_areas_used >= power_thresholds['product_areas']
        and active_days >= power_thresholds['active_days']
        and interaction >= power_thresholds['interaction']
    ):
        return 'power'
    if (
        visits >= healthy_visits
        and engaged_seconds >= healthy_engaged
        and product_areas_used >= 1
        and active_days >= healthy_active_days
    ):
        return 'healthy'
    if visits <= passive_visits or engaged_seconds < passive_engaged or interaction < 0.2:
        return 'passive'
    return 'light'


def _company_user_period_active(row):
    return any(_to_int(row.get(key)) > 0 for key in ('visits', 'engaged_seconds', 'click_count', 'active_days'))


def _company_health_distribution(project_id, company_id, start_date, end_date, previous_start, previous_end):
    counts = Counter()
    current_user_ids = set()
    period_days = (end_date - start_date).days + 1

    current_rows = (
        _user_base_queryset(project_id, start_date, end_date)
        .filter(company_id=company_id)
        .values('user_id')
        .annotate(
            active_days=Count('date', filter=Q(visits_count__gt=0) | Q(engaged_seconds__gt=0) | Q(click_count__gt=0), distinct=True),
            visits=Sum('visits_count'),
            engaged_seconds=Sum('engaged_seconds'),
            click_count=Sum('click_count'),
            product_areas_used=Count('product_area_key', filter=Q(visits_count__gt=0), distinct=True),
        )
    )
    for row in current_rows:
        current_user_ids.add(row['user_id'])
        status = _company_user_health_status(
            row.get('visits'),
            row.get('engaged_seconds'),
            row.get('product_areas_used'),
            row.get('click_count'),
            row.get('active_days'),
            period_days=period_days,
        )
        counts[status] += 1

    previous_user_ids = set(
        _user_base_queryset(project_id, previous_start, previous_end)
        .filter(company_id=company_id)
        .values_list('user_id', flat=True)
        .distinct()
    )
    counts['dropped'] += len(previous_user_ids - current_user_ids)

    total = sum(counts.values())
    if total <= 0:
        return []

    return [
        {
            'status': status,
            'label': label,
            'count': int(counts.get(status, 0)),
            'pct': round(int(counts.get(status, 0)) / total * 100, 1),
        }
        for status, label in USER_HEALTH_STATUSES
        if counts.get(status, 0) > 0
    ]


def _company_user_session_counts(project, company_id, user_ids, start_date, end_date):
    user_ids = [str(user_id) for user_id in user_ids or [] if user_id not in (None, '')]
    if not user_ids:
        return {}

    start_ts, end_ts = services._utc_bounds_for_local_dates(start_date, end_date, project.timezone)
    return {
        row['user_id']: _to_int(row.get('sessions'))
        for row in (
            PageVisit.objects
            .filter(
                project=project,
                company_id=company_id,
                user_id__in=user_ids,
                visit_start_ts__gte=start_ts,
                visit_start_ts__lt=end_ts,
            )
            .exclude(user_id__isnull=True)
            .exclude(user_id='')
            .values('user_id')
            .annotate(sessions=Count('session_id', distinct=True))
        )
    }


def _user_rows(project, company_id, start_date, end_date, previous_start, previous_end, product_area_names):
    project_id = project.id
    period_days = (end_date - start_date).days + 1
    current_rows = list(
        _user_base_queryset(project_id, start_date, end_date)
        .filter(company_id=company_id)
        .values('user_id')
        .annotate(
            name=Max('user_name_sample'),
            active_days=Count('date', filter=Q(visits_count__gt=0) | Q(engaged_seconds__gt=0) | Q(click_count__gt=0), distinct=True),
            visits=Sum('visits_count'),
            engaged_seconds=Sum('engaged_seconds'),
            click_count=Sum('click_count'),
            last_seen=Max('date'),
        )
    )
    current = {row['user_id']: row for row in current_rows}

    previous = {
        row['user_id']: row
        for row in (
            _user_base_queryset(project_id, previous_start, previous_end)
            .filter(company_id=company_id)
            .values('user_id')
            .annotate(
                name=Max('user_name_sample'),
                active_days=Count('date', filter=Q(visits_count__gt=0) | Q(engaged_seconds__gt=0) | Q(click_count__gt=0), distinct=True),
                visits=Sum('visits_count'),
                engaged_seconds=Sum('engaged_seconds'),
                click_count=Sum('click_count'),
                last_seen=Max('date'),
            )
        )
    }
    current_active_ids = {user_id for user_id, row in current.items() if _company_user_period_active(row)}
    previous_active_ids = {user_id for user_id, row in previous.items() if _company_user_period_active(row)}
    current_table_ids = [
        row['user_id']
        for row in sorted(
            [row for row in current_rows if row['user_id'] in current_active_ids],
            key=lambda item: (-_to_int(item.get('engaged_seconds')), item['user_id']),
        )
    ]
    dropped_ids = sorted(
        previous_active_ids - current_active_ids,
        key=lambda user_id: (
            -_to_int(previous.get(user_id, {}).get('engaged_seconds')),
            previous.get(user_id, {}).get('name') or user_id,
        ),
    )
    user_ids = [*current_table_ids, *dropped_ids]

    if not user_ids:
        return []

    session_counts = _company_user_session_counts(project, company_id, user_ids, start_date, end_date)
    risk_start, risk_end, risk_previous_start, risk_previous_end = _risk_comparison_periods(start_date, end_date)
    risk_current = {
        row['user_id']: row
        for row in (
            _user_base_queryset(project_id, risk_start, risk_end)
            .filter(company_id=company_id, user_id__in=current_table_ids)
            .values('user_id')
            .annotate(visits=Sum('visits_count'), engaged_seconds=Sum('engaged_seconds'))
        )
    }
    risk_previous = {
        row['user_id']: row
        for row in (
            _user_base_queryset(project_id, risk_previous_start, risk_previous_end)
            .filter(company_id=company_id, user_id__in=current_table_ids)
            .values('user_id')
            .annotate(visits=Sum('visits_count'), engaged_seconds=Sum('engaged_seconds'))
        )
    }
    area_rows = defaultdict(dict)
    for row in (
        _user_base_queryset(project_id, start_date, end_date)
        .filter(company_id=company_id, user_id__in=user_ids)
        .values('user_id', 'product_area_key', 'product_area_name')
        .annotate(
            visits=Sum('visits_count'),
            engaged_seconds=Sum('engaged_seconds'),
            pages_used=Count('page_rule_id', filter=Q(visits_count__gt=0), distinct=True),
        )
    ):
        area_name = row.get('product_area_name') or row.get('product_area_key') or 'Unassigned'
        area_rows[row['user_id']][area_name] = {
            'productArea': area_name,
            'used': _to_int(row.get('engaged_seconds')) > 0 or _to_int(row.get('visits')) > 0,
            'engagedSeconds': _to_int(row.get('engaged_seconds')),
            'visits': _to_int(row.get('visits')),
            'activeUsers': 1,
            'pagesUsed': _to_int(row.get('pages_used')),
        }

    rows = []
    for user_id in user_ids:
        row = current.get(user_id, {})
        previous_row = previous.get(user_id, {})
        risk_current_row = risk_current.get(user_id, {})
        risk_previous_row = risk_previous.get(user_id, {})
        has_current_activity = user_id in current_active_ids
        visits = _to_int(row.get('visits'))
        engaged = _to_int(row.get('engaged_seconds'))
        previous_visits = _to_int(previous_row.get('visits'))
        previous_engaged = _to_int(previous_row.get('engaged_seconds'))
        risk_engaged = _to_int(risk_current_row.get('engaged_seconds'))
        risk_visits = _to_int(risk_current_row.get('visits'))
        previous_risk_engaged = _to_int(risk_previous_row.get('engaged_seconds'))
        previous_risk_visits = _to_int(risk_previous_row.get('visits'))
        engaged_drop = previous_risk_engaged >= 600 and risk_engaged <= previous_risk_engaged * 0.5
        visits_drop = previous_risk_visits >= 4 and risk_visits <= previous_risk_visits * 0.5
        risk_status = 'at_risk' if has_current_activity and (engaged_drop or visits_drop) else 'active' if has_current_activity else 'dropped'

        user_areas = area_rows.get(user_id, {})
        top_area = ''
        if user_areas:
            top_area = max(user_areas.values(), key=lambda item: item['engagedSeconds'])['productArea']
        product_areas_used = len([
            cell
            for cell in user_areas.values()
            if cell['used'] or cell['engagedSeconds'] or cell['visits'] or cell['pagesUsed']
        ])
        status = _company_user_health_status(
            visits,
            engaged,
            product_areas_used,
            row.get('click_count'),
            row.get('active_days'),
            period_days=period_days,
        ) if has_current_activity else 'dropped'
        fallback_email_name = str(user_id).replace(' ', '.').lower()
        last_seen = row.get('last_seen') if has_current_activity else previous_row.get('last_seen')
        display_name = row.get('name') or previous_row.get('name') or user_id

        rows.append({
            'id': user_id,
            'name': display_name,
            'email': f'{fallback_email_name}@example.com' if '@' not in fallback_email_name else fallback_email_name,
            'status': status,
            'riskStatus': risk_status,
            'lastActive': _relative_date_label(last_seen, end_date),
            'lastActiveDays': (end_date - last_seen).days if last_seen else 9999,
            'activeDays': _to_int(row.get('active_days')) if has_current_activity else 0,
            'sessionsCount': session_counts.get(user_id, 0) if has_current_activity else 0,
            'visits': visits,
            'visitsDeltaPct': _delta_pct(visits, previous_visits),
            'engagedSeconds': engaged,
            'engagedDeltaPct': _delta_pct(engaged, previous_engaged),
            'interactionPct': _safe_pct(min(_to_int(row.get('click_count')), visits), visits),
            'productAreaAdoption': [
                cell
                for cell in user_areas.values()
                if cell['used'] or cell['engagedSeconds'] or cell['visits'] or cell['pagesUsed']
            ],
            'topArea': top_area,
        })

    return sorted(rows, key=lambda item: (
        0 if item.get('riskStatus') == 'at_risk' else 2 if item['status'] == 'dropped' else 1,
        -item['engagedSeconds'],
        item['name'],
    ))


def _health_summary(company, peer_comparison, users):
    if company.get('visits', 0) <= 0:
        return 'Not enough activity in this period to generate a reliable company insight.'
    at_risk_users = len([user for user in users if user.get('riskStatus') == 'at_risk'])
    median = next((row for row in peer_comparison.get('rows', []) if row.get('rowType') == 'median'), None)
    if at_risk_users >= 2 or company.get('status') == 'at_risk':
        return 'Usage has softened and several users may need attention.'
    if median and company['avgEngagedSecondsPerUser'] > median['avgEngagedSecondsPerUser'] and company['productAreasUsed'] >= median['productAreasUsed']:
        return 'Broad adoption and strong engagement indicate a healthy expansion-ready account.'
    if company.get('productAreasUsed', 0) <= 1:
        return 'Engagement is concentrated in a narrow set of product areas.'
    return 'This account shows steady product usage with room to broaden adoption.'


def _recommended_actions(company, peer_comparison, users, top_pages, product_area_options):
    actions = []
    median = next((row for row in peer_comparison.get('rows', []) if row.get('rowType') == 'median'), None)
    at_risk_users = [user for user in users if user.get('riskStatus') == 'at_risk']
    champions = [user for user in users if user.get('riskStatus') == 'active' and user['engagedSeconds'] >= 1800]

    if at_risk_users or company.get('engagedDeltaPct', 0) <= -35 or company.get('activeUsersDeltaPct', 0) <= -35:
        actions.append({
            'type': 'Churn risk',
            'category': 'Churn risk',
            'priority': 'high',
            'title': 'Check at-risk users',
            'reason': 'Several previously active users dropped below their normal activity level.',
            'metric': f"{len(at_risk_users)} at-risk",
            'metricLabel': f"{len(at_risk_users)} at-risk",
            'signals': [_formatted_delta(company.get('engagedDeltaPct', 0))],
            'ctaLabel': 'Open users table',
            'targetAnchor': 'company-users',
        })

    recommendable_areas = [area['name'] for area in product_area_options if area.get('areaRole') == ProductArea.AREA_ROLE_PRODUCT and area.get('isAdoptionRecommendable')]
    current_product_areas = {
        row['productArea']
        for row in top_pages
        if row.get('areaRole') == ProductArea.AREA_ROLE_PRODUCT and row.get('isAdoptionRecommendable') and row.get('engagedSeconds', 0) > 0
    }
    missing_product_areas = [area for area in recommendable_areas if area not in current_product_areas][:2]
    if missing_product_areas and median and company.get('productAreasUsed', 0) < median.get('productAreasUsed', 0):
        actions.append({
            'type': 'Adoption gap',
            'category': 'Adoption gap',
            'priority': 'medium',
            'title': 'Review underused product areas',
            'reason': f"{' and '.join(missing_product_areas)} are underused compared with similar companies.",
            'metric': f'{len(missing_product_areas)} product gaps',
            'metricLabel': f'{len(missing_product_areas)} product gaps',
            'ctaLabel': 'Review areas',
            'targetAnchor': 'area-usage',
        })

    setup_areas = [area['name'] for area in product_area_options if area.get('areaRole') == ProductArea.AREA_ROLE_SETUP]
    used_setup = {row['productArea'] for row in top_pages if row.get('areaRole') == ProductArea.AREA_ROLE_SETUP and row.get('engagedSeconds', 0) > 0}
    missing_setup = [area for area in setup_areas if area not in used_setup][:1]
    if missing_setup:
        actions.append({
            'type': 'Setup gap',
            'category': 'Setup gap',
            'priority': 'medium',
            'title': 'Check integrations setup',
            'reason': f'{missing_setup[0]} appears incomplete compared with similar companies.',
            'metric': 'Setup gap',
            'metricLabel': 'Setup gap',
            'ctaLabel': 'Review areas',
            'targetAnchor': 'area-usage',
        })

    if median and company.get('productAreasUsed', 0) >= median.get('productAreasUsed', 0) and company.get('avgEngagedSecondsPerUser', 0) > median.get('avgEngagedSecondsPerUser', 0):
        actions.append({
            'type': 'Expansion',
            'category': 'Expansion',
            'priority': 'medium',
            'title': 'Expand this account',
            'reason': 'Engagement and product adoption are above the peer baseline.',
            'metric': 'Above peers',
            'metricLabel': 'Above peers',
            'signals': [f"{company.get('activeUsers', 0)} active"],
            'ctaLabel': 'Compare peers',
            'targetAnchor': 'peer-comparison',
        })

    if champions:
        actions.append({
            'type': 'Champion users',
            'category': 'Champion users',
            'priority': 'low',
            'title': 'Start from active champions',
            'reason': 'Several users show strong recent engagement and can drive expansion.',
            'metric': f"{company.get('activeUsers', 0)} active · {len(champions)} champions",
            'metricLabel': f"{company.get('activeUsers', 0)} active · {len(champions)} champions",
            'ctaLabel': 'View users',
            'targetAnchor': 'company-users',
        })

    return actions[:5]


def build_company_detail_payload(project, company_id, *, range_key='last_30_days', overview_payload=None, bulk_context=None):
    if bulk_context:
        start_date = bulk_context.start_date
        end_date = bulk_context.end_date
        previous_start = bulk_context.previous_start
        previous_end = bulk_context.previous_end
        metadata = bulk_context.metadata()
        product_areas = bulk_context.product_areas()
        company_rows = [_copy_company_detail_row(row) for row in bulk_context.company_rows()]
    else:
        start_date, end_date = services.resolve_period(project.timezone, range_key=range_key)
        previous_start, previous_end = services.previous_period(start_date, end_date)
        metadata = _area_metadata(project.id)
        product_areas = product_area_options(project.id, metadata)
        color_lookup = build_product_area_color_lookup(product_areas, prefer_explicit=True)
        metadata = apply_product_area_metadata_colors(
            metadata,
            color_lookup,
            prefer_explicit=True,
        )
        if overview_payload and overview_payload.get('companies'):
            company_rows = _company_rows_from_overview_payload(overview_payload, metadata, end_date)
        else:
            company_rows = _company_rows(project.id, start_date, end_date, previous_start, previous_end, metadata)
    product_area_names = [area['name'] for area in product_areas]
    current_company = next((row for row in company_rows if str(row['id']) == str(company_id)), None)

    if not current_company:
        return None, company_rows, product_areas

    if overview_payload and overview_payload.get('companies'):
        _hydrate_peer_optional_metadata(project.id, current_company, company_rows)

    if bulk_context:
        current_company_summary = bulk_context.company_summaries([current_company['id']]).get(current_company['id'], {})
        previous_company = bulk_context.company_summaries([current_company['id']], period='previous').get(current_company['id'], {})
    else:
        current_company_summary = _company_summaries(
            project.id,
            start_date,
            end_date,
            company_ids=[current_company['id']],
            include_active_users=False,
            metadata=metadata,
        ).get(current_company['id'], {})
        previous_company = _company_summaries(
            project.id,
            previous_start,
            previous_end,
            company_ids=[current_company['id']],
            include_active_users=False,
            metadata=metadata,
        ).get(current_company['id'], {})
    _apply_company_summary_to_detail_row(current_company, current_company_summary, previous_company, end_date)

    selected_peers = _select_peer_companies(current_company, company_rows, limit=10)
    metric_benchmark_companies = [
        row for row in company_rows
        if row['id'] != current_company['id'] and _peer_active_users(row) > 0
    ]
    if bulk_context and selected_peers:
        peer_summaries = bulk_context.company_summaries([row['id'] for row in selected_peers])
    else:
        peer_summaries = _company_summaries(
            project.id,
            start_date,
            end_date,
            company_ids=[row['id'] for row in selected_peers],
            include_active_users=False,
            metadata=metadata,
        ) if selected_peers else {}
    for peer in selected_peers:
        _apply_company_summary_to_detail_row(peer, peer_summaries.get(peer['id']))

    top_pages = _top_pages(project.id, current_company['id'], start_date, end_date, previous_start, previous_end, metadata)
    users = _user_rows(project, current_company['id'], start_date, end_date, previous_start, previous_end, product_area_names)
    peer_comparison = _peer_comparison(current_company, company_rows, product_area_names, peers=selected_peers)
    payload = {
        'schema_version': COMPANY_DETAIL_PAYLOAD_SCHEMA_VERSION,
        'project': {'id': project.id, 'name': project.name},
        'company': current_company,
        'productAreas': product_areas,
        'period': {
            'key': _detail_period_key(range_key),
            'days': _period_days(range_key),
            'startDate': start_date.isoformat(),
            'endDate': end_date.isoformat(),
            'previousStartDate': previous_start.isoformat(),
            'previousEndDate': previous_end.isoformat(),
        },
        'metricCards': _metric_cards(
            project.id,
            current_company['id'],
            start_date,
            end_date,
            previous_start,
            previous_end,
            current_company,
            previous_company,
            users,
            metadata,
            selected_peers,
            metric_benchmark_companies,
            bulk_context=bulk_context,
        ),
        'areaTreemap': _area_treemap(top_pages),
        'adoptionBreadthSeries': _area_usage_over_time(project.id, current_company['id'], start_date, end_date, metadata),
        'topPages': top_pages[:15],
        'allTopPages': top_pages,
        'peerComparison': peer_comparison,
        'companyHealthDistribution': _company_health_distribution(project.id, current_company['id'], start_date, end_date, previous_start, previous_end),
        'users': users,
    }
    payload['healthSummary'] = _health_summary(current_company, peer_comparison, users)
    payload['recommendedActions'] = _recommended_actions(current_company, peer_comparison, users, top_pages, product_areas)

    return payload, company_rows, product_areas
