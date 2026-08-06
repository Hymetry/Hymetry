"""
Profile a full analytics cache rebuild against the configured database.

Everything measured so far came from a SQLite harness, which turned out to
misreport at least one major cost: SQLite parses dates in Python because it has
no date type, so its profile shows converter work that PostgreSQL never does.
This runs the real rebuild against the real database and reports where the time
goes, so the next change is chosen from production numbers.
"""

import cProfile
import pstats
import re
from collections import deque
from io import StringIO
from time import perf_counter

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.pages import services
from apps.projects.demo import get_demo_project
from apps.projects.models import Project

_LITERAL = re.compile(r"'[^']*'|\b\d+\b")
_WHITESPACE = re.compile(r'\s+')


def _format_duration(seconds):
    seconds = float(seconds or 0)
    if seconds < 1:
        return f'{seconds * 1000:.0f}ms'
    if seconds < 60:
        return f'{seconds:.2f}s'
    minutes, remainder = divmod(seconds, 60)
    return f'{int(minutes)}m {remainder:.1f}s'


def _query_shape(sql, width=110):
    """Collapse a statement to a comparable shape by dropping its literals."""

    shape = _WHITESPACE.sub(' ', _LITERAL.sub('?', sql or '')).strip()
    return shape[:width]


class Command(BaseCommand):
    help = 'Profile a full analytics cache rebuild and report where its time goes.'

    def add_arguments(self, parser):
        parser.add_argument('--project-id', type=int)
        parser.add_argument('--demo', action='store_true', help='Profile the configured demo project.')
        parser.add_argument('--range', dest='range_key', help='Profile a single range instead of all.')
        parser.add_argument(
            '--include-user-details',
            action='store_true',
            help='Also rebuild per-user detail caches, as the scheduled job can.',
        )
        parser.add_argument(
            '--top',
            type=int,
            default=25,
            help='How many profiled frames to show per table (default: 25).',
        )
        parser.add_argument(
            '--skip-profile',
            action='store_true',
            help='Only take the timed pass. Use when the profiler overhead is unwelcome.',
        )
        parser.add_argument(
            '--query-limit',
            type=int,
            default=200_000,
            help=(
                'How many queries to retain for the database total and shape table. '
                'Raise it if the run reports hitting the limit (default: 200000).'
            ),
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
        include_user_details = options['include_user_details']

        self.stdout.write(
            f'Profiling rebuild for project {project.id} "{project.name}" '
            f'on {connection.vendor}, ranges={list(range_keys)}, '
            f'include_user_details={include_user_details}.'
        )
        self.stdout.write(
            self.style.WARNING(
                'This writes cache rows, exactly as the real command does, and takes '
                'the project rebuild lock. Do not run it alongside a scheduled rebuild.'
            )
        )

        def rebuild():
            return services.rebuild_project_analytics_caches(
                project.id,
                range_keys=range_keys,
                include_user_details=include_user_details,
            )

        self._timed_pass(rebuild, query_limit=options['query_limit'])
        if not options['skip_profile']:
            self._profiled_pass(rebuild, top=options['top'])

    def _timed_pass(self, rebuild, *, query_limit):
        """Wall clock and database share, without profiler distortion."""

        self.stdout.write('')
        self.stdout.write('=== timed pass (no profiler) ===')

        # Django keeps only the last `queries_limit` entries and warns once it
        # starts discarding. A rebuild that issues a query per company blows
        # through the 9000 default, which silently undercounts the database
        # share and leaves the shape table describing only the tail of the run.
        #
        # The log is a deque sized at connection setup, so raising the limit
        # alone changes nothing: the deque has to be replaced to widen it.
        previous_limit = connection.queries_limit
        previous_log = connection.queries_log
        connection.queries_limit = query_limit
        connection.queries_log = deque(previous_log, maxlen=query_limit)
        try:
            started = perf_counter()
            with CaptureQueriesContext(connection) as captured:
                result = rebuild()
            wall = perf_counter() - started
            queries = list(captured.captured_queries)
        finally:
            connection.queries_limit = previous_limit
            connection.queries_log = previous_log

        db_seconds = sum(float(entry.get('time') or 0) for entry in queries)
        python_seconds = max(0.0, wall - db_seconds)
        db_share = (db_seconds / wall * 100) if wall else 0

        self._warn_on_skips(result)
        if len(queries) >= query_limit:
            self.stdout.write(
                self.style.ERROR(
                    f'Hit the {query_limit:,} query capture limit, so the database total '
                    'below counts only the tail of the run. Re-run with a higher '
                    '--query-limit for a complete figure.'
                )
            )
        self.stdout.write(f'wall      : {_format_duration(wall)}')
        self.stdout.write(
            f'database  : {_format_duration(db_seconds)} ({db_share:.0f}%) '
            f'across {len(queries):,} queries'
        )
        self.stdout.write(
            f'python    : {_format_duration(python_seconds)} ({100 - db_share:.0f}%)'
        )
        self.stdout.write(
            '            capturing queries times every statement individually, so on a '
            'query-heavy rebuild the wall figure carries some of that overhead.'
        )
        self._report_query_shapes(queries)

    def _warn_on_skips(self, result):
        """A lock miss returns success with a skip reason and no rebuilt payload."""

        skipped = [
            entry
            for key in ('cache_results', 'companies_cache_results', 'users_cache_results')
            for entry in (result or {}).get(key) or []
            if isinstance(entry, dict) and entry.get('reason') == 'lock_not_acquired'
        ]
        if skipped:
            self.stdout.write(
                self.style.ERROR(
                    f'{len(skipped)} builder(s) skipped on the project lock. '
                    'Timings below are not a full rebuild; rerun when nothing else holds it.'
                )
            )

    def _report_query_shapes(self, queries, limit=12):
        by_shape = {}
        for entry in queries:
            shape = _query_shape(entry.get('sql'))
            bucket = by_shape.setdefault(shape, [0, 0.0])
            bucket[0] += 1
            bucket[1] += float(entry.get('time') or 0)

        ranked = sorted(by_shape.items(), key=lambda item: -item[1][1])[:limit]
        if not ranked:
            return

        self.stdout.write('')
        self.stdout.write(f'slowest query shapes (top {len(ranked)} of {len(by_shape)}):')
        self.stdout.write(f'  {"total":>8}  {"calls":>6}  {"each":>8}  statement')
        for shape, (count, seconds) in ranked:
            each = seconds / count if count else 0
            self.stdout.write(
                f'  {_format_duration(seconds):>8}  {count:>6}  {_format_duration(each):>8}  {shape}'
            )

        # A rebuild that queries per company or per user shows up here as a
        # large call count rather than a slow statement, and no amount of
        # tuning the statement itself will help.
        repeated = sorted(
            (item for item in by_shape.items() if item[1][0] >= 100),
            key=lambda item: -item[1][0],
        )[:limit]
        if repeated:
            self.stdout.write('')
            self.stdout.write(f'most repeated query shapes (top {len(repeated)}):')
            self.stdout.write(f'  {"calls":>6}  {"total":>8}  {"each":>8}  statement')
            for shape, (count, seconds) in repeated:
                each = seconds / count if count else 0
                self.stdout.write(
                    f'  {count:>6}  {_format_duration(seconds):>8}  {_format_duration(each):>8}  {shape}'
                )

    def _profiled_pass(self, rebuild, *, top):
        """Frame breakdown. Absolute times here are inflated by the profiler."""

        self.stdout.write('')
        self.stdout.write('=== profiled pass (times inflated; read the proportions) ===')
        profiler = cProfile.Profile()
        profiler.enable()
        rebuild()
        profiler.disable()

        for sort_key, title in (
            ('tottime', 'by self time'),
            ('cumulative', 'by cumulative time, project code only'),
        ):
            stream = StringIO()
            stats = pstats.Stats(profiler, stream=stream)
            stats.sort_stats(sort_key)
            self.stdout.write('')
            self.stdout.write(f'--- {title} ---')
            if sort_key == 'cumulative':
                stats.print_stats(r'apps[\\/]pages', top)
            else:
                stats.print_stats(top)
            self.stdout.write(stream.getvalue())
