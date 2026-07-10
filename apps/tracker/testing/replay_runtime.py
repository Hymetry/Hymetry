import json
import time
from datetime import timedelta

import requests
from django.core.management.base import CommandError
from django.test.client import RequestFactory
from django.utils import timezone

from apps.projects.models import Project
from apps.projects.utils import normalize_capture_modes
from apps.tracker.analytics_tracker import AnalyticsTracker
from apps.tracker.testing.csv_replay import build_replay_events, load_csv_rows, sort_replay_events


def resolve_project(project_id=None, api_key=None):
    if project_id is not None:
        project = Project.active.filter(id=project_id).first()
        if project is None:
            raise CommandError(f'Project {project_id} was not found.')

        if api_key and project.api_key != api_key:
            raise CommandError(
                f'Provided api key does not belong to project {project_id}.'
            )
    elif api_key:
        project = Project.active.filter(api_key=api_key).first()
        if project is None:
            raise CommandError('Project with the provided API key was not found.')
    else:
        raise CommandError('Provide either --project-id or --api-key.')

    capture_modes = normalize_capture_modes(project.tracking_capture).split(',')
    if 'analytics' not in capture_modes:
        raise CommandError(
            f"Project {project.id} tracking_capture='{project.tracking_capture}' does not include analytics. "
            "Replay commands write AnalyticsEvent data, so set tracking_capture to "
            "'analytics' or 'analytics,recording' first."
        )

    return project


def load_replay_events(
    csv_path,
    project_id,
    app_name='csv-replay',
    stream_seconds=0,
    recent_span_seconds=0,
    start_delay_seconds=0,
    max_events=None,
    now=None,
    stream_name='',
):
    reference_now = now or timezone.now()
    effective_start_delay_seconds = start_delay_seconds

    # When we delay a recent-span replay, we want event timestamps to be recent
    # relative to the delayed send time, not relative to command start time.
    if recent_span_seconds and start_delay_seconds:
        reference_now = reference_now + timedelta(seconds=start_delay_seconds)
        effective_start_delay_seconds = 0

    try:
        rows = load_csv_rows(csv_path, max_events=max_events)
    except OSError as exc:
        raise CommandError(f'Could not read CSV file: {exc}') from exc

    try:
        replay_events = build_replay_events(
            rows=rows,
            project_id=project_id,
            app_name=app_name,
            stream_seconds=stream_seconds,
            recent_span_seconds=recent_span_seconds,
            start_delay_seconds=effective_start_delay_seconds,
            now=reference_now,
            stream_name=stream_name,
        )
    except ValueError as exc:
        raise CommandError(str(exc)) from exc

    if not replay_events:
        label = f' for {stream_name}' if stream_name else ''
        raise CommandError(f'No replay events were built from the CSV input{label}.')

    return replay_events


def print_replay_plan(stdout, project, replay_events, batch_size, transport, endpoint, dry_run, title='Replay'):
    first_event = replay_events[0]
    last_event = replay_events[-1]
    batch_count = (len(replay_events) + batch_size - 1) // batch_size
    endpoint_label = endpoint if transport == 'http' else 'internal AnalyticsTracker'
    mode_label = 'dry-run' if dry_run else 'live'
    stream_names = sorted({event.stream_name for event in replay_events if event.stream_name})
    stream_label = f" streams={', '.join(stream_names)}" if stream_names else ''

    stdout.write(
        f'{title} plan ({mode_label}) for project {project.id} "{project.name}":{stream_label}'
    )
    stdout.write(f'- transport: {transport} ({endpoint_label})')
    stdout.write(f'- events: {len(replay_events)}')
    stdout.write(f'- batches: {batch_count} of up to {batch_size}')
    stdout.write(f'- first event ts: {first_event.event_timestamp.isoformat()}')
    stdout.write(f'- last event ts: {last_event.event_timestamp.isoformat()}')
    stdout.write(f'- first send not before: {first_event.send_not_before.isoformat()}')
    stdout.write(f'- last send not before: {last_event.send_not_before.isoformat()}')
    stdout.write(
        '- sample pages: '
        + ', '.join(event.payload['page'] for event in replay_events[:3])
    )


def sleep_until(scheduled_at):
    while True:
        remaining = (scheduled_at - timezone.now()).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 1))


def send_internal(payload):
    request = RequestFactory().post(
        '/hm/ae/',
        data=json.dumps(payload),
        content_type='application/json',
    )
    request._allow_demo_project_writes = True
    tracker = AnalyticsTracker(request)

    if not tracker.parse_request():
        raise CommandError('Internal replay request could not be parsed by AnalyticsTracker.')

    tracker.process_events()
    return json.loads(tracker.get_response().content.decode('utf-8'))


def send_http(payload, endpoint, timeout_seconds):
    try:
        response = requests.post(
            endpoint,
            json=payload,
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        raise CommandError(f'HTTP replay failed: {exc}') from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise CommandError(
            f'HTTP replay returned non-JSON response with status {response.status_code}.'
        ) from exc

    if response.status_code >= 400:
        raise CommandError(
            f'HTTP replay failed with status {response.status_code}: {data}'
        )

    return data


def send_replay_events(
    stdout,
    replay_events,
    api_key,
    batch_size=100,
    app_name='csv-replay',
    transport='internal',
    endpoint=None,
    timeout_seconds=30,
    batch_label='Batch',
):
    accepted_total = 0
    skipped_total = 0
    touched_sessions_total = 0
    batches_sent = 0
    started_at = timezone.now()

    sorted_events = sort_replay_events(replay_events)

    index = 0

    while index < len(sorted_events):
        scheduled_at = sorted_events[index].send_not_before
        sleep_until(scheduled_at)
        batch = []

        while index < len(sorted_events) and len(batch) < batch_size:
            next_event = sorted_events[index]
            if next_event.send_not_before > timezone.now():
                break
            batch.append(next_event)
            index += 1

        if not batch:
            continue

        payload = {
            'api_key': api_key,
            'app': app_name,
            'sentAt': timezone.now().isoformat(),
            'batch': [event.payload for event in batch],
        }

        if transport == 'http':
            result = send_http(
                payload=payload,
                endpoint=endpoint,
                timeout_seconds=timeout_seconds,
            )
        else:
            result = send_internal(payload)

        batches_sent += 1
        accepted_total += int(result.get('accepted_events', 0))
        skipped_total += int(result.get('skipped_events', 0))
        touched_sessions_total += int(result.get('sessions_touched', 0))
        sources = ','.join(sorted({event.stream_name or 'default' for event in batch}))

        stdout.write(
            f'{batch_label} {batches_sent}: accepted={result.get("accepted_events", 0)} '
            f'skipped={result.get("skipped_events", 0)} '
            f'sessions={result.get("sessions_touched", 0)} '
            f'sources={sources} '
            f'scheduled_at={scheduled_at.isoformat()}'
        )

    finished_at = timezone.now()
    summary = {
        'batches': batches_sent,
        'accepted_events': accepted_total,
        'skipped_events': skipped_total,
        'sessions_touched': touched_sessions_total,
        'elapsed_seconds': (finished_at - started_at).total_seconds(),
    }
    stdout.write(
        f'Replay finished. batches={summary["batches"]}, accepted={summary["accepted_events"]}, '
        f'skipped={summary["skipped_events"]}, sessions_touched={summary["sessions_touched"]}, '
        f'elapsed={summary["elapsed_seconds"]:.1f}s'
    )
    return summary

