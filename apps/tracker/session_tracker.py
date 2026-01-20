import datetime
import json
import uuid
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.utils import timezone

from apps.projects.models import Project
from apps.tracker.models import Session, Page, Event, Visitor
from apps.tracker.rrweb_text_filter import mask_rrweb_event
from apps.tracker.tasks import generate_clean_title


class SessionTracker:
    """Class to handle session tracking logic."""
    USER_INTERACTION_SOURCES = {1, 2, 3, 4, 5, 6, 7, 12}

    def __init__(self, request):
        self.request = request
        self.data = None
        self.session = None
        self.page = None
        self.origin = None
        self.page_url = None
        self.page_title = None
        self.session_id = None
        self.event_data = None
        self.project = None
        self.tab_id = None
        self.visitor_guid = None

    def clean_url(self, url):
        """Remove all query parameters from URL to treat pages with different query params as the same page."""
        if not url:
            return url
        parsed = urlparse(url)
        # Remove all query parameters and reconstruct URL
        clean_url = parsed._replace(query='').geturl()
        return clean_url

    def parse_request(self):
        """Parse the incoming request data."""
        try:
            self.data = json.loads(self.request.body)
            self.project = Project.objects.filter(api_key=self.data.get('api_key')).first()
            if self.project is None:
                raise PermissionDenied("You must provide a valid API_KEY")

            self.session_id = self.data.get('session_id')
            self.tab_id = self.data.get('tab_id')  # Extract tab_id from request
            self.visitor_guid = self.data.get('visitor_id')  # Extract visitor_id from request

            self.event_data = self.data.get('event_data', {})
            self.page_url = self.clean_url(self.data.get('page_url'))
            self.page_title = self.data.get('page_title', '')

            # Get origin from request
            self.origin = self.request.META.get('HTTP_ORIGIN', '')
            if not self.origin and 'HTTP_REFERER' in self.request.META:
                self.origin = self.clean_url(self.request.META['HTTP_REFERER'])

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
                # Convert string UUID to UUID object
                visitor_uuid = uuid.UUID(str(self.visitor_guid))

                # Find the most recent active session for this visitor
                self.session = Session.objects.filter(
                    visitor__visitor_guid=visitor_uuid,
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

            except (ValueError, Exception) as e:
                print(f"Error finding session for visitor {self.visitor_guid}: {str(e)}")
                self.session = None

        # Create new session if none found
        if not self.session:
            # Create or get visitor for this project
            if self.visitor_guid:
                try:
                    # Try to find existing visitor by visitor_guid
                    visitor_uuid = uuid.UUID(str(self.visitor_guid))
                    visitor = Visitor.objects.get(visitor_guid=visitor_uuid, project=self.project)
                    visitor.update_activity()
                except (Visitor.DoesNotExist, ValueError):
                    # Create new visitor with provided visitor_guid
                    visitor_uuid = uuid.UUID(str(self.visitor_guid))
                    visitor = Visitor.objects.create(
                        visitor_guid=visitor_uuid,
                        project=self.project,
                        first_visit=timezone.now(),
                        last_activity=timezone.now()
                    )
            else:
                # Create new visitor without specific visitor_id
                visitor, created = Visitor.objects.get_or_create(
                    project=self.project,
                    defaults={
                        'first_visit': timezone.now(),
                        'last_activity': timezone.now()
                    }
                )
                if not created:
                    visitor.update_activity()

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

    def get_or_create_page(self):
        """Get or create a page for the current session."""
        try:
            # Page is now unique by URL, not by session
            self.page = Page.objects.get(url=self.page_url)
            # if self.page_title and self.page.title != self.page_title:
            #    self.page.title = self.page_title
            #    self.page.save()
        except Page.DoesNotExist:
            self.page = Page.objects.create(
                url=self.page_url,
                original_title=self.page_title or self.page_url
            )
            # AI page title by Celery task
            generate_clean_title.delay(self.page.id)

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
                page_url=self.page_url
            )

            # Create Event object but don't save to database yet
            event_obj = Event(
                page=self.page,
                session=self.session,
                tab_id=self.tab_id,
                event_type=event.get('type'),
                timestamp=datetime.datetime.fromtimestamp(event['timestamp'] / 1000, tz=datetime.timezone.utc),
                data=filtered_event
            )
            event_objects.append(event_obj)
        
        # Bulk insert all events in a single database operation
        if event_objects:
            Event.objects.bulk_create(event_objects, batch_size=100)

    def get_response(self):
        """Get the response for the request."""
        return JsonResponse({
            'status': 'success',
            'session_id': str(self.session.session_id),
            'visitor_id': str(self.session.visitor.visitor_guid) if self.session.visitor and self.session.visitor.visitor_guid else None
        })
