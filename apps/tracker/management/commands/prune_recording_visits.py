from django.core.management.base import BaseCommand, CommandError

from apps.tracker.visits_retention import (
    DEFAULT_RECORDING_VISITS_PRUNE_BATCH_SIZE,
    DEFAULT_RECORDING_VISITS_RETENTION_DAYS,
    prune_expired_recording_visits,
)


class Command(BaseCommand):
    help = (
        'Permanently delete recording Sessions older than the configured '
        'retention period, including their rrweb events. Analytics data is retained.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--retention-days',
            type=int,
            default=DEFAULT_RECORDING_VISITS_RETENTION_DAYS,
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=DEFAULT_RECORDING_VISITS_PRUNE_BATCH_SIZE,
        )
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Permanently delete matched recording Visits.',
        )

    def handle(self, *args, **options):
        if options['dry_run'] and options['apply']:
            raise CommandError('--dry-run and --apply cannot be combined')
        dry_run = options['dry_run'] or not options['apply']
        try:
            result = prune_expired_recording_visits(
                retention_days=options['retention_days'],
                batch_size=options['batch_size'],
                dry_run=dry_run,
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        style = self.style.WARNING if result['dry_run'] else self.style.SUCCESS
        self.stdout.write(
            style(
                'Recording Visits retention '
                f"{'dry run' if result['dry_run'] else 'completed'}: "
                f"retention_days={result['retention_days']}, "
                f"cutoff={result['cutoff']}, "
                f"matched_sessions={result['matched_sessions']}, "
                f"deleted_sessions={result['deleted_sessions']}, "
                f"deleted_rrweb_events={result['deleted_rrweb_events']}, "
                f"deleted_visitors={result['deleted_visitors']}, "
                f"batches={result['batches']}."
            )
        )
