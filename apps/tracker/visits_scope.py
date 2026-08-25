"""Ingest-time maintenance of the denormalized Visits row scope.

The Visits table selects replayable recording ``Session`` rows by the analytical
clock its linked ``AnalyticsEvent`` rows define.  Deriving that clock at read
time forced the selected date range into a ``HAVING`` clause over
``MIN(timestamp)``, so every request aggregated the project's whole event
history before it could discard everything outside the range.

These helpers keep the same facts on ``Session`` as ordinary indexed columns:
the analytical clock, the replay flag, and whether the linked analytics clear
the low-confidence bar in :mod:`apps.tracker.analytics_eligibility`.  All are
widen-only and idempotent: replaying a batch, or ingesting events out of order,
can only extend an interval or set a flag that is already set.

Row-at-a-time writers are covered by the signal handlers at the bottom of this
module.  Signals do not fire for ``bulk_create``, which is how both ingest
paths write, so a bulk writer must call these helpers itself — see
``apps.tracker.analytics_tracker`` and ``apps.tracker.session_tracker`` for the
ingest side and :func:`refresh_visits_scope` for offline writers.
"""

from __future__ import annotations

from django.db.models import (
    Count,
    DateTimeField,
    Exists,
    Max,
    Min,
    OuterRef,
    Q,
    TextField,
    Value,
)
from django.db.models.functions import Cast, Coalesce, Concat, Greatest, Least, NullIf
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.tracker.analytics_eligibility import MEANINGFUL_EVENT_TYPES, is_meaningful
from apps.tracker.models import AnalyticsEvent, AnalyticsSession, Event, Session
from apps.tracker.replayability import (
    RRWEB_FULL_SNAPSHOT_TYPE,
    replayable_full_snapshot_events,
)


def _moment(value):
    return Value(value, output_field=DateTimeField())


def _identified(field):
    return Q(**{f'{field}__isnull': False}) & ~Q(**{field: ''})


# Identity reaches an event either directly or through its fragment, and the
# visit rollup reads it the same way (see ``INSERT_PAGE_VISITS_SQL``).  Testing
# only the fragment would call a visit anonymous whose events carried an ID.
_IDENTIFIED_EVENT = (
    _identified('user_id')
    | _identified('company_id')
    | _identified('session__user_id')
    | _identified('session__company_id')
)

# The rollup starts a new page visit when the URL or the matched rule changes,
# so a page is that pair rather than the URL alone.
_PAGE_KEY = Concat(
    Coalesce(
        NullIf('url_normalized', Value('')),
        NullIf('url', Value('')),
        Value(''),
        output_field=TextField(),
    ),
    Value('\x1f', output_field=TextField()),
    Coalesce(
        Cast('page_rule_id', output_field=TextField()),
        Value('', output_field=TextField()),
        output_field=TextField(),
    ),
    output_field=TextField(),
)

# Events without a URL never become a page visit (``INSERT_PAGE_VISITS_SQL``
# drops them), so they cannot add a page.  They still count as interaction: a
# click or a keystroke is one whether or not the payload carried a URL.
_HAS_PAGE_URL = ~Q(url_normalized='', url='')


def meaningful_analytics_session_ids(session_ids):
    """Return which of these recording sessions show meaningful analytics.

    One grouped aggregate over the linked events answers all four inputs of
    :func:`apps.tracker.analytics_eligibility.is_meaningful`.  A session with
    no linked analytics events produces no row and is absent from the result,
    which leaves it out of the Visits scope for the older and stricter reason
    that its analytical clock is null.
    """

    session_ids = [session_id for session_id in (session_ids or ()) if session_id]
    if not session_ids:
        return set()

    rows = (
        AnalyticsEvent.objects
        .filter(session__visit_session_id__in=session_ids)
        .values('session__visit_session_id')
        .annotate(
            event_start=Min('timestamp'),
            event_end=Max('timestamp'),
            last_meaningful_at=Max('timestamp', filter=Q(event_type__in=MEANINGFUL_EVENT_TYPES)),
            identified_events=Count('id', filter=_IDENTIFIED_EVENT),
            page_keys=Count(_PAGE_KEY, distinct=True, filter=_HAS_PAGE_URL),
        )
        .order_by()
    )

    meaningful = set()
    for row in rows:
        span_seconds = (row['event_end'] - row['event_start']).total_seconds()
        last_meaningful_at = row['last_meaningful_at']
        if is_meaningful(
            has_identity=row['identified_events'] > 0,
            page_count=row['page_keys'],
            span_seconds=span_seconds,
            meaningful_event_offset_seconds=(
                None
                if last_meaningful_at is None
                else (last_meaningful_at - row['event_start']).total_seconds()
            ),
        ):
            meaningful.add(row['session__visit_session_id'])
    return meaningful


