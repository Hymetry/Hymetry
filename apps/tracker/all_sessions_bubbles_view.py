from datetime import date, datetime, time, timedelta, timezone as datetime_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.shortcuts import render

from apps.projects.demo import DEMO_PROJECT_DISPLAY_NAME
from apps.tracker.bubble_cache_manager import BubbleCacheManager
from apps.tracker.constants import LEGEND_PAGE_COLORS
from apps.tracker.models import Session


class AllSessionsBubblesView:
    """Handles the display of all sessions with bubble visualization."""

    def __init__(self, request, project_id, *, is_demo_view=False):
        self.request = request
        self.project_id = project_id
        self.is_demo_view = is_demo_view
        self.selected_date = self._parse_selected_date()
        self.page = self._parse_page_number()
        self.rows_per_page = getattr(settings, 'ROWS_PER_PAGE', 100)
        self.offset = (self.page - 1) * self.rows_per_page
        self.limit = self.offset + self.rows_per_page
        self.days_back = 30
        self.user_projects = self._get_user_projects()
        self.selected_project_id = project_id
        self.project_timezone = self._get_project_timezone()

    def _get_user_projects(self):
        """Get all projects the user is a member of."""
        if not getattr(self.request.user, 'is_authenticated', False):
            return []
        from apps.projects.access import active_workspace_memberships
        from apps.projects.models import Project

        workspace_ids = active_workspace_memberships().filter(user=self.request.user).values_list('workspace_id', flat=True)
        return Project.active.filter(workspace_id__in=workspace_ids).values_list('id', flat=True)

    def _get_user_projects_with_details(self):
        """Get all projects the user is a member of with full details."""
        if not getattr(self.request.user, 'is_authenticated', False):
            return []
        from apps.projects.access import active_workspace_memberships
        from apps.projects.models import Project

        workspace_ids = active_workspace_memberships().filter(user=self.request.user).values_list('workspace_id', flat=True)
        return Project.active.filter(workspace_id__in=workspace_ids).select_related('workspace').order_by('name')

    def _get_project_timezone(self):
        """Get the timezone for the current project."""
        from apps.projects.models import Project
        try:
            project = Project.active.get(id=self.project_id)
            return project.timezone
        except Project.DoesNotExist:
            return 'UTC'  # Fallback to UTC if project not found

    def _parse_selected_date(self):
        """Parse the selected date from request parameters."""
        selected_date = self.request.GET.get('date')
        if selected_date:
            try:
                return date.fromisoformat(selected_date)
            except ValueError:
                return date.today()
        return date.today()

    def _parse_page_number(self):
        """Parse the page number from request parameters."""
        try:
            page = int(self.request.GET.get('page', 1))
            return max(1, page)
        except (TypeError, ValueError):
            return 1

    def _project_zoneinfo(self):
        try:
            return ZoneInfo(self.project_timezone or 'UTC')
        except ZoneInfoNotFoundError:
            return ZoneInfo('UTC')

    def _local_day_bounds_utc(self, start_day, end_day=None):
        """Return UTC bounds for inclusive local date range."""
        end_day = end_day or start_day
        project_tz = self._project_zoneinfo()
        start_bound = datetime.combine(start_day, time.min, tzinfo=project_tz).astimezone(datetime_timezone.utc)
        end_bound = datetime.combine(end_day + timedelta(days=1), time.min, tzinfo=project_tz).astimezone(
            datetime_timezone.utc
        )
        return start_bound, end_bound

    def _build_day_navigator(self):
        """Build the day navigator with session counts for the last 30 days, only counting sessions with cached bubble data."""
        end_day = date.today()
        start_day = end_day - timedelta(days=self.days_back - 1)

        # Filter by selected project if specified
        project_filter = self.user_projects
        if self.selected_project_id:
            project_filter = [self.selected_project_id]

        # Use optimized raw SQL for better performance
        from django.db import connection

        # Convert project_filter to SQL-safe format
        if len(project_filter) == 1:
            project_clause = f"= {project_filter[0]}"
        else:
            project_ids = ','.join(str(pid) for pid in project_filter)
            project_clause = f"IN ({project_ids})"

        start_bound, end_bound = self._local_day_bounds_utc(start_day, end_day)

        with connection.cursor() as cursor:
            cursor.execute(f"""
                SELECT
                    DATE(s.start_time AT TIME ZONE %s) AS day,
                    COUNT(*) AS count
                FROM tracker_session s
                INNER JOIN tracker_visitor v ON s.visitor_id = v.visitor_id
                WHERE s.start_time >= %s
                  AND s.start_time < %s
                  AND v.project_id {project_clause}
                  AND EXISTS (
                      SELECT 1 FROM tracker_bubblecache bc
                      WHERE bc.session_id = s.session_id
                      LIMIT 1
                  )
                GROUP BY DATE(s.start_time AT TIME ZONE %s)
                ORDER BY day
            """, [self.project_timezone, start_bound, end_bound, self.project_timezone])

            # Convert to dictionary for faster lookup
            day_counts = {row[0]: row[1] for row in cursor.fetchall()}

        # Build a list for all days in range, fill 0 if missing
        day_navigator = []
        for i in range(self.days_back):
            d = start_day + timedelta(days=i)
            day_navigator.append({
                'date': d,
                'count': day_counts.get(d, 0),
                'is_selected': d == self.selected_date,
            })

        self._normalize_day_navigator_heights(day_navigator)
        return day_navigator

    def _format_relative_day_label(self, target_date):
        if not target_date:
            return ''

        today = date.today()
        delta_days = (target_date - today).days
        if delta_days == 0:
            return 'Today'
        if delta_days == -1:
            return 'Yesterday'
        if delta_days < 0:
            return f'{abs(delta_days)} days ago'
        return ''

    def _get_selected_date_day_delta(self):
        """Return whole-day delta between today and selected_date (non-negative)."""
        if not self.selected_date:
            return 0
        return max(0, (date.today() - self.selected_date).days)

    def _normalize_day_navigator_heights(self, day_navigator):
        """Normalize bar heights for the day navigator."""
        container_height = 32
        min_bar_height = 5
        max_bar_height = container_height

        max_count = max(day['count'] for day in day_navigator) if day_navigator else 1

        for day in day_navigator:
            if max_count == 0:
                day['bar_height'] = min_bar_height
            else:
                normalized_height = (day['count'] / max_count) * (max_bar_height - min_bar_height) + min_bar_height
                day['bar_height'] = int(normalized_height)

    def _get_sessions_for_day(self):
        """Get all sessions for the selected date that have cached bubble data."""
        # Filter by selected project if specified
        project_filter = self.user_projects
        if self.selected_project_id:
            project_filter = [self.selected_project_id]

        # Use optimized raw SQL to get session IDs directly
        from django.db import connection

        # Convert project_filter to SQL-safe format
        if len(project_filter) == 1:
            project_clause = f"= {project_filter[0]}"
        else:
            project_ids = ','.join(str(pid) for pid in project_filter)
            project_clause = f"IN ({project_ids})"

        start_bound, end_bound = self._local_day_bounds_utc(self.selected_date)

        with connection.cursor() as cursor:
            cursor.execute(f"""
                SELECT
                    s.session_id, 
                    s.start_time AT TIME ZONE %s as start_time
                FROM tracker_session s
                INNER JOIN tracker_visitor v ON s.visitor_id = v.visitor_id
                WHERE s.start_time >= %s
                  AND s.start_time < %s
                  AND v.project_id {project_clause}
                  AND EXISTS (
                      SELECT 1 FROM tracker_bubblecache bc
                      WHERE bc.session_id = s.session_id
                      LIMIT 1
                  )
                ORDER BY start_time DESC
            """, [self.project_timezone, start_bound, end_bound])

            session_ids = [row[0] for row in cursor.fetchall()]

        # Get sessions with proper Django ORM for object access, but limited to our IDs
        sessions = Session.objects.filter(
            session_id__in=session_ids
        ).select_related('visitor__project').order_by('-start_time')

        return sessions

    def _get_paginated_sessions(self, all_sessions):
        """Get paginated sessions for display."""
        return all_sessions[self.offset:self.limit]

    def _get_total_sessions_and_pages(self):
        """Get total session count and pages for the selected date, only counting sessions with cache entries."""
        # Filter by selected project if specified
        project_filter = self.user_projects
        if self.selected_project_id:
            project_filter = [self.selected_project_id]

        # Use optimized raw SQL for counting - much faster than Django ORM
        from django.db import connection

        # Convert project_filter to SQL-safe format
        if len(project_filter) == 1:
            project_clause = f"= {project_filter[0]}"
        else:
            project_ids = ','.join(str(pid) for pid in project_filter)
            project_clause = f"IN ({project_ids})"

        start_bound, end_bound = self._local_day_bounds_utc(self.selected_date)

        with connection.cursor() as cursor:
            cursor.execute(f"""
                SELECT COUNT(*) as total_sessions
                FROM tracker_session s
                INNER JOIN tracker_visitor v ON s.visitor_id = v.visitor_id
                WHERE s.start_time >= %s
                  AND s.start_time < %s
                  AND v.project_id {project_clause}
                  AND EXISTS (
                      SELECT 1 FROM tracker_bubblecache bc
                      WHERE bc.session_id = s.session_id
                      LIMIT 1
                  )
            """, [start_bound, end_bound])

            total_sessions_for_day = cursor.fetchone()[0]

        total_pages = (total_sessions_for_day + self.rows_per_page - 1) // self.rows_per_page
        return total_sessions_for_day, total_pages

    def _get_cached_bubbles_for_sessions(self, session_ids):
        """Get cached bubble data for sessions."""
        return BubbleCacheManager.get_cached_bubbles_for_sessions(session_ids, self.selected_project_id)

    def _calculate_legend_from_cache(self, cached_entries):
        """Calculate legend from cached data."""
        return BubbleCacheManager.calculate_legend_from_cache(cached_entries)

    def _process_session_bubbles(self, sessions, session_cache, title_to_color):
        """Process bubble data for individual sessions with proportional gaps."""
        session_data = []

        for session in sessions:
            session_id = session.session_id
            session_cache_entries = session_cache.get(session_id, [])

            # Sort cache entries by timestamp
            session_cache_entries.sort(key=lambda x: x['timestamp'])

            processed_bubbles = []
            previous_minute = None

            for entry in session_cache_entries:
                current_minute = entry['timestamp']

                # Add gap entries if there's a gap > 1 minute
                if previous_minute is not None:
                    gap_minutes = (current_minute - previous_minute).total_seconds() / 60
                    if gap_minutes > 1:
                        # Add gap entries for each missing minute
                        for i in range(1, int(gap_minutes)):
                            gap_minute = previous_minute + timedelta(minutes=i)
                            processed_bubbles.append({
                                'minute': gap_minute,
                                'page_idx': 0,
                                'size': 0,  # No visual bubble
                                'color': 'transparent',
                                'breakdown': f"Gap ({gap_minute.strftime('%H:%M')})",
                                'is_gap': True
                            })

                # Add the actual bubble
                page_title = entry['page_title']
                if title_to_color.get(page_title) is None:
                    color = LEGEND_PAGE_COLORS[len(LEGEND_PAGE_COLORS) - 1]
                else:
                    color = title_to_color.get(page_title, "bg-gray-200")

                processed_bubbles.append({
                    'minute': entry['timestamp'],
                    'page_idx': 1,  # Simplified approach
                    'size': entry['size'],
                    'color': color,
                    'breakdown': entry['page_title'],
                    'is_gap': False,
                    'clicks': entry.get('clicks', 0),
                    'mouse_moves': entry.get('mouse_moves', 0),
                    'key_strokes': entry.get('key_strokes', 0),
                })

                previous_minute = current_minute

            session_data.append({
                'session': session,
                'bubbles': processed_bubbles,
            })

        return session_data

    def _get_empty_sessions_stats(self):
        """Get statistics about empty sessions for debugging."""
        # Filter by selected project if specified
        project_filter = self.user_projects
        if self.selected_project_id:
            project_filter = [self.selected_project_id]

        from django.db import connection

        # Convert project_filter to SQL-safe format  
        if len(project_filter) == 1:
            project_clause = f"= {project_filter[0]}"
        else:
            project_ids = ','.join(str(pid) for pid in project_filter)
            project_clause = f"IN ({project_ids})"

        with connection.cursor() as cursor:
            # Get total sessions for the date in project timezone
            cursor.execute(f"""
                SELECT COUNT(DISTINCT s.session_id) as total_sessions
                FROM tracker_session s
                INNER JOIN tracker_visitor v ON s.visitor_id = v.visitor_id
                WHERE DATE(s.start_time AT TIME ZONE 'UTC' AT TIME ZONE %s) = %s
                  AND v.project_id {project_clause}
            """, [self.project_timezone, self.selected_date])

            total_sessions = cursor.fetchone()[0]

            # Get sessions with events for the date in project timezone
            cursor.execute(f"""
                SELECT COUNT(DISTINCT s.session_id) as sessions_with_events
                FROM tracker_session s
                INNER JOIN tracker_visitor v ON s.visitor_id = v.visitor_id
                WHERE DATE(s.start_time AT TIME ZONE 'UTC' AT TIME ZONE %s) = %s
                  AND v.project_id {project_clause}
                  AND EXISTS (
                      SELECT 1 FROM tracker_event e 
                      WHERE e.session_id = s.session_id 
                      LIMIT 1
                  )
            """, [self.project_timezone, self.selected_date])

            sessions_with_events = cursor.fetchone()[0]

        empty_sessions = total_sessions - sessions_with_events

        return {
            'total_sessions': total_sessions,
            'sessions_with_events': sessions_with_events,
            'empty_sessions': empty_sessions,
            'empty_percentage': (empty_sessions / total_sessions * 100) if total_sessions > 0 else 0
        }

    def render(self):
        """Main method to render the all sessions bubbles view. Only uses cached bubble data."""
        if getattr(settings, 'TRACKER_RECORDINGS_DEBUG_EMPTY_STATS', False):
            empty_stats = self._get_empty_sessions_stats()
            if empty_stats['empty_sessions'] > 0:
                print(
                    f"Session filtering: {empty_stats['sessions_with_events']} valid, {empty_stats['empty_sessions']} empty")
                print(f"   Empty sessions: {empty_stats['empty_percentage']:.1f}%")

        # Get pagination info
        total_sessions_for_day, total_pages = self._get_total_sessions_and_pages()

        # Build day navigator
        day_navigator = self._build_day_navigator()

        # Find previous and next dates (with or without sessions)
        previous_date_with_sessions = None
        next_date_with_sessions = None

        # Find previous date
        for day in reversed(day_navigator):
            if day['date'] < self.selected_date:
                previous_date_with_sessions = day['date']
                break

        # Find next date
        for day in day_navigator:
            if day['date'] > self.selected_date:
                next_date_with_sessions = day['date']
                break

        previous_date_label = self._format_relative_day_label(previous_date_with_sessions)
        next_date_label = self._format_relative_day_label(next_date_with_sessions)
        selected_date_day_delta = self._get_selected_date_day_delta()

        # Get all sessions for the selected date
        all_sessions_for_day = self._get_sessions_for_day()

        # Get paginated sessions
        sessions = self._get_paginated_sessions(all_sessions_for_day)

        if not sessions:
            # Get the selected project for navigation
            from apps.projects.models import Project
            selected_project = Project.active.get(id=self.selected_project_id) if self.selected_project_id else None

            return render(self.request, 'tracker/recordings.html', {
                'session_data': [],
                'overall_legend_pages': [],
                'page_colors': LEGEND_PAGE_COLORS,
                'selected_date': self.selected_date,
                'selected_date_day_delta': selected_date_day_delta,
                'day_navigator': day_navigator,
                'previous_date_with_sessions': previous_date_with_sessions,
                'next_date_with_sessions': next_date_with_sessions,
                'previous_date_label': previous_date_label,
                'next_date_label': next_date_label,
                'selected_project': selected_project,
                'total_sessions_for_day': total_sessions_for_day,
                'page': 0,
                'total_pages': 0,
                'rows_per_page': self.rows_per_page,
                'project_timezone': self.project_timezone,
                'is_demo_view': self.is_demo_view,
                'demo_project_id': self.selected_project_id if self.is_demo_view else None,
                'demo_project_display_name': DEMO_PROJECT_DISPLAY_NAME,
            })

        # Use only cached bubble data (do not calculate in-memory)
        from apps.tracker.bubble_cache_manager import BubbleCacheManager

        # Get session IDs and cached bubble data
        all_session_ids = [session.session_id for session in all_sessions_for_day]
        all_session_cache, all_cached_entries = BubbleCacheManager.get_cached_bubbles_for_sessions(
            all_session_ids,
            self.selected_project_id,
        )

        # Calculate legend from all cached data
        overall_legend_pages = self._calculate_legend_from_cache(all_cached_entries)

        # Get cached bubble data for paginated sessions
        session_ids = [session.session_id for session in sessions]
        session_cache = {session_id: all_session_cache.get(session_id, []) for session_id in session_ids}

        # Create title to color mapping
        title_to_color = {item['page_title']: item['color'] for item in overall_legend_pages if not item['is_other']}

        # Process session bubbles
        session_data = self._process_session_bubbles(sessions, session_cache, title_to_color)

        # Get the selected project for navigation
        from apps.projects.models import Project
        selected_project = Project.active.get(id=self.selected_project_id) if self.selected_project_id else None

        return render(self.request, 'tracker/recordings.html', {
            'session_data': session_data,
            'overall_legend_pages': overall_legend_pages,
            'page_colors': LEGEND_PAGE_COLORS,
            'selected_date': self.selected_date,
            'selected_date_day_delta': selected_date_day_delta,
            'day_navigator': day_navigator,
            'total_sessions_for_day': total_sessions_for_day,
            'page': self.page,
            'total_pages': total_pages,
            'rows_per_page': self.rows_per_page,
            'previous_date_with_sessions': previous_date_with_sessions,
            'next_date_with_sessions': next_date_with_sessions,
            'previous_date_label': previous_date_label,
            'next_date_label': next_date_label,
            'selected_project': selected_project,
            'project_timezone': self.project_timezone,
            'is_demo_view': self.is_demo_view,
            'demo_project_id': self.selected_project_id if self.is_demo_view else None,
            'demo_project_display_name': DEMO_PROJECT_DISPLAY_NAME,
        })
