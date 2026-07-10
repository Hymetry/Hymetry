from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.tracker.testing.csv_replay import sort_replay_events
from apps.tracker.testing.replay_runtime import (
    load_replay_events,
    print_replay_plan,
    resolve_project,
    send_replay_events,
)


class Command(BaseCommand):
    help = 'Replay baseline traffic and a delayed spike in one command.'

    def add_arguments(self, parser):
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
            '--dataset-mode',
            choices=['path', 'subdomain'],
            default='path',
            help='Choose which generated CSV pair to use by default.',
        )
        parser.add_argument(
            '--baseline-csv',
            help='Override the baseline CSV file path.',
        )
        parser.add_argument(
            '--spike-csv',
            help='Override the spike CSV file path.',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
            help='How many events to send per batch.',
        )
        parser.add_argument(
            '--baseline-recent-span-seconds',
            type=int,
            default=300,
            help='Baseline timestamps are remapped into the last N seconds.',
        )
        parser.add_argument(
            '--baseline-stream-seconds',
            type=int,
            default=0,
            help='Replay baseline over this many wall-clock seconds.',
        )
        parser.add_argument(
            '--baseline-start-delay-seconds',
            type=int,
            default=0,
            help='Delay the start of baseline replay.',
        )
        parser.add_argument(
            '--baseline-max-events',
            type=int,
            help='Replay only the first N baseline rows.',
        )
        parser.add_argument(
            '--spike-recent-span-seconds',
            type=int,
            default=180,
            help='Spike timestamps are remapped into the last N seconds.',
        )
        parser.add_argument(
            '--spike-stream-seconds',
            type=int,
            default=0,
            help='Replay spike over this many wall-clock seconds.',
        )
        parser.add_argument(
            '--spike-start-delay-seconds',
            type=int,
            default=360,
            help='Delay the spike replay relative to command start.',
        )
        parser.add_argument(
            '--spike-max-events',
            type=int,
            help='Replay only the first N spike rows.',
        )
        parser.add_argument(
            '--app-name-prefix',
            default='csv-replay',
            help='Prefix for per-stream app names inside replayed events.',
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
            help='Print the combined scenario plan without sending events.',
        )

    def handle(self, *args, **options):
        project = resolve_project(options['project_id'], options['api_key'])
        api_key = project.api_key

        if not api_key:
            raise CommandError(f'Project {project.id} does not have an API key.')

        if options['transport'] == 'http' and not options['endpoint']:
            raise CommandError('--endpoint is required when --transport=http.')

        batch_size = max(options['batch_size'], 1)
        now = timezone.now()
        baseline_csv = options['baseline_csv'] or self._default_csv('generated_b2b_events', options['dataset_mode'])
        spike_csv = options['spike_csv'] or self._default_csv('generated_b2b_events_spike', options['dataset_mode'])

        baseline_events = load_replay_events(
            csv_path=baseline_csv,
            project_id=project.id,
            app_name=f'{options["app_name_prefix"]}-baseline',
            stream_seconds=options['baseline_stream_seconds'],
            recent_span_seconds=options['baseline_recent_span_seconds'],
            start_delay_seconds=options['baseline_start_delay_seconds'],
            max_events=options['baseline_max_events'],
            now=now,
            stream_name='baseline',
        )
        spike_events = load_replay_events(
            csv_path=spike_csv,
            project_id=project.id,
            app_name=f'{options["app_name_prefix"]}-spike',
            stream_seconds=options['spike_stream_seconds'],
            recent_span_seconds=options['spike_recent_span_seconds'],
            start_delay_seconds=options['spike_start_delay_seconds'],
            max_events=options['spike_max_events'],
            now=now,
            stream_name='spike',
        )

        print_replay_plan(
            stdout=self.stdout,
            project=project,
            replay_events=baseline_events,
            batch_size=batch_size,
            transport=options['transport'],
            endpoint=options['endpoint'],
            dry_run=options['dry_run'],
            title='Baseline replay',
        )
        print_replay_plan(
            stdout=self.stdout,
            project=project,
            replay_events=spike_events,
            batch_size=batch_size,
            transport=options['transport'],
            endpoint=options['endpoint'],
            dry_run=options['dry_run'],
            title='Spike replay',
        )

        combined_events = sort_replay_events(baseline_events + spike_events)
        print_replay_plan(
            stdout=self.stdout,
            project=project,
            replay_events=combined_events,
            batch_size=batch_size,
            transport=options['transport'],
            endpoint=options['endpoint'],
            dry_run=options['dry_run'],
            title='Combined scenario',
        )

        if options['dry_run']:
            return

        summary = send_replay_events(
            stdout=self.stdout,
            replay_events=combined_events,
            api_key=api_key,
            batch_size=batch_size,
            app_name=f'{options["app_name_prefix"]}-scenario',
            transport=options['transport'],
            endpoint=options['endpoint'],
            timeout_seconds=options['request_timeout_seconds'],
            batch_label='Scenario batch',
        )
        self.stdout.write(
            self.style.SUCCESS(
                'Scenario replay finished successfully. '
                f'batches={summary["batches"]}, accepted={summary["accepted_events"]}, '
                f'skipped={summary["skipped_events"]}, sessions_touched={summary["sessions_touched"]}.'
            )
        )

    def _default_csv(self, directory_name, dataset_mode):
        root = Path('docs') / 'testing' / 'page_naming' / directory_name
        return str(root / f'b2b_events_{dataset_mode}_urls.csv')

