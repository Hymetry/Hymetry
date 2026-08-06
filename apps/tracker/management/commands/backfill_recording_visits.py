from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Max, Min
from django.utils import timezone

from apps.pages.locks import project_advisory_lock
from apps.projects.models import Project
from apps.tracker.models import AnalyticsSession, Session


def _effective_end(row):
    return row.get('event_end') or row.get('ended_at') or row.get('last_activity') or row['start_time']


def _candidate_score(recording, analytics):
    recording_start = recording.get('event_start') or recording['start_time']
    recording_end = _effective_end(recording)
    analytics_start = analytics.start_time
    analytics_end = analytics.ended_at or analytics.last_activity or analytics_start
    intersects = recording_start <= analytics_end and analytics_start <= recording_end
    if intersects:
        overlap = max(
            0.0,
            (min(recording_end, analytics_end) - max(recording_start, analytics_start)).total_seconds(),
        )
        gap = 0.0
    elif recording_end < analytics_start:
        overlap = 0.0
        gap = (analytics_start - recording_end).total_seconds()
    else:
        overlap = 0.0
        gap = (recording_start - analytics_end).total_seconds()
    return (
        0 if intersects else 1,
        -overlap,
        gap,
        abs((recording_start - analytics_start).total_seconds()),
    )


def link_unambiguous_legacy_identity(project, *, days_back=180, apply=True):
    cutoff = timezone.now() - timedelta(days=max(1, int(days_back)))
    recordings = list(
        Session.objects.filter(
            visitor__project=project,
            visitor__visitor_guid__isnull=False,
            start_time__gte=cutoff,
        )
        .values(
            'session_id',
            'visitor__visitor_guid',
            'start_time',
            'last_activity',
            'ended_at',
        )
        .annotate(event_start=Min('events__timestamp'), event_end=Max('events__timestamp'))
        .order_by('start_time', 'session_id')
    )
    recordings_by_guid = defaultdict(list)
    for recording in recordings:
        recordings_by_guid[recording['visitor__visitor_guid']].append(recording)

    max_gap = max(0, int(getattr(settings, 'VISITS_ANALYTICS_MATCH_MAX_GAP_SECONDS', 5)))
    linked = 0
    ambiguous = 0
    unmatched = 0
    linked_recording_ids = set()
    analytics_sessions = AnalyticsSession.objects.filter(
        project=project,
        visit_session__isnull=True,
        visitor_guid__isnull=False,
        start_time__gte=cutoff - timedelta(seconds=max_gap),
    ).order_by('start_time', 'session_id')
    for analytics in analytics_sessions.iterator(chunk_size=1000):
        ranked = []
        for recording in recordings_by_guid.get(analytics.visitor_guid, ()):
            score = _candidate_score(recording, analytics)
            if score[2] <= max_gap:
                ranked.append((score, recording))
        ranked.sort(key=lambda item: (item[0], str(item[1]['session_id'])))
        if not ranked:
            unmatched += 1
            continue
        if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
            ambiguous += 1
            continue
        recording_id = ranked[0][1]['session_id']
        if apply:
            AnalyticsSession.objects.filter(pk=analytics.pk, visit_session__isnull=True).update(
                visit_session_id=recording_id,
            )
        linked_recording_ids.add(recording_id)
        linked += 1

    if apply and linked_recording_ids:
        Session.objects.filter(session_id__in=linked_recording_ids).update(identity_linkage_ready=True)
    return {
        'linked': linked,
        'ambiguous': ambiguous,
        'unmatched': unmatched,
    }


class Command(BaseCommand):
    help = (
        'Link only unambiguous legacy analytics identity fragments to canonical '
        'recording Sessions. Defaults to the last 180 days.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--project-id', type=int)
        parser.add_argument('--days-back', type=int, default=180)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        projects = Project.active.all().order_by('id')
        if options['project_id']:
            projects = projects.filter(id=options['project_id'])

        total_projects = 0
        for project in projects:
            with project_advisory_lock(project.id, namespace='recording-activity') as acquired:
                if not acquired:
                    self.stdout.write(
                        self.style.WARNING(f'Project {project.id}: skipped; recording activity lock is busy.')
                    )
                    continue
                identity_result = link_unambiguous_legacy_identity(
                    project,
                    days_back=options['days_back'],
                    apply=not options['dry_run'],
                )
            total_projects += 1
            self.stdout.write(
                f"Project {project.id}: identity linked={identity_result['linked']}, "
                f"ambiguous={identity_result['ambiguous']}, "
                f"unmatched={identity_result['unmatched']}"
            )

        self.stdout.write(self.style.SUCCESS(f'Processed {total_projects} project(s).'))
