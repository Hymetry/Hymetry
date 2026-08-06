import json
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Max, Min, Q, Sum
from django.utils import timezone as django_timezone

from apps.pages import analytics_memo, queries, services
from apps.pages.locks import project_advisory_lock
from apps.pages.models import PageCompanyDailyMetric, PageDailyMetric, PageUserDailyMetric
from apps.pages.product_area_colors import (
    build_product_area_color_lookup,
    product_area_color_from_lookup,
    resolve_product_area_colors,
)
from apps.projects.company_attribute_filters import (
    company_attribute_filter_scope,
    current_company_attribute_filter_state,
    narrow_queryset_to_current_company_filters,
)
from apps.projects.models import Project


# 15: The at-risk card carries a delta comparing its ending state with the
# previous period's ending state.
COMPANIES_PAYLOAD_SCHEMA_VERSION = 15
SCATTER_VISIBLE_LIMIT = 500
# Detail cache rows held before a write goes out. Each carries a serialized
# payload, so this trades statement count against memory held at once.
COMPANY_DETAIL_CACHE_WRITE_BATCH = 25
USER_HEALTH_KEYS = ('power', 'healthy', 'light', 'passive', 'dropped')


def _apply_current_company_attribute_filters(queryset):
    return narrow_queryset_to_current_company_filters(queryset)


def _base_company_queryset(project_id, start_date, end_date):
    return _apply_current_company_attribute_filters(
        PageCompanyDailyMetric.objects
        .filter(project_id=project_id, date__gte=start_date, date__lte=end_date)
        .exclude(company_id='')
    )


def _base_user_queryset(project_id, start_date, end_date):
    return _apply_current_company_attribute_filters(
        PageUserDailyMetric.objects
        .filter(project_id=project_id, date__gte=start_date, date__lte=end_date)
        .exclude(company_id__isnull=True)
        .exclude(company_id='')
    )


def _company_metrics(project_id, start_date, end_date):
    rows = (
        _base_company_queryset(project_id, start_date, end_date)
        .values('company_id')
        .annotate(
            company_name=Max('company_name_sample'),
            visits=Sum('visits_count'),
            engaged_seconds=Sum('engaged_seconds'),
            click_count=Sum('click_count'),
            visits_with_click_count=Sum('visits_with_click_count'),
            pages_used=Count('page_rule_id', filter=Q(visits_count__gt=0), distinct=True),
            product_areas_used=Count('product_area_key', filter=Q(visits_count__gt=0), distinct=True),
            last_seen_date=Max('date'),
        )
    )
    metrics = {}
    for row in rows:
        company_id = row['company_id']
        visits = int(row.get('visits') or 0)
        engaged_seconds = int(row.get('engaged_seconds') or 0)
        metrics[company_id] = {
            'company_id': company_id,
            'company_name': row.get('company_name') or company_id,
            'visits': visits,
            'engaged_seconds': engaged_seconds,
            'click_count': int(row.get('click_count') or 0),
            'visits_with_click_count': int(row.get('visits_with_click_count') or 0),
            'pages_used': int(row.get('pages_used') or 0),
            'product_areas_used': int(row.get('product_areas_used') or 0),
            'last_seen_date': row.get('last_seen_date'),
            'active_users': 0,
        }
    return metrics


def _company_users(project_id, start_date, end_date):
    return {
        row['company_id']: int(row.get('active_users') or 0)
        for row in (
            _base_user_queryset(project_id, start_date, end_date)
            .values('company_id')
            .annotate(active_users=Count('user_id', distinct=True))
        )
    }


def _company_average_active_users(project_id, start_date, end_date):
    totals = defaultdict(lambda: {'users': 0, 'days': 0})
    rows = (
        _base_user_queryset(project_id, start_date, end_date)
        .values('company_id', 'date')
        .annotate(active_users=Count('user_id', distinct=True))
    )
    for row in rows:
        bucket = totals[row['company_id']]
        bucket['users'] += int(row.get('active_users') or 0)
        bucket['days'] += 1

    return {
        company_id: round(bucket['users'] / bucket['days'], 2)
        for company_id, bucket in totals.items()
        if bucket['days'] > 0
    }


def _company_known_users(project_id, company_ids):
    company_ids = [str(company_id) for company_id in company_ids or [] if str(company_id)]
    if not company_ids:
        return {}

    return {
        row['company_id']: int(row.get('known_users') or 0)
        for row in (
            PageUserDailyMetric.objects
            .filter(project_id=project_id, company_id__in=company_ids)
            .exclude(company_id__isnull=True)
            .exclude(company_id='')
            .values('company_id')
            .annotate(known_users=Count('user_id', distinct=True))
        )
    }


def _empty_user_health_mix():
    return {key: 0 for key in USER_HEALTH_KEYS}


def _user_health_status(
    visits,
    engaged_seconds,
    product_areas_used,
    click_count,
    active_days=None,
    *,
    period_days=30,
    power_thresholds=None,
):
    visits = int(visits or 0)
    engaged_seconds = int(engaged_seconds or 0)
    product_areas_used = int(product_areas_used or 0)
    click_count = int(click_count or 0)
    active_days = min(visits, int(period_days or 1)) if active_days is None else int(active_days or 0)
    interaction = click_count / max(visits, 1)
    power_thresholds = power_thresholds or services.power_user_thresholds(period_days)
    healthy_thresholds = services.healthy_user_thresholds(period_days)
    passive_visits = services.passive_visits_threshold(period_days)
    passive_engaged = services.PASSIVE_USER_ENGAGED_SECONDS

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
        visits >= healthy_thresholds['visits']
        and engaged_seconds >= healthy_thresholds['engaged_seconds']
        and product_areas_used >= healthy_thresholds['product_areas']
        and active_days >= healthy_thresholds['active_days']
    ):
        return 'healthy'
    if visits <= passive_visits or engaged_seconds < passive_engaged or interaction < 0.2:
        return 'passive'
    return 'light'


def _company_user_health_mix(project_id, start_date, end_date, previous_start, previous_end):
    mix_by_company = defaultdict(_empty_user_health_mix)
    current_pairs = set()
    period_days = (end_date - start_date).days + 1
    power_thresholds = services.project_power_user_thresholds(project_id, start_date, end_date)

    current_rows = (
        _base_user_queryset(project_id, start_date, end_date)
        .values('company_id', 'user_id')
        .annotate(
            active_days=Count('date', filter=Q(visits_count__gt=0) | Q(engaged_seconds__gt=0) | Q(click_count__gt=0), distinct=True),
            visits=Sum('visits_count'),
            engaged_seconds=Sum('engaged_seconds'),
            click_count=Sum('click_count'),
            product_areas_used=Count('product_area_key', filter=Q(visits_count__gt=0), distinct=True),
        )
    )
    for row in current_rows:
        company_id = row['company_id']
        user_id = row['user_id']
        current_pairs.add((company_id, user_id))
        status = _user_health_status(
            row.get('visits'),
            row.get('engaged_seconds'),
            row.get('product_areas_used'),
            row.get('click_count'),
            row.get('active_days'),
            period_days=period_days,
            power_thresholds=power_thresholds,
        )
        mix_by_company[company_id][status] += 1

    previous_pairs = (
        _base_user_queryset(project_id, previous_start, previous_end)
        .values('company_id', 'user_id')
        .distinct()
    )
    for row in previous_pairs:
        pair = (row['company_id'], row['user_id'])
        if pair not in current_pairs:
            mix_by_company[row['company_id']]['dropped'] += 1

    return {company_id: dict(mix) for company_id, mix in mix_by_company.items()}


def _company_area_active_users(project_id, start_date, end_date):
    """
    Distinct users per company and product area.

    Counted rather than estimated: the adoption matrix presents this number to
    the reader as a measurement, so it has to be one.
    """

    return {
        (row['company_id'], row.get('product_area_key') or 'unassigned'): int(row.get('active_users') or 0)
        for row in (
            _base_user_queryset(project_id, start_date, end_date)
            .values('company_id', 'product_area_key')
            .annotate(active_users=Count('user_id', distinct=True))
        )
    }


def _company_area_usage(project_id, start_date, end_date, color_lookup=None):
    usage = defaultdict(list)
    area_active_users = _company_area_active_users(project_id, start_date, end_date)
    rows = (
        _base_company_queryset(project_id, start_date, end_date)
        .values('company_id', 'product_area_key')
        .annotate(
            product_area_name=Max('product_area_name'),
            product_area_color=Max('product_area__color'),
            engaged_seconds=Sum('engaged_seconds'),
            visits=Sum('visits_count'),
            pages_used=Count('page_rule_id', filter=Q(visits_count__gt=0), distinct=True),
        )
        .order_by('company_id', '-engaged_seconds')
    )
    for row in rows:
        area_key = row.get('product_area_key') or 'unassigned'
        area_name = row.get('product_area_name') or 'Unassigned'
        usage[row['company_id']].append({
            'product_area_key': area_key,
            'product_area_name': area_name,
            'color': product_area_color_from_lookup(
                color_lookup,
                {
                    'key': area_key,
                    'name': area_name,
                    'color': row.get('product_area_color') or '',
                },
            ),
            'engaged_seconds': int(row.get('engaged_seconds') or 0),
            'visits': int(row.get('visits') or 0),
            'pages_used': int(row.get('pages_used') or 0),
            'active_users': area_active_users.get((row['company_id'], area_key), 0),
        })
    return usage


