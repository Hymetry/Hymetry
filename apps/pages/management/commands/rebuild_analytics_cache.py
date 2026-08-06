from django.core.management.base import BaseCommand, CommandError

from apps.pages import services
from apps.projects.demo import get_demo_project


class Command(BaseCommand):
    help = 'Rebuild cached analytics payloads for Pages, Companies, and Users.'

    def add_arguments(self, parser):
        parser.add_argument('--project-id', type=int)
        parser.add_argument('--demo', action='store_true', help='Rebuild cache for the configured demo project.')
        parser.add_argument('--range', dest='range_key')
        parser.add_argument(
            '--all-ranges',
            action='store_true',
            help='Rebuild cache for all default analytics ranges. This is the default when --range is omitted.',
        )
        parser.add_argument(
            '--include-user-details',
            action='store_true',
            help='Also rebuild individual User details cache for every user in the selected ranges.',
        )

    def handle(self, *args, **options):
        project_id = options['project_id']
        if options['demo']:
            project_id = get_demo_project().id
        if not project_id:
            raise CommandError('Provide --project-id or --demo.')

        range_key = options.get('range_key')
        if options['all_ranges'] or not range_key:
            range_keys = services.DEFAULT_OVERVIEW_RANGE_KEYS
        else:
            range_keys = (range_key,)

        try:
            result = services.rebuild_project_analytics_caches(
                project_id,
                range_keys=range_keys,
                include_user_details=options['include_user_details'],
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(f"Analytics caches rebuilt: {result}"))
