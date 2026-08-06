"""Data preparation for the analytics-backed, replayable Visits table.

The replay identifier and analytics fragment identifiers are intentionally
different. This module keeps ``Session`` (the recording) as the routable row,
then derives its date, duration, page count, active time, and chart from raw
``AnalyticsEvent`` rows in canonically linked ``AnalyticsSession`` fragments.
rrweb data is retained only to determine replay availability and to expose a
diagnostic recording duration.

The public entry point is :func:`build_visits_context`.  It is deliberately
view-agnostic so the authenticated, workspace-slug and demo routes can all use
the same implementation.
"""

from __future__ import annotations

import hashlib
import unicodedata
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone as datetime_timezone
from functools import cmp_to_key
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import CharField, Exists, Max, Min, OuterRef, Q, Subquery, Sum
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Length
from django.utils import timezone

from apps.pages.models import PageVisit, ProductArea
from apps.pages.product_area_colors import SAFE_PRODUCT_AREA_COLOR_RE
from apps.projects.company_attribute_filters import apply_company_attribute_filters
from apps.tracker.analytics_visit_projection import build_analytics_visit_projections
from apps.tracker.models import (
    AnalyticsEvent,
    AnalyticsSession,
    Event,
    ProjectPageRule,
    Session,
)
from apps.tracker.replayability import replayable_full_snapshot_events
from apps.tracker.page_naming import (
    compile_page_rules,
    normalize_page_url_key,
    resolve_page_rule_match,
)


DEFAULT_RANGE_KEY = 'last_30_days'
DEFAULT_SORT_KEY = 'date_time'
DEFAULT_SORT_DIRECTION = 'desc'
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
UNCLASSIFIED_AREA_NAME = 'Unclassified'
UNCLASSIFIED_AREA_KEY = 'unclassified'
UNCLASSIFIED_COLOR = '#CBD5E1'

RANGE_DAYS = {
    'last_7_days': 7,
    'last_30_days': 30,
    'last_90_days': 90,
    'last_180_days': 180,
}
RANGE_OPTIONS = tuple(
    {
        'value': range_key,
        'key': range_key,
        'days': days,
        'label': f'{days} days',
        'short_label': f'{days}d',
    }
    for range_key, days in RANGE_DAYS.items()
)

SORT_KEY_ALIASES = {
    'user': 'user',
    'company': 'company',
    'date': 'date_time',
    'date_time': 'date_time',
    'datetime': 'date_time',
    'start': 'date_time',
    'start_time': 'date_time',
    'duration': 'duration',
    'active_time': 'duration',
    'observed_active_time': 'duration',
    'unique_pages': 'unique_pages',
    'pages': 'unique_pages',
}
SORT_OPTIONS = (
    {'value': 'user', 'label': 'User'},
    {'value': 'company', 'label': 'Company'},
    {'value': 'date_time', 'label': 'Date / time'},
    {'value': 'duration', 'label': 'Duration'},
    {'value': 'unique_pages', 'label': 'Unique pages'},
)

# This palette intentionally excludes the neutral tenth color used by the
# shared palette.  A neutral gray has semantic meaning on Visits: unclassified.
CLASSIFIED_COLOR_PALETTE = (
    '#4269D0',
    '#EFB118',
    '#FF725C',
    '#6CC5B0',
    '#3CA951',
    '#FF8AB7',
    '#A463F2',
    '#97BBF5',
    '#9C6B4E',
)


def _clean(value):
    return str(value or '').strip()


def _normalized_identity_text(value):
    """Return a stable, human-text identity without changing its display label."""

    normalized = unicodedata.normalize('NFKC', _clean(value))
    return ' '.join(normalized.split()).casefold()


def _product_area_name_key(value):
    """Mirror the SQL Product Area slug used while materializing PageVisit."""

    chunks = []
    pending_separator = False
    for character in _clean(value).lower():
        if character.isalnum():
            if pending_separator and chunks:
                chunks.append('-')
            chunks.append(character)
            pending_separator = False
        else:
            pending_separator = True
    return ''.join(chunks).strip('-')


def _normalized_area_key(area_key, area_name=''):
    normalized_key = _product_area_name_key(area_name)
    if normalized_key:
        return normalized_key
    normalized_key = _product_area_name_key(area_key)
    return normalized_key or 'product-area'


def _classified_page_key(page_name):
    normalized_name = _normalized_identity_text(page_name) or 'unknown page'
    return f'name:{normalized_name}'


def _entry_identity(entry):
    return entry['product_area_key'], entry['logical_key']


def _display_label_rank(value):
    label = _clean(value)
    return _normalized_identity_text(label), label


def _project_zone(timezone_name):
    try:
        return ZoneInfo(timezone_name or 'UTC')
    except ZoneInfoNotFoundError:
        return ZoneInfo('UTC')


def _coerce_aware(value):
    if value is None:
        return timezone.now()
    if timezone.is_naive(value):
        return timezone.make_aware(value, datetime_timezone.utc)
    return value


def resolve_visits_period(project_timezone, range_key=DEFAULT_RANGE_KEY, *, now=None):
    """Return normalized range metadata using calendar days in project time."""

    normalized_range = range_key if range_key in RANGE_DAYS else DEFAULT_RANGE_KEY
    zone = _project_zone(project_timezone)
    local_now = _coerce_aware(now).astimezone(zone)
    end_date = local_now.date()
    start_date = end_date - timedelta(days=RANGE_DAYS[normalized_range] - 1)
    start_local = datetime.combine(start_date, time.min, tzinfo=zone)
    end_local = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=zone)
    return {
        'range_key': normalized_range,
        'range_days': RANGE_DAYS[normalized_range],
        'start_date': start_date,
        'end_date': end_date,
        'start_ts': start_local.astimezone(datetime_timezone.utc),
        'end_ts': end_local.astimezone(datetime_timezone.utc),
        'project_zone': zone,
    }


def _effective_end(session):
    start = session.start_time
    candidate = session.ended_at or session.last_activity or start
    if not start:
        return candidate
    if not candidate or candidate < start:
        return start
    return candidate


def _recording_start(session):
    return getattr(session, '_visits_event_start', None) or session.start_time


def _recording_end(session):
    event_end = getattr(session, '_visits_event_end', None)
    event_start = getattr(session, '_visits_event_start', None)
    if event_end is not None:
        return max(event_start or event_end, event_end)
    return _effective_end(session)


