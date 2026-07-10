from collections import defaultdict, namedtuple
from datetime import timedelta

import numpy as np
from django.db.models import Case, Count, IntegerField, Q, Sum, When
from django.db.models.functions import TruncMinute
from django.utils import timezone

from apps.tracker.models import BubbleCache, Event, Session
from apps.tracker.url_titles import get_latest_analytics_titles


class SessionVisualizer:
    """Class to handle session visualization logic."""

    MIN_RADIUS = 4
    MAX_RADIUS = 14
    MAX_RADIUS_SQUARED = MAX_RADIUS * MAX_RADIUS

    def __init__(self, session, max_pages=3, use_cache=True):
        self.session = session
        self.max_pages = max_pages
        self.use_cache = use_cache
        self.PageTuple = namedtuple('PageTuple', ['title', 'url', 'event_count', 'is_other', 'color_index'])

        page_counts = list(
            session.events
            .exclude(url='')
            .values('url')
            .annotate(event_count=Count('id'))
            .order_by('-event_count', 'url')
        )
        urls = [entry['url'] for entry in page_counts]
        project_id = session.visitor.project_id if session.visitor else None
        self.url_title_map = get_latest_analytics_titles(project_id, urls)
        self.page_event_counts = {entry['url']: entry['event_count'] for entry in page_counts}
        self.pages = urls[:max_pages]
        self.other_pages = urls[max_pages:]

    def _iter_session_activity_rows(self, session, week_ago):
        return (
            session.events
            .filter(timestamp__gte=week_ago, event_type=3)
            .annotate(minute=TruncMinute('timestamp'))
            .values('url', 'minute')
            .annotate(
                clicks=Sum(
                    Case(
                        When(data__data__source=2, data__data__type=2, then=1),
                        default=0,
                        output_field=IntegerField(),
                    )
                ),
                inputs=Sum(
                    Case(
                        When(data__data__source=5, then=1),
                        default=0,
                        output_field=IntegerField(),
                    )
                ),
                mouse=Sum(
                    Case(
                        When(data__data__source=1, then=1),
                        default=0,
                        output_field=IntegerField(),
                    )
                ),
            )
            .filter(Q(clicks__gt=0) | Q(inputs__gt=0) | Q(mouse__gt=0))
        )

    def _calculate_normalization_factor(self):
        week_ago = timezone.now() - timedelta(days=7)
        activities = []

        for row in self._iter_session_activity_rows(self.session, week_ago):
            raw_activity = (row['clicks'] or 0) + (row['inputs'] or 0) + (row['mouse'] or 0)
            if raw_activity > 0:
                activities.append(raw_activity)

        if activities:
            p95 = np.percentile(activities, 95)
            self.k = (self.MAX_RADIUS_SQUARED * np.pi) / p95 if p95 > 0 else 1000
        else:
            self.k = 1000

    @classmethod
    def calculate_activity_value(cls, events):
        value = 0
        for event in events:
            try:
                event_type = event.event_type
                if event_type == 2:
                    mouse_type = event.data.get('data', {}).get('type')
                    if mouse_type == 2:
                        value += 10
                elif event_type == 5:
                    value += 3
                elif event_type == 1:
                    value += 1
            except Exception as e:
                print(f"Error processing event: {e}")
        return value

    @classmethod
    def calculate_normalization_factor_for_session(cls, session):
        week_ago = timezone.now() - timedelta(days=7)
        activities = []

        visualizer = cls(session, use_cache=False)
        for row in visualizer._iter_session_activity_rows(session, week_ago):
            raw_activity = (row['clicks'] or 0) + (row['inputs'] or 0) + (row['mouse'] or 0)
            if raw_activity > 0:
                activities.append(raw_activity)

        if activities:
            p95 = np.percentile(activities, 95)
            return (cls.MAX_RADIUS_SQUARED * np.pi) / p95 if p95 > 0 else 1
        return 1

    @classmethod
    def calculate_and_cache_bubbles_for_all_pages(cls):
        try:
            print("SessionVisualizer: Starting bubble cache calculation for all pages")

            sessions_with_events = Session.objects.filter(events__isnull=False).distinct()
            processed_count = 0
            bubbles_created = 0
            bubbles_updated = 0
            bubbles_skipped = 0

            for session in sessions_with_events:
                try:
                    from apps.tracker.bubble_cache_manager import BubbleCacheManager
                    cache_stats = BubbleCacheManager.cache_bubbles_for_session(session)
                    bubbles_created += cache_stats['bubbles_created']
                    bubbles_updated += cache_stats['bubbles_updated']
                    bubbles_skipped += cache_stats['bubbles_skipped']
                    processed_count += 1
                except Exception as e:
                    print(f"Error processing session {session.pk}: {e}")
                    continue

            print(
                "SessionVisualizer: Bubble cache calculation finished - "
                f"Processed {processed_count} sessions, "
                f"Created {bubbles_created} bubbles, "
                f"Updated {bubbles_updated} bubbles, "
                f"Skipped {bubbles_skipped} bubbles"
            )

            return {
                'processed_sessions': processed_count,
                'bubbles_created': bubbles_created,
                'bubbles_updated': bubbles_updated,
                'bubbles_skipped': bubbles_skipped,
            }

        except Exception as e:
            print(f"Error in SessionVisualizer bubble cache calculation: {e}")
            return f"Unhandled error: {e}"

    def get_legend_pages(self):
        legend_pages = []

        all_event_counts = [self.page_event_counts.get(url, 0) for url in self.pages]
        if self.other_pages:
            all_event_counts.append(sum(self.page_event_counts.get(url, 0) for url in self.other_pages))
        max_page_events = max(all_event_counts) if all_event_counts else 1

        for i, url in enumerate(self.pages):
            event_count = self.page_event_counts.get(url, 0)
            page_tuple = self.PageTuple(
                title=self.url_title_map.get(url, url),
                url=url,
                event_count=event_count,
                is_other=False,
                color_index=i + 1,
            )
            legend_pages.append((i + 1, page_tuple))

        if self.other_pages:
            total_events = sum(self.page_event_counts.get(url, 0) for url in self.other_pages)
            other_page = self.PageTuple(
                title='The others',
                url='',
                event_count=total_events,
                is_other=True,
                color_index=0,
            )
            legend_pages.append((0, other_page))

        return legend_pages, max_page_events

    def _page_index_for_url(self, url):
        if url in self.pages:
            return self.pages.index(url) + 1
        if url in self.other_pages:
            return 0
        return None

    def get_bubbles_from_cache(self):
        if not self.use_cache:
            return None

        try:
            bubbles = []
            all_cached_bubbles = BubbleCache.objects.filter(session=self.session).values(
                'timestamp', 'url', 'size'
            ).order_by('timestamp')

            minute_pages = defaultdict(lambda: defaultdict(list))
            for cache_entry in all_cached_bubbles:
                minute_pages[cache_entry['timestamp']][cache_entry['url']].append(cache_entry)

            for timestamp, pages_data in minute_pages.items():
                max_activity = 0
                dominant_url = None
                dominant_entries = []
                for url, cache_entries in pages_data.items():
                    total_activity = sum(entry['size'] for entry in cache_entries)
                    if total_activity > max_activity:
                        max_activity = total_activity
                        dominant_url = url
                        dominant_entries = cache_entries

                if dominant_url and max_activity > 0:
                    page_idx = self._page_index_for_url(dominant_url)
                    if page_idx is None:
                        continue
                    size = max(entry['size'] for entry in dominant_entries)
                    bubbles.append((timestamp, page_idx, int(size)))

            bubbles.sort(key=lambda x: x[0])
            return bubbles
        except Exception as e:
            print(f"Error getting bubbles from cache: {e}")
            return None

    def get_events_by_minute_sql(self):
        return (
            Event.objects
            .filter(session=self.session)
            .annotate(minute=TruncMinute('timestamp'))
            .values('minute', 'url')
            .annotate(
                event_count=Count('id'),
                click_count=Count('id', filter=Q(event_type=2)),
                input_count=Count('id', filter=Q(event_type=5)),
                mouse_count=Count('id', filter=Q(event_type=1)),
            )
            .order_by('minute', 'url')
        )

    @staticmethod
    def calculate_normalization_factor(project):
        week_ago = timezone.now() - timedelta(days=7)
        activity_data = (
            Event.objects
            .filter(
                session__visitor__project=project,
                timestamp__gte=week_ago,
                event_type=3,
            )
            .annotate(minute=TruncMinute('timestamp'))
            .values('url', 'minute')
            .annotate(
                clicks=Sum(
                    Case(
                        When(data__data__source=2, data__data__type=2, then=1),
                        default=0,
                        output_field=IntegerField(),
                    )
                ),
                inputs=Sum(
                    Case(
                        When(data__data__source=5, then=1),
                        default=0,
                        output_field=IntegerField(),
                    )
                ),
                mouse=Sum(
                    Case(
                        When(data__data__source=1, then=1),
                        default=0,
                        output_field=IntegerField(),
                    )
                ),
            )
            .filter(Q(clicks__gt=0) | Q(inputs__gt=0) | Q(mouse__gt=0))
        )

        activity_values = []
        for activity in activity_data:
            value = (activity['clicks'] or 0) * 10 + (activity['inputs'] or 0) * 3 + (activity['mouse'] or 0)
            if value > 0:
                activity_values.append(value)

        if activity_values:
            p95 = np.percentile(activity_values, 95)
            return (196 * np.pi) / p95 if p95 > 0 else 1000
        return 1000

    @staticmethod
    def calculate_normalization_factors_for_projects(project_ids=None):
        week_ago = timezone.now() - timedelta(days=7)

        project_id_list = None
        if project_ids is not None:
            project_id_list = list(project_ids)
            if not project_id_list:
                return {}

        qs = Event.objects.filter(
            timestamp__gte=week_ago,
            event_type=3,
        )
        if project_id_list is not None:
            qs = qs.filter(session__visitor__project_id__in=project_id_list)

        activity_rows = (
            qs.annotate(minute=TruncMinute('timestamp'))
            .values('session__visitor__project_id', 'url', 'minute')
            .annotate(
                clicks=Sum(
                    Case(
                        When(data__data__source=2, data__data__type=2, then=1),
                        default=0,
                        output_field=IntegerField(),
                    )
                ),
                inputs=Sum(
                    Case(
                        When(data__data__source=5, then=1),
                        default=0,
                        output_field=IntegerField(),
                    )
                ),
                mouse=Sum(
                    Case(
                        When(data__data__source=1, then=1),
                        default=0,
                        output_field=IntegerField(),
                    )
                ),
            )
            .filter(Q(clicks__gt=0) | Q(inputs__gt=0) | Q(mouse__gt=0))
        )

        activity_values_by_project = defaultdict(list)
        for row in activity_rows.iterator(chunk_size=2000):
            project_id = row['session__visitor__project_id']
            clicks = row['clicks'] or 0
            inputs = row['inputs'] or 0
            mouse = row['mouse'] or 0
            value = clicks * 10 + inputs * 3 + mouse
            if value > 0:
                activity_values_by_project[project_id].append(value)

        result = {}
        project_iter = project_id_list if project_id_list is not None else activity_values_by_project.keys()
        for project_id in project_iter:
            values = activity_values_by_project.get(project_id, [])
            if values:
                p95 = np.percentile(values, 95)
                k = (196 * np.pi) / p95 if p95 > 0 else 1000
            else:
                k = 1000
            result[project_id] = k

        return result

    @staticmethod
    def calculate_bubble_diameter(v, k):
        d = 2 * np.sqrt(k * v / np.pi)
        if d < 8:
            d = 8
        elif d > 28:
            d = 28
        return int(round(d))

    def _build_event_breakdown(self, event_data):
        breakdown_parts = []
        if event_data['click_count'] > 0:
            breakdown_parts.append(f"{event_data['click_count']} click{'s' if event_data['click_count'] > 1 else ''}")
        if event_data['mouse_count'] > 0:
            breakdown_parts.append(
                f"{event_data['mouse_count']} mouse move{'s' if event_data['mouse_count'] > 1 else ''}"
            )
        if event_data['input_count'] > 0:
            breakdown_parts.append(f"{event_data['input_count']} input{'s' if event_data['input_count'] > 1 else ''}")
        return ", ".join(breakdown_parts) if breakdown_parts else "no events"

    def get_bubbles(self):
        if self.use_cache:
            bubbles = self.get_bubbles_from_cache()
            if bubbles is not None:
                return bubbles

        from apps.tracker.tasks import get_project_normalization_factor

        k = get_project_normalization_factor(self.session.visitor.project.id)
        events_by_minute = self.get_events_by_minute_sql()
        if not events_by_minute:
            return []

        minute_groups = defaultdict(list)
        for event_data in events_by_minute:
            minute_groups[event_data['minute']].append(event_data)

        bubbles = []
        for minute, page_events in minute_groups.items():
            dominant_page_data = max(page_events, key=lambda x: x['event_count'])
            dominant_url = dominant_page_data['url']
            page_idx = self._page_index_for_url(dominant_url)
            if page_idx is None:
                continue

            v = (
                dominant_page_data['click_count'] * 10
                + dominant_page_data['input_count'] * 3
                + dominant_page_data['mouse_count']
            )
            d = self.calculate_bubble_diameter(v, k)
            event_breakdown = self._build_event_breakdown(dominant_page_data)

            additional_pages = []
            for page_data in page_events:
                if page_data['url'] != dominant_url and page_data['event_count'] > 0:
                    additional_pages.append(self.url_title_map.get(page_data['url'], page_data['url']))

            dominant_title = self.url_title_map.get(dominant_url, dominant_url)
            tooltip = f"{dominant_title} ({event_breakdown})"
            if additional_pages:
                tooltip += (
                    f". Additional page{'s' if len(additional_pages) > 1 else ''} this minute: "
                    f"{', '.join(additional_pages)}"
                )

            bubbles.append({
                'page': dominant_url,
                'timestamp': minute,
                'size': d,
                'tooltip': tooltip,
                'event_breakdown': event_breakdown,
                'additional_pages': additional_pages,
            })

        return self._add_gaps_to_bubbles(bubbles)

    def _add_gaps_to_bubbles(self, bubbles):
        if not bubbles:
            return bubbles

        bubbles.sort(key=lambda x: x['timestamp'])
        result = []
        previous_minute = None

        for bubble in bubbles:
            current_minute = bubble['timestamp']
            if previous_minute is not None:
                gap_minutes = (current_minute - previous_minute).total_seconds() / 60
                if gap_minutes > 1:
                    for i in range(1, int(gap_minutes)):
                        gap_minute = previous_minute + timedelta(minutes=i)
                        result.append({
                            'timestamp': gap_minute,
                            'page_idx': 0,
                            'size': 0,
                        })

            result.append(bubble)
            previous_minute = current_minute

        return result

    def get_bubble_breakdowns_from_cache(self):
        if not self.use_cache:
            return None

        try:
            bubble_breakdowns = {}
            all_cached_bubbles = BubbleCache.objects.filter(session=self.session).values(
                'timestamp',
                'url',
                'size',
                'clicks',
                'mouse_moves',
                'key_strokes',
            ).order_by('timestamp')

            minute_pages = defaultdict(lambda: defaultdict(list))
            for cache_entry in all_cached_bubbles:
                minute_pages[cache_entry['timestamp']][cache_entry['url']].append(cache_entry)

            for timestamp, pages_data in minute_pages.items():
                max_activity = 0
                dominant_url = None
                dominant_entries = []
                for url, cache_entries in pages_data.items():
                    total_activity = sum(entry['size'] for entry in cache_entries)
                    if total_activity > max_activity:
                        max_activity = total_activity
                        dominant_url = url
                        dominant_entries = cache_entries

                if dominant_url and max_activity > 0:
                    page_idx = self._page_index_for_url(dominant_url)
                    if page_idx is None:
                        continue

                    dominant_entry = max(dominant_entries, key=lambda entry: entry['size'])
                    breakdown_parts = []
                    if dominant_entry['clicks'] > 0:
                        breakdown_parts.append(
                            f"{dominant_entry['clicks']} click{'s' if dominant_entry['clicks'] > 1 else ''}"
                        )
                    if dominant_entry['mouse_moves'] > 0:
                        breakdown_parts.append(
                            f"{dominant_entry['mouse_moves']} mouse move"
                            f"{'s' if dominant_entry['mouse_moves'] > 1 else ''}"
                        )
                    if dominant_entry['key_strokes'] > 0:
                        breakdown_parts.append(
                            f"{dominant_entry['key_strokes']} input{'s' if dominant_entry['key_strokes'] > 1 else ''}"
                        )
                    event_breakdown = ", ".join(breakdown_parts) if breakdown_parts else "no events"

                    additional_pages = []
                    for url, cache_entries in pages_data.items():
                        if url != dominant_url and cache_entries:
                            additional_pages.append(self.url_title_map.get(url, url))

                    tooltip = f"{self.url_title_map.get(dominant_url, dominant_url)} ({event_breakdown})"
                    if additional_pages:
                        tooltip += (
                            f". Additional page{'s' if len(additional_pages) > 1 else ''} this minute: "
                            f"{', '.join(additional_pages)}"
                        )

                    minute_key = timestamp.strftime('%Y-%m-%d %H:%M')
                    bubble_breakdowns[(minute_key, page_idx)] = tooltip

            return bubble_breakdowns
        except Exception as e:
            print(f"Error getting bubble breakdowns from cache: {e}")
            return None

    def get_bubble_breakdowns(self):
        if self.use_cache:
            cached_breakdowns = self.get_bubble_breakdowns_from_cache()
            if cached_breakdowns:
                return cached_breakdowns

        events_by_minute = self.get_events_by_minute_sql()
        if not events_by_minute:
            return {}

        bubble_breakdowns = {}
        minute_groups = defaultdict(list)
        for event_data in events_by_minute:
            minute_groups[event_data['minute']].append(event_data)

        for minute, page_events in minute_groups.items():
            dominant_page_data = max(page_events, key=lambda x: x['event_count'])
            dominant_url = dominant_page_data['url']
            page_idx = self._page_index_for_url(dominant_url)
            if page_idx is None:
                continue

            event_breakdown = self._build_event_breakdown(dominant_page_data)
            additional_pages = []
            for page_data in page_events:
                if page_data['url'] != dominant_url and page_data['event_count'] > 0:
                    additional_pages.append(self.url_title_map.get(page_data['url'], page_data['url']))

            minute_key = minute.strftime('%Y-%m-%d %H:%M')
            dominant_title = self.url_title_map.get(dominant_url, dominant_url)
            tooltip = f"{dominant_title} ({event_breakdown})"
            if additional_pages:
                tooltip += (
                    f". Additional page{'s' if len(additional_pages) > 1 else ''} this minute: "
                    f"{', '.join(additional_pages)}"
                )

            bubble_breakdowns[(minute_key, page_idx)] = tooltip

        return bubble_breakdowns
