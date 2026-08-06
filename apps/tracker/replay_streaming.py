"""Bounded, cursor-based delivery for rrweb session replay.

The legacy consolidator intentionally remains available during rollout.  This
module freezes a recording at bootstrap time and walks that snapshot in strict
``(timestamp, id)`` order without materializing the complete rrweb payload.
"""

from __future__ import annotations

import json
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from django.conf import settings
from django.core import signing
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connections
from django.db.models import (
    BinaryField,
    CharField,
    F,
    Func,
    IntegerField,
    Max,
    Min,
    Q,
    TextField,
    Value,
    Window,
)
from django.db.models.fields.json import KeyTextTransform, KeyTransform
from django.db.models.functions import Cast, Coalesce, Length, NullIf
from django.db.models.functions.window import RowNumber
from django.utils.dateparse import parse_datetime

from apps.tracker.analytics_replay_timeline import build_analytics_replay_timeline
from apps.tracker.tools import is_valid_rrweb_event, replace_urls_with_proxy, tab_labels


REPLAY_STREAM_PROTOCOL_VERSION = 1
REPLAY_STREAM_CURSOR_SALT = "tracker.replay-stream.cursor.v1"
REPLAY_STREAM_SEEK_CURSOR_SALT = "tracker.replay-stream.seek-cursor.v1"
REPLAY_STREAM_CURSOR_MAX_LENGTH = 4096
REPLAY_STREAM_RESPONSE_OVERHEAD_BYTES = 16 * 1024
REPLAY_STREAM_BASE_URL_MAX_LENGTH = 8192
REPLAY_STREAM_META_CANDIDATE_BATCH = 16
REPLAY_STREAM_MAX_SEEK_TARGET_MS = 9_007_199_254_740_991
VALID_RRWEB_TYPES = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14}
TAB_ACTIVITY_SOURCES = {1, 2, 5}


class ReplayStreamError(ValueError):
    """A typed stream error safe for a JSON API response."""

    status_code = 422
    code = "streaming_unavailable"

    def __init__(self, message, *, code=None, status_code=None):
        super().__init__(message)
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code


class InvalidReplayCursor(ReplayStreamError):
    status_code = 400
    code = "invalid_cursor"

    def __init__(self):
        super().__init__(
            "The replay cursor is invalid.",
            code=self.code,
            status_code=self.status_code,
        )


class InvalidReplaySeekCursor(ReplayStreamError):
    status_code = 400
    code = "invalid_seek_cursor"

    def __init__(self):
        super().__init__(
            "The replay seek cursor is invalid.",
            code=self.code,
            status_code=self.status_code,
        )


class InvalidReplaySeekTarget(ReplayStreamError):
    status_code = 400
    code = "invalid_seek_target"

    def __init__(self):
        super().__init__(
            "The replay seek target must be a non-negative number of milliseconds.",
            code=self.code,
            status_code=self.status_code,
        )


@dataclass(frozen=True)
class ReplayStreamPosition:
    timestamp: datetime
    event_id: int


@dataclass(frozen=True)
class ReplayStreamEventReference:
    id: int
    timestamp: datetime
    tab_id: str | None


def _positive_setting(name, default):
    try:
        value = int(getattr(settings, name, default))
    except (TypeError, ValueError):
        value = default
    return max(1, value)


def _stream_limits():
    return {
        "bootstrap_window_ms": _positive_setting(
            "REPLAY_STREAM_BOOTSTRAP_WINDOW_SECONDS", 45
        )
        * 1000,
        "bootstrap_event_limit": _positive_setting(
            "REPLAY_STREAM_BOOTSTRAP_EVENT_LIMIT", 3000
        ),
        "bootstrap_max_bytes": _positive_setting(
            "REPLAY_STREAM_BOOTSTRAP_MAX_BYTES", 2 * 1024 * 1024
        ),
        "chunk_window_ms": _positive_setting(
            "REPLAY_STREAM_CHUNK_WINDOW_SECONDS", 60
        )
        * 1000,
        "chunk_event_limit": _positive_setting(
            "REPLAY_STREAM_CHUNK_EVENT_LIMIT", 5000
        ),
        "chunk_max_bytes": _positive_setting(
            "REPLAY_STREAM_CHUNK_MAX_BYTES", 2 * 1024 * 1024
        ),
        "prefetch_threshold_ms": _positive_setting(
            "REPLAY_STREAM_PREFETCH_THRESHOLD_SECONDS", 30
        )
        * 1000,
        "append_batch_size": _positive_setting(
            "REPLAY_STREAM_APPEND_BATCH_SIZE", 250
        ),
    }


def _ordered_events(session, watermark_id):
    valid_payloads = Q(event_type=0, data__type=0)
    for event_type in sorted(VALID_RRWEB_TYPES - {0, 2}):
        valid_payloads |= Q(event_type=event_type, data__type=event_type)
    valid_payloads |= Q(
        event_type=2,
        data__type=2,
        data__data__node__id__isnull=False,
        data__data__node__type__isnull=False,
    )
    return (
        session.events.filter(
            id__lte=watermark_id,
        )
        .filter(valid_payloads)
        .only(
            "id",
            "session_id",
            "timestamp",
            "event_type",
            "data",
            "url",
            "tab_id",
        )
        .order_by("timestamp", "id")
    )


def _meta_href(event_data):
    if not isinstance(event_data, dict) or event_data.get("type") != 4:
        return None
    nested = event_data.get("data")
    return _http_url(nested.get("href")) if isinstance(nested, dict) else None


