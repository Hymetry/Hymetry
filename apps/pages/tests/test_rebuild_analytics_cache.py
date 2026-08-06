from io import StringIO
from datetime import date, timedelta
from unittest.mock import call, patch

from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.pages import company_analytics, company_detail_analytics, services, user_analytics
from apps.pages.models import (
    CompaniesDetailCache,
    CompaniesOverviewCache,
    PagesDetailCache,
    PagesOverviewCache,
    UsersOverviewCache,
)
from apps.pages.services import DEFAULT_OVERVIEW_RANGE_KEYS
from apps.projects.models import Project
from apps.projects.tests.helpers import create_workspace_with_owner


class RebuildAnalyticsCacheCommandTests(SimpleTestCase):
    @patch('apps.pages.management.commands.rebuild_analytics_cache.services.rebuild_project_analytics_caches')
    def test_defaults_to_all_ranges(self, mock_rebuild_project_analytics_caches):
        mock_rebuild_project_analytics_caches.return_value = {
            'status': 'success',
            'project_id': 33333333,
            'range_keys': list(DEFAULT_OVERVIEW_RANGE_KEYS),
            'cache_results': [],
            'companies_cache_results': [],
            'users_cache_results': [],
        }
        output = StringIO()

        call_command(
            'rebuild_analytics_cache',
            project_id=33333333,
            stdout=output,
        )

        mock_rebuild_project_analytics_caches.assert_called_once_with(
            33333333,
            range_keys=DEFAULT_OVERVIEW_RANGE_KEYS,
            include_user_details=False,
        )
        self.assertIn('Analytics caches rebuilt', output.getvalue())

    @patch('apps.pages.management.commands.rebuild_analytics_cache.services.rebuild_project_analytics_caches')
    def test_range_rebuilds_single_range(self, mock_rebuild_project_analytics_caches):
        mock_rebuild_project_analytics_caches.return_value = {
            'status': 'success',
            'project_id': 33333333,
            'range_keys': ['last_90_days'],
            'cache_results': [],
            'companies_cache_results': [],
            'users_cache_results': [],
        }
        output = StringIO()

        call_command(
            'rebuild_analytics_cache',
            project_id=33333333,
            range_key='last_90_days',
            stdout=output,
        )

        mock_rebuild_project_analytics_caches.assert_called_once_with(
            33333333,
            range_keys=('last_90_days',),
            include_user_details=False,
        )

    @patch('apps.pages.management.commands.rebuild_analytics_cache.services.rebuild_project_analytics_caches')
    def test_include_user_details_rebuilds_user_detail_cache(self, mock_rebuild_project_analytics_caches):
        mock_rebuild_project_analytics_caches.return_value = {
            'status': 'success',
            'project_id': 33333333,
            'range_keys': ['last_30_days'],
            'include_user_details': True,
            'cache_results': [],
            'companies_cache_results': [],
            'users_cache_results': [],
        }
        output = StringIO()

        call_command(
            'rebuild_analytics_cache',
            project_id=33333333,
            range_key='last_30_days',
            include_user_details=True,
            stdout=output,
        )

        mock_rebuild_project_analytics_caches.assert_called_once_with(
            33333333,
            range_keys=('last_30_days',),
            include_user_details=True,
        )


class RebuildAnalyticsCacheInvalidationTests(TestCase):
    @patch('apps.pages.user_analytics.build_users_overview_cache')
    @patch('apps.pages.company_analytics.build_companies_overview_cache')
    @patch('apps.pages.services.build_pages_overview_cache')
    def test_empty_range_keys_skips_cache_builders(
        self,
        mock_build_pages_overview_cache,
        mock_build_companies_overview_cache,
        mock_build_users_overview_cache,
    ):
        result = services.rebuild_project_analytics_caches(33333333, range_keys=())

        self.assertEqual(result['range_keys'], [])
        self.assertEqual(result['obsolete_cache_purge']['deleted_total'], 0)
        mock_build_pages_overview_cache.assert_not_called()
        mock_build_companies_overview_cache.assert_not_called()
        mock_build_users_overview_cache.assert_not_called()