def _attach_recording_event_bounds(recordings):
    recordings = list(recordings or ())
    if not recordings:
        return recordings
    bounds = {
        row['session_id']: row
        for row in (
            Event.objects
            .filter(session_id__in=[recording.session_id for recording in recordings])
            .values('session_id')
            .annotate(event_start=Min('timestamp'), event_end=Max('timestamp'))
        )
    }
    for recording in recordings:
        row = bounds.get(recording.session_id) or {}
        recording._visits_event_start = row.get('event_start')
        recording._visits_event_end = row.get('event_end')
    return recordings


def _interval_relation(recording, analytics):
    recording_start = _recording_start(recording)
    recording_end = _recording_end(recording)
    analytics_start = analytics.start_time
    analytics_end = _effective_end(analytics)

    intersects = recording_start <= analytics_end and analytics_start <= recording_end
    overlap_seconds = 0.0
    if intersects:
        overlap_seconds = max(
            0.0,
            (min(recording_end, analytics_end) - max(recording_start, analytics_start)).total_seconds(),
        )
        gap_seconds = 0.0
    elif recording_end < analytics_start:
        gap_seconds = (analytics_start - recording_end).total_seconds()
    else:
        gap_seconds = (recording_start - analytics_end).total_seconds()

    return intersects, overlap_seconds, max(0.0, gap_seconds)


def _pair_rank(recording, analytics):
    intersects, overlap_seconds, gap_seconds = _interval_relation(recording, analytics)
    exact_id = str(recording.session_id) == str(analytics.session_id)
    return (
        0 if exact_id else 1,
        0 if intersects else 1,
        -overlap_seconds,
        gap_seconds,
        abs((_recording_start(recording) - analytics.start_time).total_seconds()),
        analytics.start_time,
        str(analytics.session_id),
        _recording_start(recording),
        str(recording.session_id),
    )


def _match_max_gap_seconds():
    # Event-backed recording bounds and analytics share client timestamps, so
    # non-overlap is tolerated only as a small clock/flush-order skew. Session
    # expiration length is far too broad and can join two separate visits.
    return int(
        getattr(
            settings,
            'VISITS_ANALYTICS_MATCH_MAX_GAP_SECONDS',
            5,
        )
    )


def _load_analytics_candidates(project, recordings, max_gap_seconds):
    if not recordings:
        return []

    lower = min(_recording_start(recording) for recording in recordings) - timedelta(seconds=max_gap_seconds)
    upper = max(_recording_end(recording) for recording in recordings) + timedelta(seconds=max_gap_seconds)
    queryset = (
        AnalyticsSession.objects
        .filter(project=project, start_time__lt=upper)
        .filter(
            Q(ended_at__gte=lower)
            | Q(ended_at__isnull=True, last_activity__gte=lower)
        )
        .order_by('start_time', 'session_id')
    )

    visitor_guids = {
        recording.visitor.visitor_guid
        for recording in recordings
        if recording.visitor_id and recording.visitor.visitor_guid
    }
    if not visitor_guids:
        return []
    queryset = queryset.filter(visitor_guid__in=visitor_guids)

    return list(queryset)


def match_recording_sessions(project, recordings, *, max_gap_seconds=None):
    """Return recording -> analytics correlations without reusing analytics rows.

    Every project requires the same browser visitor GUID and a close/overlapping
    time interval. One recording can legitimately map to several analytics
    sessions because analytics identity changes split sessions by user/company.
    """

    recordings = list(recordings or [])
    max_gap_seconds = _match_max_gap_seconds() if max_gap_seconds is None else max(0, int(max_gap_seconds))
    analytics_sessions = _load_analytics_candidates(project, recordings, max_gap_seconds)

    recordings_by_guid = defaultdict(list)
    analytics_by_guid = defaultdict(list)
    for recording in recordings:
        guid = recording.visitor.visitor_guid if recording.visitor_id else None
        if guid:
            recordings_by_guid[guid].append(recording)
    for analytics in analytics_sessions:
        if analytics.visitor_guid:
            analytics_by_guid[analytics.visitor_guid].append(analytics)

    matches = {}
    used_analytics_ids = set()

    def add_match(recording, analytics, match_type):
        bundle = matches.setdefault(
            recording.session_id,
            {
                'analytics_session': analytics,
                'analytics_sessions': [],
                'match_type': match_type,
                '_primary_rank': _pair_rank(recording, analytics),
            },
        )
        bundle['analytics_sessions'].append(analytics)
        rank = _pair_rank(recording, analytics)
        if rank < bundle['_primary_rank']:
            bundle['analytics_session'] = analytics
            bundle['match_type'] = match_type
            bundle['_primary_rank'] = rank

    # Assign each analytics fragment to its strongest recording. Recordings are
    # deliberately reusable because a user/company identity change creates a
    # new analytics session while recording continues uninterrupted.
    for guid in sorted(recordings_by_guid, key=str):
        pairs = []
        for recording in recordings_by_guid[guid]:
            for analytics in analytics_by_guid.get(guid, ()):
                _intersects, _overlap, gap_seconds = _interval_relation(recording, analytics)
                if gap_seconds <= max_gap_seconds:
                    pairs.append((_pair_rank(recording, analytics), recording, analytics))
        pairs.sort(key=lambda item: item[0])
        for _rank, recording, analytics in pairs:
            if analytics.session_id in used_analytics_ids:
                continue
            add_match(recording, analytics, 'visitor_time')
            used_analytics_ids.add(analytics.session_id)

    for bundle in matches.values():
        bundle['analytics_sessions'].sort(
            key=lambda item: (item.start_time, str(item.session_id)),
        )
        bundle.pop('_primary_rank', None)

    return matches


def _is_chromatic_color(color):
    color = _clean(color)
    if not SAFE_PRODUCT_AREA_COLOR_RE.fullmatch(color):
        return False
    red, green, blue = (int(color[index:index + 2], 16) for index in (1, 3, 5))
    # Neutral and near-neutral colors are deliberately rejected.  Their stored
    # value is preserved elsewhere in the product, but Visits reserves gray.
    return max(red, green, blue) - min(red, green, blue) >= 45


def _stable_classified_color(area_key, area_name, explicit_color=''):
    if _is_chromatic_color(explicit_color):
        return explicit_color
    identity = ' '.join((_clean(area_key) or _clean(area_name)).lower().split()) or 'classified'
    digest = hashlib.sha256(identity.encode('utf-8')).digest()
    return CLASSIFIED_COLOR_PALETTE[int.from_bytes(digest[:4], 'big') % len(CLASSIFIED_COLOR_PALETTE)]