def mark_meaningful_analytics_sessions(session_ids):
    """Flag recordings whose linked analytics clear the low-confidence bar.

    Set-only, like :func:`mark_replay_snapshot_sessions`.  Ingest can only ever
    add evidence — an identity, an extra page, a qualifying interaction, and a
    widening span all only arrive — so no later batch withdraws what an earlier
    one recorded.  The interaction-offset condition keeps that true rather than
    breaking it: the offset is the last qualifying interaction minus the first
    event, and ingest can only push the former later or the latter earlier, so
    an offset that has cleared the bar cannot fall back below it.  Only sessions
    still unflagged are examined, which keeps a long session from re-aggregating
    its whole event history on every batch.

    That invariant covers ingest alone.  Writers that rewrite stored events can
    lower the evidence, so they need
    :func:`refresh_meaningful_analytics_flags` instead — see its docstring.
    """

    session_ids = {session_id for session_id in (session_ids or ()) if session_id}
    if not session_ids:
        return 0
    unflagged = set(
        Session.objects
        .filter(pk__in=session_ids, has_meaningful_analytics=False)
        .values_list('pk', flat=True)
    )
    if not unflagged:
        return 0
    meaningful = meaningful_analytics_session_ids(unflagged)
    if not meaningful:
        return 0
    return (
        Session.objects
        .filter(pk__in=meaningful, has_meaningful_analytics=False)
        .update(has_meaningful_analytics=True)
    )


def refresh_meaningful_analytics_flags(session_ids):
    """Recompute the low-confidence flag, in both directions.

    Ingest only adds evidence, but page naming does not: rewriting stored
    ``AnalyticsEvent`` rows can lower the distinct-page count that qualified a
    session.  ``apply_rules_to_analytics_events`` rewrites both halves of the
    page key — ``url_normalized`` and ``page_rule_id`` — so two pages can
    collapse into one, and a set-only flag would keep asserting evidence that
    no longer exists.  Left stale, Visits would keep listing a session the
    Pages rollup had already dropped, because that side recomputes from events
    on every rebuild.

    This mirrors :func:`refresh_replay_snapshot_flags`, which exists for the
    same reason on the other flag.
    """

    session_ids = [session_id for session_id in (session_ids or ()) if session_id]
    if not session_ids:
        return 0

    meaningful = meaningful_analytics_session_ids(session_ids)
    scoped = Session.objects.filter(pk__in=session_ids)
    return (
        scoped
        .filter(has_meaningful_analytics=False)
        .filter(pk__in=meaningful)
        .update(has_meaningful_analytics=True)
    ) + (
        scoped
        .filter(has_meaningful_analytics=True)
        .exclude(pk__in=meaningful)
        .update(has_meaningful_analytics=False)
    )


def record_analytics_event_bounds(bounds_by_session):
    """Widen each recording session's stored analytical event interval.

    ``bounds_by_session`` maps a recording ``Session`` primary key to the
    ``(first, last)`` event timestamps observed for it in one ingest batch.
    """

    updated = 0
    for session_id, bounds in (bounds_by_session or {}).items():
        first, last = bounds
        if first is None or last is None:
            continue
        # Coalesce keeps this correct on backends whose LEAST/GREATEST return
        # null when any argument is null, which is the first-event case here.
        updated += Session.objects.filter(pk=session_id).update(
            analytics_event_start=Least(
                Coalesce('analytics_event_start', _moment(first)),
                _moment(first),
            ),
            analytics_event_end=Greatest(
                Coalesce('analytics_event_end', _moment(last)),
                _moment(last),
            ),
        )
    return updated


