from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.projects.models import Project, ProjectStatus
from apps.projects.tests.helpers import create_workspace_with_owner


SETTINGS_ALERT_ICON_PATH = 'd="M501.38-349q8.62-8.62'
SETTINGS_ICON_PATH = 'd="M10.1346 21L9.77306'


class ProjectTopNavSettingsIconTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='nav-owner',
            email='nav-owner@example.com',
            password='testpass123',
        )
        self.workspace = create_workspace_with_owner(self.user, name='Nav Workspace')
        self.project = Project.objects.create(
            workspace=self.workspace,
            name='Nav Project',
            created_by=self.user,
            api_key='NAVTOPBARTEST123',
        )
        self.client.force_login(self.user)

    def _settings_response(self):
        return self.client.get(
            reverse(
                'w:project_settings',
                kwargs={'workspace_slug': self.workspace.slug, 'project_id': self.project.id},
            )
        )

    def _mark_tracked(self, status=ProjectStatus.ACTIVE, last_event_at=None):
        now = timezone.now()
        self.project.status = status
        self.project.allowed_domains = ['app.example.com']
        self.project.first_production_event_at = now - timezone.timedelta(days=1)
        self.project.last_event_at = last_event_at or now
        self.project.save(
            update_fields=['status', 'allowed_domains', 'first_production_event_at', 'last_event_at']
        )

    def test_setup_required_project_shows_amber_alert_settings_icon(self):
        response = self._settings_response()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.project.effective_status, 'setup_required')
        self.assertContains(response, 'text-orange-500', html=False)
        self.assertContains(response, SETTINGS_ALERT_ICON_PATH, html=False)
        self.assertNotContains(response, SETTINGS_ICON_PATH, html=False)
        self.assertContains(response, 'aria-label="Settings · setup required"', html=False)

    def test_active_project_keeps_default_settings_icon(self):
        self._mark_tracked()

        response = self._settings_response()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.project.effective_status, 'active')
        self.assertContains(response, SETTINGS_ICON_PATH, html=False)
        self.assertNotContains(response, SETTINGS_ALERT_ICON_PATH, html=False)
        self.assertNotContains(response, 'text-orange-500', html=False)
        self.assertContains(response, 'aria-label="Settings"', html=False)

    def test_project_without_recent_data_keeps_default_settings_icon(self):
        self._mark_tracked(last_event_at=timezone.now() - timezone.timedelta(days=8))

        response = self._settings_response()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.project.effective_status, 'no_recent_data')
        self.assertContains(response, SETTINGS_ICON_PATH, html=False)
        self.assertNotContains(response, SETTINGS_ALERT_ICON_PATH, html=False)
        self.assertNotContains(response, 'text-orange-500', html=False)