def _area_indexes(project):
    by_id = {}
    by_key = {}
    by_name = {}
    rows = ProductArea.objects.filter(project=project).values('id', 'slug', 'name', 'short_name', 'color')
    for raw in rows:
        item = {
            'id': raw['id'],
            'key': _clean(raw['slug']),
            'name': _clean(raw['name']),
            'short_name': _clean(raw['short_name']),
            'color': _clean(raw['color']),
        }
        by_id[item['id']] = item
        if item['key']:
            by_key[item['key'].casefold()] = item
        if item['name']:
            by_name[item['name'].casefold()] = item
    return by_id, by_key, by_name


def _active_rule_metadata(project, historical_rule_ids=()):
    historical_rule_ids = {
        rule_id
        for rule_id in historical_rule_ids
        if rule_id is not None
    }
    rule_filter = Q(is_active=True)
    if historical_rule_ids:
        rule_filter |= Q(id__in=historical_rule_ids)
    relevant_rules = list(
        ProjectPageRule.objects
        .filter(project=project)
        .filter(rule_filter)
        .order_by('-priority', '-updated_at', 'id')
    )
    active_rules = [rule for rule in relevant_rules if rule.is_active]
    # PageVisit stores the rule id as historical metadata. Keep inactive rules
    # referenced by this result page available for its canonical label, while
    # URL fallback matching continues to use only the active rule set.
    return active_rules, {rule.id: rule for rule in relevant_rules}, compile_page_rules(active_rules)


def _product_area_for_rule(rule, area_by_key, area_by_name):
    area_name = _clean(rule.product_area) or _clean(rule.page_name) or UNCLASSIFIED_AREA_NAME
    normalized_key = _normalized_area_key('', area_name)
    area = area_by_key.get(normalized_key.casefold()) or area_by_name.get(area_name.casefold())
    if area:
        return {
            **area,
            'key': normalized_key,
            'name': area_name,
        }
    return {
        'id': None,
        'key': normalized_key,
        'name': area_name,
        'short_name': '',
        'color': '',
    }


def _page_entry(
    *,
    logical_key,
    page_name,
    active_seconds,
    classified,
    area_key='',
    area_name='',
    area_color='',
    page_rule_id=None,
):
    normalized_page_name = _clean(page_name) or 'Unknown page'
    if classified:
        normalized_area_name = _clean(area_name) or 'Product area'
        normalized_area_key = _normalized_area_key(area_key, normalized_area_name)
        logical_key = _classified_page_key(normalized_page_name)
        color = _stable_classified_color(normalized_area_key, normalized_area_name, area_color)
    else:
        normalized_area_name = UNCLASSIFIED_AREA_NAME
        normalized_area_key = UNCLASSIFIED_AREA_KEY
        color = UNCLASSIFIED_COLOR

    return {
        'logical_key': logical_key,
        'page': normalized_page_name,
        'seconds': max(0, int(active_seconds or 0)),
        'classified': bool(classified),
        'product_area': normalized_area_name,
        'product_area_key': normalized_area_key,
        'color': color,
        'page_rule_ids': {page_rule_id} if page_rule_id is not None else set(),
    }


def _build_segments(entries):
    combined = {}
    for entry in entries or ():
        key = _entry_identity(entry)
        if key not in combined:
            combined[key] = dict(entry)
            combined[key]['page_rule_ids'] = set(entry.get('page_rule_ids') or ())
        else:
            combined[key]['seconds'] += entry['seconds']
            combined[key]['page_rule_ids'].update(entry.get('page_rule_ids') or ())
            # Historical samples can contain more than one title for the same
            # logical URL.  Keep one deterministic label while still merging
            # the active time into a single page segment.
            if _display_label_rank(entry['page']) < _display_label_rank(combined[key]['page']):
                combined[key]['page'] = entry['page']

    groups = {}
    for entry in combined.values():
        if entry['seconds'] <= 0:
            continue
        area_key = entry['product_area_key']
        group = groups.setdefault(
            area_key,
            {
                'product_area': entry['product_area'],
                'product_area_key': area_key,
                'color': entry['color'],
                'classified': entry['classified'],
                'seconds': 0,
                'pages': [],
            },
        )
        group['seconds'] += entry['seconds']
        group['pages'].append(entry)

    ordered_groups = sorted(
        groups.values(),
        key=lambda group: (-group['seconds'], group['product_area'].casefold(), group['product_area_key']),
    )
    segments = []
    public_groups = []
    for group in ordered_groups:
        ordered_pages = sorted(
            group['pages'],
            key=lambda page: (-page['seconds'], page['page'].casefold(), str(page['logical_key'])),
        )
        public_pages = []
        for page in ordered_pages:
            page_rule_ids = sorted(page.get('page_rule_ids') or ())
            segment = {
                'page': page['page'],
                'page_name': page['page'],
                'pageKey': str(page['logical_key']),
                'page_key': str(page['logical_key']),
                'seconds': page['seconds'],
                'activeSeconds': page['seconds'],
                'active_seconds': page['seconds'],
                'productArea': group['product_area'],
                'product_area': group['product_area'],
                'productAreaKey': group['product_area_key'],
                'product_area_key': group['product_area_key'],
                'color': group['color'],
                'classified': group['classified'],
                'pageRuleIds': page_rule_ids,
                'page_rule_ids': page_rule_ids,
            }
            segments.append(segment)
            public_pages.append(segment)
        public_groups.append({
            'productArea': group['product_area'],
            'product_area': group['product_area'],
            'productAreaKey': group['product_area_key'],
            'product_area_key': group['product_area_key'],
            'seconds': group['seconds'],
            'activeSeconds': group['seconds'],
            'color': group['color'],
            'classified': group['classified'],
            'pages': public_pages,
        })
    return segments, public_groups


def _clipped_page_visit_seconds(project, analytics_windows):
    if not analytics_windows:
        return {}
    rows = (
        PageVisit.objects
        .filter(project=project, session_id__in=analytics_windows)
        .values('id', 'session_id', 'visit_start_ts', 'visit_end_ts', 'engaged_seconds')
    )
    clipped = {}
    for row in rows:
        window_start, window_end = analytics_windows[row['session_id']]
        if window_end <= window_start:
            window_end = window_start + timedelta(seconds=1)
        visit_start = row['visit_start_ts']
        visit_end = max(row.get('visit_end_ts') or visit_start, visit_start)
        overlap_start = max(visit_start, window_start)
        overlap_end = min(visit_end, window_end)
        is_point_visit = visit_end == visit_start
        if is_point_visit:
            if not (window_start <= visit_start < window_end):
                continue
        elif overlap_end <= overlap_start:
            continue

        engaged_seconds = max(0, int(row.get('engaged_seconds') or 0))
        visit_seconds = max(0.0, (visit_end - visit_start).total_seconds())
        overlap_seconds = max(0.0, (overlap_end - overlap_start).total_seconds())
        if visit_seconds <= 0:
            adjusted_seconds = engaged_seconds
        elif overlap_seconds >= visit_seconds:
            adjusted_seconds = engaged_seconds
        else:
            # PageVisit stores only a rolled-up engaged total, so a boundary
            # crossing has no event-level slices left to sum exactly. Prorating
            # by its overlap keeps the total bounded to the replay interval.
            adjusted_seconds = min(
                engaged_seconds,
                max(0, int(round(engaged_seconds * overlap_seconds / visit_seconds))),
            )
        clipped[row['id']] = {
            'session_id': row['session_id'],
            'seconds': adjusted_seconds,
        }
    return clipped


