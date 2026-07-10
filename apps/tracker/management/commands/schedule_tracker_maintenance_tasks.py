from django.core.management.base import BaseCommand
from django_celery_beat.models import IntervalSchedule, PeriodicTask


class Command(BaseCommand):
    help = 'Create or update periodic Celery Beat tasks used by session replay analytics.'

    TASKS = (
        (
            'Bubble cache refresh',
            'apps.tracker.tasks.run_calculate_bubble_cache',
            5,
            IntervalSchedule.MINUTES,
        ),
        (
            'Calculate normalization factors daily',
            'apps.tracker.tasks.calculate_project_normalization_factors',
            1,
            IntervalSchedule.DAYS,
        ),
        (
            'Celery backend cleanup',
            'celery.backend_cleanup',
            1,
            IntervalSchedule.DAYS,
        ),
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--mode',
            choices=['real', 'fast'],
            default='real',
            help='Use production cadence or fast local-test cadence.',
        )

    def handle(self, *args, **options):
        is_fast = options['mode'] == 'fast'
        for name, task_path, every, period in self.TASKS:
            if is_fast:
                every, period = 30, IntervalSchedule.SECONDS
            schedule, _ = IntervalSchedule.objects.get_or_create(every=every, period=period)
            periodic_task, _ = PeriodicTask.objects.get_or_create(
                name=name,
                defaults={'task': task_path, 'interval': schedule, 'enabled': True},
            )
            periodic_task.task = task_path
            periodic_task.interval = schedule
            periodic_task.crontab = None
            periodic_task.clocked = None
            periodic_task.solar = None
            periodic_task.args = '[]'
            periodic_task.kwargs = '{}'
            periodic_task.one_off = False
            periodic_task.enabled = True
            periodic_task.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"Configured tracker maintenance tasks in {'fast' if is_fast else 'real'} mode."
            )
        )
