from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.tracker.testing.replay_runtime import (
    load_replay_events,
    print_replay_plan,
    resolve_project,
    send_replay_events,
)


class Command(BaseCommand):
    help = 'Replay generated analytics CSV into the analytics ingestion pipeline.'

    def add_arguments(self, parser):
        parser.add_argument('csv_path', help='Path to the generated CSV file.')
        parser.add_argument(
            '--project-id',
            type=int,
            help='Project id to attach replayed events to.',
        )
        parser.add_argument(
            '--api-key',
            help='Project API key. Required when project id is not provided.',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
            help='How many events to send per batch.',
        )
        parser.add_argument(
            '--stream-seconds',
            type=int,
            default=0,
            help='Replay over this many wall-clock seconds while preserving event order.',
        )
        parser.add_argument(
            '--recent-span-seconds',
            type=int,
            default=0,
            help='Remap timestamps into the recent past and send batches immediately.',
        )
        parser.add_argument(
            '--start-delay-seconds',
            type=int,
            default=0,
            help='Wait this many seconds before sending the first batch.',
        )
        parser.add_argument(
            '--max-events',
            type=int,
            help='Replay only the first N rows from the CSV.',
        )
        parser.add_argument(
            '--app-name',
            default='csv-replay',
            help='Value to place into the analytics payload app field.',
        )
        parser.add_argument(
            '--transport',
            choices=['internal', 'http'],
            default='internal',
            help='Use internal tracker code directly or send HTTP requests to an endpoint.',
        )
        parser.add_argument(
            '--endpoint',
            help='Analytics endpoint URL. Required when transport=http.',
        )
        parser.add_argument(
            '--request-timeout-seconds',
            type=int,
            default=30,
            help='HTTP timeout in seconds for transport=http.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Parse CSV and print the replay plan without sending events.',
        )

    def handle(self, *args, **options):
        project = resolve_project(options['project_id'], options['api_key'])
        api_key = project.api_key

        if not api_key:
            raise CommandError(f'Project {project.id} does not have an API key.')

        if options['transport'] == 'http' and not options['endpoint']:
            raise CommandError('--endpoint is required when --transport=http.')

        batch_size = max(options['batch_size'], 1)
        replay_events = load_replay_events(
            csv_path=options['csv_path'],
            project_id=project.id,
            app_name=options['app_name'],
            stream_seconds=options['stream_seconds'],
            recent_span_seconds=options['recent_span_seconds'],
            start_delay_seconds=options['start_delay_seconds'],
            max_events=options['max_events'],
            now=timezone.now(),
        )

        print_replay_plan(
            stdout=self.stdout,
            project=project,
            replay_events=replay_events,
            batch_size=batch_size,
            transport=options['transport'],
            endpoint=options['endpoint'],
            dry_run=options['dry_run'],
        )

        if options['dry_run']:
            return

        summary = send_replay_events(
            stdout=self.stdout,
            replay_events=replay_events,
            api_key=api_key,
            batch_size=batch_size,
            app_name=options['app_name'],
            transport=options['transport'],
            endpoint=options['endpoint'],
            timeout_seconds=options['request_timeout_seconds'],
        )
        self.stdout.write(
            self.style.SUCCESS(
                'Replay finished successfully. '
                f'batches={summary["batches"]}, accepted={summary["accepted_events"]}, '
                f'skipped={summary["skipped_events"]}, sessions_touched={summary["sessions_touched"]}.'
            )
        )

