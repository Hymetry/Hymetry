import json

from django.core.management.base import BaseCommand
from django_celery_beat.models import IntervalSchedule, PeriodicTask

from apps.pages.services import DEFAULT_OVERVIEW_RANGE_KEYS
class Command(BaseCommand):
    help = 'Create or update periodic Celery Beat tasks for prepared Pages analytics.'

    ROLLING_TASK_NAME = 'Pages analytics rolling rebuild'
    NIGHTLY_TASK_NAME = 'Pages analytics nightly backfill'
    TASK_PATH = 'apps.pages.tasks.refresh_recent_pages_analytics_task'
    RANGE_KEYS = DEFAULT_OVERVIEW_RANGE_KEYS

    def add_arguments(self, parser):
        parser.add_argument(
            '--mode',
            choices=['real', 'fast'],
            default='real',
            help='Use production cadence or fast local-test cadence.',
        )

    def handle(self, *args, **options):
        is_fast = options['mode'] == 'fast'

        if is_fast:
            rolling_schedule, _ = IntervalSchedule.objects.get_or_create(
                every=60,
                period=IntervalSchedule.SECONDS,
            )
            nightly_schedule, _ = IntervalSchedule.objects.get_or_create(
                every=5,
                period=IntervalSchedule.MINUTES,
            )
        else:
            rolling_schedule, _ = IntervalSchedule.objects.get_or_create(
                every=1,
                period=IntervalSchedule.HOURS,
            )
            nightly_schedule, _ = IntervalSchedule.objects.get_or_create(
                every=1,
                period=IntervalSchedule.DAYS,
            )

        rolling_task = self._save_interval_task(
            name=self.ROLLING_TASK_NAME,
            schedule=rolling_schedule,
            kwargs={
                'lookback_days': 2,
                'active_since_days': 2,
                'range_keys': list(self.RANGE_KEYS),
                'exclude_project_ids': [],
            },
        )
        nightly_task = self._save_interval_task(
            name=self.NIGHTLY_TASK_NAME,
            schedule=nightly_schedule,
            kwargs={
                'lookback_days': 180,
                'active_since_days': 180,
                'range_keys': list(self.RANGE_KEYS),
                'exclude_project_ids': [],
            },
        )

        cadence_label = 'fast' if is_fast else 'real'
        self.stdout.write(
            self.style.SUCCESS(
                f'Configured Pages analytics periodic tasks in {cadence_label} mode. '
                f'Rolling: {rolling_schedule} (task id {rolling_task.id}). '
                f'Nightly: {nightly_schedule} (task id {nightly_task.id}).'
            )
        )

    def _save_interval_task(self, *, name, schedule, kwargs):
        serialized_kwargs = json.dumps(kwargs)
        periodic_task, _ = PeriodicTask.objects.get_or_create(
            name=name,
            defaults={
                'task': self.TASK_PATH,
                'interval': schedule,
                'args': '[]',
                'kwargs': serialized_kwargs,
                'enabled': True,
            },
        )
        periodic_task.task = self.TASK_PATH
        periodic_task.interval = schedule
        periodic_task.crontab = None
        periodic_task.clocked = None
        periodic_task.solar = None
        periodic_task.args = '[]'
        periodic_task.kwargs = serialized_kwargs
        periodic_task.one_off = False
        periodic_task.enabled = True
        periodic_task.save()
        return periodic_task
