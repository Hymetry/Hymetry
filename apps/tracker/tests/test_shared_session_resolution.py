import json
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.projects.models import Project
from apps.projects.tests.helpers import create_workspace_with_owner
from apps.tracker.models import AnalyticsSession, Event, Session


class SharedSessionResolutionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='shared-session-owner',
            email='shared-session-owner@example.com',
            password='testpass123',
        )
        self.workspace = create_workspace_with_owner(self.user, name='Shared session workspace')
        self.project = Project.objects.create(
            workspace=self.workspace,
            name='Shared session project',
            created_by=self.user,
            api_key='SHARED_SESSION_PROJECT',
            timezone='UTC',
            tracking_capture='analytics,recording',
            allowed_domains=['example.com'],
        )
        self.visitor_id = str(uuid.uuid4())

    def _analytics_payload(self, events):
        return {
            'api_key': self.project.api_key,
            'visitor_id': self.visitor_id,
            'batch': events,
        }

    def _analytics_event(self, timestamp, *, user_id=None, company_id=None):
        return {
            'type': 'click',
            'ts': timestamp.isoformat(),
            'visitor_id': self.visitor_id,
            'user_id': user_id,
            'company_id': company_id,
            'user': {'id': user_id, 'traits': {'name': 'Jane'} if user_id else {}},
            'company': {'id': company_id, 'traits': {'name': company_id} if company_id else {}},
            'page': {'url': 'https://example.com/dashboard', 'title': 'Dashboard'},
            'elementKey': 'Button: Continue',
        }

    def _recording_payload(self, timestamp):
        return {
            'api_key': self.project.api_key,
            'visitor_id': self.visitor_id,
            'tab_id': 'tab-1',
            'page_url': 'https://example.com/batch-fallback',
            'event_data': {
                'type': 'batch',
                'events': [
                    {
                        'type': 3,
                        'timestamp': int(timestamp.timestamp() * 1000),
                        'data': {'source': 2, 'type': 2},
                        '_hymetry_page_url': 'https://example.com/event-route',
                    },
                ],
            },
        }

    def test_recording_and_analytics_share_one_canonical_session(self):
        event_time = timezone.now() - timedelta(seconds=5)
        analytics_response = self.client.post(
            '/hm/ae/',
            data=json.dumps(self._analytics_payload([self._analytics_event(event_time)])),
            content_type='application/json',
            HTTP_ORIGIN='https://example.com',
        )
        recording_response = self.client.post(
            '/hm/e/',
            data=json.dumps(self._recording_payload(event_time + timedelta(seconds=1))),
            content_type='application/json',
            HTTP_ORIGIN='https://example.com',
        )

        self.assertEqual(analytics_response.status_code, 200)
        self.assertEqual(recording_response.status_code, 200)
        self.assertEqual(Session.objects.count(), 1)
        canonical = Session.objects.get()
        fragment = AnalyticsSession.objects.get()
        self.assertEqual(fragment.visit_session_id, canonical.session_id)
        self.assertEqual(recording_response.json()['session_id'], str(canonical.session_id))
        self.assertEqual(Event.objects.get().url, 'https://example.com/event-route')

    def test_identity_change_creates_fragments_without_rewriting_anonymous_time(self):
        start = timezone.now() - timedelta(seconds=10)
        response = self.client.post(
            '/hm/ae/',
            data=json.dumps(
                self._analytics_payload([
                    self._analytics_event(start),
                    self._analytics_event(
                        start + timedelta(seconds=5),
                        user_id='jane',
                        company_id='acme',
                    ),
                ])
            ),
            content_type='application/json',
            HTTP_ORIGIN='https://example.com',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Session.objects.count(), 1)
        fragments = list(AnalyticsSession.objects.order_by('start_time'))
        self.assertEqual(len(fragments), 2)
        self.assertIsNone(fragments[0].user_id)
        self.assertIsNone(fragments[0].company_id)
        self.assertEqual(fragments[0].ended_at, start + timedelta(seconds=5))
        self.assertEqual(fragments[1].user_id, 'jane')
        self.assertEqual(fragments[1].company_id, 'acme')
        self.assertEqual(fragments[0].visit_session_id, fragments[1].visit_session_id)

    @patch('apps.tracker.models.Session._cleanup_redis_data')
    def test_true_timeout_gap_creates_a_new_session_from_event_time(self, _cleanup):
        start = timezone.now() - timedelta(hours=2)
        response = self.client.post(
            '/hm/ae/',
            data=json.dumps(
                self._analytics_payload([
                    self._analytics_event(start),
                    self._analytics_event(start + timedelta(minutes=31)),
                ])
            ),
            content_type='application/json',
            HTTP_ORIGIN='https://example.com',
        )

        self.assertEqual(response.status_code, 200)
        sessions = list(Session.objects.order_by('start_time'))
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0].ended_at, start + timedelta(minutes=30))
        self.assertEqual(sessions[1].start_time, start + timedelta(minutes=31))

    @override_settings(SESSION_MAX_DURATION_SECONDS=12 * 60 * 60)
    @patch('apps.tracker.models.Session._cleanup_redis_data')
    def test_continuous_analytics_activity_rolls_over_at_twelve_hours(self, _cleanup):
        start = timezone.now() - timedelta(hours=13)
        events = [
            self._analytics_event(start + timedelta(minutes=offset))
            for offset in range(0, (12 * 60) + 1, 20)
        ]

        response = self.client.post(
            '/hm/ae/',
            data=json.dumps(self._analytics_payload(events)),
            content_type='application/json',
            HTTP_ORIGIN='https://example.com',
        )

        self.assertEqual(response.status_code, 200)
        sessions = list(Session.objects.order_by('start_time'))
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0].start_time, start)
        self.assertEqual(sessions[0].ended_at, start + timedelta(hours=12))
        self.assertEqual(sessions[1].start_time, start + timedelta(hours=12))
        self.assertIsNone(sessions[1].ended_at)
        self.assertEqual(
            AnalyticsSession.objects.filter(visit_session=sessions[0]).count(),
            1,
        )
        self.assertEqual(
            AnalyticsSession.objects.filter(visit_session=sessions[1]).count(),
            1,
        )
