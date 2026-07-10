from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from apps.pages.models import ProductArea
from apps.projects.models import Project
from apps.projects.tests.helpers import create_workspace_with_owner
from apps.tracker.models import ProjectPageNamingRun, ProjectPageNamingRunStatus, ProjectPageRule


class _FakeAdapter:
    def unique_urls_total(self):
        return 1


class RefreshPageGroupShortLabelsCommandTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='short-label-owner',
            email='short-label-owner@example.com',
            password='testpass123',
        )
        self.workspace = create_workspace_with_owner(self.user, name='Short Label Workspace')
        self.project = Project.objects.create(
            workspace=self.workspace,
            name='Short Label Project',
            created_by=self.user,
            tracking_capture='analytics',
        )

    @patch('apps.tracker.management.commands.refresh_page_group_short_labels.services.rebuild_project_analytics_caches')
    @patch('apps.tracker.management.commands.refresh_page_group_short_labels.apply_rules_to_analytics_events')
    @patch('apps.tracker.management.commands.refresh_page_group_short_labels.generate_page_naming_rules')
    @patch('apps.tracker.management.commands.refresh_page_group_short_labels.build_hybrid_urls')
    @patch('apps.tracker.management.commands.refresh_page_group_short_labels.get_source_adapter')
    def test_command_forces_one_llm_call_and_syncs_short_labels(
        self,
        mock_get_source_adapter,
        mock_build_hybrid_urls,
        mock_generate_page_naming_rules,
        mock_apply_rules_to_analytics_events,
        mock_rebuild_project_analytics_caches,
    ):
        mock_get_source_adapter.return_value = _FakeAdapter()
        mock_build_hybrid_urls.return_value = ['example.com/projects']
        mock_generate_page_naming_rules.return_value = {
            'prompt_name': 'title_prompt_config:daily_stable_prompt',
            'prompt_version': 'db-1',
            'rules': [
                {
                    'pattern': r'^example\.com/projects$',
                    'page_group': 'Project management',
                    'page_group_short_name': 'Projects',
                    'page_name': 'Projects overview',
                    'priority': 220,
                }
            ],
            'payload': {'rules': []},
        }
        mock_apply_rules_to_analytics_events.return_value = 12
        mock_rebuild_project_analytics_caches.return_value = {
            'status': 'success',
            'cache_results': [],
            'companies_cache_results': [{'status': 'success'}],
            'users_cache_results': [{'status': 'success'}],
        }
        output = StringIO()

        call_command(
            'refresh_page_group_short_labels',
            project_id=self.project.id,
            model='gpt-5.4-mini',
            skip_analytics_backfill=True,
            stdout=output,
        )

        mock_generate_page_naming_rules.assert_called_once()
        self.assertEqual(mock_generate_page_naming_rules.call_args.kwargs['model_name'], 'gpt-5.4-mini')
        mock_apply_rules_to_analytics_events.assert_not_called()
        mock_rebuild_project_analytics_caches.assert_called_once_with(self.project.id)
        self.assertEqual(ProjectPageRule.objects.filter(project=self.project, is_active=True).count(), 1)
        self.assertEqual(ProjectPageNamingRun.objects.get(project=self.project).status, ProjectPageNamingRunStatus.SUCCESS)
        self.assertEqual(
            ProductArea.objects.get(project=self.project, slug='project-management').short_name,
            'Projects',
        )
        self.assertIn('llm_calls=1', output.getvalue())
        self.assertIn('product_areas_synced=1', output.getvalue())
        self.assertIn('events_updated=0', output.getvalue())

    @patch('apps.tracker.management.commands.refresh_page_group_short_labels.services.rebuild_project_analytics_caches')
    @patch('apps.tracker.management.commands.refresh_page_group_short_labels.apply_rules_to_analytics_events')
    @patch('apps.tracker.management.commands.refresh_page_group_short_labels.generate_page_naming_rules')
    @patch('apps.tracker.management.commands.refresh_page_group_short_labels.build_hybrid_urls')
    @patch('apps.tracker.management.commands.refresh_page_group_short_labels.get_source_adapter')
    def test_reuse_active_rules_skips_llm_call(
        self,
        mock_get_source_adapter,
        mock_build_hybrid_urls,
        mock_generate_page_naming_rules,
        mock_apply_rules_to_analytics_events,
        mock_rebuild_project_analytics_caches,
    ):
        ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^example\.com/projects$',
            product_area='Project management',
            product_area_short_name='Projects',
            page_name='Projects overview',
            priority=220,
            is_active=True,
        )
        ProductArea.objects.create(
            project=self.project,
            slug='project-management',
            name='Project management',
            short_name='Project management',
        )
        mock_rebuild_project_analytics_caches.return_value = {
            'status': 'success',
            'cache_results': [],
            'companies_cache_results': [{'status': 'success'}],
            'users_cache_results': [{'status': 'success'}],
        }
        output = StringIO()

        call_command(
            'refresh_page_group_short_labels',
            project_id=self.project.id,
            reuse_active_rules=True,
            skip_analytics_backfill=True,
            stdout=output,
        )

        mock_get_source_adapter.assert_not_called()
        mock_build_hybrid_urls.assert_not_called()
        mock_generate_page_naming_rules.assert_not_called()
        mock_apply_rules_to_analytics_events.assert_not_called()
        mock_rebuild_project_analytics_caches.assert_called_once_with(self.project.id)
        self.assertEqual(
            ProductArea.objects.get(project=self.project, slug='project-management').short_name,
            'Projects',
        )
        self.assertIn('llm_calls=0', output.getvalue())
        self.assertIn('events_updated=0', output.getvalue())
