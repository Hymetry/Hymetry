"""
Compare benchmark series computed the old way against the index-backed way.

The unit tests compare the two implementations on synthetic pools. This runs
them against a real project's own data, over every default range and every
benchmarked metric, comparing dates and values point by point. It reads only:
no cache row is written and no payload is stored.
"""

from time import perf_counter

from django.core.management.base import BaseCommand, CommandError

from apps.pages import company_analytics, services
from apps.pages.company_detail_analytics import (
    BulkCompanyDetailContext,
    _benchmark_metric_series,
    _benchmark_metric_series_from_index,
    _benchmark_series_index,
    _copy_company_detail_row,
    _peer_active_users,
)
from apps.projects.demo import get_demo_project
from apps.projects.models import Project

BENCHMARKED_METRICS = (
    'activeUsers',
    'avgPerUser',
    'adoptionBreadth',
    'visits',
    'engaged',
    'interaction',
)


class Command(BaseCommand):
    help = 'Verify the index-backed benchmark series matches the original, on real data.'

    def add_arguments(self, parser):
        parser.add_argument('--project-id', type=int)
        parser.add_argument('--demo', action='store_true')
        parser.add_argument('--range', dest='range_key')
        parser.add_argument(
            '--limit',
            type=int,
            default=0,
            help='Check only the first N companies per range. 0 checks every company.',
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
            f'Comparing benchmark series for project {project.id} "{project.name}". '
            'Read only: nothing is written.'
        )

        total_compared = 0
        total_mismatched = 0
        for range_key in range_keys:
            compared, mismatched = self._check_range(
                project, range_key, limit=options['limit'],
            )
            total_compared += compared
            total_mismatched += mismatched

        self.stdout.write('')
        if total_mismatched:
            self.stdout.write(self.style.ERROR(
                f'{total_mismatched:,} of {total_compared:,} series differ. Do not ship.'
            ))
            raise CommandError('Benchmark series parity check failed.')
        self.stdout.write(self.style.SUCCESS(
            f'All {total_compared:,} series match, dates and values.'
        ))

    def _check_range(self, project, range_key, *, limit):
        overview = company_analytics.build_companies_overview_payload(project, range_key=range_key)
        bulk_context = BulkCompanyDetailContext(
            project, range_key=range_key, overview_payload=overview,
        )
        company_rows = [_copy_company_detail_row(row) for row in bulk_context.company_rows()]
        pool = [row for row in company_rows if _peer_active_users(row) > 0]
        subjects = company_rows[:limit] if limit else company_rows

        metric_company_ids = [str(row['id']) for row in company_rows]
        daily_by_company = bulk_context.daily_company_values(
            metric_company_ids, active_user_company_ids=metric_company_ids,
        )

        self.stdout.write('')
        self.stdout.write(
            f'Range {range_key}: {len(subjects)} companies checked '
            f'against a pool of {len(pool)}.'
        )

        compared = 0
        mismatched = 0
        old_seconds = 0.0
        new_seconds = 0.0

        for key in BENCHMARKED_METRICS:
            started = perf_counter()
            index = _benchmark_series_index(pool, daily_by_company, key)
            index_seconds = perf_counter() - started

            for row in subjects:
                company_id = str(row['id'])
                benchmark_companies = [
                    peer for peer in pool if str(peer['id']) != company_id
                ]

                started = perf_counter()
                expected = _benchmark_metric_series(benchmark_companies, daily_by_company, key)
                old_seconds += perf_counter() - started

                started = perf_counter()
                actual = _benchmark_metric_series_from_index(index, company_id)
                new_seconds += perf_counter() - started

                compared += 1
                if actual != expected:
                    mismatched += 1
                    if mismatched <= 5:
                        self._report_difference(range_key, key, company_id, expected, actual)

            new_seconds += index_seconds

        speedup = (old_seconds / new_seconds) if new_seconds else 0
        self.stdout.write(
            f'  {compared:,} series compared, {mismatched:,} differ. '
            f'old {old_seconds:.2f}s, new {new_seconds:.2f}s ({speedup:.1f}x)'
        )
        return compared, mismatched

    def _report_difference(self, range_key, key, company_id, expected, actual):
        self.stdout.write(self.style.ERROR(
            f'  MISMATCH range={range_key} metric={key} company={company_id}: '
            f'lengths {len(expected)} vs {len(actual)}'
        ))
        for position, (want, got) in enumerate(zip(expected, actual)):
            if want != got:
                self.stdout.write(self.style.ERROR(
                    f'    point {position}: expected {want} got {got}'
                ))
                break
