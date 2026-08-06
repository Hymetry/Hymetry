from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.tracker.models import AnalyticsSession, Session, Visitor


class SessionResolutionError(ValueError):
    """Raised when an event cannot be assigned to one canonical visit."""


@dataclass(frozen=True)
class SessionResolutionPoint:
    event_time: datetime.datetime
    activity_time: datetime.datetime | None = None


def _aware_utc(value):
    if value is None:
        return None
    if timezone.is_naive(value):
        value = timezone.make_aware(value, datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc)


def _timeout():
    return datetime.timedelta(seconds=int(getattr(settings, 'SESSION_EXPIRATION_SECONDS', 1800)))


def _max_duration():
    return datetime.timedelta(
        seconds=max(1, int(getattr(settings, 'SESSION_MAX_DURATION_SECONDS', 43200)))
    )


def _maximum_end(session, max_duration):
    return session.start_time + max_duration


def _effective_end(session, timeout, max_duration):
    inactivity_end = (
        session.ended_at
        if session.ended_at is not None
        else (session.last_activity or session.start_time) + timeout
    )
    return min(inactivity_end, _maximum_end(session, max_duration))


def _get_or_create_locked_visitor(project, visitor_guid, event_time):
    if visitor_guid is None:
        return Visitor.objects.create(
            project=project,
            first_visit=event_time,
            last_activity=event_time,
        )

    try:
        with transaction.atomic():
            visitor, _created = Visitor.objects.get_or_create(
                project=project,
                visitor_guid=visitor_guid,
                defaults={
                    'first_visit': event_time,
                    'last_activity': event_time,
                },
            )
    except IntegrityError:
        visitor = Visitor.objects.get(project=project, visitor_guid=visitor_guid)

    return Visitor.objects.select_for_update().get(pk=visitor.pk)


def _requested_session(sessions, requested_session_id):
    if not requested_session_id:
        return None
    try:
        requested_uuid = uuid.UUID(str(requested_session_id))
    except (TypeError, ValueError, AttributeError):
        return None
    return next((session for session in sessions if session.session_id == requested_uuid), None)


def _mark_session_update(session, *fields):
    pending_fields = getattr(session, '_resolver_update_fields', set())
    pending_fields.update(fields)
    session._resolver_update_fields = pending_fields


def _flush_session_updates(session, *fields):
    update_fields = set(getattr(session, '_resolver_update_fields', set()))
    update_fields.update(fields)
    if not update_fields:
        return
    session.save(update_fields=sorted(update_fields))
    session._resolver_update_fields = set()


def _close_session(session, ended_at):
    ended_at = max(session.start_time, ended_at)
    session.ended_at = ended_at
    if session.last_activity and session.last_activity > ended_at:
        session.last_activity = ended_at
    _flush_session_updates(session, 'last_activity', 'ended_at')
    AnalyticsSession.objects.filter(
        visit_session=session,
        ended_at__isnull=True,
    ).update(ended_at=ended_at)
    session._cleanup_redis_data()


