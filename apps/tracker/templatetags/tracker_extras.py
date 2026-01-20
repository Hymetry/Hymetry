from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from django import template
from django.utils import timezone

from apps.tracker.models import Page

register = template.Library()
PAGE_COLORS = [
    "#4269D0",  # blue
    "#EFB118",  # yellow
    "#FF725C",  # red
    "#6CC5B0",  # light-green
    "#3CA951",  # green
    "#FF8AB7",  # pink
    "#A463F2",  # purple
    "#97BBF5",  # light-blue
    "#9C6B4E",  # brown
    "#E5E7EB",  # gray
]

PALETTE_CLASSES = [
    "c-blue", "c-yellow", "c-red", "c-light-green", "c-green",
    "c-pink", "c-purple", "c-light-blue", "c-brown", "c-gray"
]

# Event type mapping based on rrweb's IncrementalSource enum
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


@register.filter
def sum_events(pages):
    """Calculate total events across all pages, supporting pseudo-pages with event_count."""
    total = 0
    for page in pages:
        if hasattr(page, 'events'):
            total += page.events.count()
        elif hasattr(page, 'event_count'):
            total += page.event_count
    return total


@register.filter
def session_timeline(session):
    """Generate a timeline of page numbers and event counts for each minute."""
    # Get all events for all pages in the session
    all_events = []
    # Get pages that have events in this session
    pages_with_events = session.events.values('page').distinct()
    for page_data in pages_with_events:
        page_id = page_data['page']
        page = Page.objects.get(id=page_id)
        events = session.events.filter(page=page).order_by('timestamp')
        for event in events:
            all_events.append((event.timestamp, page))

    if not all_events:
        return []

    # Find the time range
    start_time = min(event[0] for event in all_events)
    end_time = max(event[0] for event in all_events)

    # Create a timeline with all minutes
    timeline = []
    current_time = start_time.replace(second=0, microsecond=0)
    end_time = end_time.replace(second=0, microsecond=0)

    # Get all pages for this session
    pages = []
    for page_data in pages_with_events:
        page_id = page_data['page']
        page = Page.objects.get(id=page_id)
        pages.append(page)

    while current_time <= end_time:
        # Count events per page for this minute
        page_counts = defaultdict(int)
        for event_time, page in all_events:
            event_time = event_time.replace(second=0, microsecond=0)
            if event_time == current_time:
                page_counts[page] += 1

        # Find page with most events
        if page_counts:
            max_page = max(page_counts.items(), key=lambda x: x[1])
            # Get 1-based index of the page
            page_index = pages.index(max_page[0]) + 1
            timeline.append((current_time, f"P{page_index}_{max_page[1]}"))
        else:
            timeline.append((current_time, "P0_0"))

        # Move to next minute
        current_time += timezone.timedelta(minutes=1)

    return timeline


@register.filter
def page_color(page_index):
    try:
        idx = int(page_index)
        if idx == 0:
            return "#BDBDBD"  # grey for others
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
        # Ensure both are int
        event_count = int(event_count)
        max_count = int(max_count)
        min_size = 8
        max_size = 28
        if max_count <= 0:
            return min_size
        # Debug print
        # print(f"event_count={event_count}, max_count={max_count}")
        size = min_size + (max_size - min_size) * float(event_count) / float(max_count)
        if size < min_size:
            return min_size
        if size > max_size:
            return max_size
        return round(size)
    except Exception as e:
        # print(f"circle_size error: {e}")
        return 8


@register.filter
def nonzero_bubbles(timeline):
    """Return only timeline entries with nonzero events (not 'P0_0')."""
    return [item for item in timeline if item[1] != 'P0_0']


