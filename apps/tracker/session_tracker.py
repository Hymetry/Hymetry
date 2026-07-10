import datetime
import json
import logging
import uuid
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.utils import timezone

from apps.projects.domain_utils import request_matches_allowed_domains
from apps.projects.utils import normalize_capture_modes
from apps.projects.models import Project
from apps.projects.services import record_project_production_event
from apps.tracker.models import Event, Session, Visitor
from apps.tracker.page_naming import (
    ensure_project_first_event_at,
    normalize_page_url,
)
from apps.tracker.rrweb_text_filter import mask_rrweb_event
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
        self.project = None
        self.tab_id = None
        self.visitor_guid = None

    def clean_url(self, url):
        """Strip query strings and fragments before any recording URL is stored."""
        if url is None:
            return ''
        value = str(url).strip()
        try:
            parsed = urlsplit(value)
            return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))
        except ValueError:
            return value.split('#', 1)[0].split('?', 1)[0]

    def masking_page_url(self):
        return normalize_page_url(self.page_url)

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
        """Find or create a session based on visitor_id."""
        events = self.event_data.get('events', []) if self.event_data else []
        earliest_interaction_time, _ = self._get_interaction_window(events)

        # Try to find existing session by visitor_id
        if self.visitor_guid:
            try:
                # Find the most recent active session for this visitor
                self.session = Session.objects.filter(
                    visitor__visitor_guid=self.visitor_guid,
                    visitor__project=self.project,
                    ended_at__isnull=True
                ).order_by('-last_activity').first()

                if self.session:
                    if self._close_if_future_last_activity():
                        self.session = None
                    elif earliest_interaction_time and self.session.last_activity:
                        gap_seconds = (earliest_interaction_time - self.session.last_activity).total_seconds()
                        if gap_seconds >= settings.SESSION_EXPIRATION_SECONDS:
                            reference_time = self.session.last_activity or timezone.now()
                            self._close_session_at(
                                reference_time + timezone.timedelta(seconds=settings.SESSION_EXPIRATION_SECONDS)
                            )
                            self.session = None
                        else:
                            return True
                    else:
                        # Fallback to server time only when we don't have interaction timestamps.
                        if self.session.check_and_close_if_expired():
                            self.session = None
                        else:
                            return True

            except (ValueError, Exception):
                logger.exception("Error finding session for visitor %s", self.visitor_guid)
                self.session = None

        # Create new session if none found
        if not self.session:
            # Create or get visitor for this project
            if self.visitor_guid:
                visitor, created = Visitor.objects.get_or_create(
                    visitor_guid=self.visitor_guid,
                    project=self.project,
                    defaults={
                        'first_visit': timezone.now(),
                        'last_activity': timezone.now()
                    }
                )
                if not created:
                    visitor.update_activity()
            else:
                # Without a browser visitor id we cannot reliably stitch batches together,
                # so fall back to an ephemeral visitor record for this request.
                visitor = Visitor.objects.create(
                    project=self.project,
                    first_visit=timezone.now(),
                    last_activity=timezone.now()
                )

            self.session = Session.objects.create(
                session_id=uuid.uuid4(),
                visitor=visitor,
                start_time=timezone.now(),
                last_activity=timezone.now()
            )
            return True

        return False

    def update_session_activity(self):
        """Update session's last activity timestamp from actual user interaction events only.

        - Do nothing if there is no session or no events in the payload
        - Set `last_activity` to the latest event timestamp if it is newer than stored value
        - Only count incremental snapshot sources that reflect user interactions
        - Clamp timestamps that are far in the future to avoid clock skew keeping sessions open
        """
        if not self.session:
            return

        events = self.event_data.get('events', []) if self.event_data else []
        if not events:
            return

        try:
            _, latest_interaction_time = self._get_interaction_window(events)

            if latest_interaction_time and (
                self.session.last_activity is None or latest_interaction_time > self.session.last_activity
            ):
                self.session.last_activity = latest_interaction_time
                self.session.save()
        except Exception:
            # If parsing fails, do not bump last_activity
            return

    def _get_interaction_window(self, events):
        """Return the earliest and latest interaction timestamps from rrweb events."""
        earliest = None
        latest = None
        for event in events:
            if not self._is_user_interaction_event(event):
                continue
            event_time = self._parse_event_timestamp(event)
            if not event_time:
                continue
            if earliest is None or event_time < earliest:
                earliest = event_time
            if latest is None or event_time > latest:
                latest = event_time
        return earliest, latest

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

    def _close_session_at(self, end_time):
        if not self.session:
            return
        if self.session.last_activity is None or self.session.last_activity > end_time:
            self.session.last_activity = end_time
        self.session.ended_at = end_time
        self.session.save(update_fields=['last_activity', 'ended_at'])
        self.session._cleanup_redis_data()

    def _close_if_future_last_activity(self):
        if not self.session or not self.session.last_activity:
            return False
        now = timezone.now()
        max_skew = datetime.timedelta(seconds=self._max_clock_skew_seconds())
        if self.session.last_activity > now + max_skew:
            self._close_session_at(now)
            return True
        return False

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
        
        # Prepare all events for bulk insertion
        event_objects = []
        for event in events:
            # Filter sensitive data from the event before storing
            filtered_event = mask_rrweb_event(
                event,
                session_id=str(self.session.pk) if self.session else None,
                visitor_id=str(self.visitor_guid) if self.visitor_guid else None,
                page_url=self.masking_page_url()
            )

            # Create Event object but don't save to database yet
            event_obj = Event(
                session=self.session,
                url=self.page_url,
                tab_id=self.tab_id,
                event_type=event.get('type'),
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

    def get_response(self):
        """Get the response for the request."""
        return JsonResponse({
            'status': 'success',
            'session_id': str(self.session.session_id),
            'visitor_id': str(self.session.visitor.visitor_guid) if self.session.visitor and self.session.visitor.visitor_guid else None
        })
