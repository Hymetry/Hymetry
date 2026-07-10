import json
from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from django_celery_beat.models import ClockedSchedule, PeriodicTask


class SchedulePagesAnalyticsTasksCommandTests(TestCase):
    def test_command_replaces_clocked_schedule_with_interval_schedule(self):
        clocked = ClockedSchedule.objects.create(
            clocked_time=timezone.now() + timedelta(hours=1),
        )

        for name in (
            'Pages analytics rolling rebuild',
            'Pages analytics nightly backfill',
        ):
            PeriodicTask.objects.create(
                name=name,
                task='old.task',
                clocked=clocked,
                one_off=True,
                enabled=False,
            )

        call_command('schedule_pages_analytics_tasks', mode='real')

        rolling_task = PeriodicTask.objects.get(name='Pages analytics rolling rebuild')
        self.assertEqual(rolling_task.task, 'apps.pages.tasks.refresh_recent_pages_analytics_task')
        self.assertIsNotNone(rolling_task.interval)
        self.assertIsNone(rolling_task.crontab)
        self.assertIsNone(rolling_task.clocked)
        self.assertIsNone(rolling_task.solar)
        self.assertFalse(rolling_task.one_off)
        self.assertTrue(rolling_task.enabled)
        rolling_kwargs = json.loads(rolling_task.kwargs)
        self.assertEqual(rolling_kwargs['lookback_days'], 2)
        self.assertEqual(rolling_kwargs['active_since_days'], 2)
        self.assertEqual(
            rolling_kwargs['range_keys'],
            ['last_7_days', 'last_30_days', 'last_90_days', 'last_180_days'],
        )
        self.assertEqual(rolling_kwargs['exclude_project_ids'], [])

        nightly_task = PeriodicTask.objects.get(name='Pages analytics nightly backfill')
        self.assertEqual(nightly_task.task, 'apps.pages.tasks.refresh_recent_pages_analytics_task')
        self.assertIsNotNone(nightly_task.interval)
        self.assertIsNone(nightly_task.crontab)
        self.assertIsNone(nightly_task.clocked)
        self.assertIsNone(nightly_task.solar)
        self.assertFalse(nightly_task.one_off)
        self.assertTrue(nightly_task.enabled)
        nightly_kwargs = json.loads(nightly_task.kwargs)
        self.assertEqual(nightly_kwargs['lookback_days'], 180)
        self.assertEqual(nightly_kwargs['active_since_days'], 180)
        self.assertEqual(
            nightly_kwargs['range_keys'],
            ['last_7_days', 'last_30_days', 'last_90_days', 'last_180_days'],
        )
        self.assertEqual(nightly_kwargs['exclude_project_ids'], [])