class RebuildUserDetailCacheCommandTests(SimpleTestCase):
    @patch('apps.pages.management.commands.rebuild_user_detail_cache.user_analytics.hydrate_users_detail_cache')
    def test_all_users_uses_bulk_hydrate_for_single_range(self, mock_hydrate_users_detail_cache):
        mock_hydrate_users_detail_cache.return_value = {
            'status': 'success',
            'items_count': 42,
            'skipped_count': 0,
            'errors': [],
        }
        output = StringIO()

        call_command(
            'rebuild_user_detail_cache',
            project_id=33333333,
            all_users=True,
            range_key='last_30_days',
            stdout=output,
        )

        mock_hydrate_users_detail_cache.assert_called_once_with(
            33333333,
            range_key='last_30_days',
        )
        self.assertIn('User detail caches rebuilt', output.getvalue())
        self.assertIn("'items_count': 42", output.getvalue())

    @patch('apps.pages.management.commands.rebuild_user_detail_cache.user_analytics.hydrate_users_detail_cache')
    def test_all_users_all_ranges_uses_bulk_hydrate_for_each_range(self, mock_hydrate_users_detail_cache):
        mock_hydrate_users_detail_cache.return_value = {
            'status': 'success',
            'items_count': 10,
            'skipped_count': 0,
            'errors': [],
        }

        call_command(
            'rebuild_user_detail_cache',
            project_id=33333333,
            all_users=True,
            all_ranges=True,
            stdout=StringIO(),
        )

        self.assertEqual(
            mock_hydrate_users_detail_cache.call_args_list,
            [
                call(33333333, range_key='last_7_days'),
                call(33333333, range_key='last_30_days'),
                call(33333333, range_key='last_90_days'),
                call(33333333, range_key='last_180_days'),
            ],
        )

    @patch('apps.pages.management.commands.rebuild_user_detail_cache.build_user_detail_cache')
    def test_single_user_all_ranges_rebuilds_selected_user_for_each_range(self, mock_build_user_detail_cache):
        mock_build_user_detail_cache.return_value = {'status': 'success'}

        call_command(
            'rebuild_user_detail_cache',
            project_id=33333333,
            user_id='user-1',
            all_ranges=True,
            stdout=StringIO(),
        )

        self.assertEqual(
            mock_build_user_detail_cache.call_args_list,
            [
                call(33333333, 'user-1', range_key='last_7_days'),
                call(33333333, 'user-1', range_key='last_30_days'),
                call(33333333, 'user-1', range_key='last_90_days'),
                call(33333333, 'user-1', range_key='last_180_days'),
            ],
        )


class ObsoleteAnalyticsCachePurgeTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username='owner@example.com',
            email='owner@example.com',
            password='password',
        )
        workspace = create_workspace_with_owner(user, name='Rebuild Cache Workspace')
        self.project = Project.objects.create(
            workspace=workspace,
            id=33333333,
            name='Demo',
            created_by=user,
            timezone='UTC',
        )
        self.cache_kwargs = {
            'project': self.project,
            'range_key': 'last_90_days',
            'start_date': date(2026, 2, 27),
            'end_date': date(2026, 5, 27),
            'generated_at': timezone.now(),
        }

    def test_purge_deletes_only_obsolete_schema_rows_for_selected_ranges(self):
        PagesOverviewCache.objects.create(
            **self.cache_kwargs,
            filters_hash='default',
            payload_json={'schema_version': services.OVERVIEW_PAYLOAD_SCHEMA_VERSION},
        )
        PagesOverviewCache.objects.create(
            **self.cache_kwargs,
            filters_hash='old',
            payload_json={'schema_version': services.OVERVIEW_PAYLOAD_SCHEMA_VERSION - 1},
        )
        PagesOverviewCache.objects.create(
            project=self.project,
            range_key='last_30_days',
            start_date=date(2026, 4, 28),
            end_date=date(2026, 5, 27),
            generated_at=timezone.now(),
            filters_hash='old',
            payload_json={'schema_version': services.OVERVIEW_PAYLOAD_SCHEMA_VERSION - 1},
        )
        PagesDetailCache.objects.create(
            **self.cache_kwargs,
            page_rule_id='old-page',
            payload_json={'schema_version': services.OVERVIEW_PAYLOAD_SCHEMA_VERSION - 1},
        )
        CompaniesOverviewCache.objects.create(
            **self.cache_kwargs,
            filters_hash='old',
            payload_json={'schema_version': company_analytics.COMPANIES_PAYLOAD_SCHEMA_VERSION - 1},
        )
        CompaniesDetailCache.objects.create(
            **self.cache_kwargs,
            company_id='old-company',
            payload_json={'schema_version': company_detail_analytics.COMPANY_DETAIL_PAYLOAD_SCHEMA_VERSION - 1},
        )
        UsersOverviewCache.objects.create(
            **self.cache_kwargs,
            filters_hash='old',
            payload_json={'schema_version': user_analytics.USERS_PAYLOAD_SCHEMA_VERSION - 1},
        )

        result = services.purge_obsolete_analytics_cache_rows(
            self.project.id,
            range_keys=('last_90_days',),
        )

        self.assertEqual(result['deleted_total'], 5)
        self.assertEqual(PagesOverviewCache.objects.filter(project=self.project, range_key='last_90_days').count(), 1)
        self.assertEqual(PagesOverviewCache.objects.filter(project=self.project, range_key='last_30_days').count(), 1)
        self.assertFalse(PagesDetailCache.objects.filter(project=self.project).exists())
        self.assertFalse(CompaniesOverviewCache.objects.filter(project=self.project).exists())
        self.assertFalse(CompaniesDetailCache.objects.filter(project=self.project).exists())
        self.assertFalse(UsersOverviewCache.objects.filter(project=self.project).exists())

    def test_filtered_cleanup_keeps_reachable_variants_and_every_default(self):
        """Reachability decides, not expiry.

        A variant past its TTL is still a correct answer for the window it was
        built for, so it survives; a variant for a window no request can resolve
        any more cannot be served to anyone and goes. The unfiltered row stays
        either way.
        """

        now = timezone.now()
        reachable_start, reachable_end = services.resolve_period(
            self.project.timezone,
            range_key='last_90_days',
        )
        unreachable_window = {
            'start_date': self.cache_kwargs['start_date'],
            'end_date': self.cache_kwargs['end_date'],
        }
        reachable_window = {
            'start_date': reachable_start,
            'end_date': reachable_end,
        }
        for cache_model in (
            PagesOverviewCache,
            CompaniesOverviewCache,
            UsersOverviewCache,
        ):
            for filters_hash, window, expires_at in (
                ('default', unreachable_window, now - timedelta(hours=1)),
                ('superseded-filter', unreachable_window, now + timedelta(hours=1)),
                ('reachable-filter', reachable_window, now - timedelta(hours=1)),
            ):
                cache_model.objects.create(
                    project=self.project,
                    range_key='last_90_days',
                    generated_at=now,
                    filters_hash=filters_hash,
                    payload_json={},
                    expires_at=expires_at,
                    **window,
                )

        result = services.purge_expired_filtered_overview_caches(
            self.project.id,
            now=now,
        )

        self.assertEqual(result['deleted_total'], 3)
        for cache_model in (
            PagesOverviewCache,
            CompaniesOverviewCache,
            UsersOverviewCache,
        ):
            self.assertTrue(
                cache_model.objects.filter(
                    project=self.project,
                    filters_hash='default',
                ).exists(),
            )
            self.assertTrue(
                cache_model.objects.filter(
                    project=self.project,
                    filters_hash='reachable-filter',
                ).exists(),
            )
            self.assertFalse(
                cache_model.objects.filter(
                    project=self.project,
                    filters_hash='superseded-filter',
                ).exists(),
            )