def _meta_context_before(*, queryset, session_id, watermark_id, position, tab_keys):
    """Load one latest valid Meta href per selected tab at the chunk boundary."""

    if position is None or not tab_keys:
        return {}
    meta_href = KeyTextTransform("href", KeyTransform("data", "data"))
    context = {}
    unresolved_tabs = set(tab_keys)
    rank_offset = 0
    while unresolved_tabs:
        concrete_tabs = [
            tab_id for tab_id in unresolved_tabs if tab_id != "unknown"
        ]
        tab_filter = Q(tab_id__in=concrete_tabs)
        if "unknown" in unresolved_tabs:
            tab_filter |= Q(tab_id__isnull=True) | Q(tab_id="") | Q(tab_id="unknown")

        rows = (
            queryset.model.objects.filter(
                session_id=session_id,
                id__lte=watermark_id,
                event_type=4,
                data__type=4,
            )
            .filter(tab_filter)
            .filter(
                Q(timestamp__lt=position.timestamp)
                | Q(timestamp=position.timestamp, id__lte=position.event_id)
            )
            .annotate(
                _stream_tab_key=Coalesce(
                    NullIf(
                        "tab_id",
                        Value("", output_field=CharField()),
                    ),
                    Value("unknown", output_field=CharField()),
                ),
                _stream_meta_href=meta_href,
            )
            .filter(_stream_meta_href__iregex=r"^\s*https?://[^/?#\s]+")
            .annotate(_stream_href_length=Length("_stream_meta_href"))
            .filter(_stream_href_length__lte=REPLAY_STREAM_BASE_URL_MAX_LENGTH)
            .annotate(
                _stream_rank=Window(
                    expression=RowNumber(),
                    partition_by=[F("_stream_tab_key")],
                    order_by=[F("timestamp").desc(), F("id").desc()],
                )
            )
            .filter(
                _stream_rank__gt=rank_offset,
                _stream_rank__lte=rank_offset + REPLAY_STREAM_META_CANDIDATE_BATCH,
            )
            .values("_stream_tab_key", "_stream_meta_href", "_stream_rank")
        )
        candidates_by_tab = {tab_id: [] for tab_id in unresolved_tabs}
        for row in rows:
            candidates_by_tab.setdefault(row["_stream_tab_key"], []).append(row)

        still_unresolved = set()
        for tab_id in unresolved_tabs:
            candidates = sorted(
                candidates_by_tab.get(tab_id, []),
                key=lambda row: row["_stream_rank"],
            )
            for candidate in candidates:
                valid_href = _http_url(candidate["_stream_meta_href"])
                if valid_href:
                    context[tab_id] = valid_href
                    break
            else:
                if len(candidates) == REPLAY_STREAM_META_CANDIDATE_BATCH:
                    still_unresolved.add(tab_id)
        unresolved_tabs = still_unresolved
        rank_offset += REPLAY_STREAM_META_CANDIDATE_BATCH
    return context


def _relative_timestamp_ms(timestamp, origin_timestamp):
    return max(0, round((timestamp - origin_timestamp).total_seconds() * 1000, 3))


def _epoch_timestamp_ms(timestamp):
    return round(timestamp.timestamp() * 1000, 3)


def _http_url(value):
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if len(candidate) > REPLAY_STREAM_BASE_URL_MAX_LENGTH:
        return None
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None
    return candidate if parsed.scheme.lower() in {"http", "https"} and parsed.netloc else None


def _normalized_event(event, origin_timestamp, meta_base_url=None):
    raw = event.data if isinstance(event.data, dict) else {}
    event_type = raw.get("type", event.event_type)
    normalized = {
        "type": event_type,
        "data": raw.get("data", {} if event_type == 3 else raw),
        "timestamp": _relative_timestamp_ms(event.timestamp, origin_timestamp),
    }
    # New captures may carry an explicit event-time URL. Historical batches do
    # not, so their latest same-tab Meta href must outrank the batch-level
    # Event.url, including when that Meta event was delivered in a prior chunk.
    base_url = (
        _http_url(raw.get("_hymetry_page_url"))
        or _http_url(meta_base_url)
        or _http_url(event.url)
    )
    replace_urls_with_proxy([normalized], base_url=base_url)
    return normalized


