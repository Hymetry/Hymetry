"""
Verify the memoized at-risk user series against the unmemoized computation.

The memo behind `_daily_at_risk_user_count_series` is shared between two
callers that ask different questions about the same company: a peer chart
passes every user, while the company's own page leaves out users who have
dropped. Its key therefore carries the resolved user set, and the risk being
checked here is that key failing to tell those apart and serving one caller's
answer to the other.

Every series is computed once with the memo bypassed, then again through the
memo inside a single long-lived scope, in the interleaved order a rebuild
produces. Read only: nothing is written.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.pages import services
from apps.pages.analytics_memo import analytics_memo_scope
from apps.pages.company_detail_analytics import (
    _daily_at_risk_user_count_series,
    _daily_at_risk_user_count_series_uncached,
    _user_base_queryset,
)
from apps.projects.demo import get_demo_project
from apps.projects.models import Project


class Command(BaseCommand):
    help = 'Verify the memoized at-risk user series matches the direct computation.'

    def add_arguments(self, parser):
        parser.add_argument('--project-id', type=int)
        parser.add_argument('--demo', action='store_true')
        parser.add_argument('--range', dest='range_key')
        parser.add_argument(
            '--limit',
            type=int,
            default=40,
            help='Companies per range. 0 checks every company (slow: no memo on the oracle side).',
        )

    def handle(self, *args, **options):
        project_id = options['project_id']
        if options['demo']:
            project_id = get_demo_project().id
        if not project_id:
            raise CommandError('Provide --project-id or --demo.')

        project = Project.active.filter(pk=project_id).first()
        if project is None:
            raise CommandError(f'Project {project_id} does not exist.')

        range_keys = (
            (options['range_key'],)
            if options['range_key']
            else services.DEFAULT_OVERVIEW_RANGE_KEYS
        )

        self.stdout.write(
            f'Verifying at-risk user series for project {project.id} "{project.name}". '
            'Read only: nothing is written.'
        )

        compared = 0
        mismatched = 0
        for range_key in range_keys:
            range_compared, range_mismatched = self._check_range(
                project, range_key, limit=options['limit'],
            )
            compared += range_compared
            mismatched += range_mismatched

        self.stdout.write('')
        if mismatched:
            self.stdout.write(self.style.ERROR(
                f'{mismatched:,} of {compared:,} series differ. The memo key is not '
                'separating callers correctly.'
            ))
            raise CommandError('At-risk series parity check failed.')
        self.stdout.write(self.style.SUCCESS(
            f'All {compared:,} series match the unmemoized computation.'
        ))

    def _check_range(self, project, range_key, *, limit):
        start_date, end_date = services.resolve_period(project.timezone, range_key=range_key)
        previous_start, previous_end = services.previous_period(start_date, end_date)

        company_ids = list(
            _user_base_queryset(project.id, start_date, end_date)
            .exclude(company_id__isnull=True)
            .exclude(company_id='')
            .values_list('company_id', flat=True)
            .distinct()
            .order_by('company_id')
        )
        if limit:
            company_ids = company_ids[:limit]

        cases = []
        for company_id in company_ids:
            user_ids = [
                str(user_id)
                for user_id in (
                    _user_base_queryset(project.id, start_date, end_date)
                    .filter(company_id=company_id)
                    .values_list('user_id', flat=True)
                    .distinct()
                    .order_by('user_id')
                )
                if user_id not in (None, '')
            ]
            if not user_ids:
                continue

            # How a peer chart asks: every user counts.
            peer_users = [{'id': user_id, 'riskStatus': 'active'} for user_id in user_ids]
            # How the company's own page asks: dropped users are left out. Half
            # the users are marked dropped so the two sets genuinely differ,
            # which is the case a too-coarse key would confuse.
            own_users = [
                {'id': user_id, 'riskStatus': 'dropped' if index % 2 else 'active'}
                for index, user_id in enumerate(user_ids)
            ]
            cases.append((str(company_id), peer_users, own_users))

        if not cases:
            self.stdout.write('')
            self.stdout.write(f'Range {range_key}: no companies with users.')
            return 0, 0

        # Ground truth with the memo bypassed entirely.
        expected = {}
        for company_id, peer_users, own_users in cases:
            for label, users in (('peer', peer_users), ('own', own_users)):
                resolved = frozenset(
                    str(user['id'])
                    for user in users
                    if user.get('riskStatus') != 'dropped'
                )
                expected[(company_id, label)] = _daily_at_risk_user_count_series_uncached(
                    project.id,
                    company_id,
                    resolved,
                    start_date,
                    end_date,
                    previous_start,
                    previous_end,
                )

        compared = 0
        mismatched = 0
        # One scope for the whole range, as a rebuild has, so a key collision
        # between companies or between the two callers would surface.
        with analytics_memo_scope():
            for label in ('peer', 'own', 'peer', 'own'):
                for company_id, peer_users, own_users in cases:
                    users = peer_users if label == 'peer' else own_users
                    actual = _daily_at_risk_user_count_series(
                        project.id,
                        company_id,
                        users,
                        start_date,
                        end_date,
                        previous_start,
                        previous_end,
                    )
                    compared += 1
                    if actual != expected[(company_id, label)]:
                        mismatched += 1
                        if mismatched <= 5:
                            self.stdout.write(self.style.ERROR(
                                f'  MISMATCH range={range_key} company={company_id} '
                                f'caller={label}'
                            ))

        self.stdout.write('')
        self.stdout.write(
            f'Range {range_key}: {len(cases)} companies, '
            f'{compared:,} series compared, {mismatched:,} differ.'
        )
        return compared, mismatched
