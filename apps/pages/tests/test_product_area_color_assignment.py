from contextlib import nullcontext
from datetime import date, datetime, timezone as datetime_timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.pages import company_analytics, services, user_analytics, user_detail_analytics
from apps.pages.models import (
    CompaniesDetailCache,
    PageDailyMetric,
    PagesDetailCache,
    ProductArea,
    UsersDetailCache,
)
from apps.pages.product_area_color_assignment import (
    COLOR_CACHE_MODELS,
    assign_not_stable_project_product_area_colors,
    assign_stable_project_product_area_colors,
)
from apps.pages.tasks import (
    PAGES_LOCK_MAX_RETRIES,
    PagesRebuildLockUnavailable,
    _pages_lock_retry_countdown,
    run_daily_stable_product_area_colors,
    run_hourly_not_stable_product_area_colors,
)
from apps.projects.models import LifecycleStatus, Project, ProjectPageNamingState, Workspace
from apps.tracker.models import ProjectPageNamingRunMode, ProjectPageRule


class ProductAreaColorAssignmentTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username='product-area-color-owner',
            email='product-area-color-owner@example.com',
            password='testpass123',
        )
        self.workspace = Workspace.objects.create(
            name='Product area color workspace',
            website_url='example.com',
            created_by=self.owner,
        )
        self.project = Project.objects.create(
            workspace=self.workspace,
            name='Product area color project',
            owner=self.owner,
            timezone='America/Los_Angeles',
            page_naming_state=ProjectPageNamingState.NOT_STABLE,
        )

    def _area(self, name, slug, color='', *, rule_is_active=True):
        area = ProductArea.objects.create(
            project=self.project,
            name=name,
            slug=slug,
            color=color,
        )
        ProjectPageRule.objects.create(
            project=self.project,
            pattern=f'^/{slug}$',
            product_area=name,
            page_name=f'{name} page',
            priority=100,
            is_active=rule_is_active,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )
        return area

    def _metric(self, area, metric_date, visits_count, page_rule_id):
        return PageDailyMetric.objects.create(
            project=self.project,
            date=metric_date,
            page_rule_id=page_rule_id,
            product_area=area,
            product_area_key=area.slug,
            product_area_name=area.name,
            visits_count=visits_count,
        )

    def _create_color_caches(self):
        generated_at = timezone.now()
        common = {
            'project': self.project,
            'range_key': 'last_30_days',
            'start_date': date(2026, 6, 15),
            'end_date': date(2026, 7, 14),
            'payload_json': {},
            'generated_at': generated_at,
            'is_stale': False,
        }
        for _cache_name, cache_model in COLOR_CACHE_MODELS:
            kwargs = dict(common)
            if cache_model is CompaniesDetailCache:
                kwargs['company_id'] = 'company-1'
            elif cache_model is UsersDetailCache:
                kwargs['user_id'] = 'user-1'
            elif cache_model is PagesDetailCache:
                kwargs['page_rule_id'] = 'rule-1'
            cache_model.objects.create(**kwargs)

    def test_not_stable_uses_local_seven_day_visits_overwrites_and_breaks_ties_by_slug(self):
        beta = self._area('Beta', 'beta', '#111111')
        alpha = self._area('Alpha', 'alpha', '#222222')
        gamma = self._area('Gamma', 'gamma', '#333333')

        self._metric(alpha, date(2026, 7, 7), 4, 1)
        self._metric(alpha, date(2026, 7, 13), 6, 2)
        self._metric(beta, date(2026, 7, 8), 10, 3)
        self._metric(gamma, date(2026, 7, 13), 11, 4)
        self._metric(alpha, date(2026, 7, 6), 500, 5)
        self._metric(beta, date(2026, 7, 14), 500, 6)

        result = assign_not_stable_project_product_area_colors(
            self.project.id,
            as_of=datetime(2026, 7, 14, 1, 30, tzinfo=datetime_timezone.utc),
        )

        alpha.refresh_from_db()
        beta.refresh_from_db()
        gamma.refresh_from_db()
        self.assertEqual(result['start_date'], '2026-07-07')
        self.assertEqual(result['end_date'], '2026-07-13')
        self.assertEqual(result['updated_count'], 3)
        self.assertEqual(gamma.color, '#4269D0')
        self.assertEqual(alpha.color, '#EFB118')
        self.assertEqual(beta.color, '#FF725C')
        self.assertEqual(
            [(row['slug'], row['visits_count']) for row in result['assignments']],
            [('gamma', 11), ('alpha', 10), ('beta', 10)],
        )

    def test_stable_uses_thirty_days_and_only_fills_blank_rank_positions(self):
        self.project.page_naming_state = ProjectPageNamingState.STABLE
        self.project.timezone = 'UTC'
        self.project.save(update_fields=['page_naming_state', 'timezone'])
        core = self._area('Core', 'core', '#123456')
        billing = self._area('Billing', 'billing')
        admin = self._area('Admin', 'admin', '   ')
        zero = self._area('Zero', 'zero', 'not-a-valid-color')

        self._metric(core, date(2026, 7, 14), 100, 10)
        self._metric(billing, date(2026, 7, 10), 50, 11)
        self._metric(admin, date(2026, 6, 15), 25, 12)
        self._metric(zero, date(2026, 6, 14), 1000, 13)

        result = assign_stable_project_product_area_colors(
            self.project.id,
            as_of=datetime(2026, 7, 14, 12, tzinfo=datetime_timezone.utc),
        )

        core.refresh_from_db()
        billing.refresh_from_db()
        admin.refresh_from_db()
        zero.refresh_from_db()
        self.assertEqual(result['start_date'], '2026-06-15')
        self.assertEqual(result['end_date'], '2026-07-14')
        self.assertEqual(result['updated_count'], 3)
        self.assertEqual(core.color, '#123456')
        self.assertEqual(billing.color, '#EFB118')
        self.assertEqual(admin.color, '#FF725C')
        self.assertEqual(zero.color, '#6CC5B0')

    def test_inactive_old_area_with_more_visits_does_not_take_a_palette_slot(self):
        current_low = self._area('Current low', 'current-low')
        current_high = self._area('Current high', 'current-high')
        old_area = self._area('Old area', 'old-area', rule_is_active=False)
        self._metric(current_low, date(2026, 7, 13), 5, 30)
        self._metric(current_high, date(2026, 7, 13), 10, 31)
        self._metric(old_area, date(2026, 7, 13), 1000, 32)

        result = assign_not_stable_project_product_area_colors(
            self.project.id,
            as_of=datetime(2026, 7, 14, 1, 30, tzinfo=datetime_timezone.utc),
        )

        current_low.refresh_from_db()
        current_high.refresh_from_db()
        old_area.refresh_from_db()
        self.assertEqual(current_high.color, '#4269D0')
        self.assertEqual(current_low.color, '#EFB118')
        self.assertEqual(old_area.color, '')
        self.assertEqual(
            [assignment['slug'] for assignment in result['assignments']],
            ['current-high', 'current-low'],
        )

    def test_current_area_slug_matching_handles_unicode_unassigned_and_whitespace_rules(self):
        unicode_area = self._area('Аналітика', 'аналітика')
        unassigned_area = self._area('💰', 'unassigned')
        whitespace_area = ProductArea.objects.create(
            project=self.project,
            name='Whitespace only rule',
            slug='whitespace-only-rule',
        )
        ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^/whitespace$',
            product_area='   ',
            page_name='Whitespace page',
            priority=100,
            is_active=True,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )
        self._metric(unicode_area, date(2026, 7, 13), 10, 40)
        self._metric(unassigned_area, date(2026, 7, 13), 5, 41)
        self._metric(whitespace_area, date(2026, 7, 13), 1000, 42)

        result = assign_not_stable_project_product_area_colors(
            self.project.id,
            as_of=datetime(2026, 7, 14, 1, 30, tzinfo=datetime_timezone.utc),
        )

        unicode_area.refresh_from_db()
        unassigned_area.refresh_from_db()
        whitespace_area.refresh_from_db()
        self.assertEqual(unicode_area.color, '#4269D0')
        self.assertEqual(unassigned_area.color, '#EFB118')
        self.assertEqual(whitespace_area.color, '')
        self.assertEqual(
            [assignment['slug'] for assignment in result['assignments']],
            ['аналітика', 'unassigned'],
        )

    def test_color_changes_mark_all_project_color_caches_stale_but_idempotent_run_does_not(self):
        area = self._area('Core', 'core')
        self._metric(area, date(2026, 7, 13), 10, 20)
        self._create_color_caches()
        as_of = datetime(2026, 7, 14, 1, 30, tzinfo=datetime_timezone.utc)

        first_result = assign_not_stable_project_product_area_colors(self.project.id, as_of=as_of)

        self.assertEqual(first_result['updated_count'], 1)
        self.assertEqual(set(first_result['stale_cache_counts'].values()), {1})
        for _cache_name, cache_model in COLOR_CACHE_MODELS:
            self.assertTrue(cache_model.objects.get(project=self.project).is_stale)

        for _cache_name, cache_model in COLOR_CACHE_MODELS:
            cache_model.objects.filter(project=self.project).update(is_stale=False)

        second_result = assign_not_stable_project_product_area_colors(self.project.id, as_of=as_of)

        self.assertEqual(second_result['updated_count'], 0)
        self.assertEqual(set(second_result['stale_cache_counts'].values()), {0})
        for _cache_name, cache_model in COLOR_CACHE_MODELS:
            self.assertFalse(cache_model.objects.get(project=self.project).is_stale)

    def test_inactive_or_wrong_state_project_is_skipped(self):
        area = self._area('Core', 'core')

        wrong_state_result = assign_stable_project_product_area_colors(self.project.id)
        self.project.lifecycle_status = LifecycleStatus.ARCHIVED
        self.project.save(update_fields=['lifecycle_status'])
        inactive_result = assign_not_stable_project_product_area_colors(self.project.id)

        area.refresh_from_db()
        self.assertEqual(wrong_state_result['status'], 'skipped')
        self.assertEqual(inactive_result['status'], 'skipped')
        self.assertEqual(area.color, '')

    @patch('apps.pages.product_area_color_assignment.project_advisory_lock')
    def test_assignment_skips_without_mutation_when_pages_rebuild_lock_is_busy(self, advisory_lock):
        area = self._area('Core', 'core')
        advisory_lock.return_value = nullcontext(False)

        result = assign_not_stable_project_product_area_colors(self.project.id)

        area.refresh_from_db()
        advisory_lock.assert_called_once_with(self.project.id, namespace='pages-rebuild')
        self.assertEqual(result['status'], 'skipped')
        self.assertEqual(result['reason'], 'lock_not_acquired')
        self.assertEqual(area.color, '')


