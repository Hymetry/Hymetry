import hashlib
import json
from collections import Counter, defaultdict

from django.db.models import Count, Max, Min, Q, Sum
from django.utils import timezone as django_timezone

from apps.pages import queries, services
from apps.pages.models import PageDailyMetric, PageUserDailyMetric, PageVisit
from apps.pages.product_area_colors import resolve_product_area_colors
from apps.projects.models import Project
from apps.tracker.models import ProjectPageRule


USERS_PAYLOAD_SCHEMA_VERSION = 9
SCATTER_VISIBLE_LIMIT = 300
INITIAL_USERS_PAYLOAD_LIMIT = 50


def _base_user_queryset(project_id, start_date, end_date):
    return (
        PageUserDailyMetric.objects
        .filter(project_id=project_id, date__gte=start_date, date__lte=end_date)
        .exclude(user_id__isnull=True)
        .exclude(user_id='')
    )


def _period_key_days(range_key):
    return {
        'last_7_days': 7,
        'last_30_days': 30,
        'last_90_days': 90,
        'last_180_days': 180,
    }.get(range_key, 30)


def _format_duration(seconds):
    seconds = max(0, int(seconds or 0))
    if seconds < 60:
        return f'{seconds}s'
    hours = seconds // 3600
    minutes = round((seconds % 3600) / 60)
    if hours:
        return f'{hours}h {minutes}m' if minutes else f'{hours}h'
    return f'{minutes}m'


def _stable_random_score(value, salt):
    token = f'{salt}|{value}'.encode('utf-8')
    return int(hashlib.sha256(token).hexdigest()[:16], 16)


def _random_scatter_sample(users, limit, salt):
    if len(users) <= limit:
        return list(users)

    return sorted(
        users,
        key=lambda user: (
            _stable_random_score(user.get('id') or user.get('email') or user.get('name') or '', salt),
            user.get('id') or user.get('email') or user.get('name') or '',
        ),
    )[:limit]


def _weekly_scaled_threshold(base_value, period_days):
    return services.weekly_scaled_threshold(base_value, period_days)


def _active_days_threshold(period_days, share):
    return services.active_days_threshold(period_days, share)


def _passive_visits_threshold(period_days):
    return services.passive_visits_threshold(period_days)


def _safe_email(user_id):
    value = str(user_id or '').strip()
    return value if '@' in value else ''


def _email_for_user(user_id, email_lookup):
    return (email_lookup or {}).get(str(user_id or '')) or _safe_email(user_id)


def _name_from_user_id(user_id):
    value = str(user_id or '').strip()
    if '@' in value:
        value = value.split('@', 1)[0]
    value = value.replace('.', ' ').replace('_', ' ').replace('-', ' ')
    return ' '.join(word.capitalize() for word in value.split()) or str(user_id or 'User')


def _format_date(value):
    return value.isoformat() if value else ''


def _relative_date_label(value, end_date):
    if not value:
        return '-'
    days = max(0, (end_date - value).days)
    if days <= 0:
        return 'Today'
    return f'{days}d ago'


def _last_active_sort(value, end_date):
    if not value:
        return 9999
    return max(0, (end_date - value).days)


def _delta_pct_value(current, previous):
    delta = services._delta_pct(current, previous)
    return delta.get('value') if isinstance(delta, dict) and delta.get('value') is not None else 0


def _delta_payload(current, previous, *, lower_is_better=False):
    delta = services._delta_pct(current, previous)
    value = delta.get('value') if isinstance(delta, dict) else 0
    if lower_is_better and value is not None:
        if value <= -5:
            delta['direction'] = 'positive'
        elif value >= 5:
            delta['direction'] = 'negative'
        else:
            delta['direction'] = 'neutral'
    return delta


def _user_metrics(project_id, start_date, end_date):
    rows = (
        _base_user_queryset(project_id, start_date, end_date)
        .values('user_id')
        .annotate(
            user_name=Max('user_name_sample'),
            company_id=Max('company_id'),
            visits=Sum('visits_count'),
            engaged_seconds=Sum('engaged_seconds'),
            click_count=Sum('click_count'),
            pages_used=Count('page_rule_id', filter=Q(visits_count__gt=0), distinct=True),
            product_areas_used=Count('product_area_key', filter=Q(visits_count__gt=0), distinct=True),
            active_days=Count('date', filter=Q(visits_count__gt=0), distinct=True),
            first_seen_date=Min('date'),
            last_seen_date=Max('date'),
        )
    )
    metrics = {}
    for row in rows:
        user_id = str(row.get('user_id') or '').strip()
        if not user_id:
            continue
        metrics[user_id] = {
            'user_id': user_id,
            'user_name': row.get('user_name') or '',
            'company_id': row.get('company_id') or '',
            'visits': int(row.get('visits') or 0),
            'engaged_seconds': int(row.get('engaged_seconds') or 0),
            'click_count': int(row.get('click_count') or 0),
            'pages_used': int(row.get('pages_used') or 0),
            'product_areas_used': int(row.get('product_areas_used') or 0),
            'active_days': int(row.get('active_days') or 0),
            'first_seen_date': row.get('first_seen_date'),
            'last_seen_date': row.get('last_seen_date'),
        }
    return metrics


def _user_period_active(row):
    return any(int(row.get(key) or 0) > 0 for key in ('visits', 'engaged_seconds', 'click_count', 'active_days'))