def _first_seen_dates(project_id):
    # Lifetime-wide and therefore identical for every range in a rebuild, while
    # being the one company scan that cannot be bounded by the selected period.
    # Callers only read it, so a whole rebuild can share one result.
    return analytics_memo.memoized(
        'company_first_seen_dates',
        project_id,
        lambda: _first_seen_dates_uncached(project_id),
    )


def _first_seen_dates_uncached(project_id):
    return {
        row['company_id']: row['first_seen_date']
        for row in (
            _apply_current_company_attribute_filters(
                PageCompanyDailyMetric.objects.filter(project_id=project_id),
            )
            .exclude(company_id='')
            .values('company_id')
            .annotate(first_seen_date=Min('date'))
        )
    }


def _companies_active_before(project_id, before_date):
    return set(
        _apply_current_company_attribute_filters(
            PageCompanyDailyMetric.objects.filter(project_id=project_id, date__lt=before_date),
        )
        .exclude(company_id='')
        .values_list('company_id', flat=True)
        .distinct()
    )


def _period_company_first_dates(project_id, start_date, end_date):
    first_dates = {}
    for queryset in (
        _base_company_queryset(project_id, start_date, end_date),
        _base_user_queryset(project_id, start_date, end_date),
    ):
        for row in (
            queryset
            .values('company_id')
            .annotate(first_date=Min('date'))
        ):
            company_id = row['company_id']
            first_date = row.get('first_date')
            if first_date and (company_id not in first_dates or first_date < first_dates[company_id]):
                first_dates[company_id] = first_date
    return first_dates


def _active_company_ids_by_day(project_id, start_date, end_date):
    # Both the active-companies trend and the median-breadth trend need this for
    # the same two windows, so a payload build asks for each window twice.
    return analytics_memo.memoized(
        'active_company_ids_by_day',
        (project_id, start_date, end_date),
        lambda: _active_company_ids_by_day_uncached(project_id, start_date, end_date),
    )


def _active_company_ids_by_day_uncached(project_id, start_date, end_date):
    active_by_day = {
        day: set()
        for day in services._date_range(start_date, end_date)
    }
    for queryset in (
        _base_company_queryset(project_id, start_date, end_date),
        _base_user_queryset(project_id, start_date, end_date),
    ):
        for row in queryset.values('date', 'company_id').distinct():
            day = row.get('date')
            company_id = row.get('company_id')
            if day in active_by_day and company_id:
                active_by_day[day].add(company_id)
    return active_by_day


def _average_daily_value(values):
    values = [float(value or 0) for value in values or []]
    if not values:
        return 0
    return sum(values) / len(values)


def _daily_active_companies(project_id, start_date, end_date):
    active_by_day = _active_company_ids_by_day(project_id, start_date, end_date)
    return [
        len(active_by_day[day])
        for day in services._date_range(start_date, end_date)
    ]


def _daily_new_reactivated(project_id, start_date, end_date, first_seen_dates, previous_active, active_before_previous):
    buckets = {day: 0 for day in services._date_range(start_date, end_date)}
    for company_id, first_current_date in _period_company_first_dates(
        project_id,
        start_date,
        end_date,
    ).items():
        first_seen_date = first_seen_dates.get(company_id)
        is_new = (
            first_seen_date is not None
            and start_date <= first_seen_date <= end_date
        )
        is_reactivated = company_id not in previous_active and company_id in active_before_previous
        if first_current_date in buckets and (is_new or is_reactivated):
            buckets[first_current_date] += 1

    return [
        buckets.get(day, 0)
        for day in services._date_range(start_date, end_date)
    ]


def _daily_median_breadth(project_id, start_date, end_date):
    active_by_day = _active_company_ids_by_day(project_id, start_date, end_date)
    areas_by_day_and_company = defaultdict(set)
    rows = (
        _base_company_queryset(project_id, start_date, end_date)
        .filter(visits_count__gt=0)
        .exclude(product_area_key__isnull=True)
        .values('date', 'company_id', 'product_area_key')
        .distinct()
    )
    for row in rows:
        areas_by_day_and_company[(row['date'], row['company_id'])].add(
            row['product_area_key'],
        )

    return [
        round(services._median([
            len(areas_by_day_and_company.get((day, company_id), ()))
            for company_id in active_by_day[day]
        ]), 1)
        for day in services._date_range(start_date, end_date)
    ]


def at_risk_history_floor(start_date, end_date):
    """
    Earliest day the at-risk trend for this period reads facts from.

    The trend's first chart point already compares two full windows, so it
    reaches back two periods less a day before the period even starts. A caller
    planning several ranges needs this to know what a shared read must cover.
    """

    period_days = (end_date - start_date).days + 1
    return start_date - timedelta(days=(period_days * 2) - 1)


def _at_risk_facts_uncached(project_id, history_start, end_date):
    company_facts_by_day = defaultdict(dict)
    company_fact_dates = defaultdict(list)
    users_by_day = defaultdict(lambda: defaultdict(set))

    for row in (
        _base_company_queryset(project_id, history_start, end_date)
        .values('date', 'company_id', 'product_area_key')
        .annotate(
            visits=Sum('visits_count'),
            engaged_seconds=Sum('engaged_seconds'),
        )
        .iterator(chunk_size=2000)
    ):
        day = row['date']
        company_id = row['company_id']
        facts = company_facts_by_day[day].setdefault(company_id, {
            'engaged_seconds': 0,
            'product_areas': set(),
        })
        facts['engaged_seconds'] += int(row.get('engaged_seconds') or 0)
        if int(row.get('visits') or 0) > 0 and row.get('product_area_key') is not None:
            facts['product_areas'].add(row['product_area_key'])

    for day, facts_by_company in company_facts_by_day.items():
        for company_id in facts_by_company:
            company_fact_dates[company_id].append(day)
    for dates in company_fact_dates.values():
        dates.sort()

    for row in (
        _base_user_queryset(project_id, history_start, end_date)
        .values('date', 'company_id', 'user_id')
        .distinct()
        .iterator(chunk_size=2000)
    ):
        if row.get('user_id') is not None:
            users_by_day[row['date']][row['company_id']].add(row['user_id'])

    return company_facts_by_day, company_fact_dates, users_by_day


def _at_risk_facts(project_id, history_start, end_date):
    """
    Load the daily facts the at-risk trend walks, reusing a wider load.

    A rebuild charts every range over both its selected and its previous
    window, and those spans nest inside one another rather than sharing an
    edge, so one read over their union serves them all.

    Surrounding days are inert in either direction. The rolling windows only
    visit days inside the span being charted, and the last-seen search is
    bounded below by the current window's start and above by the point being
    charted, so it can neither see later days nor reach past its own window.
    """

    return analytics_memo.covering_range(
        'at_risk_facts',
        project_id,
        history_start,
        end_date,
        lambda load_start, load_end: _at_risk_facts_uncached(project_id, load_start, load_end),
    )


