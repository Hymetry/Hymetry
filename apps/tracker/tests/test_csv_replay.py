from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from apps.tracker.testing.csv_replay import build_replay_events, deterministic_visitor_id, ensure_absolute_url
from apps.projects.models import Project
from apps.projects.tests.helpers import create_workspace_with_owner
from apps.tracker.models import AnalyticsEvent, SafeInputRegexTemplate
from apps.tracker.testing.replay_runtime import load_replay_events


class CsvReplayTests(SimpleTestCase):
    def test_ensure_absolute_url_adds_https_scheme(self):
        absolute_url = ensure_absolute_url('example.com/acme/dashboard?tab=usage')

        self.assertEqual(absolute_url, 'https://example.com/acme/dashboard?tab=usage')

    def test_deterministic_visitor_id_is_stable_for_same_inputs(self):
        first = deterministic_visitor_id(101, 'Acme Logistics', 'liam.smith@acme.com')
        second = deterministic_visitor_id(101, 'Acme Logistics', 'liam.smith@acme.com')

        self.assertEqual(first, second)

    def test_build_replay_events_recent_span_preserves_relative_positions(self):
        rows = [
            {
                'event_time': '2026-04-01 00:00:00',
                'company_name': 'Acme Logistics',
                'user_email': 'liam.smith@acme.com',
                'full_url': 'example.com/acme/dashboard?tab=usage',
                'clicked_element': 'Tab: Usage',
            },
            {
                'event_time': '2026-04-01 00:10:00',
                'company_name': 'Acme Logistics',
                'user_email': 'liam.smith@acme.com',
                'full_url': 'example.com/acme/accounts/123',
                'clicked_element': 'Link: Account details',
            },
        ]
        now = datetime(2026, 4, 6, 12, 0, 0, tzinfo=timezone.utc)

        replay_events = build_replay_events(
            rows=rows,
            project_id=77,
            recent_span_seconds=300,
            now=now,
        )

        self.assertEqual(replay_events[0].event_timestamp, datetime(2026, 4, 6, 11, 55, 0, tzinfo=timezone.utc))
        self.assertEqual(replay_events[1].event_timestamp, datetime(2026, 4, 6, 12, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(replay_events[0].send_not_before, now)
        self.assertEqual(replay_events[1].send_not_before, now)
        self.assertEqual(replay_events[0].payload['page'], 'https://example.com/acme/dashboard?tab=usage')

    def test_build_replay_events_stream_mode_delays_send_time(self):
        rows = [
            {
                'event_time': '2026-04-01 00:00:00',
                'company_name': 'Acme Logistics',
                'user_email': 'liam.smith@acme.com',
                'full_url': 'example.com/acme/dashboard',
                'clicked_element': 'Tab: Overview',
            },
            {
                'event_time': '2026-04-01 00:10:00',
                'company_name': 'Acme Logistics',
                'user_email': 'liam.smith@acme.com',
                'full_url': 'example.com/acme/accounts/123',
                'clicked_element': 'Link: Account details',
            },
        ]
        now = datetime(2026, 4, 6, 12, 0, 0, tzinfo=timezone.utc)

        replay_events = build_replay_events(
            rows=rows,
            project_id=77,
            stream_seconds=120,
            start_delay_seconds=30,
            now=now,
        )

        self.assertEqual(replay_events[0].event_timestamp, datetime(2026, 4, 6, 12, 0, 30, tzinfo=timezone.utc))
        self.assertEqual(replay_events[1].event_timestamp, datetime(2026, 4, 6, 12, 2, 30, tzinfo=timezone.utc))
        self.assertEqual(replay_events[0].send_not_before, replay_events[0].event_timestamp)
        self.assertEqual(replay_events[1].send_not_before, replay_events[1].event_timestamp)

    def test_load_replay_events_recent_span_with_delay_keeps_events_recent_to_delayed_start(self):
        temp_dir = TemporaryDirectory()
        csv_path = Path(temp_dir.name) / 'delayed_recent.csv'
        csv_path.write_text(
            '\n'.join(
                [
                    'event_time,company_name,user_email,full_url,page_title,clicked_element',
                    '2026-04-01 00:00:00,Acme Logistics,liam.smith@acme.com,example.com/acme/dashboard,Dashboard,Tab: Usage',
                    '2026-04-01 00:10:00,Acme Logistics,liam.smith@acme.com,example.com/acme/accounts/123,Account 123,Link: Account details',
                ]
            ),
            encoding='utf-8',
        )
        now = datetime(2026, 4, 6, 12, 0, 0, tzinfo=timezone.utc)

        try:
            replay_events = load_replay_events(
                csv_path=str(csv_path),
                project_id=77,
                recent_span_seconds=180,
                start_delay_seconds=360,
                now=now,
                stream_name='spike',
            )
        finally:
            temp_dir.cleanup()

        self.assertEqual(replay_events[0].event_timestamp, datetime(2026, 4, 6, 12, 3, 0, tzinfo=timezone.utc))
        self.assertEqual(replay_events[1].event_timestamp, datetime(2026, 4, 6, 12, 6, 0, tzinfo=timezone.utc))
        self.assertEqual(replay_events[0].send_not_before, datetime(2026, 4, 6, 12, 6, 0, tzinfo=timezone.utc))
        self.assertEqual(replay_events[1].send_not_before, datetime(2026, 4, 6, 12, 6, 0, tzinfo=timezone.utc))


class ReplayAnalyticsCsvCommandTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='csv-replay-owner',
            email='owner@example.com',
            password='testpass123',
        )
        self.workspace = create_workspace_with_owner(self.user, name='CSV Replay Workspace')
        self.project = Project.objects.create(
            workspace=self.workspace,
            name='CSV Replay Project',
            created_by=self.user,
            api_key='CSVREPLAYTEST123',
            tracking_capture='analytics,recording',
        )

    def _write_csv(self):
        temp_dir = TemporaryDirectory()
        path = Path(temp_dir.name) / 'replay.csv'
        path.write_text(
            '\n'.join(
                [
                    'event_time,company_name,user_email,full_url,page_title,clicked_element',
                    '2026-04-01 00:00:00,Acme Logistics,liam.smith@acme.com,example.com/acme/dashboard?tab=usage,Dashboard,Tab: Usage',
                    '2026-04-01 00:10:00,Acme Logistics,liam.smith@acme.com,example.com/acme/accounts/123,Account 123,Link: Account details',
                ]
            ),
            encoding='utf-8',
        )
        return temp_dir, path

    def _write_csv_rows(self, rows, filename='replay_custom.csv'):
        temp_dir = TemporaryDirectory()
        path = Path(temp_dir.name) / filename
        path.write_text(
            '\n'.join(
                ['event_time,company_name,user_email,full_url,page_title,clicked_element'] + rows
            ),
            encoding='utf-8',
        )
        return temp_dir, path

    def test_dry_run_prints_replay_plan(self):
        temp_dir, csv_path = self._write_csv()
        stdout = StringIO()
        try:
            call_command(
                'replay_analytics_csv',
                str(csv_path),
                '--project-id',
                str(self.project.id),
                '--recent-span-seconds',
                '300',
                '--dry-run',
                stdout=stdout,
            )
        finally:
            temp_dir.cleanup()

        output = stdout.getvalue()
        self.assertIn('Replay plan (dry-run)', output)
        self.assertIn('events: 2', output)
        self.assertIn('transport: internal', output)

    def test_live_replay_creates_analytics_events(self):
        temp_dir, csv_path = self._write_csv()
        stdout = StringIO()
        try:
            call_command(
                'replay_analytics_csv',
                str(csv_path),
                '--project-id',
                str(self.project.id),
                '--recent-span-seconds',
                '300',
                '--batch-size',
                '2',
                stdout=stdout,
            )
        finally:
            temp_dir.cleanup()

        self.assertEqual(AnalyticsEvent.objects.count(), 2)
        event = AnalyticsEvent.objects.order_by('timestamp').first()
        self.assertEqual(event.company_id, 'acme-logistics')
        self.assertEqual(event.url, 'https://example.com/acme/dashboard')
        self.assertEqual(event.url_normalized, 'example.com/acme/dashboard')
        self.assertEqual(event.element_key, 'Tab: Usage')

    def test_live_replay_masks_sensitive_element_key_text(self):
        SafeInputRegexTemplate.objects.create(
            name='card-number',
            pattern=r'(?:\d[ -]?){13,19}',
            description='Mask card-like numbers in analytics element labels.',
            keep_prefix_digits=4,
        )
        temp_dir, csv_path = self._write_csv_rows(
            [
                '2026-04-01 00:00:00,Acme Logistics,liam.smith@acme.com,example.com/acme/billing,Subscription,Input: 4242 4242 4242 4242',
            ],
            filename='replay_sensitive.csv',
        )
        stdout = StringIO()
        try:
            call_command(
                'replay_analytics_csv',
                str(csv_path),
                '--project-id',
                str(self.project.id),
                '--recent-span-seconds',
                '300',
                stdout=stdout,
            )
        finally:
            temp_dir.cleanup()

        event = AnalyticsEvent.objects.get()
        self.assertEqual(event.element_key, 'Input: 4242 **** **** ****')

    def test_replay_requires_project_with_analytics_capture(self):
        self.project.tracking_capture = 'recording'
        self.project.save(update_fields=['tracking_capture'])
        temp_dir, csv_path = self._write_csv()
        try:
            with self.assertRaisesMessage(CommandError, "does not include analytics"):
                call_command(
                    'replay_analytics_csv',
                    str(csv_path),
                    '--project-id',
                    str(self.project.id),
                    '--recent-span-seconds',
                    '300',
                )
        finally:
            temp_dir.cleanup()


class ReplayPageNamingScenarioCommandTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='scenario-replay-owner',
            email='scenario-owner@example.com',
            password='testpass123',
        )
        self.workspace = create_workspace_with_owner(self.user, name='Scenario Replay Workspace')
        self.project = Project.objects.create(
            workspace=self.workspace,
            name='Scenario Replay Project',
            created_by=self.user,
            api_key='SCENARIOREPLAYTEST123',
            tracking_capture='analytics,recording',
        )

    def _write_csv(self, rows, filename):
        temp_dir = TemporaryDirectory()
        path = Path(temp_dir.name) / filename
        path.write_text(
            '\n'.join(
                ['event_time,company_name,user_email,full_url,page_title,clicked_element'] + rows
            ),
            encoding='utf-8',
        )
        return temp_dir, path

    def test_dry_run_prints_baseline_spike_and_combined_plans(self):
        baseline_dir, baseline_csv = self._write_csv(
            [
                '2026-04-01 00:00:00,Acme Logistics,liam.smith@acme.com,example.com/acme/dashboard,Dashboard,Tab: Usage',
            ],
            'baseline.csv',
        )
        spike_dir, spike_csv = self._write_csv(
            [
                '2026-04-01 00:00:00,BluePeak Finance,ava.johnson@bluepeak.com,example.com/bluepeak/reports,Reports,Button: Run report',
            ],
            'spike.csv',
        )
        stdout = StringIO()
        try:
            call_command(
                'replay_page_naming_scenario',
                '--project-id',
                str(self.project.id),
                '--baseline-csv',
                str(baseline_csv),
                '--spike-csv',
                str(spike_csv),
                '--baseline-recent-span-seconds',
                '60',
                '--spike-recent-span-seconds',
                '60',
                '--spike-start-delay-seconds',
                '0',
                '--dry-run',
                stdout=stdout,
            )
        finally:
            baseline_dir.cleanup()
            spike_dir.cleanup()

        output = stdout.getvalue()
        self.assertIn('Baseline replay plan (dry-run)', output)
        self.assertIn('Spike replay plan (dry-run)', output)
        self.assertIn('Combined scenario plan (dry-run)', output)

    def test_live_scenario_replay_creates_events_from_both_streams(self):
        baseline_dir, baseline_csv = self._write_csv(
            [
                '2026-04-01 00:00:00,Acme Logistics,liam.smith@acme.com,example.com/acme/dashboard,Dashboard,Tab: Usage',
                '2026-04-01 00:01:00,Acme Logistics,liam.smith@acme.com,example.com/acme/accounts/123,Account 123,Link: Account details',
            ],
            'baseline.csv',
        )
        spike_dir, spike_csv = self._write_csv(
            [
                '2026-04-01 00:00:00,BluePeak Finance,ava.johnson@bluepeak.com,example.com/bluepeak/reports,Reports,Button: Run report',
                '2026-04-01 00:01:00,BluePeak Finance,ava.johnson@bluepeak.com,example.com/bluepeak/reports/usage,Usage report,Tab: Table',
            ],
            'spike.csv',
        )
        stdout = StringIO()
        try:
            call_command(
                'replay_page_naming_scenario',
                '--project-id',
                str(self.project.id),
                '--baseline-csv',
                str(baseline_csv),
                '--spike-csv',
                str(spike_csv),
                '--baseline-recent-span-seconds',
                '60',
                '--spike-recent-span-seconds',
                '60',
                '--spike-start-delay-seconds',
                '0',
                '--batch-size',
                '2',
                stdout=stdout,
            )
        finally:
            baseline_dir.cleanup()
            spike_dir.cleanup()

        self.assertEqual(AnalyticsEvent.objects.count(), 4)
        pages = list(AnalyticsEvent.objects.order_by('timestamp').values_list('url', flat=True))
        self.assertIn('https://example.com/acme/dashboard', pages)
        self.assertIn('https://example.com/bluepeak/reports', pages)
        page_keys = list(AnalyticsEvent.objects.order_by('timestamp').values_list('url_normalized', flat=True))
        self.assertIn('example.com/acme/dashboard', page_keys)
        self.assertIn('example.com/bluepeak/reports', page_keys)