def _visit_queryset(project, start_date, end_date):
    start_ts, end_ts = services._utc_bounds_for_local_dates(start_date, end_date, project.timezone)
    return (
        PageVisit.objects
        .filter(project=project, visit_start_ts__gte=start_ts, visit_start_ts__lt=end_ts)
        .exclude(user_id__isnull=True)
        .exclude(user_id='')
    )


def _visit_identity(project, start_date, end_date):
    rows = (
        _visit_queryset(project, start_date, end_date)
        .values('user_id')
        .annotate(
            user_name=Max('user_name_sample'),
            company_id=Max('company_id'),
            company_name=Max('company_name_sample'),
            sessions=Count('session_id', distinct=True),
            last_visit_ts=Max('visit_start_ts'),
        )
    )
    return {str(row['user_id']): row for row in rows if row.get('user_id')}


def _company_names(project_id, start_date, end_date):
    names = {}
    for row in (
        _base_user_queryset(project_id, start_date, end_date)
        .exclude(company_id__isnull=True)
        .exclude(company_id='')
        .values('company_id')
        .annotate(company_name=Max('company_id'))
    ):
        names[row['company_id']] = row.get('company_name') or row['company_id']
    return names


def _company_names_from_visits(project, start_date, end_date):
    names = {}
    for row in (
        _visit_queryset(project, start_date, end_date)
        .exclude(company_id__isnull=True)
        .exclude(company_id='')
        .values('company_id')
        .annotate(company_name=Max('company_name_sample'))
    ):
        names[row['company_id']] = row.get('company_name') or row['company_id']
    return names


def _company_engaged_totals(project_id, start_date, end_date):
    return {
        row['company_id']: int(row.get('engaged_seconds') or 0)
        for row in (
            _base_user_queryset(project_id, start_date, end_date)
            .exclude(company_id__isnull=True)
            .exclude(company_id='')
            .values('company_id')
            .annotate(engaged_seconds=Sum('engaged_seconds'))
        )
    }


def _product_area_short_label(name, short_name=''):
    short_label = str(short_name or '').strip()
    full_name = str(name or '').strip()
    if short_label and short_label != full_name and len(short_label) <= 8:
        return short_label
    words = full_name.split()
    if len(words) > 1:
        return ''.join(word[0] for word in words if word).upper()[:7]
    return full_name[:7] if len(full_name) <= 8 else f'{full_name[:6]}.'


def _product_area_options(project_id, start_date, end_date):
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
        name = row.get('product_area_name') or row.get('product_area_key') or 'Unassigned'
        if name in seen:
            continue
        seen.add(name)
        options.append({
            'key': row.get('product_area_key') or 'unassigned',
            'name': name,
            'shortName': _product_area_short_label(name, row.get('product_area_short_name')),
            'color': row.get('product_area_color') or '',
        })
    if options:
        return resolve_product_area_colors(options[:9])

    fallback_rows = (
        _base_user_queryset(project_id, start_date, end_date)
        .values('product_area_key')
        .annotate(
            product_area_name=Max('product_area_name'),
            engaged_seconds=Sum('engaged_seconds'),
        )
        .order_by('-engaged_seconds', 'product_area_name')
    )
    for row in fallback_rows:
        name = row.get('product_area_name') or row.get('product_area_key') or 'Unassigned'
        if name in seen:
            continue
        seen.add(name)
        options.append({
            'key': row.get('product_area_key') or 'unassigned',
            'name': name,
            'shortName': _product_area_short_label(name),
            'color': '',
        })
    return resolve_product_area_colors(options[:9])


def _page_rule_names(project_id, page_rule_ids):
    ids = [int(value) for value in page_rule_ids if value is not None]
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


def _area_usage_by_user(project_id, start_date, end_date):
    usage = defaultdict(list)
    rows = (
        _base_user_queryset(project_id, start_date, end_date)
        .values('user_id', 'product_area_key')
        .annotate(
            product_area_name=Max('product_area_name'),
            engaged_seconds=Sum('engaged_seconds'),
            visits=Sum('visits_count'),
            clicks=Sum('click_count'),
        )
        .order_by('user_id', '-engaged_seconds')
    )
    for row in rows:
        name = row.get('product_area_name') or row.get('product_area_key') or 'Unassigned'
        usage[str(row['user_id'])].append({
            'name': name,
            'engagedSeconds': int(row.get('engaged_seconds') or 0),
            'visits': int(row.get('visits') or 0),
            'clicks': int(row.get('clicks') or 0),
        })
    return usage


def _feature_usage_by_user(project_id, start_date, end_date):
    raw_rows = (
        _base_user_queryset(project_id, start_date, end_date)
        .values('user_id', 'page_rule_id', 'product_area_key')
        .annotate(
            product_area_name=Max('product_area_name'),
            engaged_seconds=Sum('engaged_seconds'),
            visits=Sum('visits_count'),
            clicks=Sum('click_count'),
        )
        .order_by('user_id', '-engaged_seconds')
    )
    rows = list(raw_rows)
    rule_names = _page_rule_names(project_id, {row.get('page_rule_id') for row in rows})
    features = defaultdict(list)
    feature_product_areas = {}
    page_features = []
    seen_features = set()

    for row in rows:
        rule = rule_names.get(row.get('page_rule_id')) or {}
        area_name = row.get('product_area_name') or rule.get('product_area') or 'Unassigned'
        page_name = rule.get('page_name') or area_name
        if not page_name:
            continue
        feature_product_areas[page_name] = area_name
        if page_name not in seen_features:
            seen_features.add(page_name)
            page_features.append({
                'value': page_name,
                'label': page_name,
                'group': area_name,
                'search': f'{page_name} {area_name}',
            })
        features[str(row['user_id'])].append({
            'feature': page_name,
            'productArea': area_name,
            'engagedSeconds': int(row.get('engaged_seconds') or 0),
            'visits': int(row.get('visits') or 0),
            'clicks': int(row.get('clicks') or 0),
        })
    return features, page_features, feature_product_areas


