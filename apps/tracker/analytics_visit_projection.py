"""Project canonical analytical visits onto one elapsed event clock.

The projection deliberately knows nothing about rrweb.  A recording
``Session`` is used only as the canonical key for resolving linked
``AnalyticsSession`` fragments.  Raw ``AnalyticsEvent`` timestamps define
the clock and page ownership.
"""

from __future__ import annotations

import hashlib
import math
import unicodedata
from collections import defaultdict

from apps.pages.models import ProductArea
from apps.pages.product_area_colors import SAFE_PRODUCT_AREA_COLOR_RE
from apps.tracker.models import AnalyticsEvent, AnalyticsSession
from apps.tracker.page_naming import normalize_page_url_key


ANALYTICS_ACTIVE_GAP_CAP_MS = 30_000
# A terminal observation has no following gap from which to infer time. Reserve
# one millisecond at the analytical boundary so its page remains represented in
# both Visits and replay without materially extending a multi-event visit.
ANALYTICS_TERMINAL_MARKER_MS = 1
ANALYTICS_VISIT_SOURCE = 'analytics_events'
UNCLASSIFIED_AREA_NAME = 'Unclassified'
UNCLASSIFIED_AREA_KEY = 'unclassified'
UNCLASSIFIED_COLOR = '#CBD5E1'

# The neutral tenth shared-palette color is intentionally excluded because
# gray identifies unclassified and inactive intervals in Visits.
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


