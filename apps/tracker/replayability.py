"""Shared rrweb replayability checks for recording-backed Visits."""

from apps.tracker.models import Event


RRWEB_FULL_SNAPSHOT_TYPE = 2


def replayable_full_snapshot_events(*, session_id=None):
    """Return full snapshots that contain the serialized DOM root rrweb needs."""

    queryset = Event.objects.filter(
        event_type=RRWEB_FULL_SNAPSHOT_TYPE,
        data__type=RRWEB_FULL_SNAPSHOT_TYPE,
        data__data__node__id__isnull=False,
        data__data__node__type__isnull=False,
    )
    if session_id is not None:
        queryset = queryset.filter(session_id=session_id)
    return queryset


def is_replayable_full_snapshot(event_data):
    """Validate one normalized rrweb event without consulting the database."""

    if not isinstance(event_data, dict):
        return False
    if event_data.get('type') != RRWEB_FULL_SNAPSHOT_TYPE:
        return False
    snapshot_data = event_data.get('data')
    if not isinstance(snapshot_data, dict):
        return False

    node = snapshot_data.get('node')
    return (
        isinstance(node, dict)
        and node.get('id') is not None
        and node.get('type') is not None
    )
