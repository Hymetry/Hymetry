from datetime import timedelta
from contextlib import contextmanager
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.projects.models import Project, ProjectPageNamingState
from apps.projects.tests.helpers import create_workspace_with_owner
from apps.pages.models import (
    CompaniesDetailCache,
    CompaniesOverviewCache,
    PagesDetailCache,
    PagesOverviewCache,
    PagesScatterTooltipCache,
    ProductArea,
    UsersDetailCache,
    UsersOverviewCache,
)
from apps.tracker.models import (
    AnalyticsEvent,
    AnalyticsSession,
    ProjectPageNamingPhase,
    ProjectPageNamingRun,
    ProjectPageNamingRunMode,
    ProjectPageNamingRunStatus,
    ProjectPageRule,
    ProjectPageRuleVersion,
)
from apps.tracker.page_naming import reset_project_page_naming_to_bootstrap, run_page_naming_for_project


@contextmanager
def _acquired_lock(_project_id):
    yield True


class PageNamingRunBackfillTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='page-naming-owner',
            email='page-naming-owner@example.com',
            password='testpass123',
        )
        self.workspace = create_workspace_with_owner(self.user, name='Page Naming Run Workspace')
        self.project = Project.objects.create(
            workspace=self.workspace,
            name='Stable Backfill Project',
            created_by=self.user,
            api_key='PAGEBACKFILL123',
            tracking_capture='analytics',
            page_naming_state=ProjectPageNamingState.STABLE,
        )
        self.session = AnalyticsSession.objects.create(
            project=self.project,
            visitor_guid=uuid4(),
            user_id='user-1',
            company_id='acme',
            start_time=timezone.now(),
            last_activity=timezone.now(),
        )
        self.event = AnalyticsEvent.objects.create(
            session=self.session,
            timestamp=timezone.now(),
            url='https://example.com/acme/dashboard?tab=usage',
            url_normalized='example.com/acme/dashboard',
            page_name='Undefined',
            page_rule=None,
        )

    def test_daily_stable_run_backfills_existing_analytics_events(self):
        ai_result = {
            'prompt_name': 'test:daily_stable_prompt',
            'prompt_version': 'db-test',
            'rules': [
                {
                    'pattern': r'^example\.com/(?P<company>[a-z\-]+)/dashboard$',
                    'page_group': 'Workspace',
                    'page_group_short_name': 'Work',
                    'page_name': 'Dashboard',
                    'priority': 100,
                }
            ],
            'payload': {
                'rules': [
                    {
                        'pattern': r'^example\.com/(?P<company>[a-z\-]+)/dashboard$',
                        'page_group': 'Workspace',
                        'page_group_short_name': 'Work',
                        'page_name': 'Dashboard',
                        'priority': 100,
                    }
                ]
            },
        }

        with patch('apps.tracker.page_naming.project_page_naming_lock', _acquired_lock),                 patch('apps.tracker.page_naming.calculate_new_url_metrics', return_value={
                    'new_urls_1h': 0,
                    'new_urls_24h': 0.0,
                    'urls_last_hour': set(),
                    'urls_last_day': {'example.com/acme/dashboard'},
                    'events_1h': 0,
                }),                 patch('apps.tracker.page_naming.build_hybrid_urls', return_value=['example.com/acme/dashboard']),                 patch('apps.tracker.page_naming.generate_page_naming_rules', return_value=ai_result):
            run = run_page_naming_for_project(self.project.id, ProjectPageNamingRunMode.DAILY_STABLE)

        self.assertEqual(run.status, 'success')
        self.assertEqual(run.output_rules_count, 1)

        self.event.refresh_from_db()
        self.assertEqual(self.event.product_area, 'Workspace')
        self.assertEqual(self.event.page_name, 'Dashboard')
        self.assertIsNotNone(self.event.page_rule_id)
        self.assertEqual(ProjectPageRule.objects.get(pk=self.event.page_rule_id).product_area, 'Workspace')
        self.assertEqual(
            ProjectPageRule.objects.get(pk=self.event.page_rule_id).created_by,
            ProjectPageNamingRunMode.DAILY_STABLE,
        )

    def test_daily_stable_run_skips_ai_when_active_rules_cover_recent_urls(self):
        ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^example\.com/acme/dashboard$',
            product_area='Workspace',
            page_name='Dashboard',
            priority=100,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
            is_active=True,
        )

        with patch('apps.tracker.page_naming.project_page_naming_lock', _acquired_lock), \
                patch('apps.tracker.page_naming.calculate_new_url_metrics', return_value={
                    'new_urls_1h': 0,
                    'new_urls_24h': 0.0,
                    'urls_last_hour': set(),
                    'urls_last_day': {'example.com/acme/dashboard'},
                    'events_1h': 0,
                }), \
                patch('apps.tracker.page_naming.build_hybrid_urls', return_value=['example.com/acme/dashboard']), \
                patch('apps.tracker.page_naming.generate_page_naming_rules') as generate_mock:
            run = run_page_naming_for_project(self.project.id, ProjectPageNamingRunMode.DAILY_STABLE)

        self.assertEqual(run.status, 'skipped')
        self.assertEqual(run.skip_reason, 'recent_urls_covered_by_active_rules')
        self.assertEqual(run.input_urls_count, 1)
        generate_mock.assert_not_called()

    def test_daily_stable_run_marks_project_not_stable_before_ai_when_new_urls_spike(self):
        with patch('apps.tracker.page_naming.project_page_naming_lock', _acquired_lock), \
                patch('apps.tracker.page_naming.calculate_new_url_metrics', return_value={
                    'new_urls_1h': 0,
                    'new_urls_24h': 31.0,
                    'urls_last_hour': set(),
                    'urls_last_day': {'example.com/acme/dashboard'},
                    'events_1h': 0,
                }), \
                patch('apps.tracker.page_naming.build_hybrid_urls') as build_urls_mock, \
                patch('apps.tracker.page_naming.generate_page_naming_rules') as generate_mock:
            run = run_page_naming_for_project(self.project.id, ProjectPageNamingRunMode.DAILY_STABLE)

        self.assertEqual(run.status, 'skipped')
        self.assertEqual(run.skip_reason, 'project_became_not_stable')
        build_urls_mock.assert_not_called()
        generate_mock.assert_not_called()

        self.project.refresh_from_db()
        self.assertEqual(self.project.page_naming_state, ProjectPageNamingState.NOT_STABLE)

    def test_hourly_unstable_run_skips_ai_when_active_rules_cover_recent_urls(self):
        ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^example\.com/acme/dashboard$',
            product_area='Workspace',
            page_name='Dashboard',
            priority=150,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
            is_active=True,
        )

        with patch('apps.tracker.page_naming.project_page_naming_lock', _acquired_lock), \
                patch('apps.tracker.page_naming.calculate_new_url_metrics', return_value={
                    'new_urls_1h': 1,
                    'new_urls_24h': 12.0,
                    'urls_last_hour': {'example.com/acme/dashboard'},
                    'urls_last_day': {'example.com/acme/dashboard'},
                    'events_1h': 1,
                }), \
                patch('apps.tracker.page_naming.build_hybrid_urls', return_value=['example.com/acme/dashboard']), \
                patch('apps.tracker.page_naming.generate_page_naming_rules') as generate_mock:
            run = run_page_naming_for_project(self.project.id, ProjectPageNamingRunMode.HOURLY_UNSTABLE)

        self.assertEqual(run.status, 'skipped')
        self.assertEqual(run.skip_reason, 'recent_urls_covered_by_active_rules')
        self.assertEqual(run.input_urls_count, 1)
        generate_mock.assert_not_called()

    def test_hourly_unstable_run_uses_bootstrap_phase_before_two_successful_bootstrap_versions(self):
        self.project.page_naming_state = ProjectPageNamingState.NOT_STABLE
        self.project.save(update_fields=['page_naming_state'])
        ai_result = {
            'prompt_name': 'test:bootstrap_page_naming_prompt',
            'prompt_version': 'db-test',
            'rules': [
                {
                    'pattern': r'^example\.com/acme/settings$',
                    'page_group': 'Workspace',
                    'page_group_short_name': 'Work',
                    'page_name': 'Settings',
                    'priority': 150,
                }
            ],
            'payload': {'rules': []},
        }

        with patch('apps.tracker.page_naming.project_page_naming_lock', _acquired_lock), \
                patch('apps.tracker.page_naming.calculate_new_url_metrics', return_value={
                    'new_urls_1h': 1,
                    'new_urls_24h': 12.0,
                    'urls_last_hour': {'example.com/acme/settings'},
                    'urls_last_day': {'example.com/acme/settings'},
                    'events_1h': 1,
                }), \
                patch('apps.tracker.page_naming.build_hybrid_urls', return_value=['example.com/acme/settings']), \
                patch('apps.tracker.page_naming.generate_page_naming_rules', return_value=ai_result) as generate_mock:
            run = run_page_naming_for_project(self.project.id, ProjectPageNamingRunMode.HOURLY_UNSTABLE)

        self.assertEqual(run.status, 'success')
        self.assertEqual(run.phase, ProjectPageNamingPhase.BOOTSTRAP)
        self.assertEqual(generate_mock.call_args.kwargs['phase'], ProjectPageNamingPhase.BOOTSTRAP)
        self.assertEqual(ProjectPageRuleVersion.objects.get(run=run).phase, ProjectPageNamingPhase.BOOTSTRAP)

    def test_hourly_unstable_bootstrap_phase_runs_even_when_active_rules_cover_recent_urls(self):
        self.project.page_naming_state = ProjectPageNamingState.NOT_STABLE
        self.project.save(update_fields=['page_naming_state'])
        ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^example\.com/acme/dashboard$',
            product_area='Workspace',
            page_name='Dashboard',
            priority=150,
            created_by=ProjectPageNamingRunMode.HOURLY_UNSTABLE,
            is_active=True,
        )
        previous_run = ProjectPageNamingRun.objects.create(
            project=self.project,
            mode=ProjectPageNamingRunMode.HOURLY_UNSTABLE,
            phase=ProjectPageNamingPhase.BOOTSTRAP,
            status=ProjectPageNamingRunStatus.SUCCESS,
        )
        ProjectPageRuleVersion.objects.create(
            project=self.project,
            run=previous_run,
            mode=ProjectPageNamingRunMode.HOURLY_UNSTABLE,
            phase=ProjectPageNamingPhase.BOOTSTRAP,
        )
        ai_result = {
            'prompt_name': 'test:bootstrap_page_naming_prompt',
            'prompt_version': 'db-test',
            'rules': [
                {
                    'pattern': r'^example\.com/acme/dashboard$',
                    'page_group': 'Workspace',
                    'page_group_short_name': 'Work',
                    'page_name': 'Dashboard',
                    'priority': 150,
                }
            ],
            'payload': {'rules': []},
        }

        with patch('apps.tracker.page_naming.project_page_naming_lock', _acquired_lock), \
                patch('apps.tracker.page_naming.calculate_new_url_metrics', return_value={
                    'new_urls_1h': 1,
                    'new_urls_24h': 12.0,
                    'urls_last_hour': {'example.com/acme/dashboard'},
                    'urls_last_day': {'example.com/acme/dashboard'},
                    'events_1h': 1,
                }), \
                patch('apps.tracker.page_naming.build_hybrid_urls', return_value=['example.com/acme/dashboard']), \
                patch('apps.tracker.page_naming.generate_page_naming_rules', return_value=ai_result) as generate_mock:
            run = run_page_naming_for_project(self.project.id, ProjectPageNamingRunMode.HOURLY_UNSTABLE)

        self.assertEqual(run.status, 'success')
        self.assertEqual(run.phase, ProjectPageNamingPhase.BOOTSTRAP)
        self.assertEqual(generate_mock.call_args.kwargs['phase'], ProjectPageNamingPhase.BOOTSTRAP)

    def test_hourly_unstable_run_uses_incremental_phase_after_two_bootstrap_versions(self):
        self.project.page_naming_state = ProjectPageNamingState.NOT_STABLE
        self.project.save(update_fields=['page_naming_state'])
        for _ in range(2):
            previous_run = ProjectPageNamingRun.objects.create(
                project=self.project,
                mode=ProjectPageNamingRunMode.HOURLY_UNSTABLE,
                phase=ProjectPageNamingPhase.BOOTSTRAP,
                status=ProjectPageNamingRunStatus.SUCCESS,
            )
            ProjectPageRuleVersion.objects.create(
                project=self.project,
                run=previous_run,
                mode=ProjectPageNamingRunMode.HOURLY_UNSTABLE,
                phase=ProjectPageNamingPhase.BOOTSTRAP,
            )
        ai_result = {
            'prompt_name': 'test:hourly_unstable_prompt',
            'prompt_version': 'db-test',
            'rules': [
                {
                    'pattern': r'^example\.com/acme/settings$',
                    'page_group': 'Workspace',
                    'page_group_short_name': 'Work',
                    'page_name': 'Settings',
                    'priority': 150,
                }
            ],
            'payload': {'rules': []},
        }

        with patch('apps.tracker.page_naming.project_page_naming_lock', _acquired_lock), \
                patch('apps.tracker.page_naming.calculate_new_url_metrics', return_value={
                    'new_urls_1h': 1,
                    'new_urls_24h': 12.0,
                    'urls_last_hour': {'example.com/acme/settings'},
                    'urls_last_day': {'example.com/acme/settings'},
                    'events_1h': 1,
                }), \
                patch('apps.tracker.page_naming.build_hybrid_urls', return_value=['example.com/acme/settings']), \
                patch('apps.tracker.page_naming.generate_page_naming_rules', return_value=ai_result) as generate_mock:
            run = run_page_naming_for_project(self.project.id, ProjectPageNamingRunMode.HOURLY_UNSTABLE)

        self.assertEqual(run.status, 'success')
        self.assertEqual(run.phase, ProjectPageNamingPhase.INCREMENTAL)
        self.assertEqual(generate_mock.call_args.kwargs['phase'], ProjectPageNamingPhase.INCREMENTAL)
        self.assertEqual(ProjectPageRuleVersion.objects.get(run=run).phase, ProjectPageNamingPhase.INCREMENTAL)

    def test_hourly_unstable_bootstrap_count_resets_after_state_change(self):
        self.project.page_naming_state = ProjectPageNamingState.NOT_STABLE
        self.project.page_naming_state_changed_at = timezone.now()
        self.project.save(update_fields=['page_naming_state', 'page_naming_state_changed_at'])
        for _ in range(2):
            previous_run = ProjectPageNamingRun.objects.create(
                project=self.project,
                mode=ProjectPageNamingRunMode.HOURLY_UNSTABLE,
                phase=ProjectPageNamingPhase.BOOTSTRAP,
                status=ProjectPageNamingRunStatus.SUCCESS,
            )
            version = ProjectPageRuleVersion.objects.create(
                project=self.project,
                run=previous_run,
                mode=ProjectPageNamingRunMode.HOURLY_UNSTABLE,
                phase=ProjectPageNamingPhase.BOOTSTRAP,
            )
            ProjectPageRuleVersion.objects.filter(pk=version.pk).update(
                created_at=self.project.page_naming_state_changed_at - timedelta(minutes=1)
            )
        ai_result = {
            'prompt_name': 'test:bootstrap_page_naming_prompt',
            'prompt_version': 'db-test',
            'rules': [
                {
                    'pattern': r'^example\.com/acme/settings$',
                    'page_group': 'Workspace',
                    'page_group_short_name': 'Work',
                    'page_name': 'Settings',
                    'priority': 150,
                }
            ],
            'payload': {'rules': []},
        }

        with patch('apps.tracker.page_naming.project_page_naming_lock', _acquired_lock), \
                patch('apps.tracker.page_naming.calculate_new_url_metrics', return_value={
                    'new_urls_1h': 1,
                    'new_urls_24h': 12.0,
                    'urls_last_hour': {'example.com/acme/settings'},
                    'urls_last_day': {'example.com/acme/settings'},
                    'events_1h': 1,
                }), \
                patch('apps.tracker.page_naming.build_hybrid_urls', return_value=['example.com/acme/settings']), \
                patch('apps.tracker.page_naming.generate_page_naming_rules', return_value=ai_result) as generate_mock:
            run = run_page_naming_for_project(self.project.id, ProjectPageNamingRunMode.HOURLY_UNSTABLE)

        self.assertEqual(run.status, 'success')
        self.assertEqual(run.phase, ProjectPageNamingPhase.BOOTSTRAP)
        self.assertEqual(generate_mock.call_args.kwargs['phase'], ProjectPageNamingPhase.BOOTSTRAP)

    def test_reset_project_page_naming_to_bootstrap_clears_current_mapping_state_without_touching_cache(self):
        self.project.page_naming_state = ProjectPageNamingState.STABLE
        self.project.page_naming_first_event_at = timezone.now() - timedelta(days=8)
        self.project.save(update_fields=['page_naming_state', 'page_naming_first_event_at'])
        rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^example\.com/acme/dashboard$',
            product_area='Workspace',
            page_name='Dashboard',
            priority=150,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
            is_active=True,
        )
        self.event.product_area = 'Workspace'
        self.event.page_name = 'Dashboard'
        self.event.page_rule = rule
        self.event.save(update_fields=['product_area', 'page_name', 'page_rule'])
        generated_area = ProductArea.objects.create(
            project=self.project,
            name='Workspace',
            slug='workspace',
            source=ProductArea.SOURCE_SYSTEM,
        )
        manual_area = ProductArea.objects.create(
            project=self.project,
            name='Manual Area',
            slug='manual-area',
            source=ProductArea.SOURCE_MANUAL,
        )
        cache_defaults = {
            'project': self.project,
            'range_key': 'last_30_days',
            'start_date': timezone.now().date() - timedelta(days=29),
            'end_date': timezone.now().date(),
            'payload_json': {'schema_version': 13},
            'generated_at': timezone.now(),
        }
        cache_rows = [
            PagesOverviewCache.objects.create(**cache_defaults),
            PagesDetailCache.objects.create(**cache_defaults, page_rule_id='dashboard'),
            PagesScatterTooltipCache.objects.create(**cache_defaults),
            CompaniesOverviewCache.objects.create(**cache_defaults),
            CompaniesDetailCache.objects.create(**cache_defaults, company_id='acme'),
            UsersOverviewCache.objects.create(**cache_defaults),
            UsersDetailCache.objects.create(**cache_defaults, user_id='user-1'),
        ]

        reset_started_at = timezone.now()
        result = reset_project_page_naming_to_bootstrap(self.project)

        self.project.refresh_from_db()
        rule.refresh_from_db()
        self.event.refresh_from_db()

        self.assertEqual(self.project.page_naming_state, ProjectPageNamingState.NOT_STABLE)
        self.assertGreaterEqual(self.project.page_naming_state_changed_at, reset_started_at)
        self.assertEqual(self.project.page_naming_first_event_at, self.project.page_naming_state_changed_at)
        self.assertFalse(rule.is_active)
        self.assertEqual(self.event.product_area, '')
        self.assertEqual(self.event.page_name, 'Undefined')
        self.assertIsNone(self.event.page_rule_id)
        self.assertFalse(ProductArea.objects.filter(pk=generated_area.pk).exists())
        self.assertTrue(ProductArea.objects.filter(pk=manual_area.pk).exists())
        for cache_row in cache_rows:
            self.assertTrue(cache_row.__class__.objects.filter(pk=cache_row.pk).exists())
        self.assertEqual(result['rules_deactivated'], 1)
        self.assertEqual(result['events_reset'], 1)
        self.assertEqual(result['generated_product_areas_deleted'], 1)

    def test_reset_project_page_naming_to_bootstrap_prevents_immediate_restabilization(self):
        for _ in range(2):
            previous_run = ProjectPageNamingRun.objects.create(
                project=self.project,
                mode=ProjectPageNamingRunMode.HOURLY_UNSTABLE,
                phase=ProjectPageNamingPhase.BOOTSTRAP,
                status=ProjectPageNamingRunStatus.SUCCESS,
            )
            ProjectPageRuleVersion.objects.create(
                project=self.project,
                run=previous_run,
                mode=ProjectPageNamingRunMode.HOURLY_UNSTABLE,
                phase=ProjectPageNamingPhase.BOOTSTRAP,
            )
        self.project.page_naming_state = ProjectPageNamingState.STABLE
        self.project.page_naming_first_event_at = timezone.now() - timedelta(days=8)
        self.project.save(update_fields=['page_naming_state', 'page_naming_first_event_at'])
        reset_project_page_naming_to_bootstrap(self.project)
        ai_result = {
            'prompt_name': 'test:bootstrap_page_naming_prompt',
            'prompt_version': 'db-test',
            'rules': [
                {
                    'pattern': r'^example\.com/acme/settings$',
                    'page_group': 'Workspace',
                    'page_group_short_name': 'Work',
                    'page_name': 'Settings',
                    'priority': 150,
                }
            ],
            'payload': {'rules': []},
        }

        with patch('apps.tracker.page_naming.project_page_naming_lock', _acquired_lock), \
                patch('apps.tracker.page_naming.calculate_new_url_metrics', return_value={
                    'new_urls_1h': 1,
                    'new_urls_24h': 0.0,
                    'urls_last_hour': {'example.com/acme/settings'},
                    'urls_last_day': {'example.com/acme/settings'},
                    'events_1h': 1,
                }), \
                patch('apps.tracker.page_naming.build_hybrid_urls', return_value=['example.com/acme/settings']), \
                patch('apps.tracker.page_naming.generate_page_naming_rules', return_value=ai_result) as generate_mock:
            run = run_page_naming_for_project(self.project.id, ProjectPageNamingRunMode.HOURLY_UNSTABLE)

        self.assertEqual(run.status, 'success')
        self.assertEqual(run.phase, ProjectPageNamingPhase.BOOTSTRAP)
        self.assertEqual(generate_mock.call_args.kwargs['phase'], ProjectPageNamingPhase.BOOTSTRAP)

    def test_hourly_unstable_run_passes_active_rules_as_current_structure(self):
        ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^example\.com/acme/dashboard$',
            product_area='Workspace',
            page_name='Dashboard',
            priority=150,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
            is_active=True,
        )
        ai_result = {
            'prompt_name': 'test:hourly_unstable_prompt',
            'prompt_version': 'db-test',
            'rules': [
                {
                    'pattern': r'^example\.com/acme/settings$',
                    'page_group': 'Workspace',
                    'page_group_short_name': 'Work',
                    'page_name': 'Settings',
                    'priority': 150,
                }
            ],
            'payload': {'rules': []},
        }

        with patch('apps.tracker.page_naming.project_page_naming_lock', _acquired_lock), \
                patch('apps.tracker.page_naming.calculate_new_url_metrics', return_value={
                    'new_urls_1h': 1,
                    'new_urls_24h': 12.0,
                    'urls_last_hour': {'example.com/acme/settings'},
                    'urls_last_day': {'example.com/acme/settings'},
                    'events_1h': 1,
                }), \
                patch('apps.tracker.page_naming.build_hybrid_urls', return_value=['example.com/acme/settings']), \
                patch('apps.tracker.page_naming.generate_page_naming_rules', return_value=ai_result) as generate_mock:
            run = run_page_naming_for_project(self.project.id, ProjectPageNamingRunMode.HOURLY_UNSTABLE)

        self.assertEqual(run.status, 'success')
        _, kwargs = generate_mock.call_args
        self.assertEqual(kwargs['existing_rules'][0]['pattern'], r'^example\.com/acme/dashboard$')
        self.assertEqual(kwargs['existing_rules'][0]['page_group'], 'Workspace')
        self.assertEqual(kwargs['existing_rules'][0]['page_group_short_name'], 'Workspace')
        self.assertEqual(kwargs['existing_rules'][0]['page_name'], 'Dashboard')
        self.assertEqual(kwargs['existing_rules'][0]['priority'], 150)

    def test_hourly_unstable_run_marks_project_stable_after_hard_window_when_24h_churn_is_low(self):
        self.project.page_naming_state = ProjectPageNamingState.NOT_STABLE
        self.project.page_naming_first_event_at = timezone.now() - timedelta(days=5)
        self.project.save(update_fields=['page_naming_state', 'page_naming_first_event_at'])

        with patch('apps.tracker.page_naming.project_page_naming_lock', _acquired_lock), \
                patch('apps.tracker.page_naming.calculate_new_url_metrics', return_value={
                    'new_urls_1h': 0,
                    'new_urls_24h': 4.0,
                    'urls_last_hour': set(),
                    'urls_last_day': {'example.com/acme/dashboard'},
                    'events_1h': 1,
                }):
            run = run_page_naming_for_project(self.project.id, ProjectPageNamingRunMode.HOURLY_UNSTABLE)

        self.assertEqual(run.status, 'skipped')
        self.assertEqual(run.skip_reason, 'project_became_stable')

        self.project.refresh_from_db()
        self.assertEqual(self.project.page_naming_state, ProjectPageNamingState.STABLE)

    def test_hourly_unstable_run_does_not_mark_project_stable_after_hard_window_when_24h_churn_is_high(self):
        self.project.page_naming_state = ProjectPageNamingState.NOT_STABLE
        self.project.page_naming_first_event_at = timezone.now() - timedelta(days=5)
        self.project.save(update_fields=['page_naming_state', 'page_naming_first_event_at'])

        with patch('apps.tracker.page_naming.project_page_naming_lock', _acquired_lock), \
                patch('apps.tracker.page_naming.calculate_new_url_metrics', return_value={
                    'new_urls_1h': 0,
                    'new_urls_24h': 12.0,
                    'urls_last_hour': set(),
                    'urls_last_day': {'example.com/acme/dashboard'},
                    'events_1h': 1,
                }):
            run = run_page_naming_for_project(self.project.id, ProjectPageNamingRunMode.HOURLY_UNSTABLE)

        self.assertEqual(run.status, 'skipped')
        self.assertEqual(run.skip_reason, 'no_new_urls_last_hour')

        self.project.refresh_from_db()
        self.assertEqual(self.project.page_naming_state, ProjectPageNamingState.NOT_STABLE)

    def test_hourly_title_backfill_run_applies_existing_rules(self):
        ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^example\.com/acme/dashboard$',
            product_area='Workspace',
            page_name='Dashboard',
            priority=100,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
            is_active=True,
        )

        with patch('apps.tracker.page_naming.project_page_naming_lock', _acquired_lock), \
                patch('apps.tracker.page_naming.calculate_new_url_metrics', return_value={
                    'new_urls_1h': 0,
                    'new_urls_24h': 0.0,
                    'urls_last_hour': set(),
                    'urls_last_day': {'example.com/acme/dashboard'},
                    'events_1h': 0,
                }):
            run = run_page_naming_for_project(self.project.id, ProjectPageNamingRunMode.HOURLY_TITLE_BACKFILL)

        self.assertEqual(run.status, 'success')
        self.assertEqual(run.input_urls_count, 1)
        self.assertEqual(run.output_rules_count, 1)
        self.assertEqual(run.prompt_name, '')
        self.assertEqual(run.prompt_version, '')

        self.event.refresh_from_db()
        self.assertEqual(self.event.product_area, 'Workspace')
        self.assertEqual(self.event.page_name, 'Dashboard')
        self.assertIsNotNone(self.event.page_rule_id)

    def test_hourly_title_backfill_run_skips_without_active_rules(self):
        with patch('apps.tracker.page_naming.project_page_naming_lock', _acquired_lock), \
                patch('apps.tracker.page_naming.calculate_new_url_metrics', return_value={
                    'new_urls_1h': 0,
                    'new_urls_24h': 0.0,
                    'urls_last_hour': set(),
                    'urls_last_day': {'example.com/acme/dashboard'},
                    'events_1h': 0,
                }), \
                patch('apps.tracker.page_naming.openai.OpenAI') as openai_mock:
            run = run_page_naming_for_project(self.project.id, ProjectPageNamingRunMode.HOURLY_TITLE_BACKFILL)

        self.assertEqual(run.status, 'skipped')
        self.assertEqual(run.skip_reason, 'no_active_rules')
        self.assertEqual(run.input_urls_count, 1)
        openai_mock.assert_not_called()

        self.event.refresh_from_db()
        self.assertEqual(self.event.product_area, '')
        self.assertEqual(self.event.page_name, 'Undefined')
        self.assertIsNone(self.event.page_rule_id)

    def test_hourly_title_backfill_run_skips_when_active_rules_do_not_match(self):
        ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^example\.com/acme/settings$',
            product_area='Workspace',
            page_name='Settings',
            priority=100,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
            is_active=True,
        )

        with patch('apps.tracker.page_naming.project_page_naming_lock', _acquired_lock), \
                patch('apps.tracker.page_naming.calculate_new_url_metrics', return_value={
                    'new_urls_1h': 0,
                    'new_urls_24h': 0.0,
                    'urls_last_hour': set(),
                    'urls_last_day': {'example.com/acme/dashboard'},
                    'events_1h': 0,
                }), \
                patch('apps.tracker.page_naming.openai.OpenAI') as openai_mock:
            run = run_page_naming_for_project(self.project.id, ProjectPageNamingRunMode.HOURLY_TITLE_BACKFILL)

        self.assertEqual(run.status, 'skipped')
        self.assertEqual(run.skip_reason, 'no_matching_rules')
        self.assertEqual(run.input_urls_count, 1)
        self.assertEqual(run.output_rules_count, 0)
        openai_mock.assert_not_called()

        self.event.refresh_from_db()
        self.assertEqual(self.event.product_area, '')
        self.assertEqual(self.event.page_name, 'Undefined')
        self.assertIsNone(self.event.page_rule_id)

    def test_hourly_title_backfill_run_skips_when_no_unresolved_urls(self):
        self.event.product_area = 'Workspace'
        self.event.page_name = 'Dashboard'
        self.event.save(update_fields=['product_area', 'page_name'])

        with patch('apps.tracker.page_naming.project_page_naming_lock', _acquired_lock), \
                patch('apps.tracker.page_naming.calculate_new_url_metrics', return_value={
                    'new_urls_1h': 0,
                    'new_urls_24h': 0.0,
                    'urls_last_hour': set(),
                    'urls_last_day': {'example.com/acme/dashboard'},
                    'events_1h': 0,
                }):
            run = run_page_naming_for_project(self.project.id, ProjectPageNamingRunMode.HOURLY_TITLE_BACKFILL)

        self.assertEqual(run.status, 'skipped')
        self.assertEqual(run.skip_reason, 'no_unresolved_urls')
        self.assertEqual(run.input_urls_count, 0)
