from django.core.management.base import BaseCommand, CommandError

from apps.pages.services import DEFAULT_OVERVIEW_RANGE_KEYS, build_pages_overview_cache


class Command(BaseCommand):
    help = 'Rebuild cached Pages overview payload for a project/range.'

    def add_arguments(self, parser):
        parser.add_argument('--project-id', type=int, required=True)
        parser.add_argument('--range', dest='range_key', default='last_30_days')
        parser.add_argument(
            '--all-ranges',
            action='store_true',
            help='Rebuild overview cache for all default Pages ranges.',
        )
        parser.add_argument('--start-date')
        parser.add_argument('--end-date')

    def handle(self, *args, **options):
        range_keys = DEFAULT_OVERVIEW_RANGE_KEYS if options['all_ranges'] else (options['range_key'],)
        results = []

        try:
            for range_key in range_keys:
                results.append(
                    build_pages_overview_cache(
                        options['project_id'],
                        range_key=range_key,
                        start_date=options.get('start_date'),
                        end_date=options.get('end_date'),
                    )
                )
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        if options['all_ranges']:
            self.stdout.write(self.style.SUCCESS(f"Pages overview caches rebuilt: {results}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Pages overview cache rebuilt: {results[0]}"))