def _page_visit_entry(row, rules_by_id, active_seconds):
    rule_id = row.get('page_rule_id')
    rule = rules_by_id.get(rule_id)
    classified = rule_id is not None
    normalized_url = normalize_page_url_key(row.get('url_normalized')) or _clean(row.get('url_normalized'))
    page_name = (
        _clean(getattr(rule, 'page_name', ''))
        or _clean(row.get('page_name_original'))
        or _clean(row.get('representative_page_name'))
        or normalized_url
    )
    return _page_entry(
        logical_key='' if classified else f'url:{normalized_url}',
        page_name=page_name,
        active_seconds=active_seconds,
        classified=classified,
        area_key=row.get('product_area__slug') or row.get('product_area_key'),
        area_name=(
            _clean(getattr(rule, 'product_area', ''))
            or row.get('product_area__name')
            or row.get('product_area_name')
        ),
        area_color=row.get('product_area__color'),
        page_rule_id=rule_id,
    )


def _page_visit_metrics(project, analytics_ids, rules_by_id, *, page_visit_seconds=None):
    if not analytics_ids or page_visit_seconds == {}:
        return {}
    page_visits = PageVisit.objects.filter(project=project, session_id__in=analytics_ids)
    if page_visit_seconds is not None:
        page_visits = page_visits.filter(id__in=page_visit_seconds)
    rows = (
        page_visits
        .values('session_id')
        .annotate(
            duration_seconds=Sum('engaged_seconds'),
            user_id_sample=Min('user_id', filter=~Q(user_id__isnull=True) & ~Q(user_id='')),
            user_name_sample_value=Min('user_name_sample', filter=~Q(user_name_sample='')),
            company_id_sample=Min('company_id', filter=~Q(company_id__isnull=True) & ~Q(company_id='')),
            company_name_sample_value=Min('company_name_sample', filter=~Q(company_name_sample='')),
        )
        .order_by()
    )
    metrics = {
        row['session_id']: {
            **row,
            'duration_seconds': int(row.get('duration_seconds') or 0),
            'unique_pages': 0,
            'logical_pages': set(),
        }
        for row in rows
    }
    if page_visit_seconds is not None:
        duration_by_session = defaultdict(int)
        for item in page_visit_seconds.values():
            duration_by_session[item['session_id']] += item['seconds']
        for session_id, payload in metrics.items():
            payload['duration_seconds'] = duration_by_session[session_id]
    classified_page_rows = (
        page_visits
        .filter(page_rule_id__isnull=False)
        .values(
            'session_id',
            'page_rule_id',
            'product_area_key',
            'product_area_name',
            'product_area__slug',
            'product_area__name',
        )
        .annotate(representative_page_name=Min('page_name_original'))
        .order_by()
    )
    for row in classified_page_rows:
        entry = _page_visit_entry(row, rules_by_id, active_seconds=0)
        metrics[row['session_id']]['logical_pages'].add(_entry_identity(entry))
    unclassified_page_rows = (
        page_visits
        .filter(page_rule_id__isnull=True)
        .values('session_id', 'url_normalized')
        .distinct()
    )
    for row in unclassified_page_rows:
        normalized_url = normalize_page_url_key(row.get('url_normalized')) or _clean(row.get('url_normalized'))
        metrics[row['session_id']]['logical_pages'].add((
            UNCLASSIFIED_AREA_KEY,
            f'url:{normalized_url}',
        ))
    for payload in metrics.values():
        payload['unique_pages'] = len(payload['logical_pages'])
    return metrics


def _page_visit_segments(project, analytics_ids, rules_by_id, *, page_visit_seconds=None):
    segments_by_session = defaultdict(list)
    if not analytics_ids or page_visit_seconds == {}:
        return segments_by_session
    page_visits = PageVisit.objects.filter(project=project, session_id__in=analytics_ids)
    if page_visit_seconds is not None:
        page_visits = page_visits.filter(id__in=page_visit_seconds)
    rows = (
        page_visits
        .values(
            'id',
            'session_id',
            'page_rule_id',
            'url_normalized',
            'page_name_original',
            'product_area_id',
            'product_area_key',
            'product_area_name',
            'product_area__slug',
            'product_area__name',
            'product_area__color',
            'engaged_seconds',
        )
    )
    for row in rows:
        segments_by_session[row['session_id']].append(
            _page_visit_entry(
                row,
                rules_by_id,
                active_seconds=(
                    page_visit_seconds[row['id']]['seconds']
                    if page_visit_seconds is not None
                    else row.get('engaged_seconds')
                ),
            )
        )
    return segments_by_session


def _display_name(sample_name, entity_id):
    return _clean(sample_name) or _clean(entity_id) or 'Unknown'


def _representative_identity(analytics_sessions, metrics_by_analytics):
    candidates = []
    for analytics in analytics_sessions:
        metrics = metrics_by_analytics.get(analytics.session_id) or {}
        user_id = _clean(metrics.get('user_id_sample')) or _clean(analytics.user_id)
        company_id = _clean(metrics.get('company_id_sample')) or _clean(analytics.company_id)
        if not user_id and not company_id:
            continue
        user_name = _clean(metrics.get('user_name_sample_value'))
        company_name = _clean(metrics.get('company_name_sample_value'))
        candidates.append((
            int(metrics.get('duration_seconds') or 0),
            bool(user_id) + bool(company_id),
            bool(user_name) + bool(company_name),
            analytics.start_time,
            str(analytics.session_id),
            user_id,
            user_name,
            company_id,
            company_name,
        ))
    if not candidates:
        return '', '', '', ''
    winner = max(candidates)
    return winner[-4], winner[-3], winner[-2], winner[-1]


def _normalize_sort(sort_key, sort_direction):
    normalized_key = SORT_KEY_ALIASES.get(_clean(sort_key).lower(), DEFAULT_SORT_KEY)
    normalized_direction = _clean(sort_direction).lower()
    if normalized_direction not in {'asc', 'desc'}:
        normalized_direction = DEFAULT_SORT_DIRECTION
    return normalized_key, normalized_direction