def _daily_at_risk_companies(project_id, start_date, end_date, first_seen_dates):
    """
    Count the fixed-window at-risk cohort as of every selected chart date.

    Each point compares an equal-length rolling current and previous window,
    using the same lifecycle precedence and risk rules as the headline. Daily
    facts are loaded once for the complete history needed by every point, then
    moved through two in-memory windows. The final windows are therefore the
    exact selected and previous periods used by the headline classifier.
    """

    chart_dates = list(services._date_range(start_date, end_date))
    if not chart_dates:
        return []

    period_days = len(chart_dates)
    history_start = at_risk_history_floor(start_date, end_date)
    company_facts_by_day, company_fact_dates, users_by_day = _at_risk_facts(
        project_id,
        history_start,
        end_date,
    )

    def new_window():
        return {
            'company_days': Counter(),
            'engaged_seconds': Counter(),
            'product_areas': defaultdict(Counter),
            'users': defaultdict(Counter),
        }

    def adjust_count(counter, key, amount):
        next_value = counter.get(key, 0) + amount
        if next_value > 0:
            counter[key] = next_value
        else:
            counter.pop(key, None)

    def adjust_distinct(window, key, company_id, values, direction):
        counts_by_company = window[key]
        counts = counts_by_company[company_id]
        for value in values:
            adjust_count(counts, value, direction)
        if not counts:
            counts_by_company.pop(company_id, None)

    def adjust_day(window, day, direction):
        for company_id, facts in company_facts_by_day.get(day, {}).items():
            adjust_count(window['company_days'], company_id, direction)
            adjust_count(
                window['engaged_seconds'],
                company_id,
                direction * int(facts.get('engaged_seconds') or 0),
            )
            adjust_distinct(
                window,
                'product_areas',
                company_id,
                facts.get('product_areas') or (),
                direction,
            )

        for company_id, user_ids in users_by_day.get(day, {}).items():
            adjust_distinct(window, 'users', company_id, user_ids, direction)

    def company_ids(window):
        return set(window['company_days']) | set(window['users'])

    def risk_row(company_id, window, window_start, window_end):
        dates = company_fact_dates.get(company_id, ())
        last_seen_date = None
        if dates:
            index = bisect_right(dates, window_end) - 1
            if index >= 0 and dates[index] >= window_start:
                last_seen_date = dates[index]
        return {
            'company_id': company_id,
            'engaged_seconds': int(window['engaged_seconds'].get(company_id) or 0),
            'active_users': len(window['users'].get(company_id, ())),
            'product_areas_used': len(window['product_areas'].get(company_id, ())),
            'last_seen_date': last_seen_date,
            'selected_end_date': window_end,
        }

    def comparison_row(company_id, window):
        """
        Build only what a comparison window contributes to a risk reason.

        Staleness is read from the current row alone, so resolving a previous
        last-seen date here would cost a search per company per chart point and
        never be looked at.
        """

        return {
            'engaged_seconds': int(window['engaged_seconds'].get(company_id) or 0),
            'active_users': len(window['users'].get(company_id, ())),
            'product_areas_used': len(window['product_areas'].get(company_id, ())),
        }

    current_window = new_window()
    previous_window = new_window()
    current_start = start_date - timedelta(days=period_days - 1)
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=period_days - 1)
    for day in services._date_range(current_start, start_date):
        adjust_day(current_window, day, 1)
    for day in services._date_range(previous_start, previous_end):
        adjust_day(previous_window, day, 1)

    values = []
    for index, day in enumerate(chart_dates):
        if index:
            departing_current_day = current_start
            departing_previous_day = previous_start
            current_start += timedelta(days=1)
            previous_start += timedelta(days=1)
            previous_end += timedelta(days=1)
            adjust_day(current_window, departing_current_day, -1)
            adjust_day(current_window, day, 1)
            adjust_day(previous_window, departing_previous_day, -1)
            adjust_day(previous_window, previous_end, 1)

        current_company_ids = company_ids(current_window)
        previous_company_ids = company_ids(previous_window)
        active_before_previous = {
            company_id
            for company_id in current_company_ids
            if first_seen_dates.get(company_id) is not None
            and first_seen_dates[company_id] < previous_start
        }
        thresholds = {
            'start_date': current_start,
            'end_date': day,
        }
        count = 0

        for company_id in current_company_ids:
            is_new, is_reactivated = _company_lifecycle_flags(
                company_id,
                first_seen_dates.get(company_id),
                previous_company_ids,
                active_before_previous,
                thresholds,
            )
            if is_new or is_reactivated:
                # Lifecycle outranks risk, so neither metric row is ever read.
                continue
            if _risk_reasons(
                risk_row(company_id, current_window, current_start, day),
                comparison_row(company_id, previous_window),
                period_days=period_days,
            ):
                count += 1

        values.append(count)

    return values


def _percent_delta(current, previous):
    return services._delta_pct(current, previous)


def _pp_delta(current, previous):
    return services._delta_pp(current, previous)


def _interaction_pct(row):
    return services._pct(row.get('visits_with_click_count'), row.get('visits'))


def _avg_engaged_per_user(row):
    active_users = int(row.get('active_users') or 0)
    if active_users <= 0:
        return 0
    return round(int(row.get('engaged_seconds') or 0) / active_users)


def _p75(values):
    return _percentile(values, 0.75)


def _p90(values):
    return _percentile(values, 0.90)


def _percentile(values, percentile):
    values = sorted(value for value in values if value is not None)
    if not values:
        return 0
    index = min(len(values) - 1, int(round((len(values) - 1) * percentile)))
    return values[index]


def _healthy_or_power_user_share(row):
    mix = row.get('user_health_mix') or row.get('userHealthMix') or {}
    total = sum(int(mix.get(key) or 0) for key in USER_HEALTH_KEYS)
    if total <= 0:
        return 0
    strong_users = int(mix.get('power') or 0) + int(mix.get('healthy') or 0)
    return strong_users / total


def _risk_reasons(current, previous, *, period_days):
    reasons = []
    previous_engaged = int(previous.get('engaged_seconds') or 0)
    current_engaged = int(current.get('engaged_seconds') or 0)
    previous_users = int(previous.get('active_users') or 0)
    current_users = int(current.get('active_users') or 0)
    previous_areas = int(previous.get('product_areas_used') or 0)
    current_areas = int(current.get('product_areas_used') or 0)

    if previous_engaged >= 1800 and current_engaged <= previous_engaged * 0.5:
        reasons.append('Engaged drop')
    if previous_users >= 2 and current_users <= previous_users * 0.5:
        reasons.append('Users dropped')
    if previous_areas >= 2 and current_areas < previous_areas:
        reasons.append(f'Product areas {previous_areas} -> {current_areas}')
    if current_users == 1 and previous_users >= 2:
        reasons.append('Only 1 active user')
    if period_days >= 14:
        last_seen_date = current.get('last_seen_date')
        selected_end = current.get('selected_end_date')
        stale_days = 7 if period_days <= 30 else 14
        if last_seen_date and selected_end and (selected_end - last_seen_date).days >= stale_days:
            reasons.append(f'No activity {stale_days}d')

    return reasons


