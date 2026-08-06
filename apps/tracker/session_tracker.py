import datetime
import json
import logging
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.utils import timezone

from apps.projects.demo import is_demo_project
from apps.projects.domain_utils import request_matches_allowed_domains
from apps.projects.utils import normalize_capture_modes
from apps.projects.models import Project
from apps.projects.services import record_project_production_event
from apps.tracker.models import Event
from apps.tracker.page_naming import (
    ensure_project_first_event_at,
    normalize_page_url,
)
from apps.tracker.rrweb_text_filter import mask_rrweb_event
from apps.tracker.session_resolver import SessionResolutionPoint, resolve_visit_session_batch
from apps.tracker.visitor_ids import normalize_project_visitor_uuid

logger = logging.getLogger(__name__)


class SessionTracker:
    """Class to handle session tracking logic."""
    USER_INTERACTION_SOURCES = {1, 2, 3, 4, 5, 6, 7, 12}

    def __init__(self, request):
        self.request = request
        self.data = None
        self.session = None
        self.origin = None
        self.page_url = None
        self.page_title = None
        self.session_id = None
        self.event_data = None
        self.event_sessions = {}
        self.project = None
        self.tab_id = None
        self.visitor_guid = None

    def clean_url(self, url):
        """Strip query strings and fragments before persisting page URLs."""
        if url is None:
            return ''
        value = str(url).strip()
        try:
            parsed = urlsplit(value)
            return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))
        except ValueError:
            return value.split('#', 1)[0].split('?', 1)[0]

    def masking_page_url(self, page_url=None):
        return normalize_page_url(self.page_url if page_url is None else page_url)

    def project_uses_recording(self):
        capture_modes = {
            mode for mode in normalize_capture_modes(self.project.tracking_capture).split(',') if mode
        }
        return 'recording' in capture_modes

    def parse_request(self):
        """Parse the incoming request data."""
        try:
            self.data = json.loads(self.request.body)
            self.project = Project.active.select_related('workspace').filter(
                api_key=self.data.get('api_key'),
                workspace__archived_at__isnull=True,
            ).first()
            if self.project is None:
                raise PermissionDenied("You must provide a valid API_KEY")
            if is_demo_project(self.project):
                raise PermissionDenied("The demo project is read-only.")
            self.session_id = self.data.get('session_id')
            self.tab_id = self.data.get('tab_id')  # Extract tab_id from request
            self.visitor_guid = normalize_project_visitor_uuid(
                self.project.id,
                self.data.get('visitor_id'),
            )

            self.event_data = self.data.get('event_data', {})
            self.page_url = self.clean_url(self.data.get('page_url'))
            self.page_title = self.data.get('page_title', '')

            # Get origin from request
            self.origin = self.request.META.get('HTTP_ORIGIN', '')
            if not self.origin and 'HTTP_REFERER' in self.request.META:
                self.origin = self.clean_url(self.request.META['HTTP_REFERER'])

            if not request_matches_allowed_domains(self.request, self.project, self.page_url):
                raise PermissionDenied("Origin is not allowed for this project's allowed domains.")

            return True
        except json.JSONDecodeError:
            return False

    def find_session(self):
        """Resolve the canonical visit shared by recording and analytics."""
        events = self.event_data.get('events', []) if self.event_data else []
        indexed_points = []
        for index, event in enumerate(events):
            event_time = self._parse_event_timestamp(event)
            if event_time is None:
                continue
            indexed_points.append(
                (
                    index,
                    SessionResolutionPoint(
                        event_time=event_time,
                        activity_time=(
                            event_time
                            if self._is_user_interaction_event(event)
                            else None
                        ),
                    ),
                )
            )

        if not indexed_points:
            indexed_points.append(
                (
                    None,
                    SessionResolutionPoint(
                        event_time=datetime.datetime.now(tz=datetime.timezone.utc),
                    ),
                )
            )

        _visitor, resolved = resolve_visit_session_batch(
            self.project,
            self.visitor_guid,
            [point for _index, point in indexed_points],
            requested_session_id=self.session_id,
        )
        self.event_sessions = {
            index: session
            for (index, _point), session in zip(indexed_points, resolved)
            if index is not None
        }
        latest_index = max(
            range(len(indexed_points)),
            key=lambda index: indexed_points[index][1].event_time,
        )
        self.session = resolved[latest_index]
        return True

    def update_session_activity(self):
        """Compatibility no-op; the shared resolver updates activity atomically."""
        return

    def _max_clock_skew_seconds(self):
        return getattr(settings, 'SESSION_MAX_CLOCK_SKEW_SECONDS', 300)

    def _clamp_future_timestamp(self, event_time):
        if not event_time:
            return None
        now = timezone.now()
        max_skew = datetime.timedelta(seconds=self._max_clock_skew_seconds())
        if event_time > now + max_skew:
            return now
        return event_time

    def _is_user_interaction_event(self, event):
        event_type = event.get('type')
        if isinstance(event_type, str):
            try:
                event_type = int(event_type)
            except (TypeError, ValueError):
                return False
        if event_type != 3:
            return False
        event_data = event.get('data', {})
        if not isinstance(event_data, dict):
            return False
        source = event_data.get('source')
        if isinstance(source, str):
            try:
                source = int(source)
            except (TypeError, ValueError):
                return False
        return source in self.USER_INTERACTION_SOURCES

    def _parse_event_timestamp(self, event):
        timestamp = event.get('timestamp')
        if timestamp is None:
            return None
        try:
            timestamp_ms = float(timestamp)
        except (TypeError, ValueError):
            return None
        try:
            event_time = datetime.datetime.fromtimestamp(timestamp_ms / 1000, tz=datetime.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
        return self._clamp_future_timestamp(event_time)

    def process_events(self):
        """Process events (single or batch) using bulk insertion to avoid N+1 queries."""
        events = self.event_data.get('events', [])
        current_meta_url = ''

        # Prepare all events for bulk insertion
        event_objects = []
        used_sessions = {}
        for index, event in enumerate(events):
            event_session = self.event_sessions.get(index, self.session)
            used_sessions[event_session.pk] = event_session
            event_type = event.get('type')
            if str(event_type) == '4':
                raw_meta = event.get('data', {})
                if isinstance(raw_meta, dict):
                    current_meta_url = self.clean_url(raw_meta.get('href')) or current_meta_url
            event_page_url = (
                self.clean_url(event.get('_hymetry_page_url'))
                or current_meta_url
                or self.page_url
            )

            # Filter sensitive data from the event before storing
            filtered_event = mask_rrweb_event(
                event,
                session_id=str(event_session.pk),
                visitor_id=str(self.visitor_guid) if self.visitor_guid else None,
                page_url=self.masking_page_url(event_page_url)
            )

            # Create Event object but don't save to database yet
            event_obj = Event(
                session=event_session,
                url=event_page_url,
                tab_id=self.tab_id,
                event_type=event_type,
                timestamp=datetime.datetime.fromtimestamp(event['timestamp'] / 1000, tz=datetime.timezone.utc),
                data=filtered_event
            )
            event_objects.append(event_obj)
        
        # Bulk insert all events in a single database operation
        if event_objects:
            Event.objects.bulk_create(event_objects, batch_size=100)
            first_event_time = min((event.timestamp for event in event_objects), default=None)
            last_event_time = max((event.timestamp for event in event_objects), default=first_event_time)
            ensure_project_first_event_at(self.project, first_event_time)
            record_project_production_event(self.project, first_event_time, last_event_time)
            for used_session in used_sessions.values():
                if used_session.ended_at is not None:
                    used_session._cleanup_redis_data()

    def get_response(self):
        """Get the response for the request."""
        return JsonResponse({
            'status': 'success',
            'session_id': str(self.session.session_id),
            'visitor_id': str(self.session.visitor.visitor_guid) if self.session.visitor and self.session.visitor.visitor_guid else None
        })
