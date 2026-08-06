from django.core.management.base import BaseCommand, CommandError

from apps.pages import services, user_analytics
from apps.pages.user_detail_analytics import build_user_detail_cache
from apps.projects.demo import get_demo_project


class Command(BaseCommand):
    help = 'Rebuild cached User details payload for a project/user/range.'

    def add_arguments(self, parser):
        parser.add_argument('--project-id', type=int)
        parser.add_argument('--demo', action='store_true', help='Rebuild cache for the configured demo project.')
        parser.add_argument('--user-id')
        parser.add_argument('--range', dest='range_key', default='last_30_days')
        parser.add_argument(
            '--all-users',
            action='store_true',
            help='Rebuild detail cache for every user present in the cached Users overview payload for this range.',
        )
        parser.add_argument(
            '--all-ranges',
            action='store_true',
            help='Rebuild User details cache for all default analytics ranges.',
        )

    def handle(self, *args, **options):
        project_id = options['project_id']
        if options['demo']:
            project_id = get_demo_project().id
        if not project_id:
            raise CommandError('Provide --project-id or --demo.')

        range_key = options['range_key']
        if options['all_ranges'] or not range_key:
            range_keys = services.DEFAULT_OVERVIEW_RANGE_KEYS
        else:
            range_keys = (range_key,)

        user_id = str(options.get('user_id') or '').strip()
        if not user_id and not options['all_users']:
            raise CommandError('Provide --user-id or --all-users.')

        results = []
        try:
            if options['all_users']:
                for selected_range_key in range_keys:
                    result = user_analytics.hydrate_users_detail_cache(
                        project_id,
                        range_key=selected_range_key,
                    )
                    if result.get('status') == 'skipped':
                        reason = result.get('reason') or 'unknown'
                        raise CommandError(
                            f'Current Users overview cache is required for --all-users range {selected_range_key}: {reason}.'
                        )
                    results.append({
                        'project_id': project_id,
                        'range_key': selected_range_key,
                        **result,
                    })
            else:
                for selected_range_key in range_keys:
                    results.append(build_user_detail_cache(project_id, user_id, range_key=selected_range_key))
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        if len(results) == 1 and not options['all_users']:
            self.stdout.write(self.style.SUCCESS(f"User detail cache rebuilt: {results[0]}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"User detail caches rebuilt: {results}"))