def _compare_rows(left, right, sort_key, direction):
    if sort_key == 'user':
        missing_labels = {'Unknown', 'Anonymous', 'Identity unavailable for this legacy visit'}
        left_value = None if left['user_name'] in missing_labels else left['user_name'].casefold()
        right_value = None if right['user_name'] in missing_labels else right['user_name'].casefold()
    elif sort_key == 'company':
        missing_labels = {'Unknown', 'Identity unavailable for this legacy visit'}
        left_value = None if left['company_name'] in missing_labels else left['company_name'].casefold()
        right_value = None if right['company_name'] in missing_labels else right['company_name'].casefold()
    elif sort_key == 'duration':
        left_value = left['duration_seconds']
        right_value = right['duration_seconds']
    elif sort_key == 'unique_pages':
        left_value = left['unique_pages']
        right_value = right['unique_pages']
    else:
        left_value = left['started_at']
        right_value = right['started_at']

    # Missing entity labels remain at the end in either direction.
    if left_value is None and right_value is not None:
        return 1
    if right_value is None and left_value is not None:
        return -1
    if left_value != right_value:
        comparison = -1 if left_value < right_value else 1
        return comparison if direction == 'asc' else -comparison

    # The default tie breaker is newest visit first, followed by replay UUID.
    if left['started_at'] != right['started_at']:
        return -1 if left['started_at'] > right['started_at'] else 1
    left_id = str(left['session_id'])
    right_id = str(right['session_id'])
    return -1 if left_id < right_id else (1 if left_id > right_id else 0)


def _positive_int(value, default, maximum=None):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if parsed < 1:
        parsed = default
    if maximum is not None:
        parsed = min(parsed, maximum)
    return parsed


def _recorded_sessions_queryset(project):
    linked_analytics_events = AnalyticsEvent.objects.filter(
        session__project=project,
        session__visit_session_id=OuterRef('session_id'),
    )
    replay_snapshots = replayable_full_snapshot_events(
        session_id=OuterRef('session_id'),
    )
    return (
        Session.objects
        .filter(visitor__project=project)
        .alias(
            has_replay_snapshot=Exists(replay_snapshots),
            has_linked_analytics_event=Exists(linked_analytics_events),
        )
        .annotate(
            analytics_event_start=Min(
                'analytics_fragments__events__timestamp',
                filter=Q(analytics_fragments__project=project),
            ),
            analytics_event_end=Max(
                'analytics_fragments__events__timestamp',
                filter=Q(analytics_fragments__project=project),
            ),
        )
        .filter(has_replay_snapshot=True)
        .filter(has_linked_analytics_event=True)
        .select_related('visitor')
    )


def _base_visits_recordings_queryset(
    project,
    *,
    period,
    entity_type='',
    entity_id='',
    page_filter_type='',
    page_filter_id='',
):
    """Return the replayable recording scope before company attributes."""

    recordings_queryset = _recorded_sessions_queryset(project).filter(
        analytics_event_start__gte=period['start_ts'],
        analytics_event_start__lt=period['end_ts'],
    )
    if entity_type and entity_id:
        identity_filter = {
            f'{entity_type}_id': entity_id,
        }
        matching_identity = AnalyticsSession.objects.filter(
            project=project,
            visit_session_id=OuterRef('session_id'),
            **identity_filter,
        )
        recordings_queryset = recordings_queryset.alias(
            matches_entity_filter=Exists(matching_identity),
        ).filter(matches_entity_filter=True)

    if page_filter_type and page_filter_id:
        matching_page = AnalyticsEvent.objects.filter(
            session__project=project,
            session__visit_session_id=OuterRef('session_id'),
        )
        if page_filter_type == 'area':
            if page_filter_id == UNCLASSIFIED_AREA_KEY:
                matching_page = matching_page.filter(page_rule_id__isnull=True)
            else:
                selected_area_names = {
                    _normalized_identity_text(name)
                    for name in ProductArea.objects.filter(
                        project=project,
                        slug=page_filter_id,
                    ).values_list('name', flat=True)
                }
                matching_rule_ids = [
                    row['id']
                    for row in ProjectPageRule.objects.filter(project=project).values(
                        'id',
                        'product_area',
                    )
                    if (
                        _normalized_identity_text(row['product_area']) in selected_area_names
                        or _normalized_area_key('', row['product_area']) == page_filter_id
                    )
                ]
                matching_page = matching_page.filter(page_rule_id__in=matching_rule_ids)
        else:
            try:
                page_rule_id = int(page_filter_id)
            except (TypeError, ValueError):
                page_rule_id = -1
            matching_page = matching_page.filter(page_rule_id=page_rule_id)
        recordings_queryset = recordings_queryset.alias(
            matches_page_filter=Exists(matching_page),
        ).filter(matches_page_filter=True)

    return recordings_queryset


def _apply_recording_company_attribute_filters(
    recordings_queryset,
    project,
    company_attribute_state,
    *,
    entity_type='',
    entity_id='',
):
    """Qualify complete recordings through the applicable linked company.

    An unscoped/page-scoped replay may qualify through any linked company so
    the complete replay remains visible. A selected company or user is
    correlated with its own identity fragments and cannot be qualified by a
    company belonging only to another identity in the same replay.
    """

    if not company_attribute_state or not company_attribute_state.active:
        return recordings_queryset

    matching_identity_queryset = AnalyticsSession.objects.filter(
        project=project,
        visit_session_id=OuterRef('session_id'),
    )
    selected_company_id = entity_id if entity_type == 'company' and entity_id else ''
    selected_user_id = entity_id if entity_type == 'user' and entity_id else ''
    if selected_company_id:
        # A selected company and an attribute cohort are one correlated company
        # predicate. Another company linked to the same replay must not qualify
        # the selected company accidentally.
        matching_identity_queryset = matching_identity_queryset.filter(
            company_id=selected_company_id,
        )
    elif selected_user_id:
        # Multi-user replays use the company attached to the selected user's
        # identity fragments, not a company belonging only to another user.
        matching_identity_queryset = matching_identity_queryset.filter(
            user_id=selected_user_id,
        )
    matching_company_identity = apply_company_attribute_filters(
        matching_identity_queryset,
        company_attribute_state,
        company_field='company_id',
    )
    recordings_queryset = recordings_queryset.alias(
        matches_company_attribute_filter=Exists(matching_company_identity),
    )
    return recordings_queryset.filter(matches_company_attribute_filter=True)


