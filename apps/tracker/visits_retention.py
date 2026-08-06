from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.tracker.models import (
    Event,
    Session,
    Visitor,
)


DEFAULT_RECORDING_VISITS_RETENTION_DAYS = 30
DEFAULT_RECORDING_VISITS_PRUNE_BATCH_SIZE = 100


def _expired_sessions(cutoff):
    return Session.objects.filter(start_time__lt=cutoff)


def _retention_counts(cutoff):
    expired_sessions = _expired_sessions(cutoff)
    return {
        'sessions': expired_sessions.count(),
        'rrweb_events': Event.objects.filter(session__in=expired_sessions).count(),
    }


def prune_expired_recording_visits(
    *,
    retention_days=DEFAULT_RECORDING_VISITS_RETENTION_DAYS,
    batch_size=DEFAULT_RECORDING_VISITS_PRUNE_BATCH_SIZE,
    now=None,
    dry_run=False,
):
    retention_days = int(retention_days)
    batch_size = int(batch_size)
    if retention_days <= 0:
        raise ValueError('retention_days must be greater than zero')
    if batch_size <= 0:
        raise ValueError('batch_size must be greater than zero')

    cutoff = (now or timezone.now()) - timedelta(days=retention_days)
    if dry_run:
        counts = _retention_counts(cutoff)
        return {
            'retention_days': retention_days,
            'cutoff': cutoff.isoformat(),
            **{f'matched_{key}': value for key, value in counts.items()},
            **{f'deleted_{key}': 0 for key in counts},
            'deleted_visitors': 0,
            'batches': 0,
            'dry_run': True,
        }

    deleted = {
        'sessions': 0,
        'rrweb_events': 0,
        'visitors': 0,
    }
    batches = 0
    while True:
        session_ids = list(
            _expired_sessions(cutoff)
            .order_by('session_id')
            .values_list('session_id', flat=True)[:batch_size]
        )
        if not session_ids:
            break

        with transaction.atomic():
            visitor_ids = list(
                Session.objects.filter(session_id__in=session_ids)
                .exclude(visitor_id=None)
                .values_list('visitor_id', flat=True)
                .distinct()
            )
            batch_counts = {
                'rrweb_events': Event.objects.filter(
                    session_id__in=session_ids,
                ).count(),
            }

            Session.objects.filter(session_id__in=session_ids).delete()
            deleted['sessions'] += len(session_ids)
            for key, value in batch_counts.items():
                deleted[key] += value

            if visitor_ids:
                orphan_visitors = Visitor.objects.filter(
                    visitor_id__in=visitor_ids,
                    sessions__isnull=True,
                )
                orphan_count = orphan_visitors.count()
                orphan_visitors.delete()
                deleted['visitors'] += orphan_count
        batches += 1

    return {
        'retention_days': retention_days,
        'cutoff': cutoff.isoformat(),
        **{f'matched_{key}': value for key, value in deleted.items() if key != 'visitors'},
        **{f'deleted_{key}': value for key, value in deleted.items()},
        'batches': batches,
        'dry_run': False,
    }
