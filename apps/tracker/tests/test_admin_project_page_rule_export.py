import csv
from io import StringIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.projects.models import Project
from apps.projects.tests.helpers import create_workspace_with_owner
from apps.tracker.models import ProjectPageNamingRunMode, ProjectPageRule


class ProjectPageRuleAdminExportTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin_user = user_model.objects.create_superuser(
            username='admin-export-user',
            email='admin-export@example.com',
            password='testpass123',
        )
        self.client.force_login(self.admin_user)
        self.workspace = create_workspace_with_owner(self.admin_user, name='Admin Export Workspace')

        self.project_a = Project.objects.create(
            workspace=self.workspace,
            name='Alpha Project',
            created_by=self.admin_user,
            api_key='ALPHAPROJECT123',
        )
        self.project_b = Project.objects.create(
            workspace=self.workspace,
            name='Beta Project',
            created_by=self.admin_user,
            api_key='BETAPROJECT123',
        )

        self.rule_a = ProjectPageRule.objects.create(
            project=self.project_a,
            pattern=r'^example\.com/alpha/dashboard$',
            product_area='Alpha',
            product_area_short_name='Alpha',
            page_name='Alpha dashboard',
            priority=100,
            is_active=True,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )
        self.rule_b = ProjectPageRule.objects.create(
            project=self.project_b,
            pattern=r'^example\.com/beta/reports$',
            product_area='Beta',
            product_area_short_name='Beta',
            page_name='Beta reports',
            priority=120,
            is_active=False,
            created_by=ProjectPageNamingRunMode.HOURLY_UNSTABLE,
        )

    def test_changelist_displays_export_csv_button(self):
        response = self.client.get(reverse('admin:tracker_projectpagerule_changelist'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('admin:tracker_projectpagerule_export_csv'))
        self.assertContains(response, 'Export CSV')

    def test_export_csv_respects_current_admin_filters(self):
        response = self.client.get(
            reverse('admin:tracker_projectpagerule_export_csv'),
            {'project__id__exact': self.project_a.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')

        rows = list(csv.reader(StringIO(response.content.decode('utf-8-sig'))))

        self.assertEqual(
            rows[0],
            [
                'id',
                'project_id',
                'project_name',
                'product_area',
                'product_area_short_name',
                'page_name',
                'pattern',
                'priority',
                'is_active',
                'created_by',
                'created_at',
                'updated_at',
            ],
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][0], str(self.rule_a.id))
        self.assertEqual(rows[1][1], str(self.project_a.id))
        self.assertEqual(rows[1][2], 'Alpha Project')
        self.assertEqual(rows[1][3], 'Alpha')
        self.assertEqual(rows[1][4], 'Alpha')
        self.assertEqual(rows[1][5], 'Alpha dashboard')
        self.assertNotIn(str(self.rule_b.id), [row[0] for row in rows[1:]])