def _resolve_point(
    sessions,
    point,
    *,
    visitor,
    timeout,
    max_duration,
    requested_session_id=None,
):
    event_time = _aware_utc(point.event_time)
    activity_time = _aware_utc(point.activity_time)
    requested = _requested_session(sessions, requested_session_id)

    candidates = [
        session
        for session in sessions
        if session.start_time <= event_time < _effective_end(session, timeout, max_duration)
    ]
    if requested is not None and requested not in candidates:
        requested_end = _effective_end(requested, timeout, max_duration)
        if requested.start_time <= event_time < requested_end:
            candidates.append(requested)

    if len(candidates) > 1:
        raise SessionResolutionError(
            f'Event at {event_time.isoformat()} overlaps multiple sessions for visitor {visitor.pk}.'
        )

    session = candidates[0] if candidates else None
    if session is None:
        future_sessions = [
            candidate
            for candidate in sessions
            if candidate.start_time > event_time
            and candidate.start_time - event_time < timeout
            and (candidate.last_activity or candidate.start_time) < event_time + max_duration
        ]
        if len(future_sessions) > 1:
            raise SessionResolutionError(
                f'Event at {event_time.isoformat()} has multiple future session candidates.'
            )
        if future_sessions:
            session = future_sessions[0]
            session.start_time = event_time
            _mark_session_update(session, 'start_time')

    if session is None:
        if activity_time is None and sessions:
            passive_session = next(
                (
                    candidate
                    for candidate in reversed(sessions)
                    if candidate.start_time <= event_time
                ),
                sessions[0],
            )
            if event_time < _maximum_end(passive_session, max_duration):
                if not passive_session.identity_linkage_ready:
                    passive_session.identity_linkage_ready = True
                    _mark_session_update(passive_session, 'identity_linkage_ready')
                return passive_session

        previous_open = next(
            (
                candidate
                for candidate in reversed(sessions)
                if candidate.ended_at is None and candidate.start_time <= event_time
            ),
            None,
        )
        if previous_open is not None:
            cutoff = _effective_end(previous_open, timeout, max_duration)
            if event_time >= cutoff:
                _close_session(previous_open, cutoff)

        next_session = next(
            (candidate for candidate in sessions if candidate.start_time > event_time),
            None,
        )
        ended_at = None
        if next_session is not None:
            ended_at = min(
                event_time + timeout,
                event_time + max_duration,
                next_session.start_time,
            )
        session = Session.objects.create(
            visitor=visitor,
            start_time=event_time,
            last_activity=activity_time or event_time,
            ended_at=ended_at,
            identity_linkage_ready=True,
        )
        sessions.append(session)
        sessions.sort(key=lambda item: (item.start_time, str(item.session_id)))
    else:
        update_fields = []
        if not session.identity_linkage_ready:
            session.identity_linkage_ready = True
            update_fields.append('identity_linkage_ready')
        if event_time < session.start_time:
            session.start_time = event_time
            update_fields.append('start_time')
        if activity_time is not None and activity_time > (session.last_activity or session.start_time):
            session.last_activity = activity_time
            update_fields.append('last_activity')
            if session.ended_at is not None:
                next_session = next(
                    (
                        candidate
                        for candidate in sessions
                        if candidate.session_id != session.session_id
                        and candidate.start_time > session.start_time
                    ),
                    None,
                )
                extended_end = activity_time + timeout
                if next_session is not None:
                    extended_end = min(extended_end, next_session.start_time)
                extended_end = min(extended_end, _maximum_end(session, max_duration))
                session.ended_at = extended_end
                update_fields.append('ended_at')
        if update_fields:
            _mark_session_update(session, *update_fields)

    return session


@transaction.atomic
def resolve_visit_session_batch(
    project,
    visitor_guid,
    points,
    *,
    requested_session_id=None,
):
    """Resolve event-time points to canonical Sessions under one visitor lock."""

    normalized_points = [
        SessionResolutionPoint(
            event_time=_aware_utc(point.event_time),
            activity_time=_aware_utc(point.activity_time),
        )
        for point in points
    ]
    if not normalized_points:
        raise SessionResolutionError('At least one event timestamp is required.')

    first_event_time = min(point.event_time for point in normalized_points)
    visitor = _get_or_create_locked_visitor(project, visitor_guid, first_event_time)
    late_window = datetime.timedelta(
        seconds=max(0, int(getattr(settings, 'SESSION_LATE_EVENT_MAX_AGE_SECONDS', 86400)))
    )
    last_event_time = max(point.event_time for point in normalized_points)
    lower_bound = first_event_time - late_window
    upper_bound = last_event_time + late_window
    sessions = list(
        Session.objects.select_for_update()
        .filter(visitor=visitor)
        .filter(
            Q(ended_at__isnull=True)
            | Q(
                start_time__lt=upper_bound,
                ended_at__gte=lower_bound,
            )
        )
        .order_by('start_time', 'session_id')
    )
    timeout = _timeout()
    max_duration = _max_duration()

    indexed_points = sorted(
        enumerate(normalized_points),
        key=lambda item: (item[1].event_time, item[0]),
    )
    resolved = [None] * len(normalized_points)
    for original_index, point in indexed_points:
        resolved[original_index] = _resolve_point(
            sessions,
            point,
            visitor=visitor,
            timeout=timeout,
            max_duration=max_duration,
            requested_session_id=requested_session_id,
        )

    for session in sessions:
        _flush_session_updates(session)

    latest_activity = max(
        (point.activity_time or point.event_time for point in normalized_points),
        default=first_event_time,
    )
    visitor_update_fields = []
    if first_event_time < visitor.first_visit:
        visitor.first_visit = first_event_time
        visitor_update_fields.append('first_visit')
    if latest_activity > visitor.last_activity:
        visitor.last_activity = latest_activity
        visitor_update_fields.append('last_activity')
    if visitor_update_fields:
        visitor.save(update_fields=visitor_update_fields)

    return visitor, resolved
