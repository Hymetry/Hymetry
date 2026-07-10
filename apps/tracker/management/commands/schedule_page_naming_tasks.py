from django.core.management.base import BaseCommand
from django_celery_beat.models import IntervalSchedule, PeriodicTask


class Command(BaseCommand):
    help = 'Create or update periodic Celery Beat tasks for page naming'

    UNSTABLE_TASK_NAME = 'Page naming unstable projects'
    STABLE_TASK_NAME = 'Page naming stable projects'
    TITLE_BACKFILL_TASK_NAME = 'Page naming delayed analytics title backfill'

    def _save_interval_task(self, periodic_task, task_name, schedule):
        periodic_task.task = task_name
        periodic_task.interval = schedule
        periodic_task.crontab = None
        periodic_task.clocked = None
        periodic_task.solar = None
        periodic_task.one_off = False
        periodic_task.enabled = True
        periodic_task.save()

    def add_arguments(self, parser):
        parser.add_argument(
            '--mode',
            choices=['real', 'fast'],
            default='real',
            help='Use real production-like cadence or fast local-test cadence.',
        )
    def handle(self, *args, **options):
        mode = options['mode']
        is_fast = mode == 'fast'

        if is_fast:
            unstable_schedule, _ = IntervalSchedule.objects.get_or_create(
                every=20,
                period=IntervalSchedule.SECONDS,
            )
            title_backfill_schedule = unstable_schedule
            stable_schedule, _ = IntervalSchedule.objects.get_or_create(
                every=60,
                period=IntervalSchedule.SECONDS,
            )
        else:
            unstable_schedule, _ = IntervalSchedule.objects.get_or_create(
                every=1,
                period=IntervalSchedule.HOURS,
            )
            title_backfill_schedule = unstable_schedule
            stable_schedule, _ = IntervalSchedule.objects.get_or_create(
                every=1,
                period=IntervalSchedule.DAYS,
            )

        unstable_task, unstable_created = PeriodicTask.objects.get_or_create(
            name=self.UNSTABLE_TASK_NAME,
            defaults={
                'task': 'apps.tracker.tasks.run_hourly_page_naming',
                'interval': unstable_schedule,
                'enabled': True,
            },
        )
        if not unstable_created:
            self._save_interval_task(
                unstable_task,
                'apps.tracker.tasks.run_hourly_page_naming',
                unstable_schedule,
            )

        title_backfill_task, title_backfill_created = PeriodicTask.objects.get_or_create(
            name=self.TITLE_BACKFILL_TASK_NAME,
            defaults={
                'task': 'apps.tracker.tasks.run_hourly_page_title_backfill',
                'interval': title_backfill_schedule,
                'enabled': True,
            },
        )
        if not title_backfill_created:
            self._save_interval_task(
                title_backfill_task,
                'apps.tracker.tasks.run_hourly_page_title_backfill',
                title_backfill_schedule,
            )

        stable_task, stable_created = PeriodicTask.objects.get_or_create(
            name=self.STABLE_TASK_NAME,
            defaults={
                'task': 'apps.tracker.tasks.run_daily_page_naming',
                'interval': stable_schedule,
                'enabled': True,
            },
        )
        if not stable_created:
            self._save_interval_task(
                stable_task,
                'apps.tracker.tasks.run_daily_page_naming',
                stable_schedule,
            )

        cadence_label = 'fast' if is_fast else 'real'
        self.stdout.write(
            self.style.SUCCESS(
                f'Configured page naming periodic tasks in {cadence_label} mode. '
                f'Unstable: {unstable_schedule}. Title backfill: {title_backfill_schedule}. Stable: {stable_schedule}.'
            )
        )
