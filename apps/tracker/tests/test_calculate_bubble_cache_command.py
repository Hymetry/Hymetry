import uuid
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.projects.models import Project
from apps.projects.tests.helpers import create_workspace_with_owner
from apps.tracker.models import Session, Visitor


class CalculateBubbleCacheCommandTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="bubble-cache-command-owner",
            email="bubble-cache-command-owner@example.com",
            password="testpass123",
        )
        self.workspace = create_workspace_with_owner(self.user, name="Bubble Cache Workspace")
        self.first_project = Project.objects.create(
            workspace=self.workspace,
            id=33333333,
            name="First",
            created_by=self.user,
            api_key="BUBBLE_CACHE_DEMO",
            timezone="UTC",
            tracking_capture="analytics,recording",
        )
        self.regular_project = Project.objects.create(
            workspace=self.workspace,
            id=44444444,
            name="Regular",
            created_by=self.user,
            api_key="BUBBLE_CACHE_REGULAR",
            timezone="UTC",
            tracking_capture="analytics,recording",
        )
        self._create_session(self.first_project)
        self._create_session(self.regular_project)

    def _create_session(self, project):
        now = timezone.now()
        visitor = Visitor.objects.create(
            project=project,
            visitor_guid=uuid.uuid4(),
            first_visit=now,
            last_activity=now + timedelta(minutes=5),
        )
        return Session.objects.create(
            visitor=visitor,
            session_id=uuid.uuid4(),
            start_time=now,
            last_activity=now + timedelta(minutes=5),
            ended_at=now + timedelta(minutes=6),
        )

    def _cache_result(self):
        return {
            "success": True,
            "cache_entries": 0,
            "cache_created": 0,
            "cache_updated": 0,
            "sessions": 1,
            "events": 0,
            "time": 0,
            "timing": {},
            "normalization_factor": 1.0,
        }

    @patch("apps.tracker.management.commands.calculate_bubble_cache.BubbleCacheManager.cache_bubbles_for_project")
    def test_global_rebuild_processes_all_real_projects(self, mock_cache_bubbles):
        mock_cache_bubbles.return_value = self._cache_result()

        call_command("calculate_bubble_cache", stdout=StringIO())

        processed_project_ids = [call.kwargs["project_id"] for call in mock_cache_bubbles.call_args_list]
        self.assertCountEqual(processed_project_ids, [self.first_project.id, self.regular_project.id])

    @patch("apps.tracker.management.commands.calculate_bubble_cache.BubbleCacheManager.cache_bubbles_for_project")
    def test_explicit_project_id_rebuilds_requested_project(self, mock_cache_bubbles):
        mock_cache_bubbles.return_value = self._cache_result()

        call_command(
            "calculate_bubble_cache",
            project_id=self.first_project.id,
            force=True,
            stdout=StringIO(),
        )

        mock_cache_bubbles.assert_called_once_with(
            project_id=self.first_project.id,
            days_back=7,
            force=True,
        )