def mark_replay_snapshot_sessions(session_ids):
    """Flag recording sessions that have stored a replayable full snapshot."""

    session_ids = {session_id for session_id in (session_ids or ()) if session_id}
    if not session_ids:
        return 0
    return (
        Session.objects
        .filter(pk__in=session_ids, has_replay_snapshot=False)
        .update(has_replay_snapshot=True)
    )


def refresh_replay_snapshot_flags(session_ids):
    """Recompute only the replay flag, in both directions.

    A snapshot can stop being replayable — pruned, moved to another recording,
    or rewritten with an unusable DOM root — so this clears the flag as well as
    setting it.  The ingest helper stays set-only because ingest only appends.
    """

    session_ids = [session_id for session_id in (session_ids or ()) if session_id]
    if not session_ids:
        return 0
    replayable_snapshots = replayable_full_snapshot_events(session_id=OuterRef('pk'))
    scoped = Session.objects.filter(pk__in=session_ids)
    return (
        scoped
        .filter(has_replay_snapshot=False)
        .filter(Exists(replayable_snapshots))
        .update(has_replay_snapshot=True)
    ) + (
        scoped
        .filter(has_replay_snapshot=True)
        .filter(~Exists(replayable_snapshots))
        .update(has_replay_snapshot=False)
    )


def refresh_visits_scope(session_ids):
    """Recompute the scope for recordings written outside the ingest path.

    Demo cloning, stream repair, synthetic imports and archive restores insert
    recording rows wholesale rather than observing events arrive, so they
    recompute both facts from what was written.  Unlike the ingest helpers this
    is authoritative: it clears a stored interval whose events have gone.
    """

    session_ids = [session_id for session_id in (session_ids or ()) if session_id]
    if not session_ids:
        return 0

    bounds = {
        row['session__visit_session_id']: row
        for row in (
            AnalyticsEvent.objects
            .filter(session__visit_session_id__in=session_ids)
            .values('session__visit_session_id')
            .annotate(event_start=Min('timestamp'), event_end=Max('timestamp'))
            .order_by()
        )
    }
    meaningful = meaningful_analytics_session_ids(session_ids)
    replayable_snapshots = replayable_full_snapshot_events(session_id=OuterRef('pk'))
    updates = []
    for session in (
        Session.objects
        .filter(pk__in=session_ids)
        .annotate(stores_replay_snapshot=Exists(replayable_snapshots))
    ):
        row = bounds.get(session.pk) or {}
        session.analytics_event_start = row.get('event_start')
        session.analytics_event_end = row.get('event_end')
        session.has_replay_snapshot = bool(session.stores_replay_snapshot)
        session.has_meaningful_analytics = session.pk in meaningful
        updates.append(session)

    Session.objects.bulk_update(
        updates,
        [
            'analytics_event_start',
            'analytics_event_end',
            'has_replay_snapshot',
            'has_meaningful_analytics',
        ],
        batch_size=500,
    )
    return len(updates)


@receiver(post_save, sender=Event, dispatch_uid='visits_scope_replay_snapshot_saved')
@receiver(post_delete, sender=Event, dispatch_uid='visits_scope_replay_snapshot_deleted')
def _refresh_replay_snapshot(sender, instance, raw=False, **kwargs):
    """Keep the replay flag current for a singly written rrweb event."""

    if raw or not instance.session_id:
        return
    if instance.event_type == RRWEB_FULL_SNAPSHOT_TYPE:
        refresh_replay_snapshot_flags([instance.session_id])


@receiver(post_save, sender=AnalyticsEvent, dispatch_uid='visits_scope_event_bounds')
def _record_analytics_event_bound(sender, instance, raw=False, **kwargs):
    """Widen the analytical interval for a singly saved analytics event.

    The low-confidence flag is re-examined here too.  It reads the session's
    stored events rather than this one, so it has to run after the write that
    makes the new event visible — a receiver, not a caller-side computation.
    """

    if raw or not instance.session_id:
        return
    visit_session_id = (
        AnalyticsSession.objects
        .filter(pk=instance.session_id)
        .values_list('visit_session_id', flat=True)
        .first()
    )
    if visit_session_id:
        record_analytics_event_bounds({
            visit_session_id: (instance.timestamp, instance.timestamp),
        })
        mark_meaningful_analytics_sessions([visit_session_id])
