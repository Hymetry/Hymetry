import time
from collections import defaultdict
from datetime import datetime, timedelta

from django.utils import timezone

from apps.tracker.constants import LEGEND_PAGE_COLORS
from apps.tracker.models import BubbleCache, Event, Session
from apps.tracker.url_titles import apply_titles_to_entries, get_latest_analytics_titles


class BubbleCacheManager:
    @staticmethod
    def cache_bubbles_for_session(session, visualizer=None):
        """
        Calculate and cache bubble sizes for all minutes in a session.
        If a visualizer is provided, use it; otherwise, create one.
        Returns a dictionary with detailed statistics.
        """
        from apps.tracker.session_visualizer import SessionVisualizer
        if visualizer is None:
            visualizer = SessionVisualizer(session)
        # Use the same logic as get_bubbles, but only cache
        from apps.tracker.tasks import get_project_normalization_factor
        k = get_project_normalization_factor(session.visitor.project.id)
        events_by_minute = visualizer.get_events_by_minute_sql()
        if not events_by_minute:
            return {'bubbles_created': 0, 'bubbles_updated': 0, 'bubbles_skipped': 0}
        minute_groups = defaultdict(list)
        for event_data in events_by_minute:
            minute_groups[event_data['minute']].append(event_data)
        title_map = get_latest_analytics_titles(
            session.visitor.project_id,
            [event_data.get('url', '') for event_data in events_by_minute],
        )
        
        bubbles_created = 0
        bubbles_updated = 0
        bubbles_skipped = 0

        for minute, page_events in minute_groups.items():
            dominant_page_data = max(page_events, key=lambda x: x['event_count'])
            dominant_url = dominant_page_data['url']
            # Calculate v for this minute
            v = (
                    dominant_page_data['click_count'] * 10 +
                    dominant_page_data['input_count'] * 3 +
                    dominant_page_data['mouse_count']
            )
            d = visualizer.calculate_bubble_diameter(v, k)
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
                if page_data['url'] != dominant_url and page_data['event_count'] > 0:
                    additional_pages.append(title_map.get(page_data['url'], page_data['url']))
            dominant_title = title_map.get(dominant_url, dominant_url)
            tooltip = f"{dominant_title} ({event_breakdown})"
            if additional_pages:
                tooltip += f". Additional page{'s' if len(additional_pages) > 1 else ''} this minute: {', '.join(additional_pages)}"
            
            # Check if cache entry already exists
            existing_cache = BubbleCache.objects.filter(
                url=dominant_url,
                session=session,
                timestamp=minute
            ).first()
            
            if existing_cache:
                # Check if any data has changed before updating
                new_seconds_spent = dominant_page_data.get('seconds_spent', 0)
                if (existing_cache.size != d or 
                    existing_cache.clicks != dominant_page_data['click_count'] or
                    existing_cache.mouse_moves != dominant_page_data['mouse_count'] or
                    existing_cache.key_strokes != dominant_page_data['input_count'] or
                    existing_cache.seconds_spent != new_seconds_spent):
                    
                    # Update existing cache entry only if data has changed
                    existing_cache.size = d
                    existing_cache.clicks = dominant_page_data['click_count']
                    existing_cache.mouse_moves = dominant_page_data['mouse_count']
                    existing_cache.key_strokes = dominant_page_data['input_count']
                    existing_cache.seconds_spent = new_seconds_spent
                    existing_cache.save()
                    bubbles_updated += 1
                else:
                    # No changes needed, skip update
                    bubbles_skipped += 1
            else:
                # Create new cache entry
                BubbleCache.objects.create(
                    session=session,
                    url=dominant_url,
                    timestamp=minute,
                    size=d,
                    clicks=dominant_page_data['click_count'],
                    mouse_moves=dominant_page_data['mouse_count'],
                    key_strokes=dominant_page_data['input_count'],
                    seconds_spent=dominant_page_data.get('seconds_spent', 0),
                )
                bubbles_created += 1
        
        return {
            'bubbles_created': bubbles_created,
            'bubbles_updated': bubbles_updated,
            'bubbles_skipped': bubbles_skipped
        }

    @staticmethod
    def _calculate_time_based_dominance(session_events):
        """
        Calculate time-based dominance for each minute.
        Returns dict: {minute: (dominant_page_data, total_activity)}
        """
        from collections import defaultdict

        if not session_events:
            return {}

        # Group events by minute
        minute_events = defaultdict(list)
        for event in session_events:
            minute = event['timestamp'].replace(second=0, microsecond=0)
            minute_events[minute].append(event)

        minute_dominance = {}

        for minute, events in minute_events.items():
            if not events:
                continue

            # Sort events by timestamp
            events.sort(key=lambda x: x['timestamp'])

            # Calculate time spent on each page in this minute
            page_time = defaultdict(lambda: {'seconds': 0, 'events': []})

            current_page = None
            current_page_start = None

            for i, event in enumerate(events):
                event_page = event['url']
                event_time = event['timestamp']

                # If this is a page transition or first event
                if current_page != event_page:
                    # Calculate time spent on previous page
                    if current_page is not None and current_page_start is not None:
                        time_spent = (event_time - current_page_start).total_seconds()
                        page_time[current_page]['seconds'] += time_spent

                    # Start new page
                    current_page = event_page
                    current_page_start = event_time

                # Add event to current page
                page_time[current_page]['events'].append(event)

            # Calculate time for the last page (until end of minute)
            if current_page is not None and current_page_start is not None:
                minute_end = minute + timedelta(minutes=1)
                time_spent = (minute_end - current_page_start).total_seconds()
                page_time[current_page]['seconds'] += time_spent

            # Find dominant page (most seconds spent)
            dominant_page = None
            max_seconds = 0

            for page_id, page_data in page_time.items():
                if page_data['seconds'] > max_seconds:
                    max_seconds = page_data['seconds']
                    dominant_page = page_id

            if dominant_page is None:
                continue

            # Count event types for the dominant page
            click_count = sum(1 for e in page_time[dominant_page]['events'] if e['event_type'] == 3
                              and e['data']['data'].get('source', -1) == 2)
            input_count = sum(1 for e in page_time[dominant_page]['events'] if e['event_type'] == 3
                              and e['data']['data'].get('source', -1) == 5)
            mouse_count = sum(1 for e in page_time[dominant_page]['events'] if e['event_type'] == 3
                              and e['data']['data'].get('source', -1) == 1)

            # Calculate total activity in this minute
            total_activity = len(events)

            # Create dominant page data
            dominant_page_data = {
                'url': dominant_page,
                'seconds_spent': int(page_time[dominant_page]['seconds']),
                'click_count': click_count,
                'input_count': input_count,
                'mouse_count': mouse_count
            }

            minute_dominance[minute] = (dominant_page_data, total_activity)

        return minute_dominance

    @staticmethod
    def cache_bubbles_for_project(project_id, days_back=7, force=False):
        """
        Cache bubbles for all sessions in a project using optimized algorithm.
        Uses time-based dominance (seconds spent on each page) instead of event-count-based.
        Returns a dictionary with timing and statistics.
        """
        start_time = time.time()

        # Get sessions for this project within the date range
        cutoff_date = timezone.now().date() - timedelta(days=days_back)
        sessions = Session.objects.filter(
            visitor__project_id=project_id,
            start_time__date__gte=cutoff_date
        ).order_by('-start_time')

        if not sessions:
            return {
                'success': False,
                'error': f'No sessions found for project {project_id}',
                'time': time.time() - start_time
            }

        # Check if cache exists for these sessions
        session_ids = [session.session_id for session in sessions]
        existing_cache_count = BubbleCache.objects.filter(
            session__session_id__in=session_ids
        ).count()

        # Check if any sessions are still active (not ended)
        active_sessions = Session.objects.filter(
            session_id__in=session_ids,
            ended_at__isnull=True
        ).exists()

        # Check if ALL sessions have cache entries (not just some)
        sessions_with_cache = BubbleCache.objects.filter(
            session__session_id__in=session_ids
        ).values_list('session__session_id', flat=True).distinct().count()

        # Only skip if ALL sessions have cache entries and no sessions are active
        if (sessions_with_cache == len(sessions) and 
            existing_cache_count > 0 and 
            not force and 
            not active_sessions):
            return {
                'success': True,
                'cache_entries': existing_cache_count,
                'sessions': len(sessions),
                'time': time.time() - start_time,
                'skipped': True
            }

        # Clear existing cache for this project if forcing
        if force and existing_cache_count > 0:
            deleted_count = BubbleCache.objects.filter(
                session__session_id__in=session_ids
            ).delete()[0]

        # Get normalization factor from database
        from apps.tracker.tasks import get_project_normalization_factor
        k = get_project_normalization_factor(project_id)

        # Get all events for all sessions in this project in one optimized query
        events_start = time.time()
        start_datetime = timezone.make_aware(datetime.combine(cutoff_date, datetime.min.time()))

        all_events_data = list(
            Event.objects
            .filter(
                session__in=sessions,
                timestamp__gte=start_datetime,
                data__type=3,  # rrweb incremental events
                data__data__source__in=[1, 2, 5]  # MouseMove, MouseInteraction, Input
            )
            .values(
                'timestamp',
                'url',
                'session__session_id',
                'event_type',
                'data'
            )
            .order_by('session__session_id', 'timestamp')
        )
        title_map = get_latest_analytics_titles(project_id, [event.get('url', '') for event in all_events_data])

        events_time = time.time() - events_start

        # Process each session to calculate time-based dominance
        cache_entries = []
        cache_created = 0
        cache_updated = 0

        cache_creation_start = time.time()
        for session in sessions:
            session_id = session.session_id
            session_events = [e for e in all_events_data if e['session__session_id'] == session_id]

            # at least 2 events per session
            if len(session_events) < 3:
                continue

            # Calculate time-based dominance for each minute
            minute_dominance = BubbleCacheManager._calculate_time_based_dominance(session_events)

            # Create cache entries for each minute with activity
            for minute, (dominant_page_data, total_activity) in minute_dominance.items():
                if total_activity == 0:
                    continue  # Skip minutes with no events

                # Calculate activity value based on events during this time period
                v = (
                        dominant_page_data['click_count'] * 10 +
                        dominant_page_data['input_count'] * 3 +
                        dominant_page_data['mouse_count']
                )

                # Calculate bubble size using the database-stored normalization factor
                from apps.tracker.session_visualizer import SessionVisualizer
                d = SessionVisualizer.calculate_bubble_diameter(v, k)

                # Build breakdown
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

                # Get page title
                dominant_url = dominant_page_data['url']
                dominant_title = title_map.get(dominant_url, dominant_url)

                # Build tooltip with time information
                seconds_spent = dominant_page_data['seconds_spent']
                tooltip = f"{dominant_title} ({seconds_spent}s, {event_breakdown})"

                # Check if cache entry already exists
                existing_cache = BubbleCache.objects.filter(
                    url=dominant_url,
                    session=session,
                    timestamp=minute
                ).first()
                
                if existing_cache:
                    # Check if any data has changed before updating
                    if (existing_cache.size != d or 
                        existing_cache.clicks != dominant_page_data['click_count'] or
                        existing_cache.mouse_moves != dominant_page_data['mouse_count'] or
                        existing_cache.key_strokes != dominant_page_data['input_count'] or
                        existing_cache.seconds_spent != seconds_spent):
                        
                        # Update existing cache entry only if data has changed
                        existing_cache.size = d
                        existing_cache.clicks = dominant_page_data['click_count']
                        existing_cache.mouse_moves = dominant_page_data['mouse_count']
                        existing_cache.key_strokes = dominant_page_data['input_count']
                        existing_cache.seconds_spent = seconds_spent
                        existing_cache.save()
                        cache_updated += 1
                    # If no changes needed, skip this entry
                else:
                    # Create new cache entry
                    cache_entries.append(BubbleCache(
                        session=session,
                        url=dominant_url,
                        timestamp=minute,
                        size=d,
                        clicks=dominant_page_data['click_count'],
                        mouse_moves=dominant_page_data['mouse_count'],
                        key_strokes=dominant_page_data['input_count'],
                        seconds_spent=seconds_spent
                    ))
                    cache_created += 1

        # Bulk create new cache entries (existing ones were handled individually above)
        if cache_entries:
            BubbleCache.objects.bulk_create(cache_entries)

        cache_creation_time = time.time() - cache_creation_start
        total_time = time.time() - start_time

        return {
            'success': True,
            'cache_entries': cache_created + cache_updated,
            'cache_created': cache_created,
            'cache_updated': cache_updated,
            'sessions': len(sessions),
            'events': len(all_events_data),
            'time': total_time,
            'timing': {
                'events_query': events_time,
                'cache_creation': cache_creation_time,
                'total': total_time
            },
            'normalization_factor': k
        }

    @staticmethod
    def get_cached_bubbles_for_sessions(session_ids, project_id):
        """
        Get cached bubble data for multiple sessions.
        Returns cached entries grouped by session.
        """
        cached_entries = list(
            BubbleCache.objects.filter(
                session__session_id__in=session_ids
            ).values(
                'timestamp', 'url', 'size', 'session__session_id',
                'seconds_spent', 'clicks', 'mouse_moves', 'key_strokes'
            )
        )
        cached_entries = apply_titles_to_entries(
            project_id,
            cached_entries,
            prefer_recording_titles=True,
        )

        # Group by session
        session_cache = defaultdict(list)
        for entry in cached_entries:
            session_id = entry['session__session_id']
            session_cache[session_id].append(entry)

        return session_cache, cached_entries

    @staticmethod
    def calculate_legend_from_cache(cached_entries):
        """
        Calculate page dominance legend from cached bubble data.
        Returns overall_legend_pages list.
        """
        from collections import defaultdict

        # Calculate page dominance by counting the number of minutes each page was dominant
        page_dominance_minutes = defaultdict(int)
        for entry in cached_entries:
            page_title = entry.get('page_title')
            if page_title:
                # Each cache entry represents one minute of dominance
                page_dominance_minutes[page_title] += 1

        # Sort pages by dominance minutes
        sorted_pages = sorted(page_dominance_minutes.items(), key=lambda x: x[1], reverse=True)
        top_pages = sorted_pages[:9]
        other_pages = sorted_pages[9:]

        # Calculate max dominance for percentage calculation
        max_dominance = top_pages[0][1] if top_pages else 1

        # Create overall legend data
        overall_legend_pages = []

        # Add top pages
        for i, (title, dominance_minutes) in enumerate(top_pages):
            color = LEGEND_PAGE_COLORS[i] if i < len(LEGEND_PAGE_COLORS) else LEGEND_PAGE_COLORS[0]
            percentage_width = round((dominance_minutes / max_dominance * 100) if max_dominance > 0 else 0)

            overall_legend_pages.append({
                'page_title': title,
                'color': color,
                'total_seconds': dominance_minutes * 60,  # Convert minutes to seconds for display
                'percentage_width': percentage_width,
                'is_other': False
            })

        # Add "others" group if there are other pages
        if other_pages:
            other_total_minutes = sum(dominance_minutes for _, dominance_minutes in other_pages)
            percentage_width = round((other_total_minutes / max_dominance * 100) if max_dominance > 0 else 0)

            overall_legend_pages.append({
                'page_title': 'Other',
                'color': LEGEND_PAGE_COLORS[len(LEGEND_PAGE_COLORS)-1],
                'total_seconds': other_total_minutes * 60,  # Convert minutes to seconds for display
                'percentage_width': percentage_width,
                'is_other': True
            })

        return overall_legend_pages



