from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from django_celery_beat.models import ClockedSchedule, PeriodicTask


class SchedulePageNamingTasksCommandTests(TestCase):
    def test_command_replaces_clocked_schedule_with_interval_schedule(self):
        clocked = ClockedSchedule.objects.create(
            clocked_time=timezone.now() + timedelta(hours=1),
        )

        for name in (
            'Page naming unstable projects',
            'Page naming delayed analytics title backfill',
            'Page naming stable projects',
        ):
            PeriodicTask.objects.create(
                name=name,
                task='old.task',
                clocked=clocked,
                one_off=True,
                enabled=False,
            )

        call_command('schedule_page_naming_tasks', mode='real')

        unstable_task = PeriodicTask.objects.get(name='Page naming unstable projects')
        self.assertEqual(unstable_task.task, 'apps.tracker.tasks.run_hourly_page_naming')
        self.assertIsNotNone(unstable_task.interval)
        self.assertIsNone(unstable_task.crontab)
        self.assertIsNone(unstable_task.clocked)
        self.assertIsNone(unstable_task.solar)
        self.assertFalse(unstable_task.one_off)
        self.assertTrue(unstable_task.enabled)

        title_backfill_task = PeriodicTask.objects.get(name='Page naming delayed analytics title backfill')
        self.assertEqual(title_backfill_task.task, 'apps.tracker.tasks.run_hourly_page_title_backfill')
        self.assertIsNotNone(title_backfill_task.interval)
        self.assertIsNone(title_backfill_task.crontab)
        self.assertIsNone(title_backfill_task.clocked)
        self.assertIsNone(title_backfill_task.solar)
        self.assertFalse(title_backfill_task.one_off)
        self.assertTrue(title_backfill_task.enabled)

        stable_task = PeriodicTask.objects.get(name='Page naming stable projects')
        self.assertEqual(stable_task.task, 'apps.tracker.tasks.run_daily_page_naming')
        self.assertIsNotNone(stable_task.interval)
        self.assertIsNone(stable_task.crontab)
        self.assertIsNone(stable_task.clocked)
        self.assertIsNone(stable_task.solar)
        self.assertFalse(stable_task.one_off)
        self.assertTrue(stable_task.enabled)
