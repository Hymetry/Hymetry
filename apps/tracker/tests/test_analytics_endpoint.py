import json
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import UUID, uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.projects.models import LifecycleStatus, Project, Workspace
from apps.tracker.models import AnalyticsEvent, AnalyticsSession
from apps.tracker.visitor_ids import normalize_project_visitor_uuid


class AnalyticsEndpointTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            username='analytics-owner',
            email='analytics-owner@example.com',
            password='testpass123',
        )
        self.workspace = Workspace.objects.create(
            name='Analytics Workspace',
            website_url='workspace.example',
            created_by=self.owner,
        )
        self.project = Project.objects.create(
            workspace=self.workspace,
            name='Analytics Project',
            created_by=self.owner,
            api_key='ANALYTICSTEST123',
            tracking_capture='analytics,recording',
            product_url='https://app.example.com',
            allowed_domains=['example.com'],
        )

    def test_record_analytics_500_does_not_expose_exception_text(self):
        payload = {
            'api_key': self.project.api_key,
            'visitor_id': str(uuid4()),
            'batch': [
                {
                    'type': 'click',
                    'ts': '2026-04-23T12:00:00Z',
                    'page': {'url': 'https://example.com/dashboard'},
                },
            ],
        }

        with patch('apps.tracker.analytics_tracker.AnalyticsTracker.process_events') as process_events:
            process_events.side_effect = RuntimeError('database password leaked')
            response = self.client.post(
                reverse('record_analytics'),
                data=json.dumps(payload),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {'error': 'Internal server error.'})

    def test_record_event_500_does_not_expose_exception_text(self):
        with (
            patch('apps.tracker.views.SessionTracker.parse_request', return_value=True),
            patch('apps.tracker.views.SessionTracker.project_uses_recording', return_value=True),
            patch('apps.tracker.views.SessionTracker.find_session'),
            patch('apps.tracker.views.SessionTracker.process_events') as process_events,
        ):
            process_events.side_effect = RuntimeError('secret stack detail')
            response = self.client.post(
                reverse('record_event'),
                data=json.dumps({'api_key': self.project.api_key}),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {'error': 'Internal server error.'})

    def test_record_analytics_accepts_scroll_and_mouse_move_events(self):
        visitor_id = str(uuid4())
        payload = {
            'api_key': self.project.api_key,
            'visitor_id': visitor_id,
            'batch': [
                {
                    'type': 'scroll',
                    'ts': '2026-04-23T12:00:00Z',
                    'page': {
                        'url': 'https://example.com/dashboard',
                        'title': 'Dashboard',
                    },
                },
                {
                    'type': 'mouse_move',
                    'ts': '2026-04-23T12:00:02Z',
                    'page': {
                        'url': 'https://example.com/dashboard',
                        'title': 'Dashboard',
                    },
                },
                {
                    'type': 'click',
                    'ts': '2026-04-23T12:00:03Z',
                    'page': {
                        'url': 'https://example.com/dashboard',
                        'title': 'Dashboard',
                    },
                    'elementKey': 'Button: Open dashboard',
                },
            ],
        }

        response = self.client.post(
            reverse('record_analytics'),
            data=json.dumps(payload),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                'status': 'success',
                'accepted_events': 3,
                'skipped_events': 0,
                'sessions_touched': 1,
            },
        )

        self.assertEqual(AnalyticsSession.objects.count(), 1)
        session = AnalyticsSession.objects.get()
        self.assertEqual(
            session.last_activity,
            datetime(2026, 4, 23, 12, 0, 3, tzinfo=timezone.utc),
        )

        events = list(AnalyticsEvent.objects.order_by('timestamp'))
        self.assertEqual([event.event_type for event in events], ['scroll', 'mouse_move', 'click'])
        self.assertEqual(events[0].visitor_guid, UUID(visitor_id))
        self.assertIsNone(events[0].element_key)
        self.assertIsNone(events[1].element_key)
        self.assertEqual(events[2].element_key, 'Button: Open dashboard')
        self.project.refresh_from_db()
        self.workspace.refresh_from_db()
        self.assertEqual(self.project.status, 'active')
        self.assertEqual(self.project.first_production_event_at, datetime(2026, 4, 23, 12, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(self.project.last_event_at, datetime(2026, 4, 23, 12, 0, 3, tzinfo=timezone.utc))

    def test_record_analytics_writes_ingestion_log(self):
        payload = {
            'api_key': self.project.api_key,
            'visitor_id': str(uuid4()),
            'batch': [
                {
                    'type': 'scroll',
                    'ts': '2026-04-23T12:00:00Z',
                    'page': {
                        'url': 'https://example.com/dashboard?tab=usage',
                        'title': 'Dashboard',
                    },
                },
                {
                    'type': 'click',
                    'ts': '2026-04-23T12:00:01Z',
                    'page': {
                        'url': 'https://example.com/dashboard?tab=usage',
                        'title': 'Dashboard',
                    },
                    'elementKey': 'Button: Open dashboard',
                },
            ],
        }

        with self.assertLogs('apps.tracker.analytics_tracker', level='INFO') as captured_logs:
            response = self.client.post(
                reverse('record_analytics'),
                data=json.dumps(payload),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(captured_logs.output), 1)
        self.assertIn('Analytics batch ingested', captured_logs.output[0])
        self.assertIn(f'project_id={self.project.id}', captured_logs.output[0])
        self.assertIn('accepted=2', captured_logs.output[0])
        self.assertIn('event_types=click:1,scroll:1', captured_logs.output[0])
        self.assertIn('sample_url=example.com/dashboard', captured_logs.output[0])

    def test_record_analytics_normalizes_non_uuid_visitor_ids(self):
        payload = {
            'api_key': self.project.api_key,
            'visitor_id': 'mobf9liv_zmwztu7r',
            'batch': [
                {
                    'type': 'scroll',
                    'ts': '2026-04-23T12:00:00Z',
                    'page': {
                        'url': 'https://example.com/dashboard',
                        'title': 'Dashboard',
                    },
                },
            ],
        }

        response = self.client.post(
            reverse('record_analytics'),
            data=json.dumps(payload),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(AnalyticsSession.objects.count(), 1)
        self.assertEqual(AnalyticsEvent.objects.count(), 1)
        expected_visitor_guid = normalize_project_visitor_uuid(self.project.id, 'mobf9liv_zmwztu7r')
        self.assertEqual(AnalyticsSession.objects.get().visitor_guid, expected_visitor_guid)
        self.assertEqual(AnalyticsEvent.objects.get().visitor_guid, expected_visitor_guid)

    def test_record_analytics_rejects_workspace_website_when_project_domain_differs(self):
        self.workspace.website_url = 'workspace-only.com'
        self.workspace.save(update_fields=['website_url'])
        self.project.allowed_domains = ['example.com']
        self.project.save(update_fields=['allowed_domains'])

        payload = {
            'api_key': self.project.api_key,
            'visitor_id': str(uuid4()),
            'batch': [
                {
                    'type': 'scroll',
                    'ts': '2026-04-23T12:00:00Z',
                    'page': {
                        'url': 'https://workspace-only.com/dashboard',
                        'title': 'Dashboard',
                    },
                },
            ],
        }

        response = self.client.post(
            reverse('record_analytics'),
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_ORIGIN='https://workspace-only.com',
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(AnalyticsEvent.objects.count(), 0)

    def test_record_analytics_allows_private_suffix_project_domain_subdomain(self):
        self.project.product_url = 'customer.github.io'
        self.project.allowed_domains = ['customer.github.io']
        self.project.save(update_fields=['product_url', 'allowed_domains'])

        payload = {
            'api_key': self.project.api_key,
            'visitor_id': str(uuid4()),
            'batch': [
                {
                    'type': 'scroll',
                    'ts': '2026-04-23T12:00:00Z',
                    'page': {
                        'url': 'https://www.customer.github.io/dashboard',
                        'title': 'Dashboard',
                    },
                },
            ],
        }

        response = self.client.post(
            reverse('record_analytics'),
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_ORIGIN='https://www.customer.github.io',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(AnalyticsEvent.objects.count(), 1)

    def test_record_analytics_allows_legacy_project_without_allowed_domains(self):
        self.project.allowed_domains = []
        self.project.save(update_fields=['allowed_domains'])

        payload = {
            'api_key': self.project.api_key,
            'visitor_id': str(uuid4()),
            'batch': [
                {
                    'type': 'scroll',
                    'ts': '2026-04-23T12:00:00Z',
                    'page': {
                        'url': 'https://legacy.example.net/dashboard',
                        'title': 'Dashboard',
                    },
                },
            ],
        }

        response = self.client.post(
            reverse('record_analytics'),
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_ORIGIN='https://legacy.example.net',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(AnalyticsEvent.objects.count(), 1)
        self.project.refresh_from_db()
        self.workspace.refresh_from_db()
        self.assertEqual(self.project.status, 'setup_required')
        self.assertEqual(self.project.first_production_event_at, datetime(2026, 4, 23, 12, 0, 0, tzinfo=timezone.utc))

    def test_record_analytics_rejects_archived_project(self):
        self.project.lifecycle_status = LifecycleStatus.ARCHIVED
        self.project.save(update_fields=['lifecycle_status'])

        payload = {
            'api_key': self.project.api_key,
            'visitor_id': str(uuid4()),
            'batch': [
                {
                    'type': 'scroll',
                    'ts': '2026-04-23T12:00:00Z',
                    'page': {
                        'url': 'https://example.com/dashboard',
                        'title': 'Dashboard',
                    },
                },
            ],
        }

        response = self.client.post(
            reverse('record_analytics'),
            data=json.dumps(payload),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(AnalyticsEvent.objects.count(), 0)

    def test_record_analytics_rejects_archived_workspace(self):
        self.workspace.archived_at = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
        self.workspace.save(update_fields=['archived_at'])

        payload = {
            'api_key': self.project.api_key,
            'visitor_id': str(uuid4()),
            'batch': [
                {
                    'type': 'scroll',
                    'ts': '2026-04-23T12:00:00Z',
                    'page': {
                        'url': 'https://example.com/dashboard',
                        'title': 'Dashboard',
                    },
                },
            ],
        }

        response = self.client.post(
            reverse('record_analytics'),
            data=json.dumps(payload),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(AnalyticsEvent.objects.count(), 0)