def _status_for_user(row, previous=None, *, period_days=30):
    visits = int(row.get('visits') or 0)
    engaged = int(row.get('engaged_seconds') or 0)
    areas = int(row.get('product_areas_used') or 0)
    clicks = int(row.get('click_count') or 0)
    active_days = int(row.get('active_days') or 0)
    interaction = clicks / max(visits, 1)
    power_thresholds = services.power_user_thresholds(period_days)
    healthy_visits = _weekly_scaled_threshold(3, period_days)
    healthy_engaged = _weekly_scaled_threshold(300, period_days)
    healthy_active_days = _active_days_threshold(period_days, 0.10)
    passive_visits = _passive_visits_threshold(period_days)
    passive_engaged = _weekly_scaled_threshold(60, period_days)

    if visits <= 0 and engaged <= 0:
        return 'Passive'
    if (
        visits >= power_thresholds['visits']
        and engaged >= power_thresholds['engaged_seconds']
        and areas >= power_thresholds['product_areas']
        and active_days >= power_thresholds['active_days']
        and interaction >= power_thresholds['interaction']
    ):
        return 'Power'
    if visits >= healthy_visits and engaged >= healthy_engaged and areas >= 1 and active_days >= healthy_active_days:
        return 'Healthy'
    if visits <= passive_visits or engaged < passive_engaged or interaction < 0.2:
        return 'Passive'
    return 'Light'


def _low_engagement(row):
    visits = int(row.get('visits') or 0)
    engaged = int(row.get('engaged_seconds') or 0)
    clicks = int(row.get('click_count') or 0)
    return visits <= 2 or engaged < 60 or clicks <= 0


def _daily_series(project_id, start_date, end_date, *, dropped_count=0):
    days = list(services._date_range(start_date, end_date))
    labels = [day.isoformat() for day in days]
    by_day = {
        day: {
            'active': 0,
            'engaged': 0,
            'power': 0,
            'low': 0,
            'statuses': Counter({'Dropped': dropped_count}) if dropped_count else Counter(),
        }
        for day in days
    }
    daily_user_metrics = {}
    area_rows = (
        _base_user_queryset(project_id, start_date, end_date)
        .values('date', 'user_id', 'product_area_key')
        .annotate(
            visits=Sum('visits_count'),
            engaged_seconds=Sum('engaged_seconds'),
            click_count=Sum('click_count'),
        )
    )

    for row in area_rows:
        day = row.get('date')
        if day not in by_day:
            continue
        user_id = str(row.get('user_id') or '').strip()
        if not user_id:
            continue
        key = (day, user_id)
        user_metric = daily_user_metrics.setdefault(key, {
            'date': day,
            'user_id': user_id,
            'visits': 0,
            'engaged_seconds': 0,
            'click_count': 0,
            'product_areas': set(),
        })
        visits = int(row.get('visits') or 0)
        user_metric['visits'] += visits
        user_metric['engaged_seconds'] += int(row.get('engaged_seconds') or 0)
        user_metric['click_count'] += int(row.get('click_count') or 0)

        if visits > 0 and row.get('product_area_key'):
            user_metric['product_areas'].add(row.get('product_area_key'))

    daily_rows_by_day = defaultdict(list)
    for user_metric in daily_user_metrics.values():
        daily_row = {
            'user_id': user_metric['user_id'],
            'visits': user_metric['visits'],
            'engaged_seconds': user_metric['engaged_seconds'],
            'click_count': user_metric['click_count'],
            'product_areas_used': len(user_metric['product_areas']),
            'product_area_keys': user_metric['product_areas'],
            'active_days': 1 if _user_period_active(user_metric) else 0,
        }
        daily_rows_by_day[user_metric['date']].append(daily_row)

    cumulative = {}
    for day in days:
        metric = by_day[day]
        for daily_row in daily_rows_by_day.get(day, []):
            user_id = daily_row['user_id']
            cumulative_row = cumulative.setdefault(user_id, {
                'visits': 0,
                'engaged_seconds': 0,
                'click_count': 0,
                'product_areas': set(),
                'active_days': 0,
            })

            cumulative_row['visits'] += daily_row['visits']
            cumulative_row['engaged_seconds'] += daily_row['engaged_seconds']
            cumulative_row['click_count'] += daily_row['click_count']
            cumulative_row['product_areas'].update(daily_row['product_area_keys'])
            cumulative_row['active_days'] += daily_row['active_days']

            metric['active'] += 1
            metric['engaged'] += int(daily_row.get('engaged_seconds') or 0)
            status = _status_for_user(daily_row, period_days=1)
            if status == 'Power':
                metric['power'] += 1
            if _low_engagement(daily_row):
                metric['low'] += 1

        elapsed_days = (day - start_date).days + 1
        statuses = Counter({'Dropped': dropped_count}) if dropped_count else Counter()
        for cumulative_row in cumulative.values():
            status = _status_for_user(
                {
                    'visits': cumulative_row['visits'],
                    'engaged_seconds': cumulative_row['engaged_seconds'],
                    'click_count': cumulative_row['click_count'],
                    'product_areas_used': len(cumulative_row['product_areas']),
                    'active_days': cumulative_row['active_days'],
                },
                period_days=elapsed_days,
            )
            statuses[status] += 1
        metric['statuses'] = statuses

    return {
        'labels': labels,
        'activeUsers': [by_day[day]['active'] for day in days],
        'engagedPerUser': [
            round(by_day[day]['engaged'] / by_day[day]['active']) if by_day[day]['active'] else 0
            for day in days
        ],
        'powerUsers': [by_day[day]['power'] for day in days],
        'lowEngagementUsers': [by_day[day]['low'] for day in days],
        'statusMixByDate': [
            {
                'date': day.isoformat(),
                'power': by_day[day]['statuses'].get('Power', 0),
                'healthy': by_day[day]['statuses'].get('Healthy', 0),
                'light': by_day[day]['statuses'].get('Light', 0),
                'passive': by_day[day]['statuses'].get('Passive', 0),
                'dropped': by_day[day]['statuses'].get('Dropped', 0),
            }
            for day in days
        ],
    }


