import json
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.projects.models import LifecycleStatus, Project
from apps.projects.tests.helpers import create_workspace_with_owner
from apps.tracker.models import Event, Session, Visitor
from apps.tracker.visitor_ids import normalize_project_visitor_uuid


class RecordingEventIngestionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="recording-owner",
            email="recording-owner@example.com",
            password="testpass123",
        )
        self.workspace = create_workspace_with_owner(
            self.user,
            name="Recording Event Workspace",
        )

    def _recording_payload(self, project, page_url):
        timestamp_ms = int(timezone.now().timestamp() * 1000)
        return {
            "api_key": project.api_key,
            "visitor_id": str(uuid4()),
            "tab_id": "tab-1",
            "page_url": page_url,
            "page_title": "Dashboard",
            "event_data": {
                "type": "batch",
                "events": [
                    {
                        "type": 3,
                        "timestamp": timestamp_ms,
                        "data": {"source": 2, "type": 2},
                    }
                ],
            },
        }

    def _project(self, *, name, api_key):
        return Project.objects.create(
            workspace=self.workspace,
            name=name,
            created_by=self.user,
            api_key=api_key,
            tracking_capture="analytics,recording",
        )

    def test_record_event_ignores_payload_for_analytics_only_project(self):
        project = Project.objects.create(
            workspace=self.workspace,
            name="Analytics Only Project",
            created_by=self.user,
            api_key="ANALYTICSONLY123",
            tracking_capture="analytics",
        )

        response = self.client.post(
            "/hm/e/",
            data=json.dumps(self._recording_payload(project, "https://example.com/app")),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ignored")
        self.assertEqual(Visitor.objects.count(), 0)
        self.assertEqual(Session.objects.count(), 0)
        self.assertEqual(Event.objects.count(), 0)

    def test_record_event_strips_query_from_url_for_recording_projects(self):
        project = self._project(name="Recording Project", api_key="RECORDING123")
        exact_url = "https://example.com/app/dashboard?tab=usage"

        response = self.client.post(
            "/hm/e/",
            data=json.dumps(self._recording_payload(project, exact_url)),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Event.objects.get().url, "https://example.com/app/dashboard")

    def test_record_event_normalizes_non_uuid_visitor_ids(self):
        project = self._project(
            name="Recording Project With Fallback Visitor IDs",
            api_key="RECORDINGNONUUID123",
        )
        payload = self._recording_payload(project, "https://example.com/app/dashboard")
        payload["visitor_id"] = "mobf9liv_zmwztu7r"

        response = self.client.post(
            "/hm/e/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        visitor = Visitor.objects.get()
        self.assertEqual(
            visitor.visitor_guid,
            normalize_project_visitor_uuid(project.id, "mobf9liv_zmwztu7r"),
        )
        self.assertEqual(response.json()["visitor_id"], str(visitor.visitor_guid))

    @override_settings(SESSION_MAX_DURATION_SECONDS=12 * 60 * 60)
    @patch("apps.tracker.models.Session._cleanup_redis_data")
    def test_recording_batch_crossing_twelve_hours_is_split_between_sessions(self, _cleanup):
        project = self._project(name="Long Recording Project", api_key="LONGRECORDING123")
        visitor_id = str(uuid4())
        start = timezone.now() - timedelta(hours=13)
        start = start.replace(microsecond=(start.microsecond // 1000) * 1000)
        payload = self._recording_payload(project, "https://example.com/app/dashboard")
        payload["visitor_id"] = visitor_id
        payload["event_data"]["events"] = [
            {
                "type": 2 if offset == 12 * 60 else 3,
                "timestamp": int((start + timedelta(minutes=offset)).timestamp() * 1000),
                "data": {} if offset == 12 * 60 else {"source": 2, "type": 2},
            }
            for offset in range(0, (12 * 60) + 1, 20)
        ]

        response = self.client.post(
            "/hm/e/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        sessions = list(Session.objects.order_by("start_time"))
        self.assertEqual(len(sessions), 2)
        boundary = start + timedelta(hours=12)
        self.assertEqual(sessions[0].ended_at, boundary)
        self.assertEqual(sessions[1].start_time, boundary)
        self.assertEqual(response.json()["session_id"], str(sessions[1].session_id))
        self.assertFalse(
            Event.objects.filter(session=sessions[0], timestamp__gte=boundary).exists()
        )
        self.assertTrue(
            Event.objects.filter(session=sessions[1], timestamp=boundary).exists()
        )

    def test_record_event_rejects_archived_project(self):
        project = self._project(name="Archived Recording Project", api_key="ARCHIVEDRECORDING123")
        project.lifecycle_status = LifecycleStatus.ARCHIVED
        project.save(update_fields=["lifecycle_status"])

        response = self.client.post(
            "/hm/e/",
            data=json.dumps(self._recording_payload(project, "https://example.com/app")),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Event.objects.count(), 0)

    def test_record_event_rejects_archived_workspace(self):
        project = self._project(
            name="Archived Workspace Recording Project",
            api_key="ARCHIVEDWSRECORDING123",
        )
        self.workspace.archived_at = timezone.now()
        self.workspace.save(update_fields=["archived_at"])

        response = self.client.post(
            "/hm/e/",
            data=json.dumps(self._recording_payload(project, "https://example.com/app")),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Event.objects.count(), 0)

    @override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=128)
    def test_record_event_returns_413_when_request_body_exceeds_django_limit(self):
        with self.assertLogs("apps.tracker.views", level="WARNING") as logs:
            response = self.client.post(
                "/hm/e/",
                data=json.dumps({"padding": "x" * 256}),
                content_type="text/plain;charset=UTF-8",
            )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json(), {"error": "Payload too large."})
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        self.assertIn("exceeded DATA_UPLOAD_MAX_MEMORY_SIZE", logs.output[0])
        self.assertEqual(Visitor.objects.count(), 0)
        self.assertEqual(Session.objects.count(), 0)
        self.assertEqual(Event.objects.count(), 0)