def _risk_score(reasons, current, previous):
    score = 0
    reason_text = ' '.join(reasons)
    if 'No activity' in reason_text:
        score += 35
    if 'Engaged drop' in reasons:
        score += 30
    if 'Users dropped' in reasons:
        score += 25
    if 'Product areas' in reason_text:
        score += 15
    if 'Only 1 active user' in reasons:
        score += 10
    return min(100, score + min(20, int(previous.get('engaged_seconds') or 0) // 3600))


def _company_lifecycle_flags(
    company_id,
    first_seen_date,
    previous_active,
    active_before_previous,
    thresholds,
):
    """
    Decide the lifecycle precedence that outranks any risk reason.

    Split out so the at-risk trend can settle a company from counters it already
    holds, without first assembling the metric rows that only ``_risk_reasons``
    reads. Both callers must agree on this rule, so it lives in one place.
    """

    is_new = first_seen_date is not None and thresholds['start_date'] <= first_seen_date <= thresholds['end_date']
    is_reactivated = company_id not in previous_active and company_id in active_before_previous
    return is_new, is_reactivated


def _company_risk_classification(
    row,
    previous,
    first_seen_date,
    previous_active,
    active_before_previous,
    thresholds,
    period_days,
):
    is_new, is_reactivated = _company_lifecycle_flags(
        row['company_id'],
        first_seen_date,
        previous_active,
        active_before_previous,
        thresholds,
    )
    reasons = [] if is_new or is_reactivated else _risk_reasons(row, previous, period_days=period_days)

    return reasons, is_new, is_reactivated


def _status_for_company(row, previous, first_seen_date, previous_active, active_before_previous, thresholds, period_days):
    reasons, is_new, is_reactivated = _company_risk_classification(
        row,
        previous,
        first_seen_date,
        previous_active,
        active_before_previous,
        thresholds,
        period_days,
    )
    is_at_risk = bool(reasons)

    if is_new:
        status = 'new'
    elif is_reactivated:
        status = 'reactivated'
    elif is_at_risk:
        status = 'at_risk'
    elif (
        row['active_users'] >= max(3, thresholds.get('p90_active_users', thresholds.get('p75_active_users', 0)))
        and _avg_engaged_per_user(row) >= max(
            services.power_user_thresholds(period_days)['engaged_seconds'],
            thresholds.get('p90_avg_engaged', thresholds.get('p75_avg_engaged', 0)),
        )
        and row['product_areas_used'] >= max(2, thresholds['median_product_areas'])
        and _healthy_or_power_user_share(row) >= 0.45
    ):
        status = 'power'
    else:
        status = 'healthy'

    return status, reasons, is_new, is_reactivated


ACTIVATION_STAGE_ORDER = {'not_activated': 0, 'partially_activated': 1, 'activated': 2}


def _activation_stage(row):
    """
    How far a new or reactivated account has carried its first usage.

    Takes a built company payload rather than a raw metric row. These are the
    thresholds the overview has always applied; they moved here so the table
    can be ordered and paged on the server like every other one.
    """

    active_users = int(row.get('activeUsers') or 0)
    product_areas = int(row.get('productAreasUsed') or 0)
    engaged_seconds = int(row.get('engagedSeconds') or 0)

    if active_users >= 2 and product_areas >= 3 and engaged_seconds >= 1800:
        return 'activated'
    if active_users >= 2 or product_areas >= 2:
        return 'partially_activated'
    return 'not_activated'


def _suggested_action(reasons, current=None, previous=None):
    text = ' '.join(reasons)
    current = current or {}
    previous = previous or {}
    current_users = int(current.get('active_users') or 0)
    previous_users = int(previous.get('active_users') or 0)
    current_engaged = int(current.get('engaged_seconds') or 0)
    previous_engaged = int(previous.get('engaged_seconds') or 0)
    current_areas = int(current.get('product_areas_used') or 0)
    previous_areas = int(previous.get('product_areas_used') or 0)

    if 'Only 1 active user' in text:
        return 'Add backup champions'
    if 'No activity' in text:
        if current_users >= 50:
            return 'Reconnect recent power users'
        if current_areas >= 3 and current_engaged >= 28800:
            return 'Restart cross-area usage'
        if current_users >= 20:
            return 'Re-engage active cohort'
        if current_users <= 6 and current_engaged >= 3600:
            return 'Check account owner status'
        if current_engaged >= 28800:
            return 'Restart usage cadence'
        return 'Schedule reactivation touchpoint'
    if 'Users dropped' in text and 'Engaged drop' in text:
        return 'Run user reactivation'
    if 'Users dropped' in text:
        if current_users <= max(1, previous_users // 3):
            return 'Rebuild active user base'
        return 'Re-engage inactive users'
    if 'Product areas' in text:
        if current_areas and previous_areas and current_areas < previous_areas and current_engaged >= previous_engaged:
            return 'Expand adjacent workflows'
        return 'Restore lost workflows'
    if 'Engaged drop' in text:
        if current_users >= 2:
            return 'Review workflow value'
        return 'Re-engage quiet account'
    return 'Review account health'


def _status_label(status):
    return {
        'new': 'New',
        'activated': 'Activated',
        'reactivated': 'Reactivated',
        'healthy': 'Healthy',
        'power': 'Power',
        'at_risk': 'At risk',
        'dormant': 'Dormant',
    }.get(status, status)


def _scatter_state(status):
    if status == 'at_risk':
        return 'At risk'
    if status in {'new', 'reactivated', 'activated'}:
        return 'New / reactivated' if status in {'new', 'reactivated'} else 'Regular'
    return 'Regular'


def _scatter_company_id(row):
    return str(row.get('companyId') or row.get('company_id') or row.get('companyName') or row.get('company_name') or '')


def _scatter_numeric(row, *keys):
    for key in keys:
        value = row.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0
    return 0


def _scatter_active_users(row):
    return _scatter_numeric(row, 'averageActiveUsers', 'avgActiveUsers', 'activeUsers', 'active_users')


def _scatter_has_current_activity(row):
    return any(
        _scatter_numeric(row, *keys) > 0
        for keys in (
            ('averageActiveUsers', 'avgActiveUsers', 'activeUsers', 'active_users'),
            ('visits',),
            ('engagedSeconds', 'engaged_seconds'),
        )
    )


def _scatter_change_magnitude(row):
    return max(
        abs(_scatter_numeric(row, key))
        for key in (
            'activeUsersDeltaPct',
            'visitsDeltaPct',
            'engagedDeltaPct',
            'interactionDeltaPp',
        )
    )


def _select_relevant_scatter_points(company_rows, limit=SCATTER_VISIBLE_LIMIT):
    visible_limit = max(int(limit or SCATTER_VISIBLE_LIMIT), 1)
    rows = [
        row
        for row in company_rows
        if row.get('status') != 'dormant' or _scatter_has_current_activity(row)
    ]
    if len(rows) <= visible_limit:
        return rows

    scores = defaultdict(float)
    row_count = len(rows)

    for row in rows:
        company_id = _scatter_company_id(row)
        status = row.get('status')
        if status == 'at_risk':
            scores[company_id] += 10_000_000
        elif status in {'new', 'reactivated'} or row.get('isNew') or row.get('isReactivated'):
            scores[company_id] += 9_000_000

    def add_ranked_score(key_fn, weight):
        ranked_rows = sorted(rows, key=key_fn, reverse=True)
        for rank, row in enumerate(ranked_rows):
            company_id = _scatter_company_id(row)
            scores[company_id] += weight * ((row_count - rank) / row_count)

    def add_top_outlier_score(key_fn, weight):
        top_count = min(50, max(5, visible_limit // 10))
        ranked_rows = [
            row
            for row in sorted(rows, key=key_fn, reverse=True)
            if key_fn(row) > 0
        ][:top_count]
        if not ranked_rows:
            return
        for rank, row in enumerate(ranked_rows):
            company_id = _scatter_company_id(row)
            scores[company_id] += weight * ((len(ranked_rows) - rank) / len(ranked_rows))

    add_top_outlier_score(lambda item: _scatter_numeric(item, 'engagedSeconds', 'engaged_seconds'), 4_000_000)
    add_top_outlier_score(_scatter_active_users, 3_200_000)
    add_top_outlier_score(lambda item: _scatter_numeric(item, 'avgEngagedSecondsPerUser'), 2_400_000)
    add_top_outlier_score(_scatter_change_magnitude, 1_600_000)

    add_ranked_score(lambda item: _scatter_numeric(item, 'engagedSeconds', 'engaged_seconds'), 420)
    add_ranked_score(_scatter_active_users, 280)
    add_ranked_score(lambda item: _scatter_numeric(item, 'avgEngagedSecondsPerUser'), 180)
    add_ranked_score(_scatter_change_magnitude, 140)

    return sorted(
        rows,
        key=lambda item: (
            -scores[_scatter_company_id(item)],
            str(item.get('companyName') or item.get('company_name') or ''),
        ),
    )[:visible_limit]


def _delta_value(delta):
    value = delta.get('value') if isinstance(delta, dict) else 0
    return 0 if value is None else value


def get_cached_companies_overview_payload(project_id, range_key='last_30_days', filters_hash=services.DEFAULT_FILTERS_HASH):
    """
    Read one Companies overview variant row verbatim.

    Whether the row may be served is decided by
    ``filtered_overview.variant_is_usable``, which owns that rule for all three
    surfaces. Deciding it here as well would mean two places to keep in step and
    an extra project lookup per fetch.
    """

    row = queries.fetch_one(queries.FETCH_COMPANIES_OVERVIEW_CACHE_SQL, [project_id, range_key, filters_hash])
    if not row:
        return None
    row['payload_json'] = json.loads(row.get('payload_json_text') or '{}')
    row['schema_version'] = row['payload_json'].get('schema_version') if isinstance(row['payload_json'], dict) else None
    return row


def get_cached_companies_overview_metadata(
    project_id,
    range_key='last_30_days',
    filters_hash=services.DEFAULT_FILTERS_HASH,
):
    """Freshness metadata for one Companies variant, without its payload."""

    from apps.pages import filtered_overview

    return filtered_overview.metadata_row(
        queries.FETCH_COMPANIES_OVERVIEW_METADATA_SQL,
        project_id,
        range_key,
        filters_hash,
    )


def get_cached_companies_overview_payload_json(project_id, range_key='last_30_days', filters_hash=services.DEFAULT_FILTERS_HASH):
    return queries.fetch_one(queries.FETCH_COMPANIES_OVERVIEW_CACHE_JSON_SQL, [project_id, range_key, filters_hash])


def is_current_companies_payload_schema(schema_version):
    try:
        return int(schema_version) == COMPANIES_PAYLOAD_SCHEMA_VERSION
    except (TypeError, ValueError):
        return False


def get_cached_company_detail_payload(
    project_id,
    company_id,
    range_key='last_30_days',
    filters_hash=services.DEFAULT_FILTERS_HASH,
):
    if not company_id:
        return None
    row = queries.fetch_one(
        queries.FETCH_COMPANY_DETAIL_CACHE_SQL,
        [project_id, range_key, str(company_id), filters_hash],
    )
    if not row:
        return None
    row['payload_json'] = services._coerce_json(row.get('payload_json'))
    if not row.get('schema_version') and isinstance(row['payload_json'], dict):
        row['schema_version'] = row['payload_json'].get('schema_version')
    return row


def is_current_company_detail_payload_schema(schema_version):
    from apps.pages import company_detail_analytics

    try:
        return int(schema_version) == company_detail_analytics.COMPANY_DETAIL_PAYLOAD_SCHEMA_VERSION
    except (TypeError, ValueError):
        return False


def _overview_company_id(row):
    if not isinstance(row, dict):
        return ''
    return str(row.get('companyId') or row.get('id') or '').strip()


def _overview_company_ids(overview_payload):
    seen = set()
    company_ids = []
    for row in (overview_payload or {}).get('companies') or []:
        company_id = _overview_company_id(row)
        if not company_id or company_id in seen:
            continue
        seen.add(company_id)
        company_ids.append(company_id)
    return company_ids


def empty_companies_overview_payload(project, range_key):
    start_date, end_date = services.resolve_period(project.timezone, range_key=range_key)
    previous_start, previous_end = services.previous_period(start_date, end_date)
    period_days = (end_date - start_date).days + 1
    return {
        'schema_version': COMPANIES_PAYLOAD_SCHEMA_VERSION,
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
        'scatter': {
            'visibleLimit': SCATTER_VISIBLE_LIMIT,
            'totalActiveCompanies': 0,
            'points': [],
            'futureDensityMode': {
                'enabled': False,
                'note': 'For very large datasets, add a density/heatmap background and keep individual points for important accounts.',
            },
        },
        'productAreas': [],
        'kpis': [],
        'healthDistribution': [],
        'companies': [],
        'newReactivatedCompanies': [],
        'productAreaAdoption': [],
        'newCompanyAdoptionRamp': [],
        'atRiskCompanies': [],
        'expansionOpportunities': [],
    }


def _company_detail_payload_dates(project, payload, range_key):
    period = payload.get('period') if isinstance(payload, dict) else {}
    start_value = (period or {}).get('startDate') or (period or {}).get('start_date')
    end_value = (period or {}).get('endDate') or (period or {}).get('end_date')
    if start_value and end_value:
        return services._safe_date(start_value), services._safe_date(end_value)
    return services.resolve_period(project.timezone, range_key=range_key)


def build_company_detail_cache(
    project_id,
    company_id,
    *,
    range_key='last_30_days',
    overview_payload=None,
    project=None,
    generated_at=None,
    expires_at=None,
    bulk_context=None,
    use_lock=True,
    pending_writes=None,
):
    from apps.pages import company_detail_analytics

    company_id = str(company_id or '').strip()
    if not company_id:
        return {'status': 'skipped', 'reason': 'missing_company_id', 'project_id': project_id, 'range_key': range_key}

    if use_lock:
        with project_advisory_lock(project_id, namespace='pages-rebuild') as acquired:
            if not acquired:
                return {
                    'status': 'skipped',
                    'reason': 'lock_not_acquired',
                    'project_id': project_id,
                    'range_key': range_key,
                    'company_id': company_id,
                }
            return build_company_detail_cache(
                project_id,
                company_id,
                range_key=range_key,
                overview_payload=overview_payload,
                project=project,
                generated_at=generated_at,
                expires_at=expires_at,
                bulk_context=bulk_context,
                use_lock=False,
                pending_writes=pending_writes,
            )

    project = project or Project.active.filter(pk=project_id).first()
    if project is None:
        raise ValueError(f'Project {project_id} does not exist.')

    if overview_payload is None:
        overview_cache = get_cached_companies_overview_payload(project_id, range_key=range_key)
        if not overview_cache or not is_current_companies_payload_schema(overview_cache.get('schema_version')):
            return {
                'status': 'skipped',
                'reason': 'missing_overview_cache',
                'project_id': project_id,
                'range_key': range_key,
                'company_id': company_id,
            }
        if overview_cache.get('is_stale'):
            return {
                'status': 'skipped',
                'reason': 'stale_overview_cache',
                'project_id': project_id,
                'range_key': range_key,
                'company_id': company_id,
            }
        overview_payload = overview_cache.get('payload_json') or {}

    payload, _, _ = company_detail_analytics.build_company_detail_payload(
        project,
        company_id,
        range_key=range_key,
        overview_payload=overview_payload,
        bulk_context=bulk_context,
    )
    if not payload:
        return {
            'status': 'not_found',
            'project_id': project_id,
            'range_key': range_key,
            'company_id': company_id,
        }

    start_date, end_date = _company_detail_payload_dates(project, payload, range_key)
    generated_at = generated_at or django_timezone.now()
    expires_at = expires_at or generated_at + services.CACHE_TTL

    row = [
        project_id,
        range_key,
        company_id,
        start_date,
        end_date,
        services.DEFAULT_FILTERS_HASH,
        json.dumps(payload, default=services._json_default),
        generated_at,
        expires_at,
    ]
    if pending_writes is None:
        queries.execute(queries.UPSERT_COMPANY_DETAIL_CACHE_SQL, row)
    else:
        # A caller rebuilding every company batches the writes instead, which
        # is one statement per batch rather than one per company.
        pending_writes.append(row)
    return {
        'status': 'success',
        'project_id': project_id,
        'range_key': range_key,
        'company_id': company_id,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
    }


def hydrate_companies_detail_cache(
    project_id,
    *,
    range_key='last_30_days',
    overview_payload=None,
    company_ids=None,
    project=None,
    generated_at=None,
    expires_at=None,
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
            return hydrate_companies_detail_cache(
                project_id,
                range_key=range_key,
                overview_payload=overview_payload,
                company_ids=company_ids,
                project=project,
                generated_at=generated_at,
                expires_at=expires_at,
                use_lock=False,
            )

    project = project or Project.active.filter(pk=project_id).first()
    if project is None:
        raise ValueError(f'Project {project_id} does not exist.')

    if overview_payload is None:
        overview_cache = get_cached_companies_overview_payload(project_id, range_key=range_key)
        if not overview_cache or not is_current_companies_payload_schema(overview_cache.get('schema_version')):
            return {'status': 'skipped', 'reason': 'missing_overview_cache', 'items_count': 0}
        if overview_cache.get('is_stale'):
            return {'status': 'skipped', 'reason': 'stale_overview_cache', 'items_count': 0}
        overview_payload = overview_cache.get('payload_json') or {}

    target_ids = {str(value).strip() for value in (company_ids or []) if str(value or '').strip()}
    source_ids = _overview_company_ids(overview_payload)
    if target_ids:
        source_ids = [company_id for company_id in source_ids if company_id in target_ids]

    generated_at = generated_at or django_timezone.now()
    expires_at = expires_at or generated_at + services.CACHE_TTL
    from apps.pages.company_detail_analytics import BulkCompanyDetailContext

    bulk_context = BulkCompanyDetailContext(
        project,
        range_key=range_key,
        overview_payload=overview_payload,
    )

    cached_count = 0
    skipped_count = 0
    errors = []
    # Every company here is a distinct conflict target, so the whole set can go
    # up in batches rather than one statement each.
    #
    # Flushed as it fills rather than at the end: a serialized detail payload
    # is large, and holding one per company was enough to exhaust memory on a
    # project with a thousand of them.
    pending_writes = []

    def flush_pending_writes():
        if not pending_writes:
            return
        queries.execute_values(
            queries.COMPANY_DETAIL_CACHE_INSERT_PREFIX,
            queries.COMPANY_DETAIL_CACHE_VALUES_TEMPLATE,
            queries.COMPANY_DETAIL_CACHE_CONFLICT_SUFFIX,
            pending_writes,
            page_size=COMPANY_DETAIL_CACHE_WRITE_BATCH,
        )
        pending_writes.clear()

    for company_id in source_ids:
        try:
            result = build_company_detail_cache(
                project_id,
                company_id,
                range_key=range_key,
                overview_payload=overview_payload,
                project=project,
                generated_at=generated_at,
                expires_at=expires_at,
                bulk_context=bulk_context,
                use_lock=False,
                pending_writes=pending_writes,
            )
        except Exception as exc:
            errors.append({'company_id': company_id, 'error': str(exc)})
            continue

        if result.get('status') == 'success':
            cached_count += 1
        else:
            skipped_count += 1

        if len(pending_writes) >= COMPANY_DETAIL_CACHE_WRITE_BATCH:
            flush_pending_writes()

    flush_pending_writes()

    return {
        'status': 'success' if not errors else 'partial_success',
        'items_count': cached_count,
        'skipped_count': skipped_count,
        'errors': errors,
    }


def build_companies_overview_cache(
    project_id,
    *,
    range_key='last_30_days',
    company_attribute_filter_state=None,
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
                }
            if company_attribute_filter_state is not None and company_attribute_filter_state.active:
                cached = get_cached_companies_overview_payload(
                    project_id,
                    range_key=range_key,
                    filters_hash=company_attribute_filter_state.filters_hash,
                )
                if cached and is_current_companies_payload_schema(cached.get('schema_version')):
                    return {
                        'status': 'success',
                        'reason': 'cache_hit',
                        'project_id': project_id,
                        'range_key': range_key,
                    }
            return build_companies_overview_cache(
                project_id,
                range_key=range_key,
                company_attribute_filter_state=company_attribute_filter_state,
                use_lock=False,
            )

    project = Project.active.filter(pk=project_id).first()
    if project is None:
        raise ValueError(f'Project {project_id} does not exist.')
    expected_filtered_revision = int(project.filtered_analytics_revision)
    expected_facts_revision = int(project.analytics_facts_revision)

    payload = build_companies_overview_payload(
        project,
        range_key=range_key,
        company_attribute_filter_state=company_attribute_filter_state,
    )
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
    if company_attribute_filter_state is not None and company_attribute_filter_state.active:
        # Both revisions are stored so a reader can tell an attribute edit,
        # which invalidates the cohort, from a fact rebuild, which only ages it.
        payload['freshness']['filtered_analytics_revision'] = expected_filtered_revision
        payload['freshness']['analytics_facts_revision'] = expected_facts_revision

    cache_params = [
        project_id,
        range_key,
        start_date,
        end_date,
        (
            company_attribute_filter_state.filters_hash
            if company_attribute_filter_state is not None
            else services.DEFAULT_FILTERS_HASH
        ),
        json.dumps(payload, default=services._json_default),
        source_max_event_ts,
        generated_at,
        expires_at,
    ]
    if company_attribute_filter_state is not None and company_attribute_filter_state.active:
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
            queries.execute(queries.UPSERT_COMPANIES_OVERVIEW_CACHE_SQL, cache_params)
        services.purge_expired_filtered_overview_caches(project_id)
    else:
        queries.execute(queries.UPSERT_COMPANIES_OVERVIEW_CACHE_SQL, cache_params)
    if company_attribute_filter_state is not None and company_attribute_filter_state.active:
        detail_cache_result = {
            'status': 'skipped',
            'reason': 'filtered_overview',
            'items_count': 0,
        }
    else:
        detail_cache_result = hydrate_companies_detail_cache(
            project_id,
            range_key=range_key,
            overview_payload=payload,
            project=project,
            generated_at=generated_at,
            expires_at=expires_at,
            use_lock=False,
        )
    return {
        'status': 'success',
        'project_id': project_id,
        'range_key': range_key,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'companies_count': len(payload.get('companies') or []),
        'scatter_points_count': len((payload.get('scatter') or {}).get('points') or []),
        'detail_cache_count': detail_cache_result.get('items_count', 0),
    }


def _area_distribution(areas, total_engaged):
    total = max(int(total_engaged or 0), 1)
    return [
        {
            'product_area_key': item['product_area_key'],
            'product_area_name': item['product_area_name'],
            'color': item.get('color') or '',
            'engaged_seconds': item['engaged_seconds'],
            'visits': item['visits'],
            'pages_used': item.get('pages_used', 0),
            'active_users': item.get('active_users', 0),
            'percent': round(item['engaged_seconds'] / total * 100, 1),
        }
        for item in areas
    ]


def _format_date(value):
    return value.isoformat() if value else None


def _compact_product_area_label(value):
    text = str(value or '').strip()
    if not text:
        return 'Area'

    words = [word for word in text.split() if word]
    if len(words) > 1:
        return ''.join(word[0] for word in words).upper()[:6]
    if len(text) <= 7:
        return text
    return f'{text[:6]}.'


def _normalize_product_area_short_label(name, short_name):
    short_label = str(short_name or '').strip()
    full_name = str(name or '').strip()
    if not short_label or short_label == full_name or len(short_label) > 8:
        return _compact_product_area_label(short_label or full_name)
    return short_label


def _product_area_option(row):
    name = row.get('product_area_name') or 'Unassigned'
    short_name = _normalize_product_area_short_label(name, row.get('product_area_short_name'))

    return {
        'key': row.get('product_area_key') or 'unassigned',
        'name': name,
        'shortName': short_name[:64],
        'color': row.get('product_area_color') or '',
    }


def build_companies_overview_payload(
    project,
    *,
    range_key='last_30_days',
    company_attribute_filter_state=None,
):
    if company_attribute_filter_state is not None:
        cohort = (
            services.resolve_project_company_cohort(project.id, company_attribute_filter_state)
            if company_attribute_filter_state.active
            else None
        )
        with company_attribute_filter_scope(company_attribute_filter_state, cohort=cohort):
            return build_companies_overview_payload(project, range_key=range_key)

    start_date, end_date = services.resolve_period(project.timezone, range_key=range_key)
    previous_start, previous_end = services.previous_period(start_date, end_date)
    period_days = (end_date - start_date).days + 1

    current = _company_metrics(project.id, start_date, end_date)
    previous = _company_metrics(project.id, previous_start, previous_end)
    current_users = _company_users(project.id, start_date, end_date)
    previous_users = _company_users(project.id, previous_start, previous_end)
    current_average_active_users = _company_average_active_users(project.id, start_date, end_date)
    for company_id, active_users in current_users.items():
        current.setdefault(company_id, {'company_id': company_id, 'company_name': company_id})['active_users'] = active_users
    for company_id, active_users in previous_users.items():
        previous.setdefault(company_id, {'company_id': company_id, 'company_name': company_id})['active_users'] = active_users

    company_domains = services.company_trait_domain_lookup(
        project,
        previous_start,
        end_date,
        company_ids=current.keys(),
    )
    known_users = _company_known_users(project.id, current.keys())
    first_seen_dates = _first_seen_dates(project.id)
    previous_active = set(previous.keys())
    comparison_available = bool(previous)
    active_before_previous = _companies_active_before(project.id, previous_start)
    product_areas = _product_area_options(project, start_date, end_date)
    product_area_color_lookup = build_product_area_color_lookup(product_areas, prefer_explicit=True)
    area_usage = _company_area_usage(project.id, start_date, end_date, product_area_color_lookup)
    user_health_mix = _company_user_health_mix(project.id, start_date, end_date, previous_start, previous_end)

    active_values = list(current.values())
    thresholds = {
        'start_date': start_date,
        'end_date': end_date,
        'p75_active_users': _p75([row.get('active_users', 0) for row in active_values]),
        'p90_active_users': _p90([row.get('active_users', 0) for row in active_values]),
        'p75_avg_engaged': _p75([_avg_engaged_per_user(row) for row in active_values]),
        'p90_avg_engaged': _p90([_avg_engaged_per_user(row) for row in active_values]),
        'median_product_areas': services._median([row.get('product_areas_used', 0) for row in active_values]),
    }

    company_rows = []
    at_risk_rows = []
    new_count = 0
    reactivated_count = 0
    status_counts = defaultdict(int)

    for company_id, row in current.items():
        row.setdefault('visits', 0)
        row.setdefault('engaged_seconds', 0)
        row.setdefault('click_count', 0)
        row.setdefault('visits_with_click_count', 0)
        row.setdefault('pages_used', 0)
        row.setdefault('product_areas_used', 0)
        row.setdefault('active_users', 0)
        row['selected_end_date'] = end_date
        row['user_health_mix'] = user_health_mix.get(company_id, _empty_user_health_mix())
        previous_row = previous.get(company_id, {})
        first_seen_date = first_seen_dates.get(company_id)
        status, reasons, is_new, is_reactivated = _status_for_company(
            row,
            previous_row,
            first_seen_date,
            previous_active,
            active_before_previous,
            thresholds,
            period_days,
        )
        if is_new:
            new_count += 1
        if is_reactivated:
            reactivated_count += 1

        status_counts[status] += 1
        areas = area_usage.get(company_id, [])
        active_users_delta = _percent_delta(row.get('active_users'), previous_row.get('active_users'))
        visits_delta = _percent_delta(row.get('visits'), previous_row.get('visits'))
        engaged_delta = _percent_delta(row.get('engaged_seconds'), previous_row.get('engaged_seconds'))
        interaction = _interaction_pct(row)
        previous_interaction = _interaction_pct(previous_row)
        interaction_delta = _pp_delta(interaction, previous_interaction)
        avg_engaged = _avg_engaged_per_user(row)
        average_active_users = current_average_active_users.get(company_id, 0)
        product_area_names = [item['product_area_name'] for item in areas]
        company_payload = {
            'companyId': company_id,
            'companyName': row.get('company_name') or company_id,
            'domain': company_domains.get(company_id, ''),
            'status': status,
            'statusLabel': _status_label(status),
            'isNew': is_new,
            'isReactivated': is_reactivated,
            'comparisonAvailable': comparison_available,
            'comparison_available': comparison_available,
            'activeUsers': int(row.get('active_users') or 0),
            'averageActiveUsers': average_active_users,
            'activeUsersDeltaPct': _delta_value(active_users_delta),
            'activeUsersDeltaLabel': active_users_delta.get('label'),
            'totalKnownUsers': max(int(row.get('active_users') or 0), int(known_users.get(company_id) or 0)),
            'pagesUsed': int(row.get('pages_used') or 0),
            'productAreasUsed': int(row.get('product_areas_used') or 0),
            'visits': int(row.get('visits') or 0),
            'visitsDeltaPct': _delta_value(visits_delta),
            'visitsDeltaLabel': visits_delta.get('label'),
            'engagedSeconds': int(row.get('engaged_seconds') or 0),
            'engagedDeltaPct': _delta_value(engaged_delta),
            'engagedDeltaLabel': engaged_delta.get('label'),
            'avgEngagedSecondsPerUser': avg_engaged,
            'interactionPct': interaction,
            'interactionDeltaPp': _delta_value(interaction_delta),
            'interactionDeltaLabel': interaction_delta.get('label'),
            'lastSeenDate': _format_date(row.get('last_seen_date')),
            'firstSeenDate': _format_date(first_seen_date),
            'productAreas': product_area_names,
            'productAreaDistribution': _area_distribution(areas, row.get('engaged_seconds')),
            'userHealthMix': row['user_health_mix'],
            'riskReasons': reasons,
        }
        company_rows.append(company_payload)
        if status == 'at_risk':
            at_risk_rows.append({
                **company_payload,
                'riskReason': reasons[0] if reasons else 'At risk',
                'riskScore': _risk_score(reasons, row, previous_row),
                'suggestedAction': _suggested_action(reasons, row, previous_row),
            })

    dormant_count = len(previous_active - set(current.keys()))
    if dormant_count:
        status_counts['dormant'] += dormant_count

    company_rows.sort(key=lambda item: (-item['engagedSeconds'], -item['activeUsers'], item['companyName']))
    at_risk_rows.sort(key=lambda item: (-item['riskScore'], -item['engagedSeconds'], item['companyName']))
    active_companies = len(current)

    health_distribution = _health_distribution(status_counts)
    trend_labels = [
        day.isoformat()
        for day in services._date_range(start_date, end_date)
    ]
    active_trend = _daily_active_companies(project.id, start_date, end_date)
    previous_active_trend = _daily_active_companies(
        project.id,
        previous_start,
        previous_end,
    )
    new_reactivated_trend = _daily_new_reactivated(
        project.id,
        start_date,
        end_date,
        first_seen_dates,
        previous_active,
        active_before_previous,
    )
    previous_previous_start, previous_previous_end = services.previous_period(
        previous_start,
        previous_end,
    )
    previous_previous_active = set(_period_company_first_dates(
        project.id,
        previous_previous_start,
        previous_previous_end,
    ))
    previous_new_reactivated_trend = _daily_new_reactivated(
        project.id,
        previous_start,
        previous_end,
        first_seen_dates,
        previous_previous_active,
        _companies_active_before(project.id, previous_previous_start),
    )
    median_breadth_trend = _daily_median_breadth(project.id, start_date, end_date)
    previous_median_breadth_trend = _daily_median_breadth(
        project.id,
        previous_start,
        previous_end,
    )
    at_risk_trend = _daily_at_risk_companies(
        project.id,
        start_date,
        end_date,
        first_seen_dates,
    )
    # The card reports a state, not a total, so it compares where the selected
    # period ended with where the previous one ended. Walking the previous
    # window gives that end state under the same rolling-window rules.
    previous_at_risk_trend = _daily_at_risk_companies(
        project.id,
        previous_start,
        previous_end,
        first_seen_dates,
    )
    average_daily_active_companies = _average_daily_value(active_trend)
    previous_average_daily_active_companies = _average_daily_value(
        previous_active_trend,
    )
    average_daily_new_reactivated = _average_daily_value(
        new_reactivated_trend,
    )
    previous_average_daily_new_reactivated = _average_daily_value(
        previous_new_reactivated_trend,
    )
    average_daily_median_breadth = _average_daily_value(
        median_breadth_trend,
    )
    previous_average_daily_median_breadth = _average_daily_value(
        previous_median_breadth_trend,
    )
    median_breadth_delta = round(
        average_daily_median_breadth - previous_average_daily_median_breadth,
        2,
    )
    at_risk_ending_delta = len(at_risk_rows) - (
        previous_at_risk_trend[-1] if previous_at_risk_trend else 0
    )
    average_daily_active_companies_display = round(
        average_daily_active_companies,
        2,
    )
    average_daily_new_reactivated_display = round(
        average_daily_new_reactivated,
        2,
    )
    average_daily_median_breadth_display = round(
        average_daily_median_breadth,
        2,
    )
    new_reactivated_rows = []
    for row in company_rows:
        if not (row.get('isNew') or row.get('isReactivated') or row.get('status') in {'new', 'reactivated'}):
            continue
        first_seen = first_seen_dates.get(row['companyId']) or start_date
        new_reactivated_rows.append({
            **row,
            'activationStage': _activation_stage(row),
            'daysSinceStart': max(1, (end_date - first_seen).days),
        })
    new_reactivated_rows.sort(key=lambda item: (
        ACTIVATION_STAGE_ORDER.get(item['activationStage'], 0),
        -item['daysSinceStart'],
        -item['activeUsers'],
        -item['engagedSeconds'],
        item['companyName'],
    ))

    expansion_rows = _expansion_opportunities(company_rows)
    scatter_visible_points = _select_relevant_scatter_points(company_rows, SCATTER_VISIBLE_LIMIT)

    return {
        'schema_version': COMPANIES_PAYLOAD_SCHEMA_VERSION,
        'project': {'id': project.id, 'name': project.name},
        'period': {
            'range_key': range_key,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'previous_start_date': previous_start.isoformat(),
            'previous_end_date': previous_end.isoformat(),
            'days': period_days,
        },
        'scatter': {
            'visibleLimit': SCATTER_VISIBLE_LIMIT,
            'totalActiveCompanies': active_companies,
            'shownCompanies': len(scatter_visible_points),
            'isLimited': active_companies > len(scatter_visible_points),
            'points': scatter_visible_points,
            'futureDensityMode': {
                'enabled': False,
                'note': 'For very large datasets, add a density/heatmap background and keep individual points for important accounts.',
            },
        },
        'productAreas': product_areas,
        'kpis': [
            {
                'label': 'Avg daily active companies',
                'value': average_daily_active_companies_display,
                'delta': _percent_delta(
                    average_daily_active_companies,
                    previous_average_daily_active_companies,
                ),
                'trend': active_trend,
                'trend_labels': trend_labels,
                'trend_grain': 'day',
                'trend_scope': 'daily',
                'trend_summary': 'average',
                'trend_label': 'Daily active companies',
            },
            {
                'label': 'Avg daily new / reactivated',
                'value': average_daily_new_reactivated_display,
                'secondary': f'{new_count} new | {reactivated_count} reactivated',
                'delta': _percent_delta(
                    average_daily_new_reactivated,
                    previous_average_daily_new_reactivated,
                ),
                'trend': new_reactivated_trend,
                'trend_labels': trend_labels,
                'trend_grain': 'day',
                'trend_scope': 'daily',
                'trend_summary': 'average',
                'trend_label': 'Daily new / reactivated companies',
            },
            {
                'label': 'Avg daily adoption breadth',
                'value': average_daily_median_breadth_display,
                'unit': 'areas',
                'delta': {
                    'label': services._format_signed_decimal(
                        median_breadth_delta,
                        ' areas',
                        decimal_places=2,
                    ),
                    'direction': services._direction(median_breadth_delta, 1),
                    'value': median_breadth_delta,
                },
                'trend': median_breadth_trend,
                'trend_labels': trend_labels,
                'trend_grain': 'day',
                'trend_scope': 'daily',
                'trend_summary': 'average',
                'trend_label': 'Daily adoption breadth',
            },
            {
                'label': 'At-risk companies',
                'value': len(at_risk_rows),
                'delta': {
                    'label': (
                        f'{services._format_signed(at_risk_ending_delta, "")} '
                        'vs previous ending'
                    ),
                    # A larger at-risk cohort is the bad direction, so the sign
                    # is read the other way round from a growth metric.
                    'direction': services._direction(-at_risk_ending_delta, 1),
                    'value': at_risk_ending_delta,
                },
                'trend': at_risk_trend,
                'trend_labels': trend_labels,
                'trend_grain': 'day',
                'trend_scope': 'as_of',
                'trend_summary': 'latest',
                'trend_label': 'At-risk companies',
            },
        ],
        'healthDistribution': health_distribution,
        'companies': company_rows,
        # Whole lists, like atRiskCompanies: the view embeds only the first page
        # and serves the rest from the table endpoint.
        'newReactivatedCompanies': new_reactivated_rows,
        'productAreaAdoption': _product_area_adoption(
            project,
            start_date,
            end_date,
            product_area_color_lookup,
        ),
        'newCompanyAdoptionRamp': [],
        # Kept whole so the overview can page through every at-risk account; the
        # view embeds only the first page in the rendered document.
        'atRiskCompanies': at_risk_rows,
        'expansionOpportunities': expansion_rows,
    }


def _product_area_options(project, start_date, end_date):
    project_id = project.id
    state = current_company_attribute_filter_state()
    if state is None or not state.active:
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
        options = resolve_product_area_colors(
            [_product_area_option(row) for row in rows],
            prefer_explicit=True,
        )
        if options:
            return services._project_product_area_options(project_id, options)[:len(options)]

    fallback_rows = list(
        _base_company_queryset(project_id, start_date, end_date)
        .values('product_area_key')
        .annotate(
            product_area_name=Max('product_area_name'),
            product_area_short_name=Max('product_area__short_name'),
            product_area_color=Max('product_area__color'),
            engaged_seconds=Sum('engaged_seconds'),
        )
        .order_by('-engaged_seconds', 'product_area_name')
    )
    merged_rows = {}
    for row in fallback_rows:
        key = row.get('product_area_key') or 'unassigned'
        merged = merged_rows.get(key)
        if merged is None:
            merged_rows[key] = dict(row)
        else:
            merged['engaged_seconds'] = (
                int(merged.get('engaged_seconds') or 0)
                + int(row.get('engaged_seconds') or 0)
            )
            for field in (
                'product_area_name',
                'product_area_short_name',
                'product_area_color',
            ):
                if not merged.get(field) and row.get(field):
                    merged[field] = row[field]
    fallback_rows = sorted(
        merged_rows.values(),
        key=lambda row: (
            -int(row.get('engaged_seconds') or 0),
            row.get('product_area_name') or '',
        ),
    )
    options = resolve_product_area_colors(
        [_product_area_option(row) for row in fallback_rows],
        prefer_explicit=True,
    )
    return services._project_product_area_options(project_id, options)[:len(options)]


def _health_distribution(status_counts):
    order = [
        ('new', 'New'),
        ('activated', 'Activated'),
        ('reactivated', 'Reactivated'),
        ('healthy', 'Healthy'),
        ('power', 'Power'),
        ('at_risk', 'Risk'),
        ('dormant', 'Dormant'),
    ]
    total = sum(status_counts.values()) or 1
    return [
        {
            'status': status,
            'label': label,
            'count': int(status_counts.get(status, 0)),
            'pct': round(int(status_counts.get(status, 0)) / total * 100, 1),
        }
        for status, label in order
        if status_counts.get(status, 0)
    ]


def _product_area_adoption(
    project,
    start_date,
    end_date,
    color_lookup=None,
):
    project_id = project.id
    daily_active = {
        row['date']: int(row.get('active_companies') or 0)
        for row in (
            _base_company_queryset(project_id, start_date, end_date)
            .values('date')
            .annotate(active_companies=Count('company_id', distinct=True))
        )
    }
    rows = list(
        _base_company_queryset(project_id, start_date, end_date)
        .values('date', 'product_area_key')
        .annotate(
            product_area_name=Max('product_area_name'),
            product_area_color=Max('product_area__color'),
            companies_using_area=Count('company_id', distinct=True),
            engaged_seconds=Sum('engaged_seconds'),
        )
        .order_by('date', 'product_area_name')
    )
    totals_by_area = defaultdict(int)
    for row in rows:
        totals_by_area[row.get('product_area_key') or 'unassigned'] += int(row.get('engaged_seconds') or 0)

    top_area_keys = {
        area_key
        for area_key, _ in sorted(totals_by_area.items(), key=lambda item: item[1], reverse=True)[:8]
    }
    points = []
    for row in rows:
        area_key = row.get('product_area_key') or 'unassigned'
        if area_key not in top_area_keys:
            continue
        active_companies = daily_active.get(row['date'], 0)
        companies_using_area = int(row.get('companies_using_area') or 0)
        points.append({
            'date': row['date'].isoformat(),
            'productArea': row.get('product_area_name') or 'Unassigned',
            'color': product_area_color_from_lookup(
                color_lookup,
                {
                    'key': area_key,
                    'name': row.get('product_area_name') or 'Unassigned',
                    'color': row.get('product_area_color') or '',
                },
            ),
            'adoptionPct': services._pct(companies_using_area, active_companies),
            'companiesUsingArea': companies_using_area,
            'activeCompanies': active_companies,
        })
    return points


def _format_expansion_duration(seconds):
    minutes = max(1, round(int(seconds or 0) / 60))
    if minutes >= 60:
        hours = minutes // 60
        remainder = minutes % 60
        return f'{hours}h {remainder:02d}m' if remainder else f'{hours}h'
    return f'{minutes}m'


def _common_product_area_names(company_rows):
    counts = Counter()
    for row in company_rows:
        for area_name in row.get('productAreas') or []:
            if area_name:
                counts[area_name] += 1
    return [area_name for area_name, _count in counts.most_common()]


def _first_missing_common_area(row, common_area_names):
    adopted = set(row.get('productAreas') or [])
    for area_name in common_area_names:
        if area_name and area_name not in adopted:
            return area_name
    return ''


def _expansion_reason_and_action(row, thresholds, common_area_names):
    active_users = int(row.get('activeUsers') or 0)
    avg_engaged = int(row.get('avgEngagedSecondsPerUser') or 0)
    interaction = float(row.get('interactionPct') or 0)
    product_areas = int(row.get('productAreasUsed') or 0)
    distribution = row.get('productAreaDistribution') or []
    top_area = distribution[0].get('product_area_name') if distribution else ''
    top_share = float(distribution[0].get('percent') or 0) if distribution else 0
    missing_area = _first_missing_common_area(row, common_area_names[:6])

    if top_share >= 70 and top_area:
        return f'{top_area} dominates usage', f'Expand beyond {top_area}'
    if missing_area and product_areas >= 2:
        return f'No {missing_area} adoption', f'Introduce {missing_area} workflow'
    if active_users >= thresholds['p75_active_users'] and avg_engaged >= thresholds['p75_avg_engaged']:
        if active_users >= 80:
            return f'{active_users} enterprise users engaged', 'Map executive expansion path'
        if avg_engaged >= 18000:
            return f'{_format_expansion_duration(avg_engaged)}/user depth', 'Design premium workflow rollout'
        if active_users >= 60 and product_areas >= 4:
            return f'{product_areas} areas broadly adopted', 'Package cross-area expansion'
        if avg_engaged >= 14400:
            return f'{_format_expansion_duration(avg_engaged)}/user engagement', 'Offer advanced workflow pilot'
        if interaction >= 60:
            return f'{round(interaction)}% interaction rate', 'Target power-user workflows'
        return f'{active_users} users deeply engaged', 'Map executive expansion path'
    if active_users >= thresholds['p75_active_users']:
        return f'{active_users} active users', 'Identify team champions'
    if avg_engaged >= thresholds['p75_avg_engaged']:
        return f'{_format_expansion_duration(avg_engaged)}/user engagement', 'Offer advanced workflow pilot'
    if interaction >= 60:
        return f'{round(interaction)}% interaction rate', 'Target power-user workflows'
    if product_areas >= 4:
        return f'{product_areas} areas adopted', 'Package cross-area expansion'
    if active_users >= thresholds['p50_active_users'] and avg_engaged <= thresholds['p50_avg_engaged']:
        return 'Many users, low time/user', 'Review adoption pattern'
    return 'Strong usage footprint', 'Validate expansion fit'


def _expansion_opportunities(company_rows):
    if not company_rows:
        return []

    p75_active_users = _p75([row.get('activeUsers', 0) for row in company_rows])
    p50_active_users = services._median([row.get('activeUsers', 0) for row in company_rows])
    p75_avg_engaged = _p75([row.get('avgEngagedSecondsPerUser', 0) for row in company_rows])
    p50_avg_engaged = services._median([row.get('avgEngagedSecondsPerUser', 0) for row in company_rows])
    thresholds = {
        'p75_active_users': p75_active_users,
        'p50_active_users': p50_active_users,
        'p75_avg_engaged': p75_avg_engaged,
        'p50_avg_engaged': p50_avg_engaged,
    }
    common_area_names = _common_product_area_names(company_rows)
    rows = []
    for row in company_rows:
        if row.get('status') in {'at_risk', 'dormant'}:
            continue
        if int(row.get('engagedSeconds') or 0) < 600:
            continue

        score = 0
        active_users = int(row.get('activeUsers') or 0)
        avg_engaged = int(row.get('avgEngagedSecondsPerUser') or 0)
        interaction = float(row.get('interactionPct') or 0)
        product_areas = int(row.get('productAreasUsed') or 0)
        distribution = row.get('productAreaDistribution') or []

        if active_users >= p75_active_users:
            score += 30
        elif active_users >= p50_active_users:
            score += 20
        if avg_engaged >= p75_avg_engaged:
            score += 25
        elif avg_engaged >= p50_avg_engaged:
            score += 15
        if interaction >= 60:
            score += 12
        if product_areas >= 4:
            score += 15
        elif product_areas >= 2:
            score += 8
        if distribution and float(distribution[0].get('percent') or 0) >= 70:
            score += 10

        if score < 25:
            continue

        reason, suggested_action = _expansion_reason_and_action(row, thresholds, common_area_names)

        rows.append({
            **row,
            'reason': reason,
            'suggestedAction': suggested_action,
            'potentialScore': score,
            'expansionPriority': 'high' if score >= 65 else 'medium' if score >= 40 else 'low',
        })

    return sorted(rows, key=lambda item: (-item['potentialScore'], -item['engagedSeconds'], item['companyName']))