def _engagement_buckets(users):
    buckets = [
        ('0-1m', 0, 60),
        ('1-5m', 60, 300),
        ('5-15m', 300, 900),
        ('15-60m', 900, 3600),
        ('1h+', 3600, None),
    ]
    counts = Counter()
    for row in users:
        engaged = int(row.get('engagedSeconds') or 0)
        for label, lower, upper in buckets:
            if engaged >= lower and (upper is None or engaged < upper):
                counts[label] += 1
                break
    return [{'label': label, 'bucket': label, 'count': counts[label], 'users': counts[label]} for label, _lower, _upper in buckets]


def _status_distribution(users):
    order = ['Power', 'Healthy', 'Light', 'Passive', 'Dropped']
    counts = Counter(row.get('status') or 'Passive' for row in users)
    total = sum(counts.values()) or 1
    return [
        {
            'status': status,
            'count': int(counts.get(status, 0)),
            'pct': round(int(counts.get(status, 0)) / total * 100, 1),
        }
        for status in order
    ]


def _metric_row_delta(current, previous, key):
    return _delta_pct_value(current.get(key), previous.get(key))


def _attention_rows(users, previous_metrics):
    rows = []
    for user in users:
        previous = previous_metrics.get(user['userId'] or user['id'], {})
        engaged_delta = float(user.get('engagedDeltaPct') or 0)
        visits_delta = float(user.get('visitsDeltaPct') or 0)
        engaged = int(user.get('engagedSeconds') or 0)
        visits = int(user.get('visitsCount') or 0)
        last_active_days = int(user.get('lastActiveSort') or 0)
        status = user.get('status') or 'Passive'
        score = 0
        signal = ''
        reason = ''
        severity = 'inactive'

        if engaged_delta <= -40 and int(previous.get('engaged_seconds') or 0) >= 300:
            score += 45 + min(20, abs(int(engaged_delta)) // 3)
            signal = f'{round(engaged_delta)}% engaged'
            reason = 'Activity drop'
            severity = 'negative'
        if visits_delta <= -40 and int(previous.get('visits') or 0) >= 3:
            score += 35 + min(15, abs(int(visits_delta)) // 4)
            if not signal:
                signal = f'{round(visits_delta)}% visits'
                reason = 'Dropped from active'
                severity = 'negative'
        if last_active_days >= 7:
            score += 30 + min(20, last_active_days)
            if not signal:
                signal = f'{last_active_days}d inactive'
                reason = 'Recently inactive'
                severity = 'inactive'
        if status == 'Dropped':
            score += 28
            if not signal:
                signal = f'{_format_duration(engaged)} engaged'
                reason = 'Very low usage'
                severity = 'low'
        elif status == 'Passive':
            score += 18
        if visits <= 2 or engaged < 60:
            score += 18
            if not signal:
                signal = f'{_format_duration(engaged)} engaged'
                reason = 'Very low usage'
                severity = 'low'

        if score <= 0:
            continue
        rows.append({
            'id': user.get('id'),
            'userId': user.get('userId') or user.get('id'),
            'name': user.get('name'),
            'company': user.get('company'),
            'companyId': user.get('companyId') or user.get('company_id'),
            'status': status,
            'signal': signal or 'Needs review',
            'reason': reason or 'Usage slipping',
            'severity': severity,
            'riskScore': score,
        })

    return sorted(rows, key=lambda item: (-item['riskScore'], item['name'] or ''))[:5]


def _momentum_rows(users, previous_metrics, *, period_days=30):
    rows = []
    for user in users:
        previous = previous_metrics.get(user['userId'] or user['id'], {})
        engaged_delta = float(user.get('engagedDeltaPct') or 0)
        visits_delta = float(user.get('visitsDeltaPct') or 0)
        previous_areas = int(previous.get('product_areas_used') or 0)
        current_areas = int(user.get('featuresCount') or 0)
        score = 0
        signal = ''
        reason = ''

        if engaged_delta >= 25:
            score += 38 + min(20, int(engaged_delta) // 4)
            signal = f'+{round(engaged_delta)}% engaged'
            reason = 'Growing usage'
        if visits_delta >= 25:
            score += 28 + min(15, int(visits_delta) // 5)
            if not signal:
                signal = f'+{round(visits_delta)}% visits'
                reason = 'Returned to regular usage'
        if current_areas > previous_areas and current_areas >= 2:
            score += 22 + min(20, (current_areas - previous_areas) * 6)
            if not signal:
                signal = f'+{current_areas - previous_areas} areas'
                reason = 'Expanded usage'
        if user.get('status') == 'Power' and _status_for_user(previous, period_days=period_days) != 'Power':
            score += 35
            if not signal:
                signal = 'New power user'
                reason = 'Became highly active'
        if int(user.get('activeDays') or 0) >= 7:
            score += 18
            if not signal:
                signal = '7-day streak'
                reason = 'Consistent usage'

        if score <= 0:
            continue
        rows.append({
            'id': user.get('id'),
            'userId': user.get('userId') or user.get('id'),
            'name': user.get('name'),
            'company': user.get('company'),
            'companyId': user.get('companyId') or user.get('company_id'),
            'status': user.get('status'),
            'signal': signal or 'Growing usage',
            'reason': reason or 'Growing usage',
            'momentumScore': score,
        })

    return sorted(rows, key=lambda item: (-item['momentumScore'], item['name'] or ''))[:5]


def _status_mix_rows(status_mix_by_date):
    return status_mix_by_date


def empty_users_overview_payload(project, range_key='last_30_days'):
    start_date, end_date = services.resolve_period(project.timezone, range_key=range_key)
    previous_start, previous_end = services.previous_period(start_date, end_date)
    period_days = (end_date - start_date).days + 1
    labels = [day.isoformat() for day in services._date_range(start_date, end_date)]
    return {
        'schema_version': USERS_PAYLOAD_SCHEMA_VERSION,
        'project': {'id': project.id, 'name': project.name},
        'period': {
            'range_key': range_key,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'previous_start_date': previous_start.isoformat(),
            'previous_end_date': previous_end.isoformat(),
            'days': period_days,
        },
        'freshness': {
            'generated_at': None,
            'source_max_event_ts': None,
            'is_stale': True,
            'pending_rebuild': True,
        },
        'productAreas': [],
        'pageFeatures': [],
        'featureProductAreas': {},
        'kpis': [
            {'key': 'activeUsers', 'label': 'Active users', 'value': 0, 'delta': 0, 'deltaLabel': '0%', 'deltaType': 'neutral', 'sparkline': []},
            {'key': 'engagedPerUser', 'label': 'Engaged / user', 'value': '0s', 'delta': 0, 'deltaLabel': '0%', 'deltaType': 'neutral', 'sparkline': []},
            {'key': 'powerUsers', 'label': 'Power users', 'value': 0, 'delta': 0, 'deltaLabel': '0%', 'deltaType': 'neutral', 'sparkline': []},
            {'key': 'lowEngagementUsers', 'label': 'Low-engagement users', 'value': 0, 'delta': 0, 'deltaLabel': '0%', 'deltaType': 'neutral', 'sparkline': []},
        ],
        'dailyActiveTrend': {'labels': labels, 'activeUsers': [], 'engagedSeconds': [], 'visits': [], 'features': []},
        'engagementBuckets': [],
        'statusDistribution': [],
        'statusMixByDate': [],
        'users': [],
        'scatter': [],
        'usersNeedingAttention': [],
        'usersGainingMomentum': [],
        'usersByCompany': [],
        'emptyState': {
            'title': 'No users found',
            'text': 'Try changing filters or date range.',
        },
    }


def build_users_overview_payload(project, *, range_key='last_30_days'):
    start_date, end_date = services.resolve_period(project.timezone, range_key=range_key)
    previous_start, previous_end = services.previous_period(start_date, end_date)
    period_days = (end_date - start_date).days + 1

    current_all = _user_metrics(project.id, start_date, end_date)
    previous_all = _user_metrics(project.id, previous_start, previous_end)
    current = {
        user_id: row
        for user_id, row in current_all.items()
        if _user_period_active(row)
    }
    previous = {
        user_id: row
        for user_id, row in previous_all.items()
        if _user_period_active(row)
    }
    identities = _visit_identity(project, start_date, end_date)
    previous_identities = _visit_identity(project, previous_start, previous_end)
    company_names = {
        **_company_names(project.id, previous_start, previous_end),
        **_company_names(project.id, start_date, end_date),
        **_company_names_from_visits(project, previous_start, previous_end),
        **_company_names_from_visits(project, start_date, end_date),
    }
    company_engaged = _company_engaged_totals(project.id, start_date, end_date)
    area_usage = _area_usage_by_user(project.id, start_date, end_date)
    feature_usage, page_features, feature_product_areas = _feature_usage_by_user(project.id, start_date, end_date)
    product_areas = _product_area_options(project.id, start_date, end_date)

    users = []
    user_ids = set(current) | set(previous)
    email_lookup = services.user_trait_email_lookup(project, previous_start, end_date, user_ids=user_ids)
    for user_id in user_ids:
        has_current_activity = user_id in current
        row = current.get(user_id) if has_current_activity else previous.get(user_id, {})
        identity = identities.get(user_id) or previous_identities.get(user_id) or {}
        company_id = row.get('company_id') or identity.get('company_id') or ''
        company_name = identity.get('company_name') or company_names.get(company_id) or company_id or 'Unknown company'
        name = row.get('user_name') or identity.get('user_name') or _name_from_user_id(user_id)
        previous_row = previous.get(user_id, {})
        current_row = current.get(user_id, {})
        engaged = int(current_row.get('engaged_seconds') or 0)
        previous_engaged = int(previous_row.get('engaged_seconds') or 0)
        visits = int(current_row.get('visits') or 0)
        previous_visits = int(previous_row.get('visits') or 0)
        identity_sessions = int(identity.get('sessions') or 0)
        sessions_count_estimated = bool(visits and not identity_sessions)
        estimated_sessions_count = max(1, visits / 3) if sessions_count_estimated else identity_sessions
        sessions_count = identity_sessions if identity_sessions else (max(1, round(visits / 3)) if visits else 0)
        status = 'Dropped' if not has_current_activity else _status_for_user(current_row, previous_row, period_days=period_days)
        company_total = company_engaged.get(company_id) or 0
        top_features = feature_usage.get(user_id, [])[:8]
        top_feature = top_features[0]['feature'] if top_features else ''
        last_seen_date = current_row.get('last_seen_date') if has_current_activity else previous_row.get('last_seen_date')
        product_areas_used = int(current_row.get('product_areas_used') or 0)
        previous_product_areas_used = int(previous_row.get('product_areas_used') or 0)
        click_count = int(current_row.get('click_count') or 0)

        users.append({
            'id': user_id,
            'userId': user_id,
            'name': name,
            'email': _email_for_user(user_id, email_lookup),
            'company': company_name,
            'companyId': company_id,
            'role': '',
            'segment': '',
            'status': status,
            'identified': True,
            'engagedSeconds': engaged,
            'previousEngagedSeconds': previous_engaged,
            'activityDropSeconds': max(0, previous_engaged - engaged),
            'engagedDeltaPct': _metric_row_delta(current_row, previous_row, 'engaged_seconds'),
            'visitsCount': visits,
            'previousVisitsCount': previous_visits,
            'visitsDeltaPct': _metric_row_delta(current_row, previous_row, 'visits'),
            'avgVisitSeconds': round(engaged / visits) if visits else 0,
            'featuresCount': product_areas_used,
            'featuresDelta': product_areas_used - previous_product_areas_used,
            'pageGroupsCount': product_areas_used,
            'interactionPct': services._pct(click_count, visits),
            'interactionDeltaPp': services._delta_pp(
                services._pct(click_count, visits),
                services._pct(previous_row.get('click_count'), previous_row.get('visits')),
            ).get('value') or 0,
            'clicksPerVisit': services._ratio(click_count, visits),
            'clicksCount': click_count,
            'sessionsCount': sessions_count,
            'sessionsCountEstimated': sessions_count_estimated,
            'estimatedSessionsCount': estimated_sessions_count,
            'avgSessionSeconds': round(engaged / sessions_count) if sessions_count else 0,
            'topFeature': top_feature,
            'topFeatures': top_features,
            'pageGroups': area_usage.get(user_id, []),
            'lastActive': _relative_date_label(last_seen_date, end_date),
            'lastActiveSort': _last_active_sort(last_seen_date, end_date),
            'lastSeenDate': _format_date(last_seen_date),
            'companySharePct': services._pct(engaged, company_total),
            'activeDays': int(current_row.get('active_days') or 0),
            'stickinessPct': services._pct(current_row.get('active_days'), period_days),
            'trend': [],
        })

    users.sort(key=lambda item: (-item['visitsCount'], -item['engagedSeconds'], item['name']))
    scatter_users = _random_scatter_sample(
        users,
        SCATTER_VISIBLE_LIMIT,
        f'{project.id}:{range_key}:{start_date.isoformat()}:{end_date.isoformat()}',
    )

    daily = _daily_series(project.id, start_date, end_date, dropped_count=len(set(previous) - set(current)))
    active_users = len(current)
    previous_active_users = len(previous)
    total_engaged = sum(row.get('engaged_seconds', 0) for row in current.values())
    previous_total_engaged = sum(row.get('engaged_seconds', 0) for row in previous.values())
    total_visits = sum(row.get('visits', 0) for row in current.values())
    power_users = sum(1 for row in users if row.get('status') == 'Power')
    previous_power_users = sum(
        1
        for row in previous.values()
        if _status_for_user({**row, 'selected_end_date': previous_end}, period_days=period_days) == 'Power'
    )
    low_users = sum(1 for row in current.values() if _low_engagement(row))
    previous_low_users = sum(1 for row in previous.values() if _low_engagement(row))
    engaged_per_user = round(total_engaged / active_users) if active_users else 0
    previous_engaged_per_user = round(previous_total_engaged / previous_active_users) if previous_active_users else 0
    companies_counter = Counter(row['company'] for row in users if row.get('status') != 'Dropped')

    return {
        'schema_version': USERS_PAYLOAD_SCHEMA_VERSION,
        'project': {'id': project.id, 'name': project.name},
        'period': {
            'range_key': range_key,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'previous_start_date': previous_start.isoformat(),
            'previous_end_date': previous_end.isoformat(),
            'days': period_days,
        },
        'productAreas': product_areas,
        'pageFeatures': page_features,
        'featureProductAreas': feature_product_areas,
        'kpis': [
            {
                'key': 'activeUsers',
                'label': 'Active users',
                'value': active_users,
                'delta': _delta_pct_value(active_users, previous_active_users),
                'deltaLabel': _delta_payload(active_users, previous_active_users).get('label'),
                'deltaType': _delta_payload(active_users, previous_active_users).get('direction'),
                'sparkline': daily['activeUsers'],
            },
            {
                'key': 'engagedPerUser',
                'label': 'Engaged / user',
                'value': _format_duration(engaged_per_user),
                'delta': _delta_pct_value(engaged_per_user, previous_engaged_per_user),
                'deltaLabel': _delta_payload(engaged_per_user, previous_engaged_per_user).get('label'),
                'deltaType': _delta_payload(engaged_per_user, previous_engaged_per_user).get('direction'),
                'sparkline': daily['engagedPerUser'],
            },
            {
                'key': 'powerUsers',
                'label': 'Power users',
                'value': power_users,
                'secondary': f'{services._pct(power_users, active_users)}% of active users',
                'delta': _delta_pct_value(power_users, previous_power_users),
                'deltaLabel': _delta_payload(power_users, previous_power_users).get('label'),
                'deltaType': _delta_payload(power_users, previous_power_users).get('direction'),
                'sparkline': daily['powerUsers'],
            },
            {
                'key': 'lowEngagementUsers',
                'label': 'Low-engagement users',
                'value': low_users,
                'secondary': f'{services._pct(low_users, active_users)}% of active users',
                'delta': _delta_pct_value(low_users, previous_low_users),
                'deltaLabel': _delta_payload(low_users, previous_low_users, lower_is_better=True).get('label'),
                'deltaType': _delta_payload(low_users, previous_low_users, lower_is_better=True).get('direction'),
                'sparkline': daily['lowEngagementUsers'],
            },
        ],
        'dailyActiveTrend': {
            'labels': daily['labels'],
            'activeUsers': daily['activeUsers'],
            'engagedSeconds': daily['engagedPerUser'],
            'visits': [round(total_visits / max(period_days, 1)) for _day in daily['labels']],
            'features': [len(product_areas) for _day in daily['labels']],
        },
        'engagementBuckets': _engagement_buckets(users),
        'statusDistribution': _status_distribution(users),
        'statusMixByDate': _status_mix_rows(daily['statusMixByDate']),
        'users': users,
        'scatter': scatter_users,
        'scatterMeta': {
            'visibleLimit': SCATTER_VISIBLE_LIMIT,
            'totalActiveUsers': active_users,
            'totalUsers': len(users),
            'shownUsers': len(scatter_users),
            'isLimited': len(users) > len(scatter_users),
        },
        'usersNeedingAttention': _attention_rows(users, previous),
        'usersGainingMomentum': _momentum_rows(users, previous, period_days=period_days),
        'usersByCompany': [
            {'company': company, 'activeUsers': count}
            for company, count in companies_counter.most_common()
        ],
        'emptyState': {
            'title': 'No users found',
            'text': 'Try changing filters or date range.',
        },
    }


def get_cached_users_overview_payload(project_id, range_key='last_30_days', filters_hash=services.DEFAULT_FILTERS_HASH):
    row = queries.fetch_one(queries.FETCH_USERS_OVERVIEW_CACHE_SQL, [project_id, range_key, filters_hash])
    if not row:
        return None
    row['payload_json'] = services._coerce_json(row.get('payload_json'))
    row['schema_version'] = row['payload_json'].get('schema_version') if isinstance(row['payload_json'], dict) else None
    return row


def get_cached_users_overview_payload_json(project_id, range_key='last_30_days', filters_hash=services.DEFAULT_FILTERS_HASH):
    return queries.fetch_one(queries.FETCH_USERS_OVERVIEW_CACHE_JSON_SQL, [project_id, range_key, filters_hash])


def initial_users_overview_payload(payload, *, limit=INITIAL_USERS_PAYLOAD_LIMIT):
    if not isinstance(payload, dict):
        return {}

    users = payload.get('users') if isinstance(payload.get('users'), list) else []
    scatter = payload.get('scatter') if isinstance(payload.get('scatter'), list) else []
    initial_users = users[:limit]
    initial_scatter = scatter[:limit]
    is_partial = len(users) > len(initial_users) or len(scatter) > len(initial_scatter)
    initial_payload = {**payload}
    initial_payload['users'] = initial_users
    initial_payload['scatter'] = initial_scatter
    initial_payload['usersDeferred'] = {
        'isPartial': is_partial,
        'initialLimit': limit,
        'initialUsers': len(initial_users),
        'totalUsers': len(users),
    }
    return initial_payload


def initial_users_overview_payload_from_json_text(payload_json_text, *, limit=INITIAL_USERS_PAYLOAD_LIMIT):
    try:
        payload = json.loads(payload_json_text or '{}')
    except (TypeError, ValueError, json.JSONDecodeError):
        payload = {}
    return initial_users_overview_payload(payload, limit=limit)


def deferred_users_overview_payload(payload):
    if not isinstance(payload, dict):
        payload = {}

    return {
        'schema_version': payload.get('schema_version'),
        'period': payload.get('period') or {},
        'users': payload.get('users') if isinstance(payload.get('users'), list) else [],
        'scatter': payload.get('scatter') if isinstance(payload.get('scatter'), list) else [],
        'scatterMeta': payload.get('scatterMeta') or {},
        'usersDeferred': {
            'isPartial': False,
            'initialLimit': INITIAL_USERS_PAYLOAD_LIMIT,
        },
    }


def is_current_users_payload_schema(schema_version):
    try:
        return int(schema_version) == USERS_PAYLOAD_SCHEMA_VERSION
    except (TypeError, ValueError):
        return False


def _overview_user_ids(overview_payload):
    user_ids = []
    seen = set()
    for row in (overview_payload or {}).get('users') or []:
        user_id = str(row.get('id') or row.get('userId') or '').strip()
        if not user_id or user_id in seen:
            continue
        seen.add(user_id)
        user_ids.append(user_id)
    return user_ids


def _overview_user_sort_lookup(overview_payload):
    lookup = {}
    for index, row in enumerate((overview_payload or {}).get('users') or []):
        user_id = str(row.get('id') or row.get('userId') or '').strip()
        if not user_id:
            continue
        lookup[user_id] = (
            str(row.get('companyId') or row.get('company') or ''),
            str(row.get('name') or ''),
            index,
            user_id,
        )
    return lookup


def hydrate_users_detail_cache(
    project_id,
    *,
    range_key='last_30_days',
    overview_payload=None,
    user_ids=None,
    project=None,
    generated_at=None,
    expires_at=None,
):
    from apps.pages.user_detail_analytics import BulkUserDetailContext, build_user_detail_cache

    project = project or Project.active.filter(pk=project_id).first()
    if project is None:
        raise ValueError(f'Project {project_id} does not exist.')

    if overview_payload is None:
        overview_cache = get_cached_users_overview_payload(project_id, range_key=range_key)
        if not overview_cache or not is_current_users_payload_schema(overview_cache.get('schema_version')):
            return {'status': 'skipped', 'reason': 'missing_overview_cache', 'items_count': 0}
        if overview_cache.get('is_stale'):
            return {'status': 'skipped', 'reason': 'stale_overview_cache', 'items_count': 0}
        overview_payload = overview_cache.get('payload_json') or {}

    target_ids = {str(value).strip() for value in (user_ids or []) if str(value or '').strip()}
    source_ids = _overview_user_ids(overview_payload)
    if target_ids:
        source_ids = [user_id for user_id in source_ids if user_id in target_ids]
    sort_lookup = _overview_user_sort_lookup(overview_payload)
    source_ids.sort(key=lambda user_id: sort_lookup.get(user_id, ('', '', len(source_ids), user_id)))

    generated_at = generated_at or django_timezone.now()
    expires_at = expires_at or generated_at + services.CACHE_TTL
    period = overview_payload.get('period') or {}
    try:
        start_date = services._safe_date(period.get('start_date'))
        end_date = services._safe_date(period.get('end_date'))
    except (TypeError, ValueError):
        start_date, end_date = services.resolve_period(project.timezone, range_key=range_key)
    previous_start, previous_end = services.previous_period(start_date, end_date)
    bulk_context = BulkUserDetailContext(project, start_date, end_date)
    previous_bulk_context = BulkUserDetailContext(project, previous_start, previous_end)

    cached_count = 0
    skipped_count = 0
    errors = []
    for user_id in source_ids:
        try:
            result = build_user_detail_cache(
                project_id,
                user_id,
                range_key=range_key,
                project=project,
                generated_at=generated_at,
                expires_at=expires_at,
                bulk_context=bulk_context,
                previous_bulk_context=previous_bulk_context,
            )
        except Exception as exc:
            errors.append({'user_id': user_id, 'error': str(exc)})
            continue

        if result.get('status') == 'success':
            cached_count += 1
        else:
            skipped_count += 1

    return {
        'status': 'success' if not errors else 'partial_success',
        'items_count': cached_count,
        'skipped_count': skipped_count,
        'errors': errors,
    }


def build_users_overview_cache(project_id, *, range_key='last_30_days', include_user_details=False):
    project = Project.active.filter(pk=project_id).first()
    if project is None:
        raise ValueError(f'Project {project_id} does not exist.')

    payload = build_users_overview_payload(project, range_key=range_key)
    period = payload.get('period') or {}
    start_date = services._safe_date(period.get('start_date'))
    end_date = services._safe_date(period.get('end_date'))
    generated_at = django_timezone.now()
    expires_at = generated_at + services.CACHE_TTL
    source = queries.fetch_one(queries.SOURCE_MAX_EVENT_TS_SQL, [project_id]) or {}
    source_max_event_ts = source.get('source_max_event_ts')
    payload['freshness'] = {
        'generated_at': generated_at.isoformat(),
        'source_max_event_ts': source_max_event_ts.isoformat() if source_max_event_ts else None,
        'is_stale': False,
        'pending_rebuild': False,
    }

    queries.execute(
        queries.UPSERT_USERS_OVERVIEW_CACHE_SQL,
        [
            project_id,
            range_key,
            start_date,
            end_date,
            services.DEFAULT_FILTERS_HASH,
            json.dumps(payload, default=services._json_default),
            source_max_event_ts,
            generated_at,
            expires_at,
        ],
    )
    if include_user_details:
        detail_cache_result = hydrate_users_detail_cache(
            project_id,
            range_key=range_key,
            overview_payload=payload,
            project=project,
            generated_at=generated_at,
            expires_at=expires_at,
        )
    else:
        detail_cache_result = {'status': 'skipped', 'reason': 'not_requested', 'items_count': 0}
    return {
        'status': 'success',
        'project_id': project_id,
        'range_key': range_key,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'rows_count': len(payload.get('users') or []),
        'detail_cache_status': detail_cache_result.get('status'),
        'detail_cache_count': detail_cache_result.get('items_count', 0),
    }