def _serialized_event_size(event):
    return len(
        json.dumps(
            event,
            cls=DjangoJSONEncoder,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _response_overhead_reserve(max_bytes):
    # Reserve room for the signed cursor, response keys, and JSON whitespace.
    # Sidecars are counted exactly as they are constructed below.
    return min(REPLAY_STREAM_RESPONSE_OVERHEAD_BYTES, max_bytes // 2)


def _stored_event_size_expression(queryset):
    """Return a DB-side byte estimate without selecting the JSON payload."""

    vendor = connections[queryset.db].vendor
    if vendor == "postgresql":
        json_size = Func(
            Cast("data", output_field=TextField()),
            function="OCTET_LENGTH",
            output_field=IntegerField(),
        )
        url_size = Func(
            Cast("url", output_field=TextField()),
            function="OCTET_LENGTH",
            output_field=IntegerField(),
        )
    elif vendor == "sqlite":
        json_size = Length(Cast("data", output_field=BinaryField()))
        url_size = Length(Cast("url", output_field=BinaryField()))
    else:
        json_size = Length(Cast("data", output_field=TextField()))
        url_size = Length(Cast("url", output_field=TextField()))
    return Coalesce(json_size, 0) + Coalesce(url_size, 0) + Value(64)


def _activity_source(event_data):
    if not isinstance(event_data, dict):
        return None
    try:
        event_type = int(event_data.get("type"))
    except (TypeError, ValueError):
        return None
    nested = event_data.get("data")
    if event_type != 3 or not isinstance(nested, dict):
        return None
    try:
        source = int(nested.get("source"))
    except (TypeError, ValueError):
        return None
    return source if source in TAB_ACTIVITY_SOURCES else None


def _tab_id(event):
    return event.tab_id or "unknown"


def _position_after(queryset, position):
    if position is None:
        return queryset
    return queryset.filter(
        Q(timestamp__gt=position.timestamp)
        | Q(timestamp=position.timestamp, id__gt=position.event_id)
    )


def _has_more(queryset, position):
    return _position_after(queryset, position).exists()


def _seek_boundary_ms(value):
    """Return an exact, cursor-safe millisecond boundary."""

    if isinstance(value, bool):
        raise ValueError("Invalid replay seek boundary")
    try:
        target = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Invalid replay seek boundary") from None
    if (
        not target.is_finite()
        or target < 0
        or target > REPLAY_STREAM_MAX_SEEK_TARGET_MS
    ):
        raise ValueError("Invalid replay seek boundary")
    target_microseconds = target * 1000
    if target_microseconds != target_microseconds.to_integral_value():
        raise ValueError("Invalid replay seek boundary")
    return target


def _target_boundary_ready(queryset, position, origin_timestamp, target_ms):
    """Return whether the cursor has consumed every event through target_ms."""

    target_microseconds = int(_seek_boundary_ms(target_ms) * 1000)
    target_timestamp = origin_timestamp + timedelta(microseconds=target_microseconds)
    return not _position_after(queryset, position).filter(
        timestamp__lte=target_timestamp,
    ).exists()


def _encode_cursor(
    *,
    project_id,
    session_id,
    watermark_id,
    origin_timestamp,
    position,
    current_activity_tab,
    seek_cursor=None,
    seek_target_ms=None,
):
    payload = {
        "v": REPLAY_STREAM_PROTOCOL_VERSION,
        "project_id": int(project_id),
        "session_id": str(session_id),
        "watermark_id": int(watermark_id),
        "origin_timestamp": origin_timestamp.isoformat(),
        "after_timestamp": position.timestamp.isoformat(),
        "after_event_id": int(position.event_id),
        "current_activity_tab": current_activity_tab,
    }
    if seek_cursor:
        payload["seek_cursor"] = seek_cursor
    if seek_target_ms is not None:
        payload["seek_target_ms"] = str(_seek_boundary_ms(seek_target_ms))
    return signing.dumps(
        payload,
        salt=REPLAY_STREAM_CURSOR_SALT,
        compress=True,
    )


def _encode_seek_cursor(*, project_id, session_id, watermark_id, origin_timestamp):
    return signing.dumps(
        {
            "v": REPLAY_STREAM_PROTOCOL_VERSION,
            "project_id": int(project_id),
            "session_id": str(session_id),
            "watermark_id": int(watermark_id),
            "origin_timestamp": origin_timestamp.isoformat(),
        },
        salt=REPLAY_STREAM_SEEK_CURSOR_SALT,
        compress=True,
    )


def _parse_cursor_timestamp(value):
    if not isinstance(value, str):
        raise InvalidReplayCursor()
    parsed = parse_datetime(value)
    if parsed is None or parsed.tzinfo is None:
        raise InvalidReplayCursor()
    return parsed


def _decode_cursor(cursor, *, project_id, session_id):
    if not isinstance(cursor, str) or not cursor or len(cursor) > REPLAY_STREAM_CURSOR_MAX_LENGTH:
        raise InvalidReplayCursor()
    try:
        payload = signing.loads(cursor, salt=REPLAY_STREAM_CURSOR_SALT)
    except (signing.BadSignature, TypeError, ValueError):
        raise InvalidReplayCursor() from None
    if not isinstance(payload, dict):
        raise InvalidReplayCursor()
    try:
        version = int(payload.get("v"))
        cursor_project_id = int(payload.get("project_id"))
        cursor_session_id = str(payload.get("session_id"))
        watermark_id = int(payload.get("watermark_id"))
        after_event_id = int(payload.get("after_event_id"))
    except (TypeError, ValueError):
        raise InvalidReplayCursor() from None
    if (
        version != REPLAY_STREAM_PROTOCOL_VERSION
        or cursor_project_id != int(project_id)
        or cursor_session_id != str(session_id)
        or watermark_id < 1
        or after_event_id < 1
        or after_event_id > watermark_id
    ):
        raise InvalidReplayCursor()
    current_activity_tab = payload.get("current_activity_tab")
    if current_activity_tab is not None and not isinstance(current_activity_tab, str):
        raise InvalidReplayCursor()
    seek_cursor = payload.get("seek_cursor")
    if seek_cursor is not None and (
        not isinstance(seek_cursor, str)
        or not seek_cursor
        or len(seek_cursor) > REPLAY_STREAM_CURSOR_MAX_LENGTH
    ):
        raise InvalidReplayCursor()
    seek_target_ms = payload.get("seek_target_ms")
    if seek_target_ms is not None:
        try:
            seek_target_ms = _seek_boundary_ms(seek_target_ms)
        except ValueError:
            raise InvalidReplayCursor() from None
    return {
        "watermark_id": watermark_id,
        "origin_timestamp": _parse_cursor_timestamp(payload.get("origin_timestamp")),
        "position": ReplayStreamPosition(
            timestamp=_parse_cursor_timestamp(payload.get("after_timestamp")),
            event_id=after_event_id,
        ),
        "current_activity_tab": current_activity_tab,
        "seek_cursor": seek_cursor,
        "seek_target_ms": seek_target_ms,
    }


def _decode_seek_cursor(seek_cursor, *, project_id, session_id):
    if (
        not isinstance(seek_cursor, str)
        or not seek_cursor
        or len(seek_cursor) > REPLAY_STREAM_CURSOR_MAX_LENGTH
    ):
        raise InvalidReplaySeekCursor()
    try:
        payload = signing.loads(
            seek_cursor,
            salt=REPLAY_STREAM_SEEK_CURSOR_SALT,
        )
    except (signing.BadSignature, TypeError, ValueError):
        raise InvalidReplaySeekCursor() from None
    if not isinstance(payload, dict):
        raise InvalidReplaySeekCursor()
    try:
        version = int(payload.get("v"))
        cursor_project_id = int(payload.get("project_id"))
        cursor_session_id = str(payload.get("session_id"))
        watermark_id = int(payload.get("watermark_id"))
    except (TypeError, ValueError):
        raise InvalidReplaySeekCursor() from None
    if (
        version != REPLAY_STREAM_PROTOCOL_VERSION
        or cursor_project_id != int(project_id)
        or cursor_session_id != str(session_id)
        or watermark_id < 1
    ):
        raise InvalidReplaySeekCursor()
    try:
        origin_timestamp = _parse_cursor_timestamp(payload.get("origin_timestamp"))
    except InvalidReplayCursor:
        raise InvalidReplaySeekCursor() from None
    return {
        "watermark_id": watermark_id,
        "origin_timestamp": origin_timestamp,
    }


def _human_tab_labels(queryset):
    rows = (
        queryset.values("tab_id")
        .annotate(first_timestamp=Min("timestamp"), first_id=Min("id"))
        .order_by("first_timestamp", "first_id", "tab_id")
    )
    generator = tab_labels()
    labels = {}
    for row in rows:
        tab_id = row["tab_id"] or "unknown"
        if tab_id not in labels:
            labels[tab_id] = next(generator)
    return labels


def _first_activity_tab(queryset):
    # Let the database narrow the JSON source so bootstrap does not pull a
    # mutation-heavy recording into Python merely to identify its first active
    # tab. String variants cover historical hand-built rows.
    candidates = queryset.filter(
        event_type=3,
        data__data__source__in=[1, 2, 5, "1", "2", "5"],
    )
    tab_id = candidates.values_list("tab_id", flat=True).first()
    return tab_id or ("unknown" if tab_id is not None else None)


def _latest_activity_tab_at(queryset, position):
    if position is None:
        return None
    candidates = queryset.filter(
        event_type=3,
        data__data__source__in=[1, 2, 5, "1", "2", "5"],
    ).filter(
        Q(timestamp__lt=position.timestamp)
        | Q(timestamp=position.timestamp, id__lte=position.event_id)
    )
    tab_id = (
        candidates.order_by("-timestamp", "-id")
        .values_list("tab_id", flat=True)
        .first()
    )
    return tab_id or ("unknown" if tab_id is not None else None)


def _replayable_snapshots(queryset):
    return queryset.filter(
        event_type=2,
        data__type=2,
        data__data__node__id__isnull=False,
        data__data__node__type__isnull=False,
    )


def _snapshot_reference(row):
    node_id = row["data__data__node__id"]
    node_type = row["data__data__node__type"]
    numeric = (int, float)
    if (
        not isinstance(node_id, numeric)
        or isinstance(node_id, bool)
        or not isinstance(node_type, numeric)
        or isinstance(node_type, bool)
    ):
        return None
    return ReplayStreamEventReference(
        id=row["id"],
        timestamp=row["timestamp"],
        tab_id=row["tab_id"],
    )


def _is_selected_snapshot_payload(event_data):
    nested = event_data.get("data") if isinstance(event_data, dict) else None
    node = nested.get("node") if isinstance(nested, dict) else None
    if not isinstance(node, dict):
        return False
    node_id = node.get("id")
    node_type = node.get("type")
    numeric = (int, float)
    return (
        isinstance(node_id, numeric)
        and not isinstance(node_id, bool)
        and isinstance(node_type, numeric)
        and not isinstance(node_type, bool)
    )


def _snapshot_references(queryset):
    rows = queryset.values(
        "id",
        "timestamp",
        "tab_id",
        "data__data__node__id",
        "data__data__node__type",
    )
    # Every walk here stops at the first useful row, and PostgreSQL backs
    # .iterator() with a named server-side cursor. Abandoning one leaves the
    # cursor to be closed at collection time, when its transaction may be gone;
    # that close then fails and aborts the surrounding transaction. Closing the
    # iterator deterministically keeps the cursor's lifetime inside its own
    # transaction on every backend.
    with closing(rows.iterator(chunk_size=25)) as row_iterator:
        for row in row_iterator:
            reference = _snapshot_reference(row)
            if reference is not None:
                yield reference


def _first_snapshot_reference(queryset):
    with closing(_snapshot_references(queryset)) as references:
        return next(iter(references), None)


def _first_replayable_snapshot(queryset):
    return _first_snapshot_reference(_replayable_snapshots(queryset))


def _latest_replayable_snapshot_at(queryset, target_timestamp):
    candidates = (
        _replayable_snapshots(queryset)
        .filter(timestamp__lte=target_timestamp)
        .order_by("-timestamp", "-id")
    )
    return _first_snapshot_reference(candidates)


def _first_valid_meta_reference(queryset):
    rows = queryset.values(
        "id",
        "timestamp",
        "tab_id",
        "data__data__width",
        "data__data__height",
    )
    with closing(rows.iterator(chunk_size=25)) as row_iterator:
        for row in row_iterator:
            try:
                width = int(row["data__data__width"])
                height = int(row["data__data__height"])
            except (TypeError, ValueError):
                continue
            if width > 0 and height > 0:
                return ReplayStreamEventReference(
                    id=row["id"],
                    timestamp=row["timestamp"],
                    tab_id=row["tab_id"],
                )
    return None


def _latest_initializer_meta_at(queryset, position, snapshot_tab_id):
    """Return a real rrweb Meta event safe to prefix a FullSnapshot."""

    if position is None:
        return None
    boundary = Q(timestamp__lt=position.timestamp) | Q(
        timestamp=position.timestamp,
        id__lt=position.event_id,
    )
    structurally_valid = Q(
        event_type=4,
        data__type=4,
        data__data__width__isnull=False,
        data__data__height__isnull=False,
    )
    same_tab = queryset.filter(structurally_valid, boundary)
    if snapshot_tab_id:
        same_tab = same_tab.filter(tab_id=snapshot_tab_id)
    else:
        same_tab = same_tab.filter(Q(tab_id__isnull=True) | Q(tab_id=""))
    candidate = _first_valid_meta_reference(
        same_tab.order_by("-timestamp", "-id")
    )
    if candidate is not None:
        return candidate
    return _first_valid_meta_reference(
        queryset.filter(structurally_valid, boundary).order_by("-timestamp", "-id")
    )


def _seek_target_ms(value):
    if isinstance(value, bool):
        raise InvalidReplaySeekTarget()
    try:
        target = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise InvalidReplaySeekTarget() from None
    if (
        not target.is_finite()
        or target < 0
        or target > REPLAY_STREAM_MAX_SEEK_TARGET_MS
    ):
        raise InvalidReplaySeekTarget()
    try:
        return int(target)
    except (OverflowError, ValueError):
        raise InvalidReplaySeekTarget() from None


def _recording_viewport(queryset, snapshot_position):
    if snapshot_position is None:
        return None
    candidates = queryset.filter(
        event_type=4,
    ).filter(
        Q(timestamp__lt=snapshot_position.timestamp)
        | Q(timestamp=snapshot_position.timestamp, id__lte=snapshot_position.event_id)
    )
    rows = candidates.values(
        "data__data__width",
        "data__data__height",
    )
    with closing(rows.reverse().iterator(chunk_size=25)) as row_iterator:
        for row in row_iterator:
            try:
                width = int(row["data__data__width"])
                height = int(row["data__data__height"])
            except (TypeError, ValueError):
                continue
            if width > 0 and height > 0:
                return {"width": width, "height": height}
    return None


def _chunk_payload(
    *,
    queryset,
    session_id,
    watermark_id,
    origin_timestamp,
    after_position,
    current_activity_tab,
    window_ms,
    event_limit,
    max_bytes,
    required_snapshot_position=None,
    minimum_event_count=0,
    window_anchor_position=None,
    meta_context_position=None,
):
    response_overhead = _response_overhead_reserve(max_bytes)
    content_budget = max(1, max_bytes - response_overhead)
    selected_ids = []
    selected_tab_keys = set()
    selected_stored_bytes = 0
    selected_snapshot = required_snapshot_position is None
    selection_anchor_ms = (
        _relative_timestamp_ms(window_anchor_position.timestamp, origin_timestamp)
        if window_anchor_position is not None
        else (0 if after_position is None else None)
    )
    selection_stop_reason = "end"

    # First walk only scalar columns plus a database-computed JSON size. This
    # avoids fetching/deserializing a large batch of DOM payloads before the
    # byte ceiling can be applied. The selected full rows, fetched below, have
    # a bounded aggregate stored size.
    candidates = _position_after(queryset, after_position).annotate(
        _stream_stored_bytes=_stored_event_size_expression(queryset),
    )
    candidate_rows = candidates.values(
        "id",
        "timestamp",
        "tab_id",
        "_stream_stored_bytes",
    )
    with closing(
        candidate_rows.iterator(chunk_size=min(max(event_limit, 1), 500))
    ) as candidate_iterator:
        for row in candidate_iterator:
            candidate_stored_bytes = max(1, int(row["_stream_stored_bytes"] or 0))
            candidate_stored_bytes += 1 if selected_ids else 0
            if (
                candidate_stored_bytes > content_budget
                or selected_stored_bytes + candidate_stored_bytes > content_budget
            ):
                initializer_ready = selected_snapshot and len(selected_ids) >= minimum_event_count
                if not selected_ids:
                    if required_snapshot_position is not None:
                        raise ReplayStreamError(
                            "The replay initializer exceeds the configured stream limits.",
                            code="initializer_too_large",
                        )
                    raise ReplayStreamError(
                        "A recording event exceeds the configured stream byte ceiling.",
                        code="event_too_large",
                    )
                if not initializer_ready:
                    raise ReplayStreamError(
                        "The replay initializer exceeds the configured stream limits.",
                        code="initializer_too_large",
                    )
                selection_stop_reason = "bytes"
                break

            relative_timestamp = _relative_timestamp_ms(row["timestamp"], origin_timestamp)
            if selection_anchor_ms is None:
                selection_anchor_ms = relative_timestamp
            selected_ids.append(row["id"])
            selected_tab_keys.add(row["tab_id"] or "unknown")
            selected_stored_bytes += candidate_stored_bytes

            if (
                required_snapshot_position is not None
                and row["id"] == required_snapshot_position.event_id
                and row["timestamp"] == required_snapshot_position.timestamp
            ):
                selected_snapshot = True

            initializer_ready = selected_snapshot and len(selected_ids) >= minimum_event_count
            if len(selected_ids) >= event_limit:
                if not initializer_ready:
                    raise ReplayStreamError(
                        "The replay initializer exceeds the configured event limit.",
                        code="initializer_too_many_events",
                    )
                selection_stop_reason = "events"
                break
            if initializer_ready and relative_timestamp >= selection_anchor_ms + window_ms:
                selection_stop_reason = "time"
                break

    events = []
    tab_switches = []
    event_bytes = 0
    sidecar_bytes = 0
    payload_bytes = response_overhead
    last_position = after_position
    snapshot_included = required_snapshot_position is None
    stop_reason = selection_stop_reason

    meta_href_by_tab = _meta_context_before(
        queryset=queryset,
        session_id=session_id,
        watermark_id=watermark_id,
        position=(
            meta_context_position
            if meta_context_position is not None
            else after_position
        ),
        tab_keys=selected_tab_keys,
    )
    selected_events = queryset.filter(id__in=selected_ids)
    full_row_batch_size = max(1, min(len(selected_ids), 100))
    with closing(
        selected_events.iterator(chunk_size=full_row_batch_size)
    ) as event_iterator:
        for event in event_iterator:
            if (
                not is_valid_rrweb_event(event.data, VALID_RRWEB_TYPES)
                or (event.event_type == 2 and not _is_selected_snapshot_payload(event.data))
            ):
                # The database validity filter should make this unreachable, but a
                # defensive skip keeps historical malformed JSON from returning 500.
                # Advance the opaque position so a malformed final row cannot make
                # a continuation cursor repeat forever.
                last_position = ReplayStreamPosition(event.timestamp, event.id)
                continue

            event_tab = _tab_id(event)
            event_meta_href = _meta_href(event.data)
            if event_meta_href:
                meta_href_by_tab[event_tab] = event_meta_href
            normalized = _normalized_event(
                event,
                origin_timestamp,
                meta_base_url=meta_href_by_tab.get(event_tab),
            )
            candidate_bytes = _serialized_event_size(normalized) + (1 if events else 0)
            relative_timestamp = normalized["timestamp"]

            next_activity_tab = current_activity_tab
            switch_event = None
            if _activity_source(event.data) is not None:
                next_activity_tab = _tab_id(event)
                if current_activity_tab is not None and next_activity_tab != current_activity_tab:
                    switch_event = {
                        "from_tab": current_activity_tab,
                        "to_tab": next_activity_tab,
                        "timestamp": relative_timestamp,
                        "absolute_timestamp": _epoch_timestamp_ms(event.timestamp),
                    }
            switch_bytes = 0
            if switch_event is not None:
                switch_bytes = _serialized_event_size(switch_event) + (1 if tab_switches else 0)

            if (
                candidate_bytes + switch_bytes > content_budget
                or payload_bytes + candidate_bytes + switch_bytes > max_bytes
            ):
                if not events:
                    if required_snapshot_position is not None:
                        raise ReplayStreamError(
                            "The replay initializer exceeds the configured stream limits.",
                            code="initializer_too_large",
                        )
                    raise ReplayStreamError(
                        "A recording event exceeds the configured stream byte ceiling.",
                        code="event_too_large",
                    )
                if not snapshot_included or len(events) < minimum_event_count:
                    raise ReplayStreamError(
                        "The replay initializer exceeds the configured stream limits.",
                        code="initializer_too_large",
                    )
                stop_reason = "bytes"
                break

            events.append(normalized)
            event_bytes += candidate_bytes
            payload_bytes += candidate_bytes
            last_position = ReplayStreamPosition(event.timestamp, event.id)

            if (
                required_snapshot_position is not None
                and event.id == required_snapshot_position.event_id
                and event.timestamp == required_snapshot_position.timestamp
            ):
                snapshot_included = True

            if switch_event is not None:
                tab_switches.append(switch_event)
                sidecar_bytes += switch_bytes
                payload_bytes += switch_bytes
            if _activity_source(event.data) is not None:
                current_activity_tab = next_activity_tab

    if required_snapshot_position is not None and (
        not snapshot_included or len(events) < minimum_event_count
    ):
        raise ReplayStreamError(
            "The recording does not contain enough events to initialize rrweb-player.",
            code="insufficient_initializer",
        )

    has_more = last_position is not None and _has_more(queryset, last_position)
    loaded_through_ms = (
        _relative_timestamp_ms(last_position.timestamp, origin_timestamp)
        if last_position is not None
        else 0
    )
    return {
        "events": events,
        "tab_switches": tab_switches,
        "event_bytes": event_bytes,
        "sidecar_bytes": sidecar_bytes,
        "payload_bytes": payload_bytes,
        "last_position": last_position,
        "current_activity_tab": current_activity_tab,
        "loaded_through_ms": loaded_through_ms,
        "has_more": has_more,
        "stop_reason": stop_reason if has_more else "end",
    }


def build_replay_stream_bootstrap(*, project, session):
    """Return full replay metadata and one bounded initialization chunk."""

    limits = _stream_limits()
    watermark_id = session.events.aggregate(value=Max("id"))["value"]
    empty_timeline = build_analytics_replay_timeline(project, session)
    if watermark_id is None:
        return {
            "protocol_version": REPLAY_STREAM_PROTOCOL_VERSION,
            "response_kind": "bootstrap",
            "events": [],
            "tab_switches": [],
            "human_tab_dict": {"unknown": "A"},
            "initial_tab_id": "unknown",
            "session_start_time": None,
            "rrweb_duration": 0,
            "total_duration": max(0, int(empty_timeline.get("durationMs") or 0)),
            "analytics_timeline": empty_timeline,
            "replay_available": False,
            "replay_unavailable_reason": "missing_full_snapshot",
            "recording_metadata": {
                "session_id": str(session.session_id),
                "project_id": project.id,
                "event_count": 0,
                "started_at": session.start_time.isoformat() if session.start_time else None,
                "ended_at": session.ended_at.isoformat() if session.ended_at else None,
                "viewport": None,
            },
            "loaded_through_ms": 0,
            "segment_start_ms": 0,
            "seekable_from_ms": 0,
            "has_more": False,
            "next_cursor": None,
            "seek_cursor": None,
            "stream_config": {
                "prefetch_threshold_ms": limits["prefetch_threshold_ms"],
                "append_batch_size": limits["append_batch_size"],
            },
            "chunk": {
                "event_count": 0,
                "event_bytes": 0,
                "sidecar_bytes": 0,
                "payload_bytes": 0,
                "stop_reason": "end",
            },
        }

    queryset = _ordered_events(session, watermark_id)
    first_event = queryset.only(
        "id",
        "session_id",
        "timestamp",
        "tab_id",
    ).first()
    last_event = queryset.only("id", "session_id", "timestamp").last()
    if first_event is None or last_event is None:
        # Only unsupported rows exist. Keep the response contract identical to
        # an empty/mutation-only recording without attempting cursor creation.
        analytics_timeline = empty_timeline
        return {
            "protocol_version": REPLAY_STREAM_PROTOCOL_VERSION,
            "response_kind": "bootstrap",
            "events": [],
            "tab_switches": [],
            "human_tab_dict": {"unknown": "A"},
            "initial_tab_id": "unknown",
            "session_start_time": None,
            "rrweb_duration": 0,
            "total_duration": max(0, int(analytics_timeline.get("durationMs") or 0)),
            "analytics_timeline": analytics_timeline,
            "replay_available": False,
            "replay_unavailable_reason": "missing_full_snapshot",
            "recording_metadata": {
                "session_id": str(session.session_id),
                "project_id": project.id,
                "event_count": 0,
                "started_at": session.start_time.isoformat() if session.start_time else None,
                "ended_at": session.ended_at.isoformat() if session.ended_at else None,
                "viewport": None,
            },
            "loaded_through_ms": 0,
            "segment_start_ms": 0,
            "seekable_from_ms": 0,
            "has_more": False,
            "next_cursor": None,
            "seek_cursor": None,
            "stream_config": {
                "prefetch_threshold_ms": limits["prefetch_threshold_ms"],
                "append_batch_size": limits["append_batch_size"],
            },
            "chunk": {
                "event_count": 0,
                "event_bytes": 0,
                "sidecar_bytes": 0,
                "payload_bytes": 0,
                "stop_reason": "end",
            },
        }

    origin_timestamp = first_event.timestamp
    event_count = queryset.count()
    snapshot = _first_replayable_snapshot(queryset)
    replay_available = snapshot is not None and event_count >= 2
    unavailable_reason = ""
    if snapshot is None:
        unavailable_reason = "missing_full_snapshot"
    elif event_count < 2:
        unavailable_reason = "insufficient_events"

    analytics_timeline = empty_timeline
    analytics_duration_ms = max(0, int(analytics_timeline.get("durationMs") or 0))
    rrweb_duration_ms = max(
        0, int(round((last_event.timestamp - origin_timestamp).total_seconds() * 1000))
    )
    human_tab_dict = _human_tab_labels(queryset)
    first_activity_tab = _first_activity_tab(queryset)
    initial_tab_id = first_activity_tab or _tab_id(first_event)
    if initial_tab_id not in human_tab_dict:
        human_tab_dict[initial_tab_id] = next(tab_labels())

    chunk = {
        "events": [],
        "tab_switches": [],
        "event_bytes": 0,
        "sidecar_bytes": 0,
        "payload_bytes": 0,
        "last_position": None,
        "current_activity_tab": None,
        "loaded_through_ms": 0,
        "has_more": False,
        "stop_reason": "end",
    }
    if replay_available:
        snapshot_position = ReplayStreamPosition(snapshot.timestamp, snapshot.id)
        chunk = _chunk_payload(
            queryset=queryset,
            session_id=session.pk,
            watermark_id=watermark_id,
            origin_timestamp=origin_timestamp,
            after_position=None,
            current_activity_tab=None,
            window_ms=limits["bootstrap_window_ms"],
            event_limit=limits["bootstrap_event_limit"],
            max_bytes=limits["bootstrap_max_bytes"],
            required_snapshot_position=snapshot_position,
            minimum_event_count=2,
        )
    else:
        snapshot_position = None

    seek_cursor = None
    if replay_available:
        seek_cursor = _encode_seek_cursor(
            project_id=project.id,
            session_id=session.session_id,
            watermark_id=watermark_id,
            origin_timestamp=origin_timestamp,
        )

    next_cursor = None
    if chunk["has_more"]:
        next_cursor = _encode_cursor(
            project_id=project.id,
            session_id=session.session_id,
            watermark_id=watermark_id,
            origin_timestamp=origin_timestamp,
            position=chunk["last_position"],
            current_activity_tab=chunk["current_activity_tab"],
            seek_cursor=seek_cursor,
        )

    return {
        "protocol_version": REPLAY_STREAM_PROTOCOL_VERSION,
        "response_kind": "bootstrap",
        "events": chunk["events"],
        "tab_switches": chunk["tab_switches"],
        "human_tab_dict": human_tab_dict,
        "initial_tab_id": initial_tab_id,
        "session_start_time": _epoch_timestamp_ms(origin_timestamp),
        "rrweb_duration": rrweb_duration_ms,
        "total_duration": analytics_duration_ms,
        "analytics_timeline": analytics_timeline,
        "replay_available": replay_available,
        "replay_unavailable_reason": unavailable_reason,
        "recording_metadata": {
            "session_id": str(session.session_id),
            "project_id": project.id,
            "event_count": event_count,
            "started_at": session.start_time.isoformat() if session.start_time else None,
            "ended_at": session.ended_at.isoformat() if session.ended_at else None,
            "viewport": _recording_viewport(queryset, snapshot_position),
        },
        "loaded_through_ms": chunk["loaded_through_ms"],
        "segment_start_ms": chunk["events"][0]["timestamp"] if chunk["events"] else 0,
        "seekable_from_ms": 0,
        "has_more": chunk["has_more"],
        "next_cursor": next_cursor,
        "seek_cursor": seek_cursor,
        "stream_config": {
            "prefetch_threshold_ms": limits["prefetch_threshold_ms"],
            "append_batch_size": limits["append_batch_size"],
        },
        "chunk": {
            "event_count": len(chunk["events"]),
            "event_bytes": chunk["event_bytes"],
            "sidecar_bytes": chunk["sidecar_bytes"],
            "payload_bytes": chunk["payload_bytes"],
            "stop_reason": chunk["stop_reason"],
        },
    }


def build_replay_stream_seek(*, project, session, seek_cursor, target_ms):
    """Build a bounded rrweb segment from the nearest prior FullSnapshot."""

    decoded = _decode_seek_cursor(
        seek_cursor,
        project_id=project.id,
        session_id=session.session_id,
    )
    queryset = _ordered_events(session, decoded["watermark_id"])
    first_event = queryset.only("id", "session_id", "timestamp").first()
    last_event = queryset.only("id", "session_id", "timestamp").last()
    if first_event is None or last_event is None:
        raise ReplayStreamError(
            "The recording has no seekable rrweb events.",
            code="missing_full_snapshot",
        )

    origin_timestamp = decoded["origin_timestamp"]
    rrweb_duration_ms = max(
        0,
        int(round((last_event.timestamp - origin_timestamp).total_seconds() * 1000)),
    )
    requested_seek_ms = _seek_target_ms(target_ms)
    resolved_seek_ms = min(requested_seek_ms, rrweb_duration_ms)
    target_timestamp = origin_timestamp + timedelta(milliseconds=resolved_seek_ms)
    snapshot = _latest_replayable_snapshot_at(queryset, target_timestamp)
    if snapshot is None:
        snapshot = _first_replayable_snapshot(queryset)
        if snapshot is None:
            raise ReplayStreamError(
                "The recording does not contain a valid FullSnapshot.",
                code="missing_full_snapshot",
            )

    snapshot_position = ReplayStreamPosition(snapshot.timestamp, snapshot.id)
    snapshot_ms = _relative_timestamp_ms(snapshot.timestamp, origin_timestamp)
    # Before the first captured FullSnapshot there is no DOM state to render.
    # Resolve such seeks to that first valid reconstruction point.
    resolved_seek_ms = max(resolved_seek_ms, snapshot_ms)

    events_at_or_after_snapshot = Q(timestamp__gt=snapshot.timestamp) | Q(
        timestamp=snapshot.timestamp,
        id__gte=snapshot.id,
    )
    limits = _stream_limits()
    desired_window_ms = max(
        1,
        (resolved_seek_ms - snapshot_ms) + limits["prefetch_threshold_ms"],
    )
    seek_window_ms = min(limits["chunk_window_ms"], desired_window_ms)
    initial_activity_tab = _latest_activity_tab_at(queryset, snapshot_position)

    def build_initializer_chunk(prefix_event=None):
        seek_queryset = queryset.filter(events_at_or_after_snapshot)
        if prefix_event is not None:
            seek_queryset = queryset.filter(
                Q(id=prefix_event.id) | events_at_or_after_snapshot
            )
        return _chunk_payload(
            queryset=seek_queryset,
            session_id=session.pk,
            watermark_id=decoded["watermark_id"],
            origin_timestamp=origin_timestamp,
            after_position=None,
            current_activity_tab=initial_activity_tab,
            window_ms=seek_window_ms,
            event_limit=limits["chunk_event_limit"],
            max_bytes=limits["chunk_max_bytes"],
            required_snapshot_position=snapshot_position,
            minimum_event_count=2,
            window_anchor_position=snapshot_position,
            meta_context_position=snapshot_position,
        )

    initializer_fallback = None
    chunk = None
    last_initializer_error = None

    # rrweb creates its replay iframe hidden and only makes it visible after a
    # Meta event supplies the viewport. Every replacement player therefore
    # needs the latest real Meta before its selected FullSnapshot, even when
    # the snapshot already has enough later events to satisfy rrweb's two-event
    # initializer requirement.
    initializer_meta = _latest_initializer_meta_at(
        queryset,
        snapshot_position,
        snapshot.tab_id,
    )
    if initializer_meta is not None:
        try:
            chunk = build_initializer_chunk(initializer_meta)
        except ReplayStreamError as exc:
            if exc.code not in {
                "initializer_too_large",
                "initializer_too_many_events",
                "insufficient_initializer",
            }:
                raise
            last_initializer_error = exc
        else:
            initializer_fallback = "meta"

    if chunk is None:
        if last_initializer_error is not None:
            raise last_initializer_error
        raise ReplayStreamError(
            "The selected FullSnapshot has no safe rrweb initializer chain.",
            code="insufficient_initializer",
        )

    next_cursor = None
    if chunk["has_more"]:
        next_cursor = _encode_cursor(
            project_id=project.id,
            session_id=session.session_id,
            watermark_id=decoded["watermark_id"],
            origin_timestamp=origin_timestamp,
            position=chunk["last_position"],
            current_activity_tab=chunk["current_activity_tab"],
            seek_cursor=seek_cursor,
            seek_target_ms=resolved_seek_ms,
        )

    segment_start_ms = chunk["events"][0]["timestamp"]
    initial_tab_id = initial_activity_tab or _tab_id(snapshot)
    return {
        "protocol_version": REPLAY_STREAM_PROTOCOL_VERSION,
        "response_kind": "seek",
        "events": chunk["events"],
        "tab_switches": chunk["tab_switches"],
        "initial_tab_id": initial_tab_id,
        "requested_seek_ms": requested_seek_ms,
        "seek_target_ms": resolved_seek_ms,
        "segment_start_ms": segment_start_ms,
        "seekable_from_ms": snapshot_ms,
        "seek_offset_ms": max(0, resolved_seek_ms - segment_start_ms),
        "target_ready": _target_boundary_ready(
            queryset,
            chunk["last_position"],
            origin_timestamp,
            resolved_seek_ms,
        ),
        "rrweb_duration": rrweb_duration_ms,
        "recording_metadata": {
            "viewport": _recording_viewport(queryset, snapshot_position),
        },
        "loaded_through_ms": chunk["loaded_through_ms"],
        "has_more": chunk["has_more"],
        "next_cursor": next_cursor,
        "seek_cursor": seek_cursor,
        "chunk": {
            "event_count": len(chunk["events"]),
            "event_bytes": chunk["event_bytes"],
            "sidecar_bytes": chunk["sidecar_bytes"],
            "payload_bytes": chunk["payload_bytes"],
            "stop_reason": chunk["stop_reason"],
            "initializer_fallback": initializer_fallback,
            "initializer_meta_fallback": initializer_fallback == "meta",
        },
    }


def build_replay_stream_chunk(*, project, session, cursor):
    """Return the next bounded chunk for an authorized recording."""

    decoded = _decode_cursor(
        cursor,
        project_id=project.id,
        session_id=session.session_id,
    )
    queryset = _ordered_events(session, decoded["watermark_id"])
    limits = _stream_limits()
    seek_target_ms = decoded["seek_target_ms"]
    seek_cursor = decoded["seek_cursor"] or _encode_seek_cursor(
        project_id=project.id,
        session_id=session.session_id,
        watermark_id=decoded["watermark_id"],
        origin_timestamp=decoded["origin_timestamp"],
    )
    if decoded["seek_cursor"]:
        seek_state = _decode_seek_cursor(
            seek_cursor,
            project_id=project.id,
            session_id=session.session_id,
        )
        if (
            seek_state["watermark_id"] != decoded["watermark_id"]
            or seek_state["origin_timestamp"] != decoded["origin_timestamp"]
        ):
            raise InvalidReplayCursor()
    chunk = _chunk_payload(
        queryset=queryset,
        session_id=session.pk,
        watermark_id=decoded["watermark_id"],
        origin_timestamp=decoded["origin_timestamp"],
        after_position=decoded["position"],
        current_activity_tab=decoded["current_activity_tab"],
        window_ms=limits["chunk_window_ms"],
        event_limit=limits["chunk_event_limit"],
        max_bytes=limits["chunk_max_bytes"],
    )

    next_cursor = None
    if chunk["has_more"]:
        next_cursor = _encode_cursor(
            project_id=project.id,
            session_id=session.session_id,
            watermark_id=decoded["watermark_id"],
            origin_timestamp=decoded["origin_timestamp"],
            position=chunk["last_position"],
            current_activity_tab=chunk["current_activity_tab"],
            seek_cursor=seek_cursor,
            seek_target_ms=seek_target_ms,
        )

    response = {
        "protocol_version": REPLAY_STREAM_PROTOCOL_VERSION,
        "response_kind": "chunk",
        "events": chunk["events"],
        "tab_switches": chunk["tab_switches"],
        "loaded_through_ms": chunk["loaded_through_ms"],
        "has_more": chunk["has_more"],
        "next_cursor": next_cursor,
        "seek_cursor": seek_cursor,
        "chunk": {
            "event_count": len(chunk["events"]),
            "event_bytes": chunk["event_bytes"],
            "sidecar_bytes": chunk["sidecar_bytes"],
            "payload_bytes": chunk["payload_bytes"],
            "stop_reason": chunk["stop_reason"],
        },
    }
    if seek_target_ms is not None:
        response["target_ready"] = _target_boundary_ready(
            queryset,
            chunk["last_position"],
            decoded["origin_timestamp"],
            seek_target_ms,
        )
    return response
