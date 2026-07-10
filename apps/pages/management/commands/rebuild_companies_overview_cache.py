from django.core.management.base import BaseCommand, CommandError

from apps.pages.company_analytics import build_companies_overview_cache
from apps.pages.services import DEFAULT_OVERVIEW_RANGE_KEYS


class Command(BaseCommand):
    help = 'Rebuild cached Companies overview payload for a project/range.'

    def add_arguments(self, parser):
        parser.add_argument('--project-id', type=int)
        parser.add_argument('--range', dest='range_key', default='last_30_days')
        parser.add_argument(
            '--all-ranges',
            action='store_true',
            help='Rebuild overview cache for all default Companies ranges.',
        )

    def handle(self, *args, **options):
        project_id = options['project_id']
        if not project_id:
            raise CommandError('Provide --project-id.')

        range_keys = DEFAULT_OVERVIEW_RANGE_KEYS if options['all_ranges'] else (options['range_key'],)
        results = []

        try:
            for range_key in range_keys:
                results.append(
                    build_companies_overview_cache(
                        project_id,
                        range_key=range_key,
                    )
                )
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        if options['all_ranges']:
            self.stdout.write(self.style.SUCCESS(f"Companies overview caches rebuilt: {results}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Companies overview cache rebuilt: {results[0]}"))
