from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from django import template
from django.db.models import Count
from django.utils import timezone

from apps.tracker.url_titles import get_latest_analytics_titles

register = template.Library()
PAGE_COLORS = [
    "#4269D0",
    "#EFB118",
    "#FF725C",
    "#6CC5B0",
    "#3CA951",
    "#FF8AB7",
    "#A463F2",
    "#97BBF5",
    "#9C6B4E",
    "#E5E7EB",
]

PALETTE_CLASSES = [
    "c-blue", "c-yellow", "c-red", "c-light-green", "c-green",
    "c-pink", "c-purple", "c-light-blue", "c-brown", "c-gray"
]

EVENT_TYPES = {
    0: 'mutation',
    1: 'mousemove',
    2: {
        '0': 'mouseup',
        '1': 'mousedown',
        '2': 'click',
        '3': 'contextmenu',
        '4': 'dblclick',
        '5': 'focus',
        '6': 'blur',
        '7': 'touchstart',
        '8': 'touchend',
        '9': 'touchmove'
    },
    3: 'scroll',
    4: 'viewportresize',
    5: 'input',
    6: 'mediainteraction',
    7: 'stylesheetrule',
    8: 'canvasmutation',
    9: 'font',
    10: 'log',
    12: 'drag',
    14: 'textselection'
}

MAX_PAGES_PER_SESSION_IN_TIMELINE = 10


def _get_session_url_order(session):
    url_counts = list(
        session.events
        .exclude(url='')
        .values('url')
        .annotate(event_count=Count('id'))
        .order_by('-event_count', 'url')
    )
    urls = [entry['url'] for entry in url_counts]
    title_map = get_latest_analytics_titles(session.visitor.project_id if session.visitor else None, urls)
    return url_counts, urls, title_map


@register.filter
def sum_events(pages):
    total = 0
    for page in pages:
        if hasattr(page, 'event_count'):
            total += page.event_count
        elif isinstance(page, dict) and 'event_count' in page:
            total += page['event_count']
    return total


@register.filter
def session_timeline(session):
    all_events = list(
        session.events
        .exclude(url='')
        .values_list('timestamp', 'url')
        .order_by('timestamp')
    )
    if not all_events:
        return []

    _, urls, _title_map = _get_session_url_order(session)
    start_time = min(event[0] for event in all_events).replace(second=0, microsecond=0)
    end_time = max(event[0] for event in all_events).replace(second=0, microsecond=0)

    timeline = []
    current_time = start_time
    while current_time <= end_time:
        page_counts = defaultdict(int)
        for event_time, url in all_events:
            if event_time.replace(second=0, microsecond=0) == current_time:
                page_counts[url] += 1

        if page_counts:
            max_page = max(page_counts.items(), key=lambda x: x[1])
            page_index = urls.index(max_page[0]) + 1
            timeline.append((current_time, f"P{page_index}_{max_page[1]}"))
        else:
            timeline.append((current_time, "P0_0"))

        current_time += timezone.timedelta(minutes=1)

    return timeline


@register.filter
def page_color(page_index):
    try:
        idx = int(page_index)
        if idx == 0:
            return "#BDBDBD"
        if 1 <= idx <= 10:
            return PAGE_COLORS[idx - 1]
        return "#BDBDBD"
    except Exception:
        return "#BDBDBD"


@register.filter
def max_event_count(timeline):
    max_count = 1
    for _, page_info in timeline:
        if page_info != 'P0_0':
            try:
                count = int(page_info.split('_')[1])
                if count > max_count:
                    max_count = count
            except Exception:
                pass
    return max_count


@register.filter
def page_color_class(page_index):
    try:
        idx = int(page_index)
        if idx == 0:
            return "c-light-gray"
        if 1 <= idx <= 10:
            return PALETTE_CLASSES[idx - 1]
        return "c-light-gray"
    except Exception:
        return "c-light-gray"


@register.filter
def circle_size(event_count, max_count):
    try:
        event_count = int(event_count)
        max_count = int(max_count)
        min_size = 8
        max_size = 28
        if max_count <= 0:
            return min_size
        size = min_size + (max_size - min_size) * float(event_count) / float(max_count)
        if size < min_size:
            return min_size
        if size > max_size:
            return max_size
        return round(size)
    except Exception:
        return 8


@register.filter
def nonzero_bubbles(timeline):
    return [item for item in timeline if item[1] != 'P0_0']


