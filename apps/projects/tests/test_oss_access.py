from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.projects.access import user_can_create_project, user_can_create_workspace
from apps.projects.ai_credentials import (
    get_openai_api_key_for_project,
    set_workspace_openai_key,
)
from apps.projects.models import (
    Project,
    Workspace,
    WorkspaceMemberRole,
    WorkspaceMemberStatus,
    WorkspaceMembership,
    WorkspaceOpenAICredential,
)
from apps.projects.services import create_project_in_workspace, create_workspace_for_user


@override_settings(
    HOSTED_DEMO_URL='https://hosted.example.test/projects/demo/',
    OPENAI_KEY_ENCRYPTION_KEYS='test-encryption-material',
)
class OSSAccessTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.instance_admin = User.objects.create_superuser(
            username='root@example.com', email='root@example.com', password='a-secure-password-123'
        )
        self.owner = User.objects.create_user(
            username='owner@example.com', email='owner@example.com', password='a-secure-password-123'
        )
        self.admin = User.objects.create_user(
            username='workspace-admin@example.com', email='workspace-admin@example.com', password='a-secure-password-123'
        )
        self.member = User.objects.create_user(
            username='member@example.com', email='member@example.com', password='a-secure-password-123'
        )
        self.viewer = User.objects.create_user(
            username='viewer@example.com', email='viewer@example.com', password='a-secure-password-123'
        )
        self.workspace = Workspace.objects.create(name='Primary', created_by=self.instance_admin)
        for user, role in (
            (self.owner, WorkspaceMemberRole.OWNER),
            (self.admin, WorkspaceMemberRole.ADMIN),
            (self.member, WorkspaceMemberRole.MEMBER),
            (self.viewer, WorkspaceMemberRole.VIEWER),
        ):
            WorkspaceMembership.objects.create(workspace=self.workspace, user=user, role=role)

    def test_workspace_and_project_creation_permission_matrix(self):
        self.assertTrue(user_can_create_workspace(self.instance_admin))
        self.assertTrue(user_can_create_workspace(self.owner))
        self.assertFalse(user_can_create_workspace(self.admin))
        self.assertFalse(user_can_create_workspace(self.member))
        self.assertFalse(user_can_create_workspace(self.viewer))
        self.assertTrue(user_can_create_project(self.owner, self.workspace))
        self.assertFalse(user_can_create_project(self.admin, self.workspace))
        self.assertFalse(user_can_create_project(self.member, self.workspace))

    def test_owner_creates_workspace_and_becomes_owner(self):
        workspace = create_workspace_for_user(self.owner, 'Second workspace')

        membership = WorkspaceMembership.objects.get(workspace=workspace, user=self.owner)
        self.assertEqual(membership.role, WorkspaceMemberRole.OWNER)

    def test_non_owner_direct_workspace_post_is_forbidden(self):
        self.client.force_login(self.member)
        response = self.client.post(
            reverse('workspaces:workspace_create'),
            {'name': 'Forbidden workspace'},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Workspace.objects.filter(name='Forbidden workspace').exists())

    def test_external_demo_link_opens_in_new_tab_without_local_demo(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('projects:project_list'))

        self.assertContains(response, 'https://hosted.example.test/projects/demo/')
        self.assertContains(response, 'target="_blank"')
        self.assertContains(response, 'rel="noopener noreferrer"')
        self.assertEqual(self.client.get('/projects/demo/').status_code, 404)

    def test_workspace_key_is_encrypted_and_shared_by_projects(self):
        first = create_project_in_workspace(self.owner, self.workspace, 'First')
        second = create_project_in_workspace(self.owner, self.workspace, 'Second')
        credential = set_workspace_openai_key(
            self.workspace,
            'sk-workspace-secret',
            updated_by=self.owner,
        )

        self.assertNotIn('sk-workspace-secret', credential.encrypted_api_key)
        self.assertEqual(get_openai_api_key_for_project(first), 'sk-workspace-secret')
        self.assertEqual(get_openai_api_key_for_project(second), 'sk-workspace-secret')
        self.assertEqual(WorkspaceOpenAICredential.objects.filter(workspace=self.workspace).count(), 1)

    @override_settings(OPENAI_API_KEY='global-key-must-not-be-used')
    def test_project_has_no_global_openai_key_fallback(self):
        project = create_project_in_workspace(self.owner, self.workspace, 'No workspace key')

        self.assertIsNone(get_openai_api_key_for_project(project))

    def test_deleting_historical_project_creator_does_not_delete_project(self):
        project = create_project_in_workspace(self.owner, self.workspace, 'Persistent project')
        self.owner.delete()

        project.refresh_from_db()
        self.assertIsNone(project.created_by)
