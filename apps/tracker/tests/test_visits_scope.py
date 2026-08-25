"""Contract for the denormalized Visits row scope.

The Visits table selects its rows from stored ``Session`` columns rather than
aggregating linked analytics events per request, so these tests pin down who
keeps those columns true — ingest, offline writers, and the backfill.
"""

import importlib
import json
import uuid
from datetime import datetime, timedelta, timezone as datetime_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.projects.models import Project, Workspace
from apps.tracker.models import (
    AnalyticsEvent,
    AnalyticsSession,
    Event,
    Session,
    Visitor,
)
from apps.tracker.visits_scope import (
    mark_replay_snapshot_sessions,
    record_analytics_event_bounds,
    refresh_visits_scope,
)

UTC = datetime_timezone.utc


def _full_snapshot_payload(timestamp):
    return {
        'type': 2,
        'timestamp': int(timestamp.timestamp() * 1000),
        'data': {'node': {'type': 0, 'id': 1, 'childNodes': []}},
    }


class VisitsScopeMaintenanceTests(TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
        self.owner = get_user_model().objects.create_user(
            username='scope-owner',
            email='scope-owner@example.com',
            password='testpass123',
        )
        self.workspace = Workspace.objects.create(
            name='Scope workspace',
            created_by=self.owner,
        )
        self.project = Project.objects.create(
            workspace=self.workspace,
            created_by=self.owner,
            name='Scope project',
            api_key=uuid.uuid4().hex,
            allowed_domains='example.com',
            timezone='UTC',
        )
        self.visitor_guid = uuid.uuid4()
        self.visitor = Visitor.objects.create(
            project=self.project,
            visitor_guid=self.visitor_guid,
            first_visit=self.now,
            last_activity=self.now,
        )

    def _session(self, **overrides):
        return Session.objects.create(
            visitor=self.visitor,
            start_time=self.now,
            last_activity=self.now,
            ended_at=self.now + timedelta(minutes=5),
            **overrides,
        )

    def test_bounds_widen_and_never_narrow(self):
        session = self._session()
        first = self.now
        last = self.now + timedelta(minutes=3)

        record_analytics_event_bounds({session.pk: (first, last)})
        session.refresh_from_db()
        self.assertEqual(session.analytics_event_start, first)
        self.assertEqual(session.analytics_event_end, last)

        # A later batch that arrives out of order must extend the interval in
        # both directions rather than replace it.
        record_analytics_event_bounds({
            session.pk: (first - timedelta(minutes=1), first),
        })
        record_analytics_event_bounds({
            session.pk: (last, last + timedelta(minutes=1)),
        })
        session.refresh_from_db()
        self.assertEqual(session.analytics_event_start, first - timedelta(minutes=1))
        self.assertEqual(session.analytics_event_end, last + timedelta(minutes=1))

    def test_marking_a_replay_snapshot_is_idempotent(self):
        session = self._session()

        self.assertEqual(mark_replay_snapshot_sessions([session.pk]), 1)
        self.assertEqual(mark_replay_snapshot_sessions([session.pk]), 0)
        session.refresh_from_db()
        self.assertTrue(session.has_replay_snapshot)

    def test_refresh_recomputes_both_facts_from_stored_rows(self):
        session = self._session()
        fragment = AnalyticsSession.objects.create(
            project=self.project,
            visit_session=session,
            visitor_guid=self.visitor_guid,
            start_time=self.now,
            last_activity=self.now,
        )
        first = self.now + timedelta(seconds=5)
        last = self.now + timedelta(seconds=95)
        for timestamp in (first, last):
            AnalyticsEvent.objects.create(
                session=fragment,
                event_type='click',
                timestamp=timestamp,
                visitor_guid=self.visitor_guid,
                url='https://example.com/page',
                url_normalized='example.com/page',
            )
        Event.objects.create(
            session=session,
            event_type=2,
            timestamp=self.now,
            data=_full_snapshot_payload(self.now),
        )
        # Wipe the stored scope to prove the refresh derives it, rather than
        # relying on whatever the row-level writes already set.
        Session.objects.filter(pk=session.pk).update(
            analytics_event_start=None,
            analytics_event_end=None,
            has_replay_snapshot=False,
        )

        refresh_visits_scope([session.pk])

        session.refresh_from_db()
        self.assertEqual(session.analytics_event_start, first)
        self.assertEqual(session.analytics_event_end, last)
        self.assertTrue(session.has_replay_snapshot)

    def test_refresh_clears_a_scope_whose_events_are_gone(self):
        session = self._session(
            analytics_event_start=self.now,
            analytics_event_end=self.now + timedelta(minutes=1),
            has_replay_snapshot=True,
        )

        refresh_visits_scope([session.pk])

        session.refresh_from_db()
        self.assertIsNone(session.analytics_event_start)
        self.assertIsNone(session.analytics_event_end)
        self.assertFalse(session.has_replay_snapshot)

    def test_deleting_the_only_snapshot_drops_replayability(self):
        session = self._session()
        snapshot = Event.objects.create(
            session=session,
            event_type=2,
            timestamp=self.now,
            data=_full_snapshot_payload(self.now),
        )
        session.refresh_from_db()
        self.assertTrue(session.has_replay_snapshot)

        snapshot.delete()

        session.refresh_from_db()
        self.assertFalse(session.has_replay_snapshot)

    def test_rewriting_a_snapshot_without_a_dom_root_drops_replayability(self):
        session = self._session()
        snapshot = Event.objects.create(
            session=session,
            event_type=2,
            timestamp=self.now,
            data=_full_snapshot_payload(self.now),
        )
        session.refresh_from_db()
        self.assertTrue(session.has_replay_snapshot)

        snapshot.data['data'] = {}
        snapshot.save(update_fields=['data'])

        session.refresh_from_db()
        self.assertFalse(session.has_replay_snapshot)


class VisitsScopeBackfillMigrationTests(TestCase):
    """The 0016 backfill has to derive the scope for pre-existing recordings.

    It runs against historical models, so it is exercised directly rather than
    through the live helpers it mirrors.
    """

    def setUp(self):
        self.now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
        self.owner = get_user_model().objects.create_user(
            username='backfill-owner',
            email='backfill-owner@example.com',
            password='testpass123',
        )
        self.workspace = Workspace.objects.create(
            name='Backfill workspace',
            created_by=self.owner,
        )
        self.project = Project.objects.create(
            workspace=self.workspace,
            created_by=self.owner,
            name='Backfill project',
            api_key=uuid.uuid4().hex,
            allowed_domains=['example.com'],
            timezone='UTC',
        )

    def _legacy_recording(self, *, replayable, linked):
        visitor = Visitor.objects.create(
            project=self.project,
            visitor_guid=uuid.uuid4(),
            first_visit=self.now,
            last_activity=self.now,
        )
        session = Session.objects.create(
            visitor=visitor,
            start_time=self.now,
            last_activity=self.now,
            ended_at=self.now + timedelta(minutes=5),
        )
        if replayable:
            Event.objects.create(
                session=session,
                event_type=2,
                timestamp=self.now,
                data=_full_snapshot_payload(self.now),
            )
        if linked:
            fragment = AnalyticsSession.objects.create(
                project=self.project,
                visit_session=session,
                visitor_guid=visitor.visitor_guid,
                start_time=self.now,
                last_activity=self.now,
            )
            for offset in (10, 70):
                AnalyticsEvent.objects.create(
                    session=fragment,
                    event_type='click',
                    timestamp=self.now + timedelta(seconds=offset),
                    visitor_guid=visitor.visitor_guid,
                    url='https://example.com/page',
                    url_normalized='example.com/page',
                )
        # Rows written before the migration carry no denormalized scope.
        Session.objects.filter(pk=session.pk).update(
            analytics_event_start=None,
            analytics_event_end=None,
            has_replay_snapshot=False,
        )
        return session

    def test_backfill_derives_the_scope_for_existing_recordings(self):
        from django.apps import apps as live_apps

        migration = importlib.import_module(
            'apps.tracker.migrations.0004_backfill_visits_scope',
        )
        complete = self._legacy_recording(replayable=True, linked=True)
        unlinked = self._legacy_recording(replayable=True, linked=False)
        unreplayable = self._legacy_recording(replayable=False, linked=True)

        migration.backfill_visits_scope(live_apps, None)

        complete.refresh_from_db()
        self.assertTrue(complete.has_replay_snapshot)
        self.assertEqual(
            complete.analytics_event_start,
            self.now + timedelta(seconds=10),
        )
        self.assertEqual(
            complete.analytics_event_end,
            self.now + timedelta(seconds=70),
        )

        unlinked.refresh_from_db()
        self.assertTrue(unlinked.has_replay_snapshot)
        self.assertIsNone(unlinked.analytics_event_start)

        unreplayable.refresh_from_db()
        self.assertFalse(unreplayable.has_replay_snapshot)
        self.assertEqual(
            unreplayable.analytics_event_start,
            self.now + timedelta(seconds=10),
        )


class VisitsScopeIngestTests(TestCase):
    """Ingest writes with ``bulk_create``, which fires no model signals.

    These cover the contract that both tracker endpoints maintain the scope
    themselves, because a signal-based guarantee would silently not apply.
    """

    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username='ingest-owner',
            email='ingest-owner@example.com',
            password='testpass123',
        )
        self.workspace = Workspace.objects.create(
            name='Ingest workspace',
            created_by=self.owner,
        )
        self.project = Project.objects.create(
            workspace=self.workspace,
            created_by=self.owner,
            name='Ingest project',
            api_key=uuid.uuid4().hex,
            tracking_capture='analytics,recording',
            product_url='https://example.com',
            allowed_domains=['example.com'],
            timezone='UTC',
        )
        self.visitor_guid = str(uuid.uuid4())

    def _post(self, url_name, payload):
        return self.client.post(
            reverse(url_name),
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_ORIGIN='https://example.com',
        )

    def test_recording_ingest_records_replayability(self):
        moment = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
        response = self._post('record_event', {
            'api_key': self.project.api_key,
            'visitor_id': self.visitor_guid,
            'tab_id': 'tab-1',
            'page_url': 'https://example.com/page',
            'page_title': 'Page',
            'event_data': {
                'type': 'batch',
                'events': [_full_snapshot_payload(moment)],
            },
        })

        self.assertEqual(response.status_code, 200)
        session = Session.objects.get(visitor__project=self.project)
        self.assertTrue(session.has_replay_snapshot)

    def test_analytics_ingest_records_the_event_interval(self):
        first = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
        last = first + timedelta(seconds=40)
        response = self._post('record_analytics', {
            'api_key': self.project.api_key,
            'visitor_id': self.visitor_guid,
            'batch': [
                {
                    'type': 'click',
                    'ts': moment.isoformat().replace('+00:00', 'Z'),
                    'page': {
                        'url': 'https://example.com/page',
                        'title': 'Page',
                    },
                    'elementKey': 'Button: Go',
                }
                for moment in (first, last)
            ],
        })

        self.assertEqual(response.status_code, 200)
        session = Session.objects.get(visitor__project=self.project)
        self.assertEqual(session.analytics_event_start, first)
        self.assertEqual(session.analytics_event_end, last)