def _milliseconds(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(result):
        return 0
    return int(round(result))


def _event_timestamp_ms(event):
    return int(round(event.timestamp.timestamp() * 1000))


def _normalized_identity_text(value):
    normalized = unicodedata.normalize('NFKC', _clean(value))
    return ' '.join(normalized.split()).casefold()


def _product_area_name_key(value):
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


def _is_chromatic_color(color):
    color = _clean(color)
    if not SAFE_PRODUCT_AREA_COLOR_RE.fullmatch(color):
        return False
    red, green, blue = (int(color[index:index + 2], 16) for index in (1, 3, 5))
    return max(red, green, blue) - min(red, green, blue) >= 45


def _stable_classified_color(area_key, area_name, explicit_color=''):
    if _is_chromatic_color(explicit_color):
        return explicit_color
    identity = ' '.join((_clean(area_key) or _clean(area_name)).lower().split()) or 'classified'
    digest = hashlib.sha256(identity.encode('utf-8')).digest()
    return CLASSIFIED_COLOR_PALETTE[
        int.from_bytes(digest[:4], 'big') % len(CLASSIFIED_COLOR_PALETTE)
    ]


def _area_indexes(project):
    by_key = {}
    by_name = {}
    if project is None or getattr(project, 'pk', None) is None:
        return by_key, by_name
    rows = ProductArea.objects.filter(project=project).values(
        'slug',
        'name',
        'color',
    )
    for raw in rows:
        item = {
            'key': _clean(raw.get('slug')),
            'name': _clean(raw.get('name')),
            'color': _clean(raw.get('color')),
        }
        if item['key']:
            by_key[item['key'].casefold()] = item
        if item['name']:
            by_name[item['name'].casefold()] = item
    return by_key, by_name


def _unclassified_page_name(event):
    candidates = (
        event.page_name_original,
        event.page_name,
        normalize_page_url_key(event.url_normalized),
        normalize_page_url_key(event.url),
        event.url_normalized,
        event.url,
    )
    for candidate in candidates:
        label = _clean(candidate)
        if label and label.casefold() != 'undefined':
            return label
    return 'Unknown page'


def _event_page_metadata(event, project, areas_by_key, areas_by_name):
    rule = event.page_rule
    classified = bool(
        event.page_rule_id is not None
        and rule is not None
        and rule.project_id == project.id
    )
    normalized_url = (
        normalize_page_url_key(event.url_normalized)
        or normalize_page_url_key(event.url)
        or _clean(event.url_normalized)
        or _clean(event.url)
    )

    if not classified:
        page = _unclassified_page_name(event)
        page_key = f'url:{normalized_url}' if normalized_url else _classified_page_key(page)
        return {
            'label': page,
            'page': page,
            'pageKey': page_key,
            'productArea': UNCLASSIFIED_AREA_NAME,
            'productAreaKey': UNCLASSIFIED_AREA_KEY,
            'color': UNCLASSIFIED_COLOR,
            'classified': False,
            'pageRuleIds': [],
        }

    page = _clean(rule.page_name) or _clean(event.page_name) or normalized_url or 'Unknown page'
    area_name = _clean(rule.product_area) or _clean(event.product_area) or page
    area_key = _normalized_area_key('', area_name)
    area = (
        areas_by_key.get(area_key.casefold())
        or areas_by_name.get(area_name.casefold())
        or {}
    )
    return {
        'label': page,
        'page': page,
        'pageKey': _classified_page_key(page),
        'productArea': area_name,
        'productAreaKey': area_key,
        'color': _stable_classified_color(
            area_key,
            area_name,
            area.get('color') or '',
        ),
        'classified': True,
        'pageRuleIds': [event.page_rule_id],
    }


def _inactive_metadata():
    return {
        'label': 'Inactive',
        'page': '',
        'pageKey': '',
        'productArea': 'Inactive',
        'productAreaKey': 'inactive',
        'color': UNCLASSIFIED_COLOR,
        'classified': False,
        'pageRuleIds': [],
    }


def _empty_projection(*, linkage='none', active_gap_cap_ms=ANALYTICS_ACTIVE_GAP_CAP_MS):
    return {
        'source': ANALYTICS_VISIT_SOURCE,
        'linkage': linkage,
        'clockStartMs': None,
        'clockEndMs': None,
        'durationMs': 0,
        'inactivityThresholdMs': active_gap_cap_ms,
        'segments': [],
    }


def _same_page(left, right):
    return (
        left['pageKey'],
        left['productAreaKey'],
        left['classified'],
    ) == (
        right['pageKey'],
        right['productAreaKey'],
        right['classified'],
    )


def _append_segment(segments, kind, start_ms, end_ms, metadata):
    start_ms = _milliseconds(start_ms)
    end_ms = _milliseconds(end_ms)
    if end_ms <= start_ms:
        return

    item = {
        'kind': kind,
        'startMs': start_ms,
        'endMs': end_ms,
        'durationMs': end_ms - start_ms,
        **metadata,
    }
    if segments and segments[-1]['endMs'] == item['startMs']:
        previous = segments[-1]
        if kind == 'inactive' and previous['kind'] == kind:
            previous['endMs'] = item['endMs']
            previous['durationMs'] = previous['endMs'] - previous['startMs']
            return
        if kind == 'page' and previous['kind'] == kind and _same_page(previous, item):
            previous['endMs'] = item['endMs']
            previous['durationMs'] = previous['endMs'] - previous['startMs']
            previous['pageRuleIds'] = sorted(set(
                previous.get('pageRuleIds', ())
            ) | set(item.get('pageRuleIds', ())))
            return
    segments.append(item)


def _trim_segments_to(segments, end_ms):
    """Trim chronological coverage at ``end_ms`` for a terminal marker."""

    end_ms = _milliseconds(end_ms)
    while segments and segments[-1]['startMs'] >= end_ms:
        segments.pop()
    if segments and segments[-1]['endMs'] > end_ms:
        segments[-1]['endMs'] = end_ms
        segments[-1]['durationMs'] = end_ms - segments[-1]['startMs']


def _projection_from_events(
    project,
    events,
    *,
    areas_by_key,
    areas_by_name,
    active_gap_cap_ms,
    linkage,
):
    if not events:
        return _empty_projection(
            linkage=linkage,
            active_gap_cap_ms=active_gap_cap_ms,
        )

    raw_observations = [
        (
            _event_timestamp_ms(event),
            _event_page_metadata(event, project, areas_by_key, areas_by_name),
        )
        for event in events
    ]
    observations = []
    for timestamp_ms, page in raw_observations:
        display_timestamp_ms = timestamp_ms
        if observations and display_timestamp_ms <= observations[-1][0]:
            previous_timestamp_ms, previous_page = observations[-1]
            if _same_page(previous_page, page):
                display_timestamp_ms = previous_timestamp_ms
            else:
                # Database ordering still distinguishes events whose stored
                # timestamps collide at millisecond precision. Give each page
                # transition one display millisecond so no observed page is
                # discarded as a zero-length interval.
                display_timestamp_ms = previous_timestamp_ms + 1
        observations.append((display_timestamp_ms, page))

    clock_start_ms = observations[0][0]
    raw_clock_end_ms = raw_observations[-1][0]
    display_clock_end_ms = observations[-1][0]
    duration_ms = max(0, raw_clock_end_ms - clock_start_ms)
    if display_clock_end_ms > raw_clock_end_ms:
        duration_ms = display_clock_end_ms - clock_start_ms + ANALYTICS_TERMINAL_MARKER_MS
    elif duration_ms == 0:
        duration_ms = ANALYTICS_TERMINAL_MARKER_MS
    clock_end_ms = clock_start_ms + duration_ms
    segments = []

    # Nonterminal observations use the same capped-next-event rule as prepared
    # analytical page facts.
    for index, (timestamp_ms, page) in enumerate(observations[:-1]):
        event_offset = timestamp_ms - clock_start_ms
        next_offset = observations[index + 1][0] - clock_start_ms
        active_until = min(
            next_offset,
            event_offset + active_gap_cap_ms,
        )
        _append_segment(segments, 'page', event_offset, active_until, page)
        _append_segment(
            segments,
            'inactive',
            active_until,
            next_offset,
            _inactive_metadata(),
        )

    # Page facts infer no active tail for the terminal observation. The player
    # and Visits page set still need to show that observed page, so reserve a
    # one-millisecond marker at the existing visit boundary. For a one-event
    # visit, the marker itself defines the otherwise empty clock.
    terminal_start = max(0, duration_ms - ANALYTICS_TERMINAL_MARKER_MS)
    _trim_segments_to(segments, terminal_start)
    _append_segment(
        segments,
        'page',
        terminal_start,
        duration_ms,
        observations[-1][1],
    )

    return {
        'source': ANALYTICS_VISIT_SOURCE,
        'linkage': linkage,
        'clockStartMs': clock_start_ms,
        'clockEndMs': clock_end_ms,
        'durationMs': duration_ms,
        'inactivityThresholdMs': active_gap_cap_ms,
        'segments': segments,
    }


def build_analytics_visit_projections(
    project,
    recording_sessions,
    *,
    active_gap_cap_ms=ANALYTICS_ACTIVE_GAP_CAP_MS,
):
    """Build projections for recording sessions with two canonical queries."""

    recordings = [
        recording
        for recording in recording_sessions or ()
        if getattr(recording, 'pk', None) is not None
    ]
    if not recordings:
        return {}

    active_gap_cap_ms = max(0, _milliseconds(active_gap_cap_ms))
    recording_ids = [recording.pk for recording in recordings]
    fragments = list(
        AnalyticsSession.objects.filter(
            project=project,
            visit_session_id__in=recording_ids,
        ).order_by('visit_session_id', 'start_time', 'session_id')
    )
    fragment_ids = [fragment.session_id for fragment in fragments]
    events = list(
        AnalyticsEvent.objects.filter(
            session_id__in=fragment_ids,
            session__project=project,
        )
        .select_related('page_rule', 'session')
        .order_by('timestamp', 'id')
    )

    fragment_recording_ids = {
        fragment.session_id: fragment.visit_session_id
        for fragment in fragments
    }
    events_by_recording = defaultdict(list)
    for event in events:
        recording_id = fragment_recording_ids.get(event.session_id)
        if recording_id is not None:
            events_by_recording[recording_id].append(event)

    linked_recording_ids = {
        fragment.visit_session_id
        for fragment in fragments
    }
    areas_by_key, areas_by_name = _area_indexes(project)
    return {
        recording.pk: _projection_from_events(
            project,
            events_by_recording.get(recording.pk, ()),
            areas_by_key=areas_by_key,
            areas_by_name=areas_by_name,
            active_gap_cap_ms=active_gap_cap_ms,
            linkage=('canonical' if recording.pk in linked_recording_ids else 'none'),
        )
        for recording in recordings
    }


def build_analytics_visit_projection(
    project,
    recording_session,
    *,
    active_gap_cap_ms=ANALYTICS_ACTIVE_GAP_CAP_MS,
):
    """Return the canonical analytical projection for one recording session."""

    if project is None or getattr(recording_session, 'pk', None) is None:
        return _empty_projection(active_gap_cap_ms=max(
            0,
            _milliseconds(active_gap_cap_ms),
        ))
    return build_analytics_visit_projections(
        project,
        [recording_session],
        active_gap_cap_ms=active_gap_cap_ms,
    )[recording_session.pk]
