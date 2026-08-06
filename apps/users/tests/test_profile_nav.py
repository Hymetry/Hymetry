from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.projects.models import Project
from apps.projects.tests.helpers import create_workspace_with_owner


class ProfileNavTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='profile-user',
            email='profile-user@example.com',
            password='testpass123',
        )
        self.workspace = create_workspace_with_owner(self.user, name='Golden Acme')
        self.project = Project.objects.create(
            workspace=self.workspace,
            name='Acme Project',
            created_by=self.user,
        )
        self.client.force_login(self.user)

    def test_profile_project_dropdown_matches_global_workspace_nav(self):
        response = self.client.get(reverse('users:user_profile'))

        self.assertContains(response, 'Golden Acme')
        self.assertContains(
            response,
            reverse(
                'w:project_pages',
                kwargs={'workspace_slug': self.workspace.slug, 'project_id': self.project.id},
            ),
        )
        self.assertContains(response, 'Acme Project')
        self.assertContains(response, 'Manage all projects')
        self.assertNotContains(response, 'See all projects')