class ProductAreaColorCacheBuilderLockTests(TestCase):
    def setUp(self):
        owner = get_user_model().objects.create_user(
            username='product-area-cache-lock-owner',
            email='product-area-cache-lock-owner@example.com',
            password='testpass123',
        )
        workspace = Workspace.objects.create(
            name='Product area cache lock workspace',
            website_url='example.com',
            created_by=owner,
        )
        self.project = Project.objects.create(
            workspace=workspace,
            name='Product area cache lock project',
            owner=owner,
        )

    def test_direct_cache_builders_do_not_write_when_pages_rebuild_lock_is_busy(self):
        cases = (
            (
                'pages overview',
                'apps.pages.services.project_advisory_lock',
                lambda: services.build_pages_overview_cache(self.project.id),
            ),
            (
                'pages scatter tooltips',
                'apps.pages.services.project_advisory_lock',
                lambda: services.hydrate_pages_scatter_tooltips_cache(self.project.id),
            ),
            (
                'companies overview',
                'apps.pages.company_analytics.project_advisory_lock',
                lambda: company_analytics.build_companies_overview_cache(self.project.id),
            ),
            (
                'company detail',
                'apps.pages.company_analytics.project_advisory_lock',
                lambda: company_analytics.build_company_detail_cache(self.project.id, 'company-1'),
            ),
            (
                'companies detail hydration',
                'apps.pages.company_analytics.project_advisory_lock',
                lambda: company_analytics.hydrate_companies_detail_cache(self.project.id),
            ),
            (
                'users overview',
                'apps.pages.user_analytics.project_advisory_lock',
                lambda: user_analytics.build_users_overview_cache(self.project.id),
            ),
            (
                'users detail hydration',
                'apps.pages.user_analytics.project_advisory_lock',
                lambda: user_analytics.hydrate_users_detail_cache(self.project.id),
            ),
            (
                'user detail',
                'apps.pages.user_detail_analytics.project_advisory_lock',
                lambda: user_detail_analytics.build_user_detail_cache(self.project.id, 'user-1'),
            ),
        )

        for label, lock_path, builder in cases:
            with self.subTest(builder=label):
                with patch(lock_path, return_value=nullcontext(False)) as advisory_lock:
                    result = builder()

                advisory_lock.assert_called_once_with(self.project.id, namespace='pages-rebuild')
                self.assertEqual(result['status'], 'skipped')
                self.assertEqual(result['reason'], 'lock_not_acquired')

        for _cache_name, cache_model in COLOR_CACHE_MODELS:
            self.assertFalse(cache_model.objects.filter(project=self.project).exists())


class ProductAreaColorTaskTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username='product-area-color-task-owner',
            email='product-area-color-task-owner@example.com',
            password='testpass123',
        )
        self.workspace = Workspace.objects.create(
            name='Product area color task workspace',
            website_url='example.com',
            created_by=self.owner,
        )

    def _project(self, name, state, lifecycle_status=LifecycleStatus.ACTIVE):
        return Project.objects.create(
            workspace=self.workspace,
            name=name,
            owner=self.owner,
            page_naming_state=state,
            lifecycle_status=lifecycle_status,
        )

    @patch('apps.pages.tasks.assign_stable_project_product_area_colors')
    @patch('apps.pages.tasks.assign_not_stable_project_product_area_colors')
    def test_tasks_dispatch_only_active_projects_in_their_state(self, assign_not_stable, assign_stable):
        not_stable = self._project('Not stable', ProjectPageNamingState.NOT_STABLE)
        stable = self._project('Stable', ProjectPageNamingState.STABLE)
        self._project(
            'Archived not stable',
            ProjectPageNamingState.NOT_STABLE,
            lifecycle_status=LifecycleStatus.ARCHIVED,
        )
        assign_not_stable.side_effect = lambda project_id: {'project_id': project_id}
        assign_stable.side_effect = lambda project_id: {'project_id': project_id}

        hourly_result = run_hourly_not_stable_product_area_colors.run()
        daily_result = run_daily_stable_product_area_colors.run()

        assign_not_stable.assert_called_once_with(not_stable.id)
        assign_stable.assert_called_once_with(stable.id)
        self.assertEqual(hourly_result, [{'project_id': not_stable.id}])
        self.assertEqual(daily_result, [{'project_id': stable.id}])

    @patch('apps.pages.tasks.assign_not_stable_project_product_area_colors')
    def test_hourly_task_retries_whole_dispatcher_when_any_project_lock_is_busy(self, assign_not_stable):
        first = self._project('First not stable', ProjectPageNamingState.NOT_STABLE)
        second = self._project('Second not stable', ProjectPageNamingState.NOT_STABLE)
        results_by_project = {
            first.id: {'status': 'success', 'project_id': first.id, 'updated_count': 1},
            second.id: {
                'status': 'skipped',
                'reason': 'lock_not_acquired',
                'project_id': second.id,
            },
        }
        assign_not_stable.side_effect = lambda project_id: results_by_project[project_id]

        with patch.object(
            run_hourly_not_stable_product_area_colors,
            'retry',
            side_effect=RuntimeError('retry requested'),
        ) as retry:
            with self.assertRaisesRegex(RuntimeError, 'retry requested'):
                run_hourly_not_stable_product_area_colors.run()

        self.assertEqual(
            assign_not_stable.call_args_list,
            [
                ((project_id,), {})
                for project_id in sorted((first.id, second.id))
            ],
        )
        retry.assert_called_once()
        retry_kwargs = retry.call_args.kwargs
        self.assertEqual(retry_kwargs['countdown'], 30)
        self.assertEqual(retry_kwargs['max_retries'], PAGES_LOCK_MAX_RETRIES)
        self.assertIsInstance(retry_kwargs['exc'], PagesRebuildLockUnavailable)

    @patch('apps.pages.tasks.assign_not_stable_project_product_area_colors')
    def test_hourly_task_does_not_retry_state_change_skip(self, assign_not_stable):
        project = self._project('State changed', ProjectPageNamingState.NOT_STABLE)
        assign_not_stable.return_value = {
            'status': 'skipped',
            'reason': 'project_not_active_or_state_changed',
            'project_id': project.id,
        }

        with patch.object(run_hourly_not_stable_product_area_colors, 'retry') as retry:
            result = run_hourly_not_stable_product_area_colors.run()

        retry.assert_not_called()
        self.assertEqual(result, [assign_not_stable.return_value])

    def test_lock_retry_backoff_is_exponential_and_bounded(self):
        self.assertEqual(
            [_pages_lock_retry_countdown(retries) for retries in range(7)],
            [30, 60, 120, 240, 300, 300, 300],
        )
        self.assertEqual(run_hourly_not_stable_product_area_colors.max_retries, 4)
        self.assertEqual(run_daily_stable_product_area_colors.max_retries, 4)