def company_attribute_preview_counts(project, request, state):
    """Count the Visits company scope before and after draft attributes."""

    known_identities = _visits_known_identities(project, request)
    eligible_count = (
        known_identities
        .order_by()
        .values('company_id')
        .distinct()
        .count()
    )

    if not state or not state.active:
        return {
            'matching_count': eligible_count,
            'eligible_count': eligible_count,
        }

    matching_count = (
        apply_company_attribute_filters(
            known_identities,
            state,
            company_field='company_id',
        )
        .order_by()
        .values('company_id')
        .distinct()
        .count()
    )
    return {
        'matching_count': matching_count,
        'eligible_count': eligible_count,
    }


def company_attribute_scope_company_ids(project, request):
    """Distinct identified company IDs the current Visits scope observes."""

    return (
        _visits_known_identities(project, request)
        .order_by()
        .values_list('company_id', flat=True)
        .distinct()
    )


def _visits_known_identities(project, request):
    from apps.tracker.visits_filters import (
        resolve_visits_page_filter,
        visits_page_filter_groups,
    )

    query = request.GET
    entity_type = query.get('entity_type')
    entity_id = _clean(query.get('entity_id'))
    if entity_type not in {'company', 'user'} or not entity_id:
        entity_type = ''
        entity_id = ''
    page_selection = resolve_visits_page_filter(
        visits_page_filter_groups(project),
        query.get('page_filter_type'),
        query.get('page_filter_id'),
    )
    period = resolve_visits_period(project.timezone, query.get('range'))
    recordings_queryset = _base_visits_recordings_queryset(
        project,
        period=period,
        entity_type=entity_type,
        entity_id=entity_id,
        page_filter_type=page_selection['type'],
        page_filter_id=page_selection['id'],
    )
    recording_ids = recordings_queryset.order_by().values('session_id')
    known_identities = (
        AnalyticsSession.objects
        .filter(
            project=project,
            visit_session_id__in=recording_ids,
        )
        .exclude(Q(company_id__isnull=True) | Q(company_id=''))
    )
    selected_company_id = entity_id if entity_type == 'company' and entity_id else ''
    selected_user_id = entity_id if entity_type == 'user' and entity_id else ''
    if selected_company_id:
        known_identities = known_identities.filter(company_id=selected_company_id)
    elif selected_user_id:
        known_identities = known_identities.filter(user_id=selected_user_id)
    return known_identities


def _correlation_neighborhood(project, target_recordings):
    target_recordings = list(target_recordings or ())
    if not target_recordings:
        return []
    buffer_seconds = max(
        int(getattr(settings, 'SESSION_EXPIRATION_SECONDS', 1800)),
        int(getattr(settings, 'ANALYTICS_SESSION_EXPIRATION_SECONDS', 1800)),
    ) + 60
    lower = min(recording.start_time for recording in target_recordings) - timedelta(seconds=buffer_seconds)
    upper = max(_effective_end(recording) for recording in target_recordings) + timedelta(seconds=buffer_seconds)
    queryset = (
        _recorded_sessions_queryset(project)
        .filter(start_time__lt=upper)
        .filter(Q(ended_at__gte=lower) | Q(last_activity__gte=lower))
    )
    visitor_guids = {
        recording.visitor.visitor_guid
        for recording in target_recordings
        if recording.visitor_id and recording.visitor.visitor_guid
    }
    queryset = queryset.filter(visitor__visitor_guid__in=visitor_guids)
    neighborhood = list(queryset.order_by('start_time', 'session_id'))
    by_id = {recording.session_id: recording for recording in neighborhood}
    for recording in target_recordings:
        by_id.setdefault(recording.session_id, recording)
    return _attach_recording_event_bounds(by_id.values())


def _analytics_projection_data(project, recordings):
    """Aggregate the shared chronological analytical projection for Visits."""

    recordings = list(recordings or ())
    projections = build_analytics_visit_projections(project, recordings)
    payloads = {}
    for recording in recordings:
        projection = (
            projections.get(recording.session_id)
            or projections.get(str(recording.session_id))
            or {}
        )
        entries = []
        activity_intervals = []
        clock_start_ms = projection.get('clockStartMs')
        clock_start = (
            datetime.fromtimestamp(clock_start_ms / 1000, tz=datetime_timezone.utc)
            if clock_start_ms is not None
            else None
        )
        for segment in projection.get('segments') or ():
            if segment.get('kind') != 'page':
                continue
            active_seconds = max(0, (segment.get('durationMs') or 0) / 1000)
            if active_seconds <= 0:
                continue
            entries.append({
                'logical_key': _clean(segment.get('pageKey')),
                'page': _clean(segment.get('page') or segment.get('label')) or 'Unknown page',
                'seconds': active_seconds,
                'classified': bool(segment.get('classified')),
                'product_area': (
                    _clean(segment.get('productArea'))
                    or UNCLASSIFIED_AREA_NAME
                ),
                'product_area_key': (
                    _clean(segment.get('productAreaKey'))
                    or UNCLASSIFIED_AREA_KEY
                ),
                'color': _clean(segment.get('color')) or UNCLASSIFIED_COLOR,
                'page_rule_ids': set(segment.get('pageRuleIds') or ()),
            })
            if clock_start is not None:
                activity_intervals.append({
                    'visit_start_ts': clock_start + timedelta(
                        milliseconds=int(segment.get('startMs') or 0),
                    ),
                    'visit_end_ts': clock_start + timedelta(
                        milliseconds=int(segment.get('endMs') or 0),
                    ),
                    'active_seconds': active_seconds,
                })

        segments, area_groups = _build_segments(entries)
        payloads[recording.session_id] = {
            'clock_start_ms': clock_start_ms,
            'clock_end_ms': projection.get('clockEndMs'),
            'duration_seconds': max(0, (projection.get('durationMs') or 0) / 1000),
            'observed_active_seconds': sum(segment['seconds'] for segment in segments),
            'unique_pages': len(segments),
            'segments': segments,
            'area_groups': area_groups,
            'activity_intervals': activity_intervals,
            'linkage': projection.get('linkage') or 'none',
        }
    return payloads


