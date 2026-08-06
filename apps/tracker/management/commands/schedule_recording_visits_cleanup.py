import json

from django.core.management.base import BaseCommand
from django_celery_beat.models import IntervalSchedule, PeriodicTask

from apps.tracker.visits_retention import (
    DEFAULT_RECORDING_VISITS_PRUNE_BATCH_SIZE,
    DEFAULT_RECORDING_VISITS_RETENTION_DAYS,
)


class Command(BaseCommand):
    help = 'Create or update the daily Recording Visits retention cleanup task.'

    PERIODIC_TASK_NAME = 'Recording Visits 30-day retention cleanup'
    TASK_PATH = 'apps.tracker.tasks.prune_expired_recording_visits_task'

    def add_arguments(self, parser):
        parser.add_argument(
            '--mode',
            choices=['real', 'fast'],
            default='real',
            help='Use daily production cadence or five-minute local-test cadence.',
        )

    def handle(self, *args, **options):
        is_fast = options['mode'] == 'fast'
        if is_fast:
            schedule, _ = IntervalSchedule.objects.get_or_create(
                every=5,
                period=IntervalSchedule.MINUTES,
            )
        else:
            schedule, _ = IntervalSchedule.objects.get_or_create(
                every=1,
                period=IntervalSchedule.DAYS,
            )

        kwargs = json.dumps({
            'retention_days': DEFAULT_RECORDING_VISITS_RETENTION_DAYS,
            'batch_size': DEFAULT_RECORDING_VISITS_PRUNE_BATCH_SIZE,
        })
        periodic_task, _ = PeriodicTask.objects.get_or_create(
            name=self.PERIODIC_TASK_NAME,
            defaults={
                'task': self.TASK_PATH,
                'interval': schedule,
                'args': '[]',
                'kwargs': kwargs,
                'enabled': True,
            },
        )
        periodic_task.task = self.TASK_PATH
        periodic_task.interval = schedule
        periodic_task.crontab = None
        periodic_task.clocked = None
        periodic_task.solar = None
        periodic_task.args = '[]'
        periodic_task.kwargs = kwargs
        periodic_task.one_off = False
        periodic_task.enabled = True
        periodic_task.save()

        cadence_label = 'fast' if is_fast else 'real'
        self.stdout.write(
            self.style.SUCCESS(
                'Configured Recording Visits retention cleanup in '
                f'{cadence_label} mode: {schedule} '
                f'(task id {periodic_task.id}).'
            )
        )
