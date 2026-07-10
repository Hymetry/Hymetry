import csv
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from typing import List
from urllib.parse import urlparse


@dataclass
class ReplayEvent:
    event_timestamp: datetime
    send_not_before: datetime
    payload: dict
    stream_name: str = ''


def parse_csv_timestamp(value):
    parsed = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    return parsed.replace(tzinfo=dt_timezone.utc)


def slugify_identifier(value):
    lowered = str(value or '').strip().lower()
    slug = re.sub(r'[^a-z0-9]+', '-', lowered).strip('-')
    return slug or 'unknown'


def ensure_absolute_url(value):
    text = str(value or '').strip()
    if not text:
        return ''

    parsed = urlparse(text)
    if parsed.scheme:
        return text
    return f'https://{text.lstrip("/")}'


def deterministic_visitor_id(project_id, company_name, user_email):
    source = f'{project_id}:{company_name}:{user_email}'.strip().lower()
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, source))


def load_csv_rows(csv_path, max_events=None):
    path = Path(csv_path)
    rows = []

    with path.open('r', encoding='utf-8', newline='') as csv_file:
        reader = csv.DictReader(csv_file)
        for index, row in enumerate(reader):
            if max_events is not None and index >= max_events:
                break
            rows.append(row)

    rows.sort(key=lambda row: row['event_time'])
    return rows


def _normalized_positions(source_timestamps):
    if not source_timestamps:
        return []

    source_start = source_timestamps[0]
    source_end = source_timestamps[-1]
    total_seconds = max((source_end - source_start).total_seconds(), 1)

    positions = []
    for timestamp in source_timestamps:
        delta_seconds = (timestamp - source_start).total_seconds()
        positions.append(delta_seconds / total_seconds)
    return positions


def build_replay_events(
    rows,
    project_id,
    app_name='csv-replay',
    stream_seconds=0,
    recent_span_seconds=0,
    start_delay_seconds=0,
    now=None,
    stream_name='',
):
    if stream_seconds and recent_span_seconds:
        raise ValueError('Use either stream_seconds or recent_span_seconds, not both.')

    if not rows:
        return []

    now = now or datetime.now(dt_timezone.utc)
    source_timestamps = [parse_csv_timestamp(row['event_time']) for row in rows]
    positions = _normalized_positions(source_timestamps)
    replay_events = []

    stream_start = now + timedelta(seconds=start_delay_seconds)
    recent_span_start = now - timedelta(seconds=recent_span_seconds) if recent_span_seconds else now

    for row, position in zip(rows, positions):
        company_name = row.get('company_name', '').strip()
        user_email = row.get('user_email', '').strip().lower()
        company_id = slugify_identifier(company_name)
        visitor_id = deterministic_visitor_id(project_id, company_name, user_email)

        if stream_seconds:
            event_timestamp = stream_start + timedelta(seconds=position * stream_seconds)
            send_not_before = event_timestamp
        elif recent_span_seconds:
            event_timestamp = recent_span_start + timedelta(seconds=position * recent_span_seconds)
            send_not_before = stream_start
        else:
            event_timestamp = stream_start
            send_not_before = stream_start

        payload = {
            'type': 'click',
            'ts': event_timestamp.isoformat(),
            'app': app_name,
            'visitor_id': visitor_id,
            'user_id': user_email or None,
            'company_id': company_id,
            'user': {
                'id': user_email or None,
                'traits': {
                    'email': user_email or None,
                },
            },
            'company': {
                'id': company_id,
                'traits': {
                    'name': company_name,
                },
            },
            'page': ensure_absolute_url(row.get('full_url', '')),
            'elementKey': (row.get('clicked_element', '') or 'CSV replay event')[:300],
        }

        replay_events.append(
            ReplayEvent(
                event_timestamp=event_timestamp,
                send_not_before=send_not_before,
                payload=payload,
                stream_name=stream_name,
            )
        )

    return replay_events
def sort_replay_events(items: List[ReplayEvent]) -> List[ReplayEvent]:
    return sorted(
        items,
        key=lambda item: (
            item.send_not_before,
            item.event_timestamp,
            item.stream_name,
            item.payload.get('page', ''),
        ),
    )