@register.filter
def all_bubbles(session):
    all_events = list(
        session.events
        .exclude(url='')
        .values_list('timestamp', 'url')
        .order_by('timestamp')
    )
    if not all_events:
        return []

    _, urls, _title_map = _get_session_url_order(session)
    start_time = min(event[0] for event in all_events).replace(second=0, microsecond=0)
    end_time = max(event[0] for event in all_events).replace(second=0, microsecond=0)

    timeline = []
    current_time = start_time
    while current_time <= end_time:
        for idx, url in enumerate(urls):
            count = sum(
                1
                for event_time, event_url in all_events
                if event_url == url and event_time.replace(second=0, microsecond=0) == current_time
            )
            if count > 0:
                timeline.append((current_time, idx + 1, count))
        current_time += timezone.timedelta(minutes=1)

    return list(timeline)


@register.filter
def max_event_count_bubbles(bubbles):
    try:
        return max(int(b[2]) for b in bubbles) if bubbles else 1
    except Exception:
        return 1


@register.simple_tag
def bubble_tooltip(session, page_index, minute, max_pages=3, event_count=None):
    try:
        url_counts, urls, title_map = _get_session_url_order(session)
        page_index = int(page_index)
        max_pages = int(max_pages)
        local_minute = timezone.localtime(minute)
        timestamp = local_minute.strftime('%Y-%m-%d %H:%M')
        if event_count is not None:
            event_count = int(event_count)
    except Exception:
        return f"Invalid input for tooltip (page_index={page_index}, minute={minute}, max_pages={max_pages})"

    if page_index == 0:
        if event_count == 0:
            return f"No events for others at {timestamp} (data error)"
        other_urls = urls[max_pages:]
        page_event_counts = {}
        for url in other_urls:
            count = session.events.filter(
                url=url,
                timestamp__year=local_minute.year,
                timestamp__month=local_minute.month,
                timestamp__day=local_minute.day,
                timestamp__hour=local_minute.hour,
                timestamp__minute=local_minute.minute
            ).count()
            if count > 0:
                page_event_counts[title_map.get(url, url)] = count
        page_breakdown = ", ".join(f"{count} {title}" for title, count in page_event_counts.items())
        return f"{timestamp} {event_count} events: {page_breakdown}"

    if page_index > 0 and page_index <= max_pages:
        if event_count == 0:
            return f"No events for this page at {timestamp} (data error)"
        if page_index > len(urls):
            return f"No page for index {page_index} at {timestamp}"
        url = urls[page_index - 1]
        events = session.events.filter(
            url=url,
            timestamp__year=local_minute.year,
            timestamp__month=local_minute.month,
            timestamp__day=local_minute.day,
            timestamp__hour=local_minute.hour,
            timestamp__minute=local_minute.minute
        )
        type_counts = {}
        for event in events:
            event_type = EVENT_TYPES.get(event.event_type, f'type_{event.event_type}')
            if isinstance(event_type, dict):
                mouse_type = event.data.get('data', {}).get('type')
                if mouse_type is not None:
                    event_type = event_type.get(mouse_type, 'unknown_mouse')
                else:
                    event_type = 'mouseinteraction'
            type_counts[event_type] = type_counts.get(event_type, 0) + 1
        breakdown = ", ".join(f"{count} {etype}" for etype, count in type_counts.items())
        if breakdown:
            return f"{timestamp} {event_count} events ({breakdown})"
        return f"{timestamp} {event_count} events"

    return f"No events at {timestamp} (data error)"


@register.filter
def to(start, end):
    return range(int(start), int(end) + 1)


@register.filter
def div(value, arg):
    try:
        return float(value) / float(arg) if float(arg) != 0 else 0
    except Exception:
        return 0


@register.filter
def mul(value, arg):
    try:
        return float(value) * float(arg)
    except Exception:
        return 0


@register.filter
def bubble_breakdown(breakdowns, args):
    minute, page_index = args
    return breakdowns.get((minute, page_index), "")


@register.simple_tag
def get_bubble_breakdown(bubble_breakdowns, minute, page_index):
    return bubble_breakdowns.get((minute, page_index), "")


@register.filter
def seconds_to_minutes(seconds):
    try:
        return int(seconds) // 60
    except (ValueError, TypeError):
        return 0


@register.filter
def format_in_project_timezone(dt: datetime, project_timezone: str):
    if not dt or not project_timezone:
        return dt

    try:
        tz = ZoneInfo(project_timezone)
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone=ZoneInfo("UTC"))
        local_dt = dt.astimezone(tz)
        return local_dt.strftime("%b %d, ") + local_dt.strftime("%I:%M %p").lower()
    except (KeyError, ValueError, AttributeError):
        return dt.strftime("%b %d, ") + dt.strftime("%I:%M %p").lower()
