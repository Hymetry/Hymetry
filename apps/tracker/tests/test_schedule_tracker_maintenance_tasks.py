from django.core.management import call_command
from django.test import TestCase
from django_celery_beat.models import IntervalSchedule, PeriodicTask


class ScheduleTrackerMaintenanceTasksTests(TestCase):
    def test_legacy_projection_tasks_remain_disabled(self):
        schedule = IntervalSchedule.objects.create(
            every=5,
            period=IntervalSchedule.MINUTES,
        )
        legacy = PeriodicTask.objects.create(
            name='Bubble cache refresh',
            task='apps.tracker.tasks.run_calculate_bubble_cache',
            interval=schedule,
            enabled=True,
        )

        call_command('schedule_tracker_maintenance_tasks', mode='real')

        legacy.refresh_from_db()
        self.assertFalse(legacy.enabled)
        cleanup = PeriodicTask.objects.get(name='Celery backend cleanup')
        self.assertTrue(cleanup.enabled)
        self.assertEqual(cleanup.task, 'celery.backend_cleanup')
