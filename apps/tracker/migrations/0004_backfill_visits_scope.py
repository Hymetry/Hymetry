"""Backfill the denormalized Visits row scope for existing recordings.

Kept separate from the schema migration and non-atomic on purpose: the replay
snapshot pass has to read stored rrweb payloads and the low-confidence pass
aggregates every linked analytics event a project has, so batching by session
keyset commits incrementally instead of holding one transaction over the whole
recording table.

All three facts are recomputed from their sources, so a run interrupted part
way is safe to repeat.

This target adopts the denormalized scope in one step, so the flag is judged
directly under the rule as it stands here rather than through the sequence of
successive rules the source used.  The rule is inlined rather than imported
because a migration has to keep describing the rule as it stood when it ran,
while ``apps.tracker.analytics_eligibility`` is free to change again.
"""

from django.db import migrations
from django.db.models import Count, Exists, Max, Min, OuterRef, Q, TextField, Value
from django.db.models.functions import Cast, Coalesce, Concat, NullIf

BATCH_SIZE = 1000
RRWEB_FULL_SNAPSHOT_TYPE = 2

# Mirrors apps.tracker.analytics_eligibility as of this migration.
LOW_CONFIDENCE_MAX_DURATION_SECONDS = 10
LOW_CONFIDENCE_MAX_PAGE_VISITS = 1
MEANINGFUL_EVENT_TYPES = ('click', 'scroll', 'key_press', 'touch_move')
MEANINGFUL_EVENT_MIN_OFFSET_SECONDS = 1


def _identified(field):
    return Q(**{f'{field}__isnull': False}) & ~Q(**{field: ''})


IDENTIFIED_EVENT = (
    _identified('user_id')
    | _identified('company_id')
    | _identified('session__user_id')
    | _identified('session__company_id')
)

PAGE_KEY = Concat(
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

HAS_PAGE_URL = ~Q(url_normalized='', url='')


def _session_id_batches(Session):
    last_session_id = None
    while True:
        queryset = Session.objects.order_by('session_id')
        if last_session_id is not None:
            queryset = queryset.filter(session_id__gt=last_session_id)
        batch = list(queryset.values_list('session_id', flat=True)[:BATCH_SIZE])
        if not batch:
            return
        yield batch
        last_session_id = batch[-1]


def backfill_visits_scope(apps, schema_editor):
    Session = apps.get_model('tracker', 'Session')
    AnalyticsEvent = apps.get_model('tracker', 'AnalyticsEvent')
    Event = apps.get_model('tracker', 'Event')

    for session_ids in _session_id_batches(Session):
        rows = list(
            AnalyticsEvent.objects
            .filter(session__visit_session_id__in=session_ids)
            .values('session__visit_session_id')
            .annotate(
                event_start=Min('timestamp'),
                event_end=Max('timestamp'),
                last_meaningful_at=Max(
                    'timestamp',
                    filter=Q(event_type__in=MEANINGFUL_EVENT_TYPES),
                ),
                identified_events=Count('id', filter=IDENTIFIED_EVENT),
                page_keys=Count(PAGE_KEY, distinct=True, filter=HAS_PAGE_URL),
            )
            .order_by()
        )

        bounds = {row['session__visit_session_id']: row for row in rows}
        if bounds:
            updates = []
            for session in Session.objects.filter(pk__in=list(bounds)):
                row = bounds[session.pk]
                session.analytics_event_start = row['event_start']
                session.analytics_event_end = row['event_end']
                updates.append(session)
            Session.objects.bulk_update(
                updates,
                ['analytics_event_start', 'analytics_event_end'],
                batch_size=500,
            )

        meaningful = []
        for row in rows:
            span_seconds = (row['event_end'] - row['event_start']).total_seconds()
            last_meaningful_at = row['last_meaningful_at']
            meaningful_offset_seconds = (
                None
                if last_meaningful_at is None
                else (last_meaningful_at - row['event_start']).total_seconds()
            )
            if (
                row['identified_events'] > 0
                or (
                    meaningful_offset_seconds is not None
                    and meaningful_offset_seconds >= MEANINGFUL_EVENT_MIN_OFFSET_SECONDS
                )
                or row['page_keys'] > LOW_CONFIDENCE_MAX_PAGE_VISITS
                or span_seconds >= LOW_CONFIDENCE_MAX_DURATION_SECONDS
            ):
                meaningful.append(row['session__visit_session_id'])

        batch = Session.objects.filter(pk__in=session_ids)
        if meaningful:
            (
                batch
                .filter(pk__in=meaningful, has_meaningful_analytics=False)
                .update(has_meaningful_analytics=True)
            )
        (
            batch
            .filter(has_meaningful_analytics=True)
            .exclude(pk__in=meaningful)
            .update(has_meaningful_analytics=False)
        )

        # Mirrors apps.tracker.replayability.replayable_full_snapshot_events:
        # a full snapshot only replays when it carries the serialized DOM root.
        replayable_snapshots = Event.objects.filter(
            session_id=OuterRef('pk'),
            event_type=RRWEB_FULL_SNAPSHOT_TYPE,
            data__type=RRWEB_FULL_SNAPSHOT_TYPE,
            data__data__node__id__isnull=False,
            data__data__node__type__isnull=False,
        )
        (
            Session.objects
            .filter(pk__in=session_ids, has_replay_snapshot=False)
            .filter(Exists(replayable_snapshots))
            .update(has_replay_snapshot=True)
        )


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ('tracker', '0003_visits_scope_denormalization'),
    ]

    operations = [
        migrations.RunPython(backfill_visits_scope, migrations.RunPython.noop),
    ]
