import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.projects.models import Project
from apps.projects.tests.helpers import create_workspace_with_owner
from apps.tracker.management.commands.backfill_recording_visits import (
    link_unambiguous_legacy_identity,
)
from apps.tracker.models import AnalyticsSession, Event, Session, Visitor


class RecordingIdentityBackfillTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="identity-backfill-owner",
            email="identity-backfill-owner@example.com",
            password="testpass123",
        )
        workspace = create_workspace_with_owner(user, name="Identity backfill workspace")
        self.project = Project.objects.create(
            workspace=workspace,
            created_by=user,
            name="Identity backfill project",
            api_key="IDENTITY_BACKFILL_PROJECT",
        )
        self.now = timezone.now()
        self.visitor_guid = uuid.uuid4()

    def _recording(self, offset_seconds=0):
        start = self.now + timedelta(seconds=offset_seconds)
        visitor, _created = Visitor.objects.get_or_create(
            project=self.project,
            visitor_guid=self.visitor_guid,
            defaults={
                "first_visit": start,
                "last_activity": start + timedelta(minutes=2),
            },
        )
        session = Session.objects.create(
            visitor=visitor,
            start_time=start,
            last_activity=start + timedelta(minutes=2),
            ended_at=start + timedelta(minutes=2),
        )
        Event.objects.create(
            session=session,
            event_type=2,
            timestamp=start,
            data={"type": 2, "data": {"node": {"type": 0, "id": 1}}},
        )
        return session

    def _analytics(self):
        return AnalyticsSession.objects.create(
            project=self.project,
            visitor_guid=self.visitor_guid,
            user_id="legacy-user",
            company_id="legacy-company",
            start_time=self.now,
            last_activity=self.now + timedelta(minutes=2),
            ended_at=self.now + timedelta(minutes=2),
        )

    def test_backfill_links_one_clear_candidate(self):
        recording = self._recording()
        analytics = self._analytics()

        result = link_unambiguous_legacy_identity(self.project, days_back=1)

        analytics.refresh_from_db()
        recording.refresh_from_db()
        self.assertEqual(analytics.visit_session_id, recording.session_id)
        self.assertTrue(recording.identity_linkage_ready)
        self.assertEqual(result["linked"], 1)

    def test_backfill_leaves_equal_candidates_unresolved(self):
        self._recording()
        self._recording()
        analytics = self._analytics()

        result = link_unambiguous_legacy_identity(self.project, days_back=1)

        analytics.refresh_from_db()
        self.assertIsNone(analytics.visit_session_id)
        self.assertEqual(result["ambiguous"], 1)
