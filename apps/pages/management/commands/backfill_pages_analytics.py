from django.core.management.base import BaseCommand, CommandError

from apps.pages.services import rebuild_project_pages_analytics


class Command(BaseCommand):
    help = 'Backfill prepared Pages analytics for a project/date range.'

    def add_arguments(self, parser):
        parser.add_argument('--project-id', type=int, required=True)
        parser.add_argument('--start-date', required=True)
        parser.add_argument('--end-date', required=True)

    def handle(self, *args, **options):
        try:
            result = rebuild_project_pages_analytics(
                options['project_id'],
                options['start_date'],
                options['end_date'],
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(f"Pages analytics backfill finished: {result}"))