def _identity_names(analytics_sessions):
    session_ids = [session.session_id for session in analytics_sessions]
    names = defaultdict(lambda: {'user_name': '', 'company_name': ''})
    if not session_ids:
        return names

    def latest_trait(json_field, key):
        rows = (
            AnalyticsEvent.objects
            .filter(session_id=OuterRef('session_id'))
            .annotate(trait_value=KeyTextTransform(key, json_field))
            .filter(trait_value__isnull=False)
            .annotate(trait_length=Length('trait_value'))
            .filter(trait_length__gt=0)
            .order_by('-timestamp', '-id')
        )
        return Subquery(
            rows.values('trait_value')[:1],
            output_field=CharField(),
        )

    rows = (
        AnalyticsSession.objects
        .filter(session_id__in=session_ids)
        .annotate(
            latest_user_name=latest_trait('user_traits', 'name'),
            latest_user_email=latest_trait('user_traits', 'email'),
            latest_company_name=latest_trait('company_traits', 'name'),
        )
        .values(
            'session_id',
            'latest_user_name',
            'latest_user_email',
            'latest_company_name',
        )
    )
    for row in rows:
        names[row['session_id']]['user_name'] = (
            _clean(row['latest_user_name'])
            or _clean(row['latest_user_email'])
        )
        names[row['session_id']]['company_name'] = _clean(row['latest_company_name'])
    return names


def _append_identity_interval(intervals, *, start, end, fragment=None, names=None, unavailable=False):
    if end < start:
        return
    names = names or {}
    intervals.append({
        'start': start,
        'end': end,
        'analytics_session_id': fragment.session_id if fragment is not None else None,
        'user_id': _clean(fragment.user_id) if fragment is not None else '',
        'user_name': names.get('user_name', '') if fragment is not None else '',
        'company_id': _clean(fragment.company_id) if fragment is not None else '',
        'company_name': names.get('company_name', '') if fragment is not None else '',
        'unavailable': bool(unavailable),
        'active_seconds': 0,
    })


def _identity_intervals(
    recording,
    fragments,
    names_by_session,
    *,
    analytical_start=None,
    analytical_end=None,
):
    recording_start = analytical_start or _recording_start(recording)
    recording_end = analytical_end or _recording_end(recording)
    if not fragments and not recording.identity_linkage_ready:
        intervals = []
        _append_identity_interval(
            intervals,
            start=recording_start,
            end=recording_end,
            unavailable=True,
        )
        return intervals

    intervals = []
    cursor = recording_start
    event_backed_fragments = [
        fragment
        for fragment in fragments
        if getattr(fragment, 'analytics_event_start', None) is not None
    ]
    event_backed_fragments.sort(
        key=lambda item: (item.analytics_event_start, str(item.session_id)),
    )
    # Identity changes create new analytical fragments. Raw event starts are
    # the durable boundaries here: demo tooling may deliberately attach an
    # unrelated recording and rewrite the stored fragment clock.
    for index, fragment in enumerate(event_backed_fragments):
        fragment_start = max(recording_start, fragment.analytics_event_start)
        next_fragment_start = (
            event_backed_fragments[index + 1].analytics_event_start
            if index + 1 < len(event_backed_fragments)
            else recording_end
        )
        fragment_end = min(recording_end, max(fragment_start, next_fragment_start))
        if fragment_end < recording_start or fragment_start > recording_end:
            continue
        if fragment_start > cursor:
            _append_identity_interval(intervals, start=cursor, end=fragment_start)
        visible_start = max(cursor, fragment_start)
        if fragment_end >= visible_start:
            _append_identity_interval(
                intervals,
                start=visible_start,
                end=fragment_end,
                fragment=fragment,
                names=names_by_session.get(fragment.session_id),
            )
            cursor = max(cursor, fragment_end)
    if cursor < recording_end or not intervals:
        _append_identity_interval(intervals, start=cursor, end=recording_end)
    return intervals


def _identity_state_label(interval, kind):
    if interval['unavailable']:
        return 'Identity unavailable for this legacy visit'
    if kind == 'user':
        return interval['user_name'] or interval['user_id'] or 'Anonymous'
    return interval['company_name'] or interval['company_id'] or 'Unknown'


def _identity_summary(intervals, kind):
    selected = None
    known_ids = []
    for interval in intervals:
        entity_id = interval[f'{kind}_id']
        if entity_id and entity_id not in known_ids:
            known_ids.append(entity_id)
        entity_name = interval[f'{kind}_name']
        if entity_id or entity_name:
            selected = {
                'label': entity_name or entity_id,
                'link_id': entity_id,
            }

    if selected is not None:
        return {
            **selected,
            'known_ids': known_ids,
        }

    unavailable = next(
        (interval for interval in intervals if interval['unavailable']),
        None,
    )
    fallback_label = 'Anonymous' if kind == 'user' else 'Unknown'
    if unavailable is not None:
        fallback_label = _identity_state_label(unavailable, kind)
    return {
        'label': fallback_label,
        'link_id': '',
        'known_ids': known_ids,
    }


def _attribute_identity_activity(identity_intervals, activity_intervals):
    for activity in activity_intervals:
        active_seconds = int(activity.get('active_seconds') or 0)
        if active_seconds <= 0:
            continue
        activity_start = activity['visit_start_ts']
        activity_end = activity['visit_end_ts']
        for identity in identity_intervals:
            overlap_start = max(activity_start, identity['start'])
            overlap_end = min(activity_end, identity['end'])
            if overlap_end <= overlap_start:
                continue
            identity['active_seconds'] += min(
                active_seconds,
                max(0, int((overlap_end - overlap_start).total_seconds())),
            )


