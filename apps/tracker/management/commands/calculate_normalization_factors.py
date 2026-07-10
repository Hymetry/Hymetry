from django.core.management.base import BaseCommand
from apps.tracker.tasks import calculate_project_normalization_factors


class Command(BaseCommand):
    help = 'Calculate normalization factors for all projects and cache them'

    def add_arguments(self, parser):
        parser.add_argument(
            '--async',
            action='store_true',
            help='Run the calculation asynchronously using Celery',
        )
        parser.add_argument(
            '--schedule',
            action='store_true',
            help='Schedule the task to run daily using Celery Beat',
        )

    def handle(self, *args, **options):
        if options['schedule']:
            # Schedule the task to run daily
            from django_celery_beat.models import PeriodicTask, IntervalSchedule

            # Create or get the interval schedule (daily)
            schedule, created = IntervalSchedule.objects.get_or_create(
                every=1,
                period=IntervalSchedule.DAYS,
            )
            
            # Create or update the periodic task
            task, created = PeriodicTask.objects.get_or_create(
                name='Calculate normalization factors daily',
                defaults={
                    'task': 'apps.tracker.tasks.calculate_project_normalization_factors',
                    'interval': schedule,
                    'enabled': True,
                }
            )
            
            if not created:
                task.interval = schedule
                task.save()
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully scheduled normalization factor calculation to run daily. Task ID: {task.id}'
                )
            )
            
        elif options['async']:
            # Run asynchronously using Celery
            task = calculate_project_normalization_factors.delay()
            self.stdout.write(
                self.style.SUCCESS(
                    f'Started async calculation of normalization factors. Task ID: {task.id}'
                )
            )
        else:
            # Run synchronously
            self.stdout.write('Calculating normalization factors for all projects...')
            result = calculate_project_normalization_factors()
            
            if isinstance(result, dict):
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Successfully calculated normalization factors for {len(result)} projects'
                    )
                )
                for project_id, k in result.items():
                    self.stdout.write(f'  Project {project_id}: {k}')
            else:
                self.stdout.write(
                    self.style.ERROR(f'Error: {result}')
                )
