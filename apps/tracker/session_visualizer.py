from collections import defaultdict, namedtuple
from datetime import timedelta

import numpy as np
from django.utils import timezone
from django.db.models import Count, Q
from django.db.models.functions import TruncMinute

from apps.tracker.models import BubbleCache, Page, Event, Session


class SessionVisualizer:
    """Class to handle session visualization logic."""

    # Constants for bubble sizes
    MIN_RADIUS = 4  # Minimum radius in pixels
    MAX_RADIUS = 14  # Maximum radius in pixels
    MAX_RADIUS_SQUARED = MAX_RADIUS * MAX_RADIUS  # Used in normalization factor calculation

    def __init__(self, session, max_pages=3, use_cache=True):
        """Initialize the visualizer with a session and max number of pages to show."""
        self.session = session
        self.max_pages = max_pages
        self.use_cache = use_cache

        # Define PageTuple for legend
        self.PageTuple = namedtuple('PageTuple', ['title', 'url', 'event_count', 'is_other', 'color_index'])

        # Get all pages with their event counts through events
        from django.db.models import Count
        all_pages = []
        # Get pages that have events in this session
        pages_with_events = session.events.values('page').distinct()
        for page_data in pages_with_events:
            page_id = page_data['page']
            page = Page.objects.get(id=page_id)
            event_count = session.events.filter(page=page).count()
            all_pages.append((page, event_count))

        # Sort pages by event count in descending order
        all_pages.sort(key=lambda x: x[1], reverse=True)

        # Split into top pages and others
        self.pages = [page for page, _ in all_pages[:max_pages]]
        self.other_pages = [page for page, _ in all_pages[max_pages:]]

        # Don't calculate normalization factor here - it will be retrieved from database when needed

    def _ensure_color_indices(self):
        """Ensure each page has a color index and save it to database."""
        for i, page in enumerate(self.pages):
            if page.color_index != i + 1:
                page.color_index = i + 1
                page.save(update_fields=["color_index"])
        for page in self.other_pages:
            if page.color_index != 0:
                page.color_index = 0
                page.save(update_fields=["color_index"])

    def _calculate_normalization_factor(self):
        """Calculate the normalization factor k based on p95 of raw activities."""
        # Get all activities for the last week
        week_ago = timezone.now() - timedelta(days=7)
        activities = []

        # Get pages that have events in this session
        pages_with_events = self.session.events.values('page').distinct()
        for page_data in pages_with_events:
            page_id = page_data['page']
            page = Page.objects.get(id=page_id)
            events = self.session.events.filter(page=page, timestamp__gte=week_ago)
            minute_activities = defaultdict(lambda: defaultdict(int))

            for event in events:
                try:
                    if hasattr(event, 'event_type'):
                        event_type = event.event_type
                        minute = event.timestamp.replace(second=0, microsecond=0)

                        # Count raw events first
                        if event_type == 2:  # Mouse interaction
                            mouse_type = event.data.get('data', {}).get('type')
                            if mouse_type == 2:  # Click
                                minute_activities[minute]['clicks'] += 1
                        elif event_type == 5:  # Input
                            minute_activities[minute]['input'] += 1
                        elif event_type == 1:  # Mouse movement
                            minute_activities[minute]['mouse'] += 1
                except Exception as e:
                    print(f"Error processing event for normalization: {e}")

            # Calculate raw activity for each minute
            for minute, counts in minute_activities.items():
                raw_activity = (
                        counts.get('clicks', 0) +
                        counts.get('input', 0) +
                        counts.get('mouse', 0)
                )
                if raw_activity > 0:
                    activities.append(raw_activity)

        if activities:
            p95 = np.percentile(activities, 95)
            # Calculate k based on the formula: k = 196π/p95
            # where 196 is max_radius_squared (14px * 14px)
            self.k = (self.MAX_RADIUS_SQUARED * np.pi) / p95 if p95 > 0 else 1000
        else:
            self.k = 1000

    @classmethod
    def calculate_bubble_size(cls, activity_value, normalization_factor):
        """Calculate bubble size based on activity value and normalization factor."""
        # Calculate radius using the formula: r = sqrt(activity_value * k / π)
        radius_squared = activity_value * normalization_factor / np.pi
        radius = np.sqrt(radius_squared)

        # Constrain radius between MIN_RADIUS and MAX_RADIUS
        radius = max(cls.MIN_RADIUS, min(cls.MAX_RADIUS, radius))

        # Convert radius to diameter for CSS
        size = int(radius * 2)
        return size

    @classmethod
    def calculate_activity_value(cls, events):
        """Calculate activity value based on event types."""
        value = 0
        for event in events:
            try:
                # Get an event type from event_type field
                event_type = event.event_type
                if event_type == 2:  # Mouse interaction
                    mouse_type = event.data.get('data', {}).get('type')
                    if mouse_type == 2:  # Click
                        value += 10
                elif event_type == 5:  # Input
                    value += 3
                elif event_type == 1:  # Mouse movement
                    value += 1
            except Exception as e:
                print(f"Error processing event: {e}")
        return value

    @classmethod
    def calculate_normalization_factor_for_session(cls, session):
        """Calculate normalization factor for a given session."""
        week_ago = timezone.now() - timedelta(days=7)
        activities = []

        # Get pages that have events in this session
        pages_with_events = session.events.values('page').distinct()
        for page_data in pages_with_events:
            page_id = page_data['page']
            page = Page.objects.get(id=page_id)
            events = session.events.filter(page=page, timestamp__gte=week_ago)
            minute_activities = defaultdict(lambda: defaultdict(int))

            for event in events:
                try:
                    if hasattr(event, 'event_type'):
                        event_type = event.event_type
                        minute = event.timestamp.replace(second=0, microsecond=0)

                        # Count raw events first
                        if event_type == 2:  # Mouse interaction
                            mouse_type = event.data.get('data', {}).get('type')
                            if mouse_type == 2:  # Click
                                minute_activities[minute]['clicks'] += 1
                        elif event_type == 5:  # Input
                            minute_activities[minute]['input'] += 1
                        elif event_type == 1:  # Mouse movement
                            minute_activities[minute]['mouse'] += 1
                except Exception as e:
                    print(f"Error processing event for normalization: {e}")

            # Calculate raw activity for each minute
            for minute, counts in minute_activities.items():
                raw_activity = (
                        counts.get('clicks', 0) +
                        counts.get('input', 0) +
                        counts.get('mouse', 0)
                )
                if raw_activity > 0:
                    activities.append(raw_activity)

        if activities:
            p95 = np.percentile(activities, 95)
            # Calculate k based on the formula: k = 196π/p95
            # where 196 is max_radius_squared (14px * 14px)
            return (cls.MAX_RADIUS_SQUARED * np.pi) / p95 if p95 > 0 else 1
        else:
            return 1

    @classmethod
    def calculate_and_cache_bubbles_for_all_pages(cls):
        """
        Calculate and cache bubble sizes for all pages in all sessions.
        Only processes finished minutes (not the current minute).
        """
        try:
            print("SessionVisualizer: Starting bubble cache calculation for all pages")
            
            # Get current minute to avoid processing incomplete data
            current_minute = timezone.now().replace(second=0, microsecond=0)
            
            # Get all sessions that have events
            sessions_with_events = Session.objects.filter(events__isnull=False).distinct()
            processed_count = 0
            bubbles_created = 0
            bubbles_updated = 0
            bubbles_skipped = 0
            
            for session in sessions_with_events:
                try:
                    # Use BubbleCacheManager for consistency
                    from apps.tracker.bubble_cache_manager import BubbleCacheManager
                    cache_stats = BubbleCacheManager.cache_bubbles_for_session(session)
                    bubbles_created += cache_stats['bubbles_created']
                    bubbles_updated += cache_stats['bubbles_updated']
                    bubbles_skipped += cache_stats['bubbles_skipped']
                    processed_count += 1
                    
                except Exception as e:
                    print(f"Error processing session {session.pk}: {e}")
                    continue
            
            print(f"SessionVisualizer: Bubble cache calculation finished - Processed {processed_count} sessions, "
                  f"Created {bubbles_created} bubbles, Updated {bubbles_updated} bubbles, Skipped {bubbles_skipped} bubbles")
            
            return {
                'processed_sessions': processed_count,
                'bubbles_created': bubbles_created,
                'bubbles_updated': bubbles_updated,
                'bubbles_skipped': bubbles_skipped
            }
            
        except Exception as e:
            print(f"Error in SessionVisualizer bubble cache calculation: {e}")
            return f"Unhandled error: {e}"

    def get_legend_pages(self):
        """Get pages for the legend."""
        legend_pages = []

        # Ensure color indices are set
        self._ensure_color_indices()

        # Calculate max events for normalization
        all_event_counts = [page.events.count() for page in self.pages]
        if self.other_pages:
            other_events = sum(page.events.count() for page in self.other_pages)
            all_event_counts.append(other_events)
        max_page_events = max(all_event_counts) if all_event_counts else 1

        # Add top pages with their color indices
        for i, page in enumerate(self.pages):
            # Count events for this page
            event_count = page.events.count()
            # Create a PageTuple for the page
            page_tuple = self.PageTuple(
                title=page.title,
                url=page.url,
                event_count=event_count,
                is_other=False,
                color_index=i + 1
            )
            legend_pages.append((i + 1, page_tuple))

        # Add others group if there are other pages
        if self.other_pages:
            total_events = sum(page.events.count() for page in self.other_pages)
            other_page = self.PageTuple(
                title='The others',
                url='',
                event_count=total_events,
                is_other=True,
                color_index=0  # 0 for others group
            )
            legend_pages.append((0, other_page))

        return legend_pages, max_page_events

    def get_bubbles_from_cache(self):
        """Get bubbles from cache if available."""
        if not self.use_cache:
            return None
        try:
            bubbles = []
            # Get all cached bubbles for all pages
            all_cached_bubbles = BubbleCache.objects.filter(
                session=self.session
            ).order_by('timestamp')
            # Group by timestamp to find dominant page for each minute
            minute_pages = defaultdict(lambda: defaultdict(list))
            for cache_entry in all_cached_bubbles:
                minute_pages[cache_entry.timestamp][cache_entry.page].append(cache_entry)
            # For each minute, find the page with the most activity (proxy for time spent)
            for timestamp, pages_data in minute_pages.items():
                max_activity = 0
                dominant_page = None
                dominant_page_entries = []
                for page, cache_entries in pages_data.items():
                    total_activity = sum(entry.size for entry in cache_entries)
                    if total_activity > max_activity:
                        max_activity = total_activity
                        dominant_page = page
                        dominant_page_entries = cache_entries
                if dominant_page and max_activity > 0:
                    # Determine page index for color
                    if dominant_page in self.pages:
                        page_idx = self.pages.index(dominant_page) + 1
                    elif dominant_page in self.other_pages:
                        page_idx = 0  # others group
                    else:
                        continue
                    # Use the cached size from the dominant page's cache entry for this minute
                    # Pick the largest size among the entries for this page and minute
                    size = max(entry.size for entry in dominant_page_entries)
                    bubbles.append((timestamp, page_idx, int(size)))
            # Sort by timestamp
            bubbles.sort(key=lambda x: x[0])
            return bubbles
        except Exception as e:
            print(f"Error getting bubbles from cache: {e}")
            return None

    def get_events_by_minute_sql(self):
        """Get events grouped by minute using SQL for better performance."""
        # Get events grouped by minute and page using SQL
        events_by_minute = (
            Event.objects
            .filter(session=self.session)
            .annotate(
                minute=TruncMinute('timestamp')
            )
            .values('minute', 'page__id', 'page___title', 'page__original_title', 'page__url')
            .annotate(
                event_count=Count('id'),
                click_count=Count('id', filter=Q(event_type=2)),
                input_count=Count('id', filter=Q(event_type=5)),
                mouse_count=Count('id', filter=Q(event_type=1))
            )
            .order_by('minute', 'page__id')
        )
        
        return events_by_minute

    @staticmethod
    def calculate_normalization_factor(project):
        """Calculate normalization factor k for a project based on p95 of all activity values in the last week."""
        from django.db import models
        from django.db.models import Case, When, IntegerField, Sum, Q
        from django.db.models.functions import TruncMinute
        
        week_ago = timezone.now() - timedelta(days=7)
        
        # Use database-level aggregation to avoid N+1 query issue
        # This calculates activity counts per minute per page directly in the database
        activity_data = (
            Event.objects
            .filter(
                session__visitor__project=project,
                timestamp__gte=week_ago,
                event_type=3  # Only incremental events (rrweb structure)
            )
            .annotate(minute=TruncMinute('timestamp'))
            .values('page_id', 'minute')
            .annotate(
                clicks=Sum(
                    Case(
                        When(
                            data__data__source=2,  # MouseInteraction
                            data__data__type=2,    # Click
                            then=1
                        ),
                        default=0,
                        output_field=IntegerField()
                    )
                ),
                inputs=Sum(
                    Case(
                        When(data__data__source=5, then=1),  # Input
                        default=0,
                        output_field=IntegerField()
                    )
                ),
                mouse=Sum(
                    Case(
                        When(data__data__source=1, then=1),  # MouseMove
                        default=0,
                        output_field=IntegerField()
                    )
                )
            )
            .filter(
                # Only include minutes with actual activity
                Q(clicks__gt=0) | Q(inputs__gt=0) | Q(mouse__gt=0)
            )
        )
        
        # Calculate activity values using the aggregated data
        activity_values = []
        for activity in activity_data:
            value = activity['clicks'] * 10 + activity['inputs'] * 3 + activity['mouse']
            if value > 0:
                activity_values.append(value)
        
        if activity_values:
            p95 = np.percentile(activity_values, 95)
            k = (196 * np.pi) / p95 if p95 > 0 else 1000
        else:
            k = 1000
        return k

    @staticmethod
    def calculate_bubble_diameter(v, k):
        """Calculate bubble diameter using the provided formula and clamp to [8, 28] px."""
        d = 2 * np.sqrt(k * v / np.pi)
        if d < 8:
            d = 8
        elif d > 28:
            d = 28
        return int(round(d))

    def get_bubbles(self):
        """Get bubbles for the session. Never writes to the cache. If cache is missing, calculate in-memory (read-only)."""
        if self.use_cache:
            bubbles = self.get_bubbles_from_cache()
            if bubbles is not None:
                return bubbles
            # If cache is missing, fall through to read-only calculation

        # Calculate bubbles in-memory (read-only, do not write to DB)
        from apps.tracker.tasks import get_project_normalization_factor
        k = get_project_normalization_factor(self.session.visitor.project.id)

        # Get events by minute
        events_by_minute = self.get_events_by_minute_sql()
        if not events_by_minute:
            return []

        # Group events by minute
        minute_groups = defaultdict(list)
        for event_data in events_by_minute:
            minute_groups[event_data['minute']].append(event_data)

        bubbles = []
        for minute, page_events in minute_groups.items():
            # Find the dominant page for this minute
            dominant_page_data = max(page_events, key=lambda x: x['event_count'])
            dominant_page = Page.objects.get(id=dominant_page_data['page__id'])

            # Calculate activity value
            v = (
                dominant_page_data['click_count'] * 10 +
                dominant_page_data['input_count'] * 3 +
                dominant_page_data['mouse_count']
            )

            # Calculate bubble size
            d = self.calculate_bubble_diameter(v, k)

            # Build event breakdown string for tooltip
            breakdown_parts = []
            if dominant_page_data['click_count'] > 0:
                breakdown_parts.append(
                    f"{dominant_page_data['click_count']} click{'s' if dominant_page_data['click_count'] > 1 else ''}")
            if dominant_page_data['mouse_count'] > 0:
                breakdown_parts.append(
                    f"{dominant_page_data['mouse_count']} mouse move{'s' if dominant_page_data['mouse_count'] > 1 else ''}")
            if dominant_page_data['input_count'] > 0:
                breakdown_parts.append(
                    f"{dominant_page_data['input_count']} input{'s' if dominant_page_data['input_count'] > 1 else ''}")
            event_breakdown = ", ".join(breakdown_parts) if breakdown_parts else "no events"

            # Find additional pages visited this minute
            additional_pages = []
            for page_data in page_events:
                if page_data['page__id'] != dominant_page_data['page__id'] and page_data['event_count'] > 0:
                    title = page_data['page___title'] or page_data['page__original_title']
                    additional_pages.append(title)

            dominant_title = dominant_page.title
            tooltip = f"{dominant_title} ({event_breakdown})"
            if additional_pages:
                tooltip += f". Additional page{'s' if len(additional_pages) > 1 else ''} this minute: {', '.join(additional_pages)}"

            bubbles.append({
                'page': dominant_page,
                'timestamp': minute,
                'size': d,
                'tooltip': tooltip,
                'event_breakdown': event_breakdown,
                'additional_pages': additional_pages
            })

        # Add gaps between bubbles
        bubbles = self._add_gaps_to_bubbles(bubbles)

        return bubbles
    
    def _add_gaps_to_bubbles(self, bubbles):
        """Add gap entries between bubbles to create proportional spacing."""
        if not bubbles:
            return bubbles
        
        # Sort bubbles by timestamp
        bubbles.sort(key=lambda x: x['timestamp'])
        
        result = []
        previous_minute = None
        
        for bubble in bubbles:
            current_minute = bubble['timestamp']
            
            # Add gap entries if there's a gap > 1 minute
            if previous_minute is not None:
                gap_minutes = (current_minute - previous_minute).total_seconds() / 60
                if gap_minutes > 1:
                    # Add gap entries for each missing minute
                    for i in range(1, int(gap_minutes)):
                        gap_minute = previous_minute + timedelta(minutes=i)
                        result.append({
                            'timestamp': gap_minute,
                            'page_idx': 0, # page_idx=0 for gaps
                            'size': 0
                        })
            
            # Add the actual bubble
            result.append(bubble)
            previous_minute = current_minute
        
        return result

    def get_bubble_breakdowns_from_cache(self):
        """Get bubble breakdowns from cache if available."""
        if not self.use_cache:
            return None
        try:
            bubble_breakdowns = {}
            # Get all cached bubbles for all pages
            all_cached_bubbles = BubbleCache.objects.filter(
                session=self.session
            ).order_by('timestamp')
            # Group by timestamp to find dominant page for each minute
            minute_pages = defaultdict(lambda: defaultdict(list))
            for cache_entry in all_cached_bubbles:
                minute_pages[cache_entry.timestamp][cache_entry.page].append(cache_entry)
            # For each minute, find the page with the most activity and create tooltip
            for timestamp, pages_data in minute_pages.items():
                max_activity = 0
                dominant_page = None
                dominant_page_entries = []
                # Use cache entry size as proxy for time spent
                for page, cache_entries in pages_data.items():
                    total_activity = sum(entry.size for entry in cache_entries)
                    if total_activity > max_activity:
                        max_activity = total_activity
                        dominant_page = page
                        dominant_page_entries = cache_entries
                if dominant_page and max_activity > 0:
                    # Determine page index for color
                    if dominant_page in self.pages:
                        page_idx = self.pages.index(dominant_page) + 1
                    elif dominant_page in self.other_pages:
                        page_idx = 0  # others group
                    else:
                        # Page not in top pages or others, skip
                        continue
                    # Create detailed tooltip for dominant page
                    minute_key = timestamp.strftime('%Y-%m-%d %H:%M')
                    # Get event breakdown from dominant page's cache entries
                    dominant_tooltips = [entry.tooltip for entry in dominant_page_entries]
                    if dominant_tooltips:
                        # Use the first tooltip as the main breakdown
                        event_breakdown = dominant_tooltips[0]
                    else:
                        event_breakdown = "no events"
                    # Find additional pages visited this minute
                    additional_pages = []
                    for page, cache_entries in pages_data.items():
                        if page != dominant_page and len(cache_entries) > 0:
                            title = page.title
                            additional_pages.append(title)
                    # Build tooltip
                    tooltip = f"{dominant_page.title} ({event_breakdown})"
                    if additional_pages:
                        tooltip += f". Additional page{'s' if len(additional_pages) > 1 else ''} this minute: {', '.join(additional_pages)}"
                    bubble_breakdowns[(minute_key, page_idx)] = tooltip
            return bubble_breakdowns
        except Exception as e:
            print(f"Error getting bubble breakdowns from cache: {e}")
            return None

    def get_bubble_breakdowns(self):
        """Get bubble breakdowns using SQL for better performance."""
        # Try to get from cache first
        if self.use_cache:
            cached_breakdowns = self.get_bubble_breakdowns_from_cache()
            if cached_breakdowns:
                return cached_breakdowns
        
        # Get events grouped by minute using SQL
        events_by_minute = self.get_events_by_minute_sql()
        
        if not events_by_minute:
            return {}
        
        bubble_breakdowns = {}
        
        # Group by minute to find dominant page and build tooltips
        minute_groups = defaultdict(list)
        for event_data in events_by_minute:
            minute_groups[event_data['minute']].append(event_data)
        
        # For each minute, find the page with most events and create tooltip
        for minute, page_events in minute_groups.items():
            # Find page with most events (dominant page)
            dominant_page_data = max(page_events, key=lambda x: x['event_count'])
            
            # Get the actual page object
            dominant_page = Page.objects.get(id=dominant_page_data['page__id'])
            
            # Determine page index for color
            if dominant_page in self.pages:
                page_idx = self.pages.index(dominant_page) + 1
            elif dominant_page in self.other_pages:
                page_idx = 0  # others group
            else:
                # Page not in top pages or others, skip
                continue
            
            # Build event breakdown string
            breakdown_parts = []
            if dominant_page_data['click_count'] > 0:
                breakdown_parts.append(f"{dominant_page_data['click_count']} click{'s' if dominant_page_data['click_count'] > 1 else ''}")
            if dominant_page_data['mouse_count'] > 0:
                breakdown_parts.append(f"{dominant_page_data['mouse_count']} mouse move{'s' if dominant_page_data['mouse_count'] > 1 else ''}")
            if dominant_page_data['input_count'] > 0:
                breakdown_parts.append(f"{dominant_page_data['input_count']} input{'s' if dominant_page_data['input_count'] > 1 else ''}")
            
            event_breakdown = ", ".join(breakdown_parts) if breakdown_parts else "no events"
            
            # Find additional pages visited this minute
            additional_pages = []
            for page_data in page_events:
                if page_data['page__id'] != dominant_page_data['page__id'] and page_data['event_count'] > 0:
                    title = page_data['page___title'] or page_data['page__original_title']
                    additional_pages.append(title)
            
            # Build tooltip
            minute_key = minute.strftime('%Y-%m-%d %H:%M')
            dominant_title = dominant_page_data['page___title'] or dominant_page_data['page__original_title']
            tooltip = f"{dominant_title} ({event_breakdown})"
            if additional_pages:
                tooltip += f". Additional page{'s' if len(additional_pages) > 1 else ''} this minute: {', '.join(additional_pages)}"
            
            bubble_breakdowns[(minute_key, page_idx)] = tooltip
        
        return bubble_breakdowns