def build_visits_context(
    project,
    *,
    range_key=DEFAULT_RANGE_KEY,
    sort_key=DEFAULT_SORT_KEY,
    sort_direction=DEFAULT_SORT_DIRECTION,
    entity_type='',
    entity_id='',
    page_filter_type='',
    page_filter_id='',
    page_number=1,
    page_size=DEFAULT_PAGE_SIZE,
    company_attribute_state=None,
    now=None,
):
    """Build analytical Visits that route to canonically attached recordings."""

    period = resolve_visits_period(project.timezone, range_key, now=now)
    sort_key, sort_direction = _normalize_sort(sort_key, sort_direction)
    page_size = _positive_int(page_size, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE)
    entity_type = _clean(entity_type) if entity_type in {'company', 'user'} else ''
    entity_id = _clean(entity_id) if entity_type else ''
    page_filter_type = _clean(page_filter_type) if page_filter_type in {'area', 'page'} else ''
    page_filter_id = _clean(page_filter_id) if page_filter_type else ''

    recordings_queryset = _base_visits_recordings_queryset(
        project,
        period=period,
        entity_type=entity_type,
        entity_id=entity_id,
        page_filter_type=page_filter_type,
        page_filter_id=page_filter_id,
    )
    recordings_queryset = _apply_recording_company_attribute_filters(
        recordings_queryset,
        project,
        company_attribute_state,
        entity_type=entity_type,
        entity_id=entity_id,
    )

    date_sort_is_database_paginated = sort_key == 'date_time'
    if date_sort_is_database_paginated:
        date_order = 'analytics_event_start' if sort_direction == 'asc' else '-analytics_event_start'
        paginator = Paginator(recordings_queryset.order_by(date_order, 'session_id'), page_size)
        page_obj = paginator.get_page(page_number)
        recordings = list(page_obj.object_list)
    else:
        recordings = list(recordings_queryset.order_by('analytics_event_start', 'session_id'))
    recordings = _attach_recording_event_bounds(recordings)

    projection_by_recording = _analytics_projection_data(project, recordings)
    fragments = list(
        AnalyticsSession.objects
        .filter(
            project=project,
            visit_session_id__in=[recording.session_id for recording in recordings],
        )
        .annotate(
            analytics_event_start=Min('events__timestamp'),
            analytics_event_end=Max('events__timestamp'),
        )
        .order_by('visit_session_id', 'analytics_event_start', 'session_id')
    )
    fragments_by_recording = defaultdict(list)
    for fragment in fragments:
        fragments_by_recording[fragment.visit_session_id].append(fragment)
    names_by_session = _identity_names(fragments)

    rows = []
    for recording in recordings:
        projection = projection_by_recording.get(recording.session_id, {})
        recording_fragments = fragments_by_recording.get(recording.session_id, [])
        analytical_start = (
            datetime.fromtimestamp(
                projection['clock_start_ms'] / 1000,
                tz=datetime_timezone.utc,
            )
            if projection.get('clock_start_ms') is not None
            else None
        )
        analytical_end = (
            datetime.fromtimestamp(
                projection['clock_end_ms'] / 1000,
                tz=datetime_timezone.utc,
            )
            if projection.get('clock_end_ms') is not None
            else None
        )
        identity_intervals = _identity_intervals(
            recording,
            recording_fragments,
            names_by_session,
            analytical_start=analytical_start,
            analytical_end=analytical_end,
        )
        _attribute_identity_activity(
            identity_intervals,
            projection.get('activity_intervals', ()),
        )
        user_summary = _identity_summary(identity_intervals, 'user')
        company_summary = _identity_summary(identity_intervals, 'company')
        effective_end = _recording_end(recording)
        observed_active_seconds = projection.get('observed_active_seconds') or 0
        unique_pages = int(projection.get('unique_pages') or 0)
        segments = list(projection.get('segments') or [])
        identity_unavailable = any(interval['unavailable'] for interval in identity_intervals)
        analytics_session_ids = [fragment.session_id for fragment in recording_fragments]
        recording_duration_seconds = max(
            0,
            int((effective_end - _recording_start(recording)).total_seconds()),
        )
        analytics_started_at = analytical_start or recording.analytics_event_start
        rows.append({
            'session': recording,
            'session_id': recording.session_id,
            'recording_session_id': recording.session_id,
            'analytics_session_id': analytics_session_ids[0] if analytics_session_ids else None,
            'analytics_session_ids': analytics_session_ids,
            'analytics_matched': bool(analytics_session_ids),
            'match_type': 'canonical_session' if analytics_session_ids else None,
            'match_state': (
                'identity_unavailable'
                if identity_unavailable
                else 'linked' if analytics_session_ids else 'anonymous'
            ),
            'data_source': 'analytics_events',
            'data_preparing': False,
            'identity_unavailable': identity_unavailable,
            'identity_message': (
                'Identity unavailable for this legacy visit'
                if identity_unavailable
                else ''
            ),
            'identity_intervals': identity_intervals,
            'user_id': user_summary['link_id'],
            'user_ids': user_summary['known_ids'],
            'user_name': user_summary['label'],
            'company_id': company_summary['link_id'],
            'company_ids': company_summary['known_ids'],
            'company_name': company_summary['label'],
            'started_at': analytics_started_at,
            'start_time': analytics_started_at,
            'started_at_local': analytics_started_at.astimezone(period['project_zone']),
            'start_time_local': analytics_started_at.astimezone(period['project_zone']),
            'recording_duration_seconds': recording_duration_seconds,
            'duration_seconds': projection.get('duration_seconds') or 0,
            'observed_active_seconds': observed_active_seconds,
            'unique_pages': unique_pages,
            'unique_pages_count': unique_pages,
            'segments': segments,
            'chart_segments': segments,
            'area_groups': list(projection.get('area_groups') or []),
        })

    rows.sort(key=cmp_to_key(lambda left, right: _compare_rows(left, right, sort_key, sort_direction)))
    if date_sort_is_database_paginated:
        page_obj.object_list = rows
    else:
        paginator = Paginator(rows, page_size)
        page_obj = paginator.get_page(page_number)

    query_values = [
        ('range', period['range_key']),
        ('sort', sort_key),
        ('direction', sort_direction),
    ]
    if entity_type and entity_id:
        query_values.extend((
            ('entity_type', entity_type),
            ('entity_id', entity_id),
        ))
    if page_filter_type and page_filter_id:
        query_values.extend((
            ('page_filter_type', page_filter_type),
            ('page_filter_id', page_filter_id),
        ))
    query_values.extend(
        tuple(getattr(company_attribute_state, 'canonical_pairs', ()) or ())
    )
    query_without_page = urlencode(query_values)
    context = {
        'visits': page_obj.object_list,
        'visit_rows': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'range_key': period['range_key'],
        'selected_range': period['range_key'],
        'range_days': period['range_days'],
        'range_options': RANGE_OPTIONS,
        'sort_key': sort_key,
        'sort_direction': sort_direction,
        'sort_options': SORT_OPTIONS,
        'start_date': period['start_date'],
        'end_date': period['end_date'],
        'start_ts': period['start_ts'],
        'end_ts': period['end_ts'],
        'project_timezone': str(period['project_zone']),
        'page_size': page_size,
        'total_visits': paginator.count,
        'pagination_query': query_without_page,
        # Direct aliases used by the Visits template.  Route-dependent links
        # (replay/entity/sort/pagination URLs) remain the view's responsibility.
        'visits_range_key': period['range_key'],
        'visits_range_options': tuple(
            (option['value'], option['label'])
            for option in RANGE_OPTIONS
        ),
        'visits_range_query_suffix': (
            f'&sort={sort_key}&direction={sort_direction}'
        ),
        'visits_sort_key': sort_key,
        'visits_sort_direction': sort_direction,
        'visits_total_count': paginator.count,
        'visits_entity_type': entity_type,
        'visits_entity_id': entity_id,
        'visits_page_filter_type': page_filter_type,
        'visits_page_filter_id': page_filter_id,
    }
    return context