@register.filter
def all_bubbles(session):
    """Return (minute, page_index, event_count) for every page/minute with events."""
    all_events = []
    # Get pages that have events in this session
    pages_with_events = session.events.values('page').distinct()
    for page_data in pages_with_events:
        page_id = page_data['page']
        page = Page.objects.get(id=page_id)
        events = session.events.filter(page=page).order_by('timestamp')
        for event in events:
            all_events.append((event.timestamp, page))
    if not all_events:
        return []
    start_time = min(event[0] for event in all_events)
    end_time = max(event[0] for event in all_events)
    timeline = []
    current_time = start_time.replace(second=0, microsecond=0)
    end_time = end_time.replace(second=0, microsecond=0)

    # Get all pages for this session
    pages = []
    for page_data in pages_with_events:
        page_id = page_data['page']
        page = Page.objects.get(id=page_id)
        pages.append(page)

    while current_time <= end_time:
        for idx, page in enumerate(pages):
            count = sum(1 for event_time, p in all_events if
                        p == page and event_time.replace(second=0, microsecond=0) == current_time)
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
    """
    Returns a tooltip string for the bubble at (page_index, minute), using the provided event_count as the total.
    Handles both top N pages and the 'others' group, with breakdown by page for 'others'.
    Always returns a non-empty, meaningful tooltip for every bubble.
    """
    from django.db.models import Count
    try:
        # Get pages that have events in this session, ordered by event count
        pages_with_events = session.events.values('page').annotate(event_count=Count('id')).order_by('-event_count')
        pages = []
        for page_data in pages_with_events:
            page_id = page_data['page']
            page = Page.objects.get(id=page_id)
            pages.append(page)

        page_index = int(page_index)
        max_pages = int(max_pages)
        local_minute = timezone.localtime(minute)
        timestamp = local_minute.strftime('%Y-%m-%d %H:%M')
        if event_count is not None:
            event_count = int(event_count)
    except Exception as e:
        return f"Invalid input for tooltip (page_index={page_index}, minute={minute}, max_pages={max_pages})"
    # Special case: page_index == 0 means 'others' group
    if page_index == 0:
        if event_count == 0:
            return f"No events for others at {timestamp} (data error)"
        other_pages = pages[max_pages:]
        all_events = []
        page_event_counts = {}
        for page in other_pages:
            events = session.events.filter(
                page=page,
                timestamp__year=local_minute.year,
                timestamp__month=local_minute.month,
                timestamp__day=local_minute.day,
                timestamp__hour=local_minute.hour,
                timestamp__minute=local_minute.minute
            )
            count = events.count()
            if count > 0:
                page_event_counts[page.title] = count
                all_events.extend(list(events))
        page_breakdown = ", ".join(f"{count} {title}" for title, count in page_event_counts.items())
        return f"{timestamp} {event_count} events: {page_breakdown}"
    # Top N pages
    if page_index > 0 and page_index <= max_pages:
        if event_count == 0:
            return f"No events for this page at {timestamp} (data error)"
        if page_index > len(pages):
            return f"No page for index {page_index} at {timestamp}"
        page = pages[page_index - 1]
        events = session.events.filter(
            page=page,
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
        else:
            return f"{timestamp} {event_count} events"
    # Fallback for any other case
    return f"No events at {timestamp} (data error)"


@register.filter
def to(start, end):
    """Return a range from start to end inclusive (for dropdowns)."""
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
    """Look up a breakdown by (minute, page_index) tuple."""
    minute, page_index = args
    return breakdowns.get((minute, page_index), "")


@register.simple_tag
def get_bubble_breakdown(bubble_breakdowns, minute, page_index):
    return bubble_breakdowns.get((minute, page_index), "")


@register.filter
def seconds_to_minutes(seconds):
    """Convert seconds to minutes and return as integer."""
    try:
        return int(seconds) // 60
    except (ValueError, TypeError):
        return 0


@register.filter
def format_in_project_timezone(dt: datetime, project_timezone: str):
    """Convert a datetime to the project's timezone and format it."""
    if not dt or not project_timezone:
        return dt

    try:
        # Get the timezone object
        tz = ZoneInfo(project_timezone)

        # If the datetime is naive, assume it's UTC
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone=ZoneInfo("UTC"))

        # Convert to project timezone
        local_dt = dt.astimezone(tz)

        # Format the datetime (example: "Sep 30, 01:23 pm")
        return local_dt.strftime("%b %d, ") + local_dt.strftime("%I:%M %p").lower()

    except (KeyError, ValueError, AttributeError):
        # Fallback to original datetime formatting
        return dt.strftime("%b %d, ") + dt.strftime("%I:%M %p").lower()
