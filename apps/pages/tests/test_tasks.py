from unittest.mock import patch

from django.test import SimpleTestCase

from apps.pages.tasks import (
    PAGES_LOCK_MAX_RETRIES,
    PagesRebuildLockUnavailable,
    aggregate_page_daily_metrics,
    backfill_pages_analytics_task,
    build_companies_overview_cache_task,
    build_company_detail_cache_task,
    build_page_transitions_for_project,
    build_page_visits_for_project,
    build_pages_overview_cache_task,
    build_user_detail_cache_task,
    build_users_overview_cache_task,
    hydrate_pages_scatter_tooltips_cache_task,
    refresh_recent_pages_analytics_task,
)


class PagesAnalyticsTaskRetryTests(SimpleTestCase):
    def _lock_skip(self, project_id=101):
        return {
            'status': 'skipped',
            'reason': 'lock_not_acquired',
            'project_id': project_id,
        }

    @patch('apps.pages.tasks.refresh_recent_projects_pages_analytics')
    def test_periodic_refresh_retries_when_any_nested_project_result_has_lock_skip(self, refresh):
        refresh.return_value = {
            'status': 'success',
            'projects_count': 3,
            'results': [
                {'status': 'success', 'project_id': 100},
                self._lock_skip(101),
                {
                    'status': 'skipped',
                    'reason': 'project_not_active_or_state_changed',
                    'project_id': 102,
                },
            ],
        }

        with patch.object(
            refresh_recent_pages_analytics_task,
            'retry',
            side_effect=RuntimeError('retry requested'),
        ) as retry:
            with self.assertRaisesRegex(RuntimeError, 'retry requested'):
                refresh_recent_pages_analytics_task.run(
                    lookback_days=2,
                    active_since_days=2,
                    range_keys=['last_7_days'],
                )

        retry.assert_called_once()
        retry_kwargs = retry.call_args.kwargs
        self.assertEqual(retry_kwargs['countdown'], 30)
        self.assertEqual(retry_kwargs['max_retries'], PAGES_LOCK_MAX_RETRIES)
        self.assertIsInstance(retry_kwargs['exc'], PagesRebuildLockUnavailable)
        self.assertIn('101', str(retry_kwargs['exc']))

    @patch('apps.pages.tasks.refresh_recent_projects_pages_analytics')
    def test_periodic_refresh_does_not_retry_non_lock_skips(self, refresh):
        refresh.return_value = {
            'status': 'success',
            'results': [
                {'status': 'skipped', 'reason': 'missing_project', 'project_id': 100},
                {
                    'status': 'skipped',
                    'reason': 'project_not_active_or_state_changed',
                    'project_id': 101,
                },
            ],
        }

        with patch.object(refresh_recent_pages_analytics_task, 'retry') as retry:
            result = refresh_recent_pages_analytics_task.run()

        retry.assert_not_called()
        self.assertIs(result, refresh.return_value)

    @patch('apps.pages.tasks.rebuild_project_pages_analytics')
    def test_full_rebuild_wrappers_retry_flat_lock_skip(self, rebuild):
        rebuild.return_value = self._lock_skip(201)

        for task in (
            build_page_visits_for_project,
            build_page_transitions_for_project,
            backfill_pages_analytics_task,
        ):
            with self.subTest(task=task.name):
                with patch.object(task, 'retry', side_effect=RuntimeError('retry requested')) as retry:
                    with self.assertRaisesRegex(RuntimeError, 'retry requested'):
                        task.run(201, '2026-07-01', '2026-07-02')
                retry.assert_called_once()
                self.assertEqual(retry.call_args.kwargs['countdown'], 30)

    @patch('apps.pages.services.aggregate_page_daily_metrics')
    def test_aggregate_wrapper_retries_flat_lock_skip(self, aggregate_service):
        aggregate_service.return_value = self._lock_skip(301)

        with patch.object(
            aggregate_page_daily_metrics,
            'retry',
            side_effect=RuntimeError('retry requested'),
        ) as retry:
            with self.assertRaisesRegex(RuntimeError, 'retry requested'):
                aggregate_page_daily_metrics.run(301, '2026-07-01', '2026-07-02')

        retry.assert_called_once()
        self.assertEqual(retry.call_args.kwargs['countdown'], 30)

    @patch('apps.pages.tasks.build_pages_overview_cache')
    def test_cache_wrapper_retries_flat_lock_skip(self, build_cache):
        build_cache.return_value = self._lock_skip(401)

        with patch.object(
            build_pages_overview_cache_task,
            'retry',
            side_effect=RuntimeError('retry requested'),
        ) as retry:
            with self.assertRaisesRegex(RuntimeError, 'retry requested'):
                build_pages_overview_cache_task.run(401, range_key='last_7_days')

        build_cache.assert_called_once_with(401, range_key='last_7_days')
        retry.assert_called_once()
        self.assertEqual(retry.call_args.kwargs['countdown'], 30)

    def test_all_lock_sensitive_tasks_share_the_bounded_retry_limit(self):
        for task in (
            refresh_recent_pages_analytics_task,
            build_page_visits_for_project,
            build_page_transitions_for_project,
            backfill_pages_analytics_task,
            aggregate_page_daily_metrics,
            build_pages_overview_cache_task,
            build_companies_overview_cache_task,
            build_users_overview_cache_task,
            build_company_detail_cache_task,
            build_user_detail_cache_task,
            hydrate_pages_scatter_tooltips_cache_task,
        ):
            with self.subTest(task=task.name):
                self.assertEqual(task.max_retries, PAGES_LOCK_MAX_RETRIES)
