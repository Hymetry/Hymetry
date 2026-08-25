"""The shared low-confidence anonymous session rule.

A completed session carries no analytical signal worth reporting when every one
of these holds:

* it never supplied a user ID or a company ID;
* it produced exactly one page visit;
* its analytical span is under ten seconds;
* it recorded no deliberate interaction clear of its opening second.

Four event types count as deliberate: ``click``, ``scroll``, ``key_press`` and
``touch_move``.  Each needs the visitor to have decided to press, drag or type.
How often the tracker samples one is beside the point: ``key_press`` and
``touch_move`` are sampled exactly the way ``mouse_move`` is and still count,
because neither a keystroke nor a finger dragging across glass can happen by
accident.

``mouse_move`` deliberately does not count, and the difference is not the
sampling but the intent.  A pointer sweeps across an abandoned tab on its way
somewhere else and leaves the same record a reading visitor does, so treating
it as engagement would retain exactly the traffic this rule exists to drop.
Nothing reaches a touchscreen the same way.

``touchstart`` is not recorded at all, so it is absent here by construction.  A
touch device synthesizes a click after a tap, so every tap already arrives as a
``click``; a start-of-touch record would only duplicate it.

An interaction inside :data:`MEANINGFUL_EVENT_MIN_OFFSET_SECONDS` of the
session's first event does not count either, for the same reason one step
removed.  Restored scroll position, an autofocused control, a consent banner
dismissed by an automated client — these land in the same instant as the page
view and say nothing about a visitor reading anything.  Without the offset the
rule leaked precisely the shape it targets: sub-second anonymous single-page
sessions, kept alive by one interaction fired at load.

Nothing is deleted.  Excluded sessions keep their raw events, their
``AnalyticsEvent`` rows and their ``PageVisit`` rows; only the reporting
surfaces skip them, so a changed threshold is a rebuild rather than a
re-collection.

Two pipelines apply the rule, and this module is the single place that defines
it:

``apps.tracker.visits_table``
    filters on the denormalized ``Session.has_meaningful_analytics`` flag that
    ``apps.tracker.visits_scope`` maintains, because the Visits row scope has
    to stay an indexed range scan rather than a per-request aggregate over the
    project's whole event history.
``apps.pages.queries``
    recomputes the same predicate in SQL while it prepares ``PageVisit`` rows,
    so the Pages rollup carries no dependency on how fresh the tracker
    denormalization happens to be.

``apps.pages.tests.test_low_confidence_sessions.LowConfidenceParityTests``
asserts the two answer alike.

Session grain
-------------
``AnalyticsSession`` is an identity *fragment*: a visit that starts anonymous
and then identifies itself becomes two fragments.  Judging fragments separately
would drop the anonymous opening of an identified visit, which the rule is not
meant to touch, so both pipelines group fragments back into one visit first.

They do it differently, because they can afford different things.  The tracker
groups by the recording session a fragment links to, which is free: a Visits
row *is* a recording, so a session whose recording retention has deleted has no
row to judge.  The Pages rollup cannot lean on that link — retention nulls
``AnalyticsSession.visit_session`` after 30 days while the events and prepared
visits live on, and the nightly job re-judges 180 days — so it rebuilds the
grouping from the events as a visitor run split on the session timeout.  That
is the same definition the tracker's session resolver uses, so the two agree,
and a visitor GUID is never nulled, so the Pages side keeps agreeing for as
long as the events exist.

Completion
----------
The rule only judges sessions that are over.  Both pipelines read completion
off the same fact, the last linked analytics event: a scope is complete once
that event is older than :func:`completion_cutoff`.  A session still receiving
events is kept no matter how thin it currently looks, because the very next
batch can carry the click that qualifies it.

Window safety
-------------
Only sessions shorter than :data:`LOW_CONFIDENCE_MAX_DURATION_SECONDS` can be
excluded, and the Pages rollup reads events from a window widened by a day on
each side (see :func:`apps.pages.services.rebuild_project_pages_analytics`).
Any session the rule can touch therefore lies wholly inside the read window
even when it straddles a local midnight, so a partial rebuild cannot mistake
one half of a two-page session for a single-page one.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

# A session must reach this span before it counts as meaningful on its own.
LOW_CONFIDENCE_MAX_DURATION_SECONDS = 10

# Event types that count as deliberate interaction.  `mouse_move` is excluded
# on purpose; see the module docstring.
MEANINGFUL_EVENT_TYPES = ('click', 'scroll', 'key_press', 'touch_move')

# How long after the session's first event an interaction has to land before it
# counts as deliberate rather than as load-time noise.
MEANINGFUL_EVENT_MIN_OFFSET_SECONDS = 1

# A scope producing more page visits than this has shown navigation intent.
LOW_CONFIDENCE_MAX_PAGE_VISITS = 1


def completion_cutoff(now=None):
    """Return the moment before which a session's last event means it is over.

    Mirrors :attr:`apps.tracker.models.AnalyticsSession.is_active`, so a
    session this rule treats as complete is one the tracker would no longer
    accept events into without opening a new one.
    """

    moment = now or timezone.now()
    timeout = getattr(settings, 'ANALYTICS_SESSION_EXPIRATION_SECONDS', 1800)
    return moment - timedelta(seconds=timeout)


def is_meaningful(
    *,
    has_identity,
    page_count,
    span_seconds,
    meaningful_event_offset_seconds,
):
    """Return whether one session's observed facts clear the low-confidence bar.

    This is the canonical predicate.  Both pipelines implement it in the shape
    their storage needs — an ORM aggregate for the tracker, one SQL statement
    for the Pages rollup — and the parity test drives all four inputs through
    every implementation.

    ``page_count`` is the number of distinct ``(url, page rule)`` pairs the
    session addressed rather than a count of prepared ``PageVisit`` rows.  The
    two agree on the only boundary this rule tests: visit segmentation starts a
    new visit when either of those changes or when more than the session
    timeout passes, and a session short enough to be excluded cannot contain
    such a gap.  So one distinct page means exactly one visit, and more than
    one means more than one visit.

    ``meaningful_event_offset_seconds`` is how long after the session's first
    event its *last* :data:`MEANINGFUL_EVENT_TYPES` event landed, or ``None``
    when it recorded none.  The question the rule asks is whether *any* of them
    cleared :data:`MEANINGFUL_EVENT_MIN_OFFSET_SECONDS`, and the latest one
    answers it: if the last is too early then every earlier one is too.  Asking
    it that way keeps both pipelines to a single grouped aggregate — a
    ``MAX`` beside the ``MIN`` each already computes — instead of a window
    function that would have to rank each event against its own session.
    """

    if has_identity:
        return True
    if (
        meaningful_event_offset_seconds is not None
        and meaningful_event_offset_seconds >= MEANINGFUL_EVENT_MIN_OFFSET_SECONDS
    ):
        return True
    if page_count > LOW_CONFIDENCE_MAX_PAGE_VISITS:
        return True
    return span_seconds >= LOW_CONFIDENCE_MAX_DURATION_SECONDS


def exclude_low_confidence_sessions(queryset, *, now=None):
    """Drop completed low-confidence recordings from a ``Session`` queryset.

    Applied to the Visits row scope before pagination counts it, so an
    excluded session leaves neither a row nor a place in the range total.

    A session whose last linked analytics event is newer than the cutoff is
    still in flight and is kept, which is why this cannot be a plain filter on
    the stored flag alone.
    """

    return queryset.exclude(
        Q(has_meaningful_analytics=False)
        & Q(analytics_event_end__lt=completion_cutoff(now)),
    )
