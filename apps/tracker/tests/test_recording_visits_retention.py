import json
import uuid
from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from django_celery_beat.models import ClockedSchedule, PeriodicTask

from apps.pages.models import PageVisit
from apps.projects.models import Project
from apps.projects.tests.helpers import create_workspace_with_owner
from apps.tracker.models import (
    AnalyticsEvent,
    AnalyticsSession,
    Event,
    Session,
    Visitor,
)
from apps.tracker.visits_retention import prune_expired_recording_visits


class RecordingVisitsRetentionTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username='recording-visits-retention-owner',
            email='recording-visits-retention@example.com',
            password='testpass123',
        )
        workspace = create_workspace_with_owner(
            user,
            name='Recording Visits retention workspace',
        )
        self.project = Project.objects.create(
            workspace=workspace,
            name='Recording Visits retention project',
            created_by=user,
            api_key='RECORDING_VISITS_RETENTION',
            timezone='UTC',
            tracking_capture='analytics,recording',
        )
        self.now = timezone.now().replace(microsecond=0)

    def _create_visit(self, started_at):
        visitor_guid = uuid.uuid4()
        visitor = Visitor.objects.create(
            project=self.project,
            visitor_guid=visitor_guid,
            first_visit=started_at,
            last_activity=started_at + timedelta(minutes=1),
        )
        session = Session.objects.create(
            visitor=visitor,
            start_time=started_at,
            last_activity=started_at + timedelta(minutes=1),
            ended_at=started_at + timedelta(minutes=1),
        )
        rrweb_event = Event.objects.create(
            session=session,
            url='https://example.com/page',
            tab_id='tab-1',
            event_type=3,
            timestamp=started_at,
            data={'type': 3, 'data': {'source': 2}},
        )
        analytics_session = AnalyticsSession.objects.create(
            project=self.project,
            visit_session=session,
            visitor_guid=visitor_guid,
            user_id='user-1',
            company_id='company-1',
            start_time=started_at,
            last_activity=started_at + timedelta(minutes=1),
            ended_at=started_at + timedelta(minutes=1),
        )
        analytics_event = AnalyticsEvent.objects.create(
            session=analytics_session,
            event_type='click',
            timestamp=started_at,
            visitor_guid=visitor_guid,
            user_id='user-1',
            company_id='company-1',
            user_traits={'name': 'User One'},
            company_traits={'name': 'Company One'},
            url='https://example.com/page',
            url_normalized='example.com/page',
            page_name='Page',
        )
        prepared_page_visit = PageVisit.objects.create(
            project=self.project,
            session_id=analytics_session.session_id,
            visitor_guid=visitor_guid,
            user_id='user-1',
            company_id='company-1',
            url_normalized='example.com/page',
            page_name_original='Page',
            product_area_key='core',
            product_area_name='Core',
            visit_start_ts=started_at,
            visit_end_ts=started_at + timedelta(seconds=10),
            engaged_seconds=10,
        )
        return {
            'visitor': visitor,
            'session': session,
            'rrweb_event': rrweb_event,
            'analytics_session': analytics_session,
            'analytics_event': analytics_event,
            'prepared_page_visit': prepared_page_visit,
        }

    def test_prune_deletes_only_sessions_strictly_older_than_retention(self):
        expired = self._create_visit(
            self.now - timedelta(days=30, seconds=1),
        )
        boundary = self._create_visit(
            self.now - timedelta(days=30),
        )
        recent = self._create_visit(
            self.now - timedelta(days=29),
        )

        result = prune_expired_recording_visits(
            retention_days=30,
            batch_size=1,
            now=self.now,
        )

        self.assertEqual(result['deleted_sessions'], 1)
        self.assertEqual(result['deleted_rrweb_events'], 1)
        self.assertEqual(result['deleted_visitors'], 1)
        self.assertEqual(result['batches'], 1)
        for model, key in (
            (Visitor, 'visitor'),
            (Session, 'session'),
            (Event, 'rrweb_event'),
        ):
            self.assertFalse(model.objects.filter(pk=expired[key].pk).exists())
            self.assertTrue(model.objects.filter(pk=boundary[key].pk).exists())
            self.assertTrue(model.objects.filter(pk=recent[key].pk).exists())

        expired['analytics_session'].refresh_from_db()
        self.assertIsNone(expired['analytics_session'].visit_session_id)
        self.assertTrue(
            AnalyticsEvent.objects.filter(
                pk=expired['analytics_event'].pk,
            ).exists()
        )
        self.assertTrue(
            PageVisit.objects.filter(
                pk=expired['prepared_page_visit'].pk,
            ).exists()
        )
        for payload in (boundary, recent):
            payload['analytics_session'].refresh_from_db()
            self.assertEqual(
                payload['analytics_session'].visit_session_id,
                payload['session'].session_id,
            )

    def test_dry_run_reports_without_deleting(self):
        expired = self._create_visit(
            self.now - timedelta(days=31),
        )

        result = prune_expired_recording_visits(
            retention_days=30,
            now=self.now,
            dry_run=True,
        )

        self.assertEqual(result['matched_sessions'], 1)
        self.assertEqual(result['matched_rrweb_events'], 1)
        self.assertEqual(result['deleted_sessions'], 0)
        self.assertTrue(result['dry_run'])
        self.assertTrue(
            Session.objects.filter(pk=expired['session'].pk).exists()
        )
        self.assertTrue(
            AnalyticsSession.objects.filter(
                pk=expired['analytics_session'].pk,
            ).exists()
        )

    def test_prune_keeps_visitor_that_still_has_a_recent_session(self):
        expired = self._create_visit(
            self.now - timedelta(days=31),
        )
        recent_session = Session.objects.create(
            visitor=expired['visitor'],
            start_time=self.now - timedelta(days=1),
            last_activity=self.now - timedelta(days=1),
            ended_at=self.now - timedelta(days=1),
        )

        result = prune_expired_recording_visits(
            retention_days=30,
            now=self.now,
        )

        self.assertEqual(result['deleted_sessions'], 1)
        self.assertEqual(result['deleted_visitors'], 0)
        self.assertTrue(
            Visitor.objects.filter(pk=expired['visitor'].pk).exists()
        )
        self.assertTrue(Session.objects.filter(pk=recent_session.pk).exists())

    def test_management_command_supports_dry_run_and_apply(self):
        expired = self._create_visit(
            self.now - timedelta(days=31),
        )

        dry_run_output = StringIO()
        call_command(
            'prune_recording_visits',
            '--retention-days',
            '30',
            stdout=dry_run_output,
        )
        self.assertIn('matched_sessions=1', dry_run_output.getvalue())
        self.assertTrue(
            Session.objects.filter(pk=expired['session'].pk).exists()
        )

        apply_output = StringIO()
        call_command(
            'prune_recording_visits',
            '--retention-days',
            '30',
            '--apply',
            stdout=apply_output,
        )
        self.assertIn('deleted_sessions=1', apply_output.getvalue())
        self.assertFalse(
            Session.objects.filter(pk=expired['session'].pk).exists()
        )
        self.assertTrue(
            AnalyticsSession.objects.filter(
                pk=expired['analytics_session'].pk,
            ).exists()
        )
        expired['analytics_session'].refresh_from_db()
        self.assertIsNone(expired['analytics_session'].visit_session_id)


class ScheduleRecordingVisitsCleanupTests(TestCase):
    def test_command_repairs_and_enables_daily_schedule(self):
        clocked = ClockedSchedule.objects.create(
            clocked_time=timezone.now() + timedelta(hours=1),
        )
        PeriodicTask.objects.create(
            name='Recording Visits 30-day retention cleanup',
            task='old.task',
            clocked=clocked,
            one_off=True,
            enabled=False,
        )

        call_command('schedule_recording_visits_cleanup', mode='real')

        periodic_task = PeriodicTask.objects.get(
            name='Recording Visits 30-day retention cleanup',
        )
        self.assertEqual(
            periodic_task.task,
            'apps.tracker.tasks.prune_expired_recording_visits_task',
        )
        self.assertEqual(periodic_task.interval.every, 1)
        self.assertEqual(periodic_task.interval.period, 'days')
        self.assertIsNone(periodic_task.crontab)
        self.assertIsNone(periodic_task.clocked)
        self.assertIsNone(periodic_task.solar)
        self.assertFalse(periodic_task.one_off)
        self.assertTrue(periodic_task.enabled)
        self.assertEqual(
            json.loads(periodic_task.kwargs),
            {
                'retention_days': 30,
                'batch_size': 100,
            },
        )
