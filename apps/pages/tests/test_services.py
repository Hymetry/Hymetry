import json
from datetime import date, datetime, time, timedelta
from io import StringIO
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.pages.models import (
    CompaniesOverviewCache,
    PageDailyMetric,
    PageCompanyDailyMetric,
    PageTransition,
    PageUserDailyMetric,
    PageVisit,
    PagesDetailCache,
    PagesOverviewCache,
    ProductArea,
    ProjectDailyMetric,
    UsersDetailCache,
    UsersOverviewCache,
)
from apps.pages import filtered_overview, services, user_analytics, user_detail_analytics
from apps.pages.services import build_page_detail_payload, rebuild_project_pages_analytics
from apps.projects.models import (
    CompanyAttribute,
    CompanyAttributeType,
    CompanyAttributeValue,
    Project,
    Workspace,
    WorkspaceMemberRole,
    WorkspaceMemberStatus,
    WorkspaceMembership,
)
from apps.projects.company_attribute_filters import parse_company_attribute_filters
from apps.tracker.models import AnalyticsEvent, AnalyticsSession, ProjectPageNamingRunMode, ProjectPageRule


class PagesAnalyticsServiceTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='pages-owner',
            email='pages-owner@example.com',
            password='testpass123',
        )
        self.workspace = Workspace.objects.create(
            name='Pages Analytics Workspace',
            website_url='example.com',
            created_by=self.user,
        )
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=self.user,
            role=WorkspaceMemberRole.OWNER,
            status=WorkspaceMemberStatus.ACTIVE,
        )
        self.project = Project.objects.create(
            workspace=self.workspace,
            name='Pages Analytics Project',
            created_by=self.user,
            timezone='UTC',
        )

    def test_duration_formatters_match_period_to_date_tooltip_precision(self):
        for seconds, expected in (
            (0, '0s'),
            (2.5, '3s'),
            (151, '2m 31s'),
            (3580, '59m 40s'),
            (7180, '1h 59m'),
        ):
            self.assertEqual(services._format_duration(seconds), expected)
            self.assertEqual(services._format_duration_kpi(seconds), expected)

        self.assertEqual(services._detail_format_value(2.5, 'percent'), '3%')
        self.assertEqual(services._detail_format_value(1.25, 'ratio'), '1.3')

    def test_daily_page_kpis_keep_unvisited_pages_out_and_zero_fill_empty_days(self):
        rows = [
            {
                'daily_kpi_trends': {
                    'adoption': {
                        'current': [None, 0, None],
                        'previous': [25, None, None],
                    },
                    'companies': {
                        'current': [0, 0, 0],
                        'previous': [1, 0, 0],
                    },
                },
            },
            {
                'daily_kpi_trends': {
                    'adoption': {
                        'current': [None, 100, None],
                        'previous': [75, None, None],
                    },
                    'companies': {
                        'current': [0, 2, 0],
                        'previous': [1, 0, 0],
                    },
                },
            },
        ]

        self.assertEqual(
            services._daily_average_adoption_trend(rows),
            [0, 50.0, 0],
        )
        self.assertEqual(
            services._daily_average_adoption_trend(rows, 'previous'),
            [50.0, 0, 0],
        )
        self.assertEqual(
            services._average_trend_value(
                services._daily_average_adoption_trend(rows),
            ),
            16.7,
        )
        self.assertEqual(services._daily_adopted_pages_trend(rows), [0, 1, 0])
        self.assertEqual(
            services._daily_adopted_pages_trend(rows, 'previous'),
            [2, 0, 0],
        )

    def test_fastest_growing_kpi_uses_one_fixed_winner_and_period_totals(self):
        """
        The card names one winner and charts two bars, not a growth sparkline.

        The winner is the largest relative gain, so a page that ends on more
        companies can still lose to one that grew faster. The series carries the
        two period totals the bars are drawn from, previous first.
        """

        winner = {
            'page_name': 'Winner',
            'product_area_key': 'core',
            'page_rule_id': 'winner',
            'companies_count': 8,
            'previous_companies_count': 4,
        }
        earlier_leader = {
            'page_name': 'Earlier leader',
            'product_area_key': 'core',
            'page_rule_id': 'earlier',
            'companies_count': 9,
            'previous_companies_count': 6,
        }
        rows = [winner, earlier_leader]
        fastest, growth, is_new = services._select_fastest_growing_row(
            rows,
            lambda row: row['previous_companies_count'],
        )

        kpi = services._build_fastest_growing_kpi(
            fastest,
            is_new,
            fastest['previous_companies_count'],
            comparison_available=True,
        )

        self.assertEqual(kpi['value'], 'Winner')
        self.assertEqual(kpi['delta'], '+100% companies')
        self.assertEqual(kpi['trend_values'], [4, 8])
        self.assertEqual(
            kpi['trend_labels'],
            [services.PREVIOUS_PERIOD_BAR_LABEL, services.SELECTED_PERIOD_BAR_LABEL],
        )
        self.assertEqual(kpi['trend_scope'], 'period_comparison')
        self.assertEqual(kpi['trend_delta_value'], kpi['delta_value'])

    def test_fastest_growing_kpi_handles_rounding_new_and_unavailable_comparisons(self):
        tie_row = {
            'page_name': 'Contracting',
            'product_area_key': 'core',
            'page_rule_id': 'contracting',
            'companies_count': 7,
        }
        tie_kpi = services._build_fastest_growing_kpi(
            tie_row,
            False,
            8,
            comparison_available=True,
        )
        self.assertEqual(tie_kpi['delta'], '-13% companies')
        self.assertEqual(tie_kpi['trend_values'], [8, 7])
        self.assertEqual(tie_kpi['trend_delta_value'], tie_kpi['delta_value'])

        new_row = {
            **tie_row,
            'page_name': 'New page',
            'companies_count': 5,
        }
        new_kpi = services._build_fastest_growing_kpi(
            new_row,
            True,
            0,
            comparison_available=True,
        )
        self.assertEqual(new_kpi['delta'], 'New companies')
        self.assertNotIn('trend_values', new_kpi)
        self.assertEqual(
            new_kpi['context_line'],
            'New in selected period; no previous-period baseline',
        )

        unavailable_kpi = services._build_fastest_growing_kpi(
            tie_row,
            False,
            8,
            comparison_available=False,
        )
        self.assertEqual(unavailable_kpi['delta'], 'n/a')
        self.assertNotIn('trend_values', unavailable_kpi)
        self.assertEqual(
            unavailable_kpi['context_line'],
            'Previous-period comparison unavailable',
        )

        fastest, growth, is_new = services._select_fastest_growing_row(
            [{
                **tie_row,
                'companies_count': 4,
                'previous_companies_count': 2,
            }],
            lambda row: row['previous_companies_count'],
        )
        self.assertIsNone(fastest)
        self.assertIsNone(growth)
        self.assertFalse(is_new)
        no_qualifier_kpi = services._build_fastest_growing_kpi(
            fastest,
            is_new,
            0,
            comparison_available=True,
        )
        self.assertEqual(no_qualifier_kpi['value'], 'No data')
        self.assertEqual(
            no_qualifier_kpi['context_line'],
            'No qualifying page growth',
        )

    def test_overview_payload_compression_round_trips_cache_contract(self):
        payload = {
            'schema_version': services.OVERVIEW_PAYLOAD_SCHEMA_VERSION,
            'project': {'id': self.project.id, 'name': self.project.name},
            'rows': [{'page_name': 'Dashboard', 'visits_count': 7}],
        }

        compressed = services.compress_overview_payload(payload)

        self.assertLess(len(compressed), len(json.dumps(payload)) + 20)
        self.assertEqual(
            services.decompress_overview_payload(compressed),
            payload,
        )

    def test_compression_command_backfills_cache_and_reads_binary_payload(self):
        generated_at = timezone.now()
        cache = PagesOverviewCache.objects.create(
            project=self.project,
            range_key='last_180_days',
            start_date=generated_at.date(),
            end_date=generated_at.date(),
            filters_hash='filtered',
            payload_json={
                'schema_version': services.OVERVIEW_PAYLOAD_SCHEMA_VERSION,
                'rows': [{'page_name': 'Dashboard'}],
            },
            generated_at=generated_at,
        )
        stdout = StringIO()

        call_command(
            'compress_pages_overview_caches',
            project_id=self.project.id,
            range_key='last_180_days',
            stdout=stdout,
        )

        cache.refresh_from_db()
        expected = cache.payload_json
        self.assertTrue(cache.payload_compressed)
        self.assertEqual(
            services.decompress_overview_payload(cache.payload_compressed),
            expected,
        )
        PagesOverviewCache.objects.filter(pk=cache.pk).update(
            payload_json={'wrong': True},
        )
        cached = services.get_cached_overview_payload(
            self.project.id,
            range_key='last_180_days',
            filters_hash='filtered',
        )
        self.assertEqual(cached['payload_json'], expected)
        self.assertIn('Compressed 1 Pages overview cache row(s).', stdout.getvalue())

    def test_corrupt_compressed_overview_payload_falls_back_to_json(self):
        generated_at = timezone.now()
        expected = {
            'schema_version': services.OVERVIEW_PAYLOAD_SCHEMA_VERSION,
            'rows': [{'page_name': 'Fallback page'}],
        }
        PagesOverviewCache.objects.create(
            project=self.project,
            range_key='last_180_days',
            start_date=generated_at.date(),
            end_date=generated_at.date(),
            filters_hash='corrupt-compressed',
            payload_json=expected,
            payload_compressed=b'not-a-pages-overview-payload',
            generated_at=generated_at,
        )

        with self.assertNumQueries(2):
            cached = services.get_cached_overview_payload(
                self.project.id,
                range_key='last_180_days',
                filters_hash='corrupt-compressed',
            )

        self.assertEqual(cached['payload_json'], expected)
        self.assertNotIn('payload_compressed', cached)

    def test_compression_command_does_not_overwrite_a_concurrent_rebuild(self):
        original_compress = services.compress_overview_payload

        for force in (False, True):
            with self.subTest(force=force):
                generated_at = timezone.now()
                original_payload = {
                    'schema_version': services.OVERVIEW_PAYLOAD_SCHEMA_VERSION,
                    'rows': [{'page_name': 'Original page'}],
                }
                rebuilt_payload = {
                    'schema_version': services.OVERVIEW_PAYLOAD_SCHEMA_VERSION,
                    'rows': [{'page_name': 'Rebuilt page'}],
                }
                rebuilt_compressed = original_compress(rebuilt_payload)
                cache = PagesOverviewCache.objects.create(
                    project=self.project,
                    range_key='last_180_days',
                    start_date=generated_at.date(),
                    end_date=generated_at.date(),
                    filters_hash=f'concurrent-rebuild-{force}',
                    payload_json=original_payload,
                    payload_compressed=(
                        original_compress(original_payload)
                        if force
                        else None
                    ),
                    generated_at=generated_at,
                )
                stdout = StringIO()
                raced = False

                def rebuild_while_compressing(payload):
                    nonlocal raced
                    if not raced:
                        raced = True
                        PagesOverviewCache.objects.filter(pk=cache.pk).update(
                            payload_json=rebuilt_payload,
                            payload_compressed=rebuilt_compressed,
                            generated_at=generated_at + timedelta(seconds=1),
                        )
                    return original_compress(payload)

                with patch.object(
                    services,
                    'compress_overview_payload',
                    side_effect=rebuild_while_compressing,
                ):
                    call_command(
                        'compress_pages_overview_caches',
                        project_id=self.project.id,
                        range_key='last_180_days',
                        force=force,
                        stdout=stdout,
                    )

                cache.refresh_from_db()
                self.assertTrue(raced)
                self.assertEqual(cache.payload_json, rebuilt_payload)
                self.assertEqual(
                    services.decompress_overview_payload(
                        cache.payload_compressed,
                    ),
                    rebuilt_payload,
                )
                self.assertIn(
                    'Compressed 0 Pages overview cache row(s).',
                    stdout.getvalue(),
                )
                cache.delete()

    def test_build_series_uses_product_area_and_normalized_name_identity(self):
        rows = [
            {
                'page_rule_id': 1,
                'product_area_key': 'core',
                'product_area_name': 'Core',
                'page_name': 'Dashboard',
                'visits_count': 10,
                'relative_change_series': {
                    'visits': [
                        {'date': '2026-05-01', 'current': 10},
                        {'date': '2026-05-02', 'current': 0},
                    ],
                },
            },
            {
                'page_rule_id': 2,
                'product_area_key': 'core',
                'product_area_name': 'Core',
                'page_name': 'Dashboard',
                'visits_count': 7,
                'relative_change_series': {
                    'visits': [
                        {'date': '2026-05-01', 'current': 2},
                        {'date': '2026-05-02', 'current': 5},
                    ],
                },
            },
            {
                'page_rule_id': 3,
                'product_area_key': 'work',
                'product_area_name': 'Work',
                'page_name': 'My work',
                'visits_count': 5,
                'relative_change_series': {
                    'visits': [
                        {'date': '2026-05-01', 'current': 1},
                        {'date': '2026-05-02', 'current': 4},
                    ],
                },
            },
            {
                'page_rule_id': 4,
                'product_area_key': 'billing',
                'product_area_name': 'Billing',
                'page_name': ' dashboard ',
                'visits_count': 6,
                'relative_change_series': {
                    'visits': [
                        {'date': '2026-05-01', 'current': 3},
                        {'date': '2026-05-02', 'current': 3},
                    ],
                },
            },
        ]

        result = services._build_series(rows, 'visits_count')

        self.assertEqual(result['labels'], ['2026-05-01', '2026-05-02'])
        self.assertEqual([row['page_name'].strip() for row in result['series']], ['Dashboard', 'dashboard', 'My work'])
        self.assertEqual([row['product_area_key'] for row in result['series']], ['core', 'billing', 'work'])
        self.assertEqual(
            [row['page_display_key'] for row in result['series']],
            ['core::dashboard', 'billing::dashboard', 'work::my work'],
        )
        self.assertEqual(result['series'][0]['total'], 17)
        self.assertEqual(result['series'][0]['values'], [12.0, 5.0])
        self.assertEqual(result['series'][0]['page_rule_ids'], [1, 2])
        self.assertEqual(result['series'][1]['total'], 6)
        self.assertEqual(result['series'][1]['page_rule_ids'], [4])

    def test_display_page_key_matches_sql_lower_for_unicode(self):
        mixed_case = services._page_display_key({
            'product_area_key': 'core',
            'page_name': 'Straße',
        })
        uppercase_ascii = services._page_display_key({
            'product_area_key': 'core',
            'page_name': 'STRASSE',
        })

        self.assertEqual(mixed_case, 'core::straße')
        self.assertEqual(uppercase_ascii, 'core::strasse')
        self.assertNotEqual(mixed_case, uppercase_ascii)

    def test_treemap_and_area_options_keep_same_named_product_areas_separate(self):
        rows = [
            {
                'product_area_key': 'projects-primary',
                'product_area_name': 'Projects',
                'page_group': 'Projects',
                'page_name': 'All projects',
                'engaged_seconds': 40,
                'visits_count': 2,
            },
            {
                'product_area_key': 'projects-secondary',
                'product_area_name': 'Projects',
                'page_group': 'Projects',
                'page_name': 'All projects',
                'engaged_seconds': 30,
                'visits_count': 1,
            },
        ]

        treemap = services._build_treemap(rows)
        candidates = services._overview_product_area_candidates({
            'productAreas': [
                {'key': 'projects-primary', 'name': 'Projects'},
                {'key': 'projects-secondary', 'name': 'Projects'},
            ],
        })

        self.assertEqual(len(treemap['nodes']), 2)
        self.assertEqual(
            {node['product_area_key'] for node in treemap['nodes']},
            {'projects-primary', 'projects-secondary'},
        )
        self.assertEqual([candidate['key'] for candidate in candidates], [
            'projects-primary',
            'projects-secondary',
        ])

        selection = services._product_area_filter_selection(
            {'productAreas': candidates},
            ['projects-primary'],
        )
        self.assertTrue(services._matches_product_area_filter(rows[0], selection))
        self.assertFalse(services._matches_product_area_filter(rows[1], selection))

    def test_top_actions_keep_product_area_identity_for_colliding_page_names(self):
        pages = [
            {
                'page_key': 'projects::overview',
                'page_label': 'Overview',
                'page_group': 'Projects',
                'product_area_key': 'projects',
                'product_area_name': 'Projects',
                'visits_count': 10,
                'actions': [{'element_key': 'Open project', 'clicks_count': 4}],
            },
            {
                'page_key': 'settings::overview',
                'page_label': 'Overview',
                'page_group': 'Settings',
                'product_area_key': 'settings',
                'product_area_name': 'Settings',
                'visits_count': 8,
                'actions': [{'element_key': 'Save settings', 'clicks_count': 3}],
            },
        ]

        groups = services._build_top_actions_by_page_group(pages)

        self.assertEqual(len(groups), 2)
        self.assertEqual([group['page_name'] for group in groups], ['Overview', 'Overview'])
        self.assertEqual(
            [group['product_area_key'] for group in groups],
            ['projects', 'settings'],
        )
        self.assertEqual(
            [group['product_area_name'] for group in groups],
            ['Projects', 'Settings'],
        )

    def test_product_area_identity_accepts_legacy_product_area_id(self):
        item = {
            'product_area_id': 17,
            'product_area_name': 'Projects',
        }

        self.assertTrue(services._has_product_area_identity(item))
        self.assertEqual(
            services._product_area_identity(item),
            ('17', 'Projects'),
        )
        self.assertEqual(
            services._overview_product_area_candidates({'rows': [item]})[0]['key'],
            '17',
        )

    def test_overview_sankey_uses_area_aware_page_identity(self):
        started_at = timezone.make_aware(datetime(2026, 7, 3, 10, 0))
        session_id = uuid4()
        projects_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^app\.example\.com/projects$',
            product_area='Projects',
            page_name='Overview',
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )
        projects_alias_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^app\.example\.com/project-list$',
            product_area='Projects',
            page_name='Overview',
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )
        settings_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^app\.example\.com/settings$',
            product_area='Settings',
            page_name='Overview',
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )

        def visit(url, rule, area_key, minute):
            return PageVisit.objects.create(
                project=self.project,
                session_id=session_id,
                url_normalized=url,
                page_rule_id=rule.id,
                product_area_key=area_key,
                product_area_name=rule.product_area,
                visit_start_ts=started_at + timedelta(minutes=minute),
                visit_end_ts=started_at + timedelta(minutes=minute, seconds=30),
                engaged_seconds=30,
            )

        projects_visit = visit('app.example.com/projects', projects_rule, 'projects', 0)
        projects_alias_visit = visit('app.example.com/project-list', projects_alias_rule, 'projects', 1)
        settings_visit = visit('app.example.com/settings', settings_rule, 'settings', 2)
        for index, source_visit in enumerate((projects_visit, projects_alias_visit)):
            PageTransition.objects.create(
                project=self.project,
                session_id=session_id,
                from_visit=source_visit,
                to_visit=settings_visit,
                from_page_rule_id=source_visit.page_rule_id,
                to_page_rule_id=settings_visit.page_rule_id,
                from_product_area_key='projects',
                from_product_area_name='Projects',
                to_product_area_key='settings',
                to_product_area_name='Settings',
                transition_ts=started_at + timedelta(minutes=index, seconds=45),
            )

        sankey = services._build_sankey(
            self.project.id,
            'UTC',
            started_at.date(),
            started_at.date(),
        )

        self.assertEqual({node['name'] for node in sankey['nodes']}, {
            'projects::overview',
            'settings::overview',
        })
        self.assertEqual({node['label'] for node in sankey['nodes']}, {'Overview'})
        self.assertEqual(len(sankey['links']), 1)
        self.assertEqual(sankey['links'][0]['value'], 2)
        self.assertEqual(sankey['links'][0]['sourceLabel'], 'Overview')
        self.assertEqual(sankey['links'][0]['targetLabel'], 'Overview')

    @patch('apps.pages.services.queries.fetch_all')
    def test_two_way_movement_orders_stronger_direction_and_labels_reciprocity(self, fetch_all):
        fetch_all.return_value = [{
            'page_low_id': 10,
            'page_high_id': 20,
            'page_low_name': 'Invoices',
            'page_high_name': 'Billing',
            'page_low_product_area_name': 'Finance',
            'page_high_product_area_name': 'Finance',
            'low_to_high': 70,
            'high_to_low': 190,
            'total_transitions': 260,
            'reciprocal_volume': 140,
            'reciprocity_pct': 53.846,
            'direction_balance': 70 / 190,
            'sessions_count': 81,
            'companies_count': 23,
            'users_count': 54,
        }]

        movement = services._build_two_way_movement(
            self.project.id, 'UTC', date(2026, 7, 1), date(2026, 7, 7),
        )

        row = movement['rows'][0]
        self.assertEqual((row['page_a_name'], row['page_b_name']), ('Billing', 'Invoices'))
        self.assertEqual((row['a_to_b'], row['b_to_a']), (190, 70))
        self.assertEqual(row['reciprocal_volume'], 140)
        self.assertEqual(row['reciprocity_pct'], 53.8)
        self.assertEqual(row['label'], 'Moderate')
        self.assertEqual((row['sessions_count'], row['companies_count'], row['users_count']), (81, 23, 54))

    def test_two_way_movement_product_area_filter_requires_both_endpoints(self):
        movement = {
            'rows': [
                {'page_a_product_area_name': 'Finance', 'page_b_product_area_name': 'Finance'},
                {'page_a_product_area_name': 'Finance', 'page_b_product_area_name': 'Settings'},
            ],
            'limit': 10,
            'total_pairs': 2,
        }
        selection = {'keys': {'finance'}, 'names': {'finance'}, 'options': [{'key': 'finance', 'name': 'Finance'}]}

        filtered = services._filter_two_way_movement_by_product_area(movement, selection)

        self.assertEqual(len(filtered['rows']), 1)
        self.assertEqual(filtered['total_pairs'], 1)

    def test_build_display_page_rows_unions_metrics_across_duplicate_rule_names(self):
        previous_date = date(2026, 7, 1)
        current_date = date(2026, 7, 2)
        first_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^app\.example\.com/companies$',
            product_area='CRM',
            page_name='All companies',
            priority=100,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )
        second_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^app\.example\.com/companies/all$',
            product_area='CRM',
            page_name='All companies',
            priority=90,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )

        ProjectDailyMetric.objects.create(
            project=self.project,
            date=previous_date,
            active_companies_count=1,
            active_users_count=1,
        )
        ProjectDailyMetric.objects.create(
            project=self.project,
            date=current_date,
            active_companies_count=2,
            active_users_count=2,
        )

        def add_page_metric(rule, metric_date, visits, engaged, clicks, clicked_visits):
            PageDailyMetric.objects.create(
                project=self.project,
                date=metric_date,
                page_rule_id=rule.id,
                product_area_key='crm',
                product_area_name='CRM',
                visits_count=visits,
                engaged_seconds=engaged,
                click_count=clicks,
                visits_with_click_count=clicked_visits,
            )

        def add_company_metric(rule, metric_date, company_id, visits=1, engaged=30):
            PageCompanyDailyMetric.objects.create(
                project=self.project,
                date=metric_date,
                page_rule_id=rule.id,
                product_area_key='crm',
                product_area_name='CRM',
                company_id=company_id,
                company_name_sample=company_id.title(),
                visits_count=visits,
                engaged_seconds=engaged,
            )

        def add_user_metric(rule, metric_date, user_id, company_id):
            PageUserDailyMetric.objects.create(
                project=self.project,
                date=metric_date,
                page_rule_id=rule.id,
                product_area_key='crm',
                product_area_name='CRM',
                company_id=company_id,
                user_id=user_id,
                visits_count=1,
                engaged_seconds=30,
            )

        add_page_metric(first_rule, previous_date, 1, 30, 1, 1)
        add_company_metric(first_rule, previous_date, 'acme')
        add_user_metric(first_rule, previous_date, 'user-1', 'acme')

        add_page_metric(first_rule, current_date, 2, 60, 1, 1)
        add_page_metric(second_rule, current_date, 3, 90, 2, 2)
        add_company_metric(first_rule, current_date, 'acme', visits=2, engaged=60)
        add_company_metric(second_rule, current_date, 'acme', visits=1, engaged=30)
        add_company_metric(second_rule, current_date, 'beta', visits=2, engaged=60)
        add_user_metric(first_rule, current_date, 'user-1', 'acme')
        add_user_metric(second_rule, current_date, 'user-1', 'acme')
        add_user_metric(second_rule, current_date, 'user-2', 'beta')

        rows, current_counts, previous_counts = services._build_change_rows(
            self.project.id,
            current_date,
            current_date,
            previous_date,
            previous_date,
            grain='display_page',
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['page_name'], 'All companies')
        self.assertEqual(row['row_key'], 'crm::all companies')
        self.assertEqual(row['page_display_key'], 'crm::all companies')
        self.assertEqual(row['page_rule_id'], str(second_rule.id))
        self.assertEqual(row['page_rule_ids'], [str(first_rule.id), str(second_rule.id)])
        self.assertEqual(row['companies_count'], 2)
        self.assertEqual(row['users_count'], 2)
        self.assertEqual(row['visits_count'], 5)
        self.assertEqual(row['engaged_seconds'], 150)
        self.assertEqual(row['avg_visit_seconds'], 30)
        self.assertEqual(row['interaction_pct'], 60)
        self.assertEqual(row['clicks_per_visit'], 0.6)
        self.assertEqual(row['deltas']['companies']['value'], 100)
        self.assertEqual(row['deltas']['visits']['value'], 400)
        self.assertEqual(row['relative_change_series']['visits'][0]['current'], 5)
        self.assertEqual(current_counts['active_companies_count'], 2)
        self.assertEqual(previous_counts['active_companies_count'], 1)

    def test_build_display_page_rows_keeps_same_name_in_different_product_areas(self):
        previous_date = date(2026, 7, 2)
        current_date = date(2026, 7, 3)
        crm_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^app\.example\.com/crm/overview$',
            product_area='CRM',
            page_name='Overview',
            priority=100,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )
        billing_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^app\.example\.com/billing/overview$',
            product_area='Billing',
            page_name=' overview ',
            priority=90,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )

        for rule, area_key, area_name, company_id, user_id, visits in (
            (crm_rule, 'crm', 'CRM', 'acme', 'user-1', 2),
            (billing_rule, 'billing', 'Billing', 'beta', 'user-2', 5),
        ):
            PageDailyMetric.objects.create(
                project=self.project,
                date=current_date,
                page_rule_id=rule.id,
                product_area_key=area_key,
                product_area_name=area_name,
                visits_count=visits,
                engaged_seconds=visits * 30,
            )
            PageCompanyDailyMetric.objects.create(
                project=self.project,
                date=current_date,
                page_rule_id=rule.id,
                product_area_key=area_key,
                product_area_name=area_name,
                company_id=company_id,
                company_name_sample=company_id.title(),
                visits_count=visits,
                engaged_seconds=visits * 30,
            )
            PageUserDailyMetric.objects.create(
                project=self.project,
                date=current_date,
                page_rule_id=rule.id,
                product_area_key=area_key,
                product_area_name=area_name,
                company_id=company_id,
                user_id=user_id,
                visits_count=visits,
                engaged_seconds=visits * 30,
            )

        rows, current_counts, previous_counts = services._build_change_rows(
            self.project.id,
            current_date,
            current_date,
            previous_date,
            previous_date,
            grain='display_page',
        )

        self.assertEqual(len(rows), 2)
        rows_by_area = {row['product_area_key']: row for row in rows}
        self.assertEqual(set(rows_by_area), {'crm', 'billing'})
        self.assertEqual(rows_by_area['crm']['page_name'].strip().casefold(), 'overview')
        self.assertEqual(rows_by_area['billing']['page_name'].strip().casefold(), 'overview')
        self.assertEqual(rows_by_area['crm']['row_key'], 'crm::overview')
        self.assertEqual(rows_by_area['billing']['row_key'], 'billing::overview')
        self.assertEqual(rows_by_area['crm']['page_rule_ids'], [str(crm_rule.id)])
        self.assertEqual(rows_by_area['billing']['page_rule_ids'], [str(billing_rule.id)])
        self.assertEqual(rows_by_area['crm']['visits_count'], 2)
        self.assertEqual(rows_by_area['billing']['visits_count'], 5)
        self.assertEqual(rows_by_area['crm']['companies_count'], 1)
        self.assertEqual(rows_by_area['billing']['companies_count'], 1)
        self.assertEqual(rows_by_area['crm']['users_count'], 1)
        self.assertEqual(rows_by_area['billing']['users_count'], 1)
        self.assertEqual(rows_by_area['crm']['relative_change_series']['visits'][0]['current'], 2)
        self.assertEqual(rows_by_area['billing']['relative_change_series']['visits'][0]['current'], 5)
        self.assertEqual(current_counts['active_companies_count'], 2)
        self.assertEqual(previous_counts['active_companies_count'], 0)

    def test_normalize_overview_payload_collapses_legacy_page_metric_rows(self):
        payload = services.normalize_overview_payload({
            'change_aware_rows': [
                {
                    'page_rule_id': 1,
                    'product_area_key': 'crm',
                    'product_area_name': 'CRM',
                    'page_name': ' All companies ',
                    'visits_count': 2,
                    'engaged_seconds': 30,
                    'companies_count': 1,
                },
                {
                    'page_rule_id': 2,
                    'product_area_key': 'crm',
                    'product_area_name': 'CRM',
                    'page_name': 'all COMPANIES',
                    'visits_count': 5,
                    'engaged_seconds': 60,
                    'companies_count': 1,
                },
                {
                    'page_rule_id': 3,
                    'product_area_key': 'billing',
                    'product_area_name': 'Billing',
                    'page_name': 'All companies',
                    'visits_count': 4,
                    'engaged_seconds': 45,
                    'companies_count': 1,
                },
            ],
        })

        self.assertEqual(len(payload['change_aware_rows']), 3)
        self.assertEqual(len(payload['page_metrics_rows']), 2)
        rows_by_area = {row['product_area_key']: row for row in payload['page_metrics_rows']}
        self.assertEqual(rows_by_area['crm']['page_display_key'], 'crm::all companies')
        self.assertEqual(rows_by_area['crm']['page_rule_id'], '2')
        self.assertEqual(rows_by_area['crm']['page_rule_ids'], ['1', '2'])
        self.assertEqual(rows_by_area['crm']['visits_count'], 5)
        self.assertEqual(rows_by_area['billing']['page_display_key'], 'billing::all companies')
        self.assertEqual(rows_by_area['billing']['page_rule_ids'], ['3'])
        self.assertEqual(rows_by_area['billing']['visits_count'], 4)

    def test_pages_overview_product_area_color_contract_prefers_persisted_color(self):
        ProductArea.objects.create(
            project=self.project,
            name='Billing',
            slug='billing',
            short_name='Bill',
            color='#123456',
        )
        ProductArea.objects.create(
            project=self.project,
            name='Unobserved Area',
            slug='unobserved-area',
            short_name='Unobserved',
            color='#654321',
        )
        product_areas = services._project_product_area_options(
            self.project.id,
            [{
                'product_area_key': 'billing',
                'product_area_name': 'Billing',
                'color': '#EFB118',
            }],
        )
        self.assertEqual([area['key'] for area in product_areas], ['billing'])
        self.assertEqual(product_areas[0]['color'], '#123456')
        catalog = services._project_product_area_options(
            self.project.id,
            product_areas,
            include_unobserved=True,
        )
        self.assertEqual(
            [area['key'] for area in catalog],
            ['billing', 'unobserved-area'],
        )

        payload = services.normalize_overview_payload({
            'schema_version': services.OVERVIEW_PAYLOAD_SCHEMA_VERSION,
            'productAreas': product_areas,
            'product_area_summary': [
                {'product_area_key': 'billing', 'product_area_name': 'Billing'},
            ],
            'company_engagement_by_product_area': [
                {'product_area_key': 'billing', 'product_area_name': 'Billing', 'points': []},
            ],
            'top_actions_by_page_group': [
                {'page_group': 'Invoices', 'page_rule_id': '1', 'actions': []},
            ],
            'engaged_time_treemap': {
                'total_engaged_seconds': 60,
                'nodes': [{
                    'name': 'Billing',
                    'page_group': 'Billing',
                    'value': 60,
                    'engaged_seconds': 60,
                    'children': [{
                        'name': 'Invoices',
                        'page_group': 'Billing',
                        'value': 60,
                        'engaged_seconds': 60,
                    }],
                }],
            },
            'sankey': {
                'nodes': [{
                    'name': 'Invoices',
                    'product_area_key': 'billing',
                    'product_area_name': 'Billing',
                }],
                'links': [{
                    'source': 'Invoices',
                    'target': 'Invoices',
                    'source_product_area': 'Billing',
                    'target_product_area': 'Billing',
                    'value': 1,
                }],
            },
        })

        self.assertEqual(services.OVERVIEW_PAYLOAD_SCHEMA_VERSION, 25)
        self.assertEqual([area['key'] for area in payload['productAreas']], ['billing'])
        self.assertNotIn('Invoices', [area['name'] for area in payload['productAreas']])
        self.assertEqual(payload['productAreas'][0]['product_area_color'], '#123456')
        self.assertEqual(payload['product_area_summary'][0]['color'], '#123456')
        self.assertEqual(payload['company_engagement_by_product_area'][0]['color'], '#123456')
        self.assertEqual(payload['engaged_time_treemap']['nodes'][0]['color'], '#123456')
        self.assertEqual(payload['engaged_time_treemap']['nodes'][0]['children'][0]['color'], '#123456')
        self.assertEqual(payload['sankey']['nodes'][0]['product_area_color'], '#123456')
        self.assertEqual(payload['sankey']['links'][0]['source_product_area_color'], '#123456')
        self.assertEqual(payload['sankey']['links'][0]['target_product_area_color'], '#123456')

        filtered = services.filter_overview_payload_by_product_areas(payload, ['billing'])
        self.assertEqual(filtered['productAreas'][0]['color'], '#123456')

    def test_page_detail_flow_colors_overlay_live_product_area_colors(self):
        ProductArea.objects.create(
            project=self.project,
            name='Billing',
            slug='billing',
            color='#123456',
        )
        ProductArea.objects.create(
            project=self.project,
            name='Core',
            slug='core',
            color='#654321',
        )
        cached_payload = {
            'page': {
                'displayName': 'Billing',
                'productAreaId': 'billing',
                'productAreaName': 'Billing',
                'productAreaColor': '#FFFFFF',
            },
            'flow': {
                'previousPages': [{'pageName': 'Dashboard', 'visits': 8}],
                'nextPages': [{'pageName': 'Invoices', 'visits': 6}],
                'links': [
                    {
                        'source': 'Dashboard',
                        'target': 'Billing',
                        'source_product_area': 'Core',
                        'target_product_area': 'Billing',
                        'source_product_area_color': '#FFFFFF',
                        'target_product_area_color': '#FFFFFF',
                        'value': 8,
                    },
                    {
                        'source': 'Billing',
                        'target': 'Invoices',
                        'source_product_area': 'Billing',
                        'target_product_area': 'Billing',
                        'value': 6,
                    },
                ],
                'sankey': {
                    'nodes': [{'name': 'Dashboard'}, {'name': 'Billing'}, {'name': 'Invoices'}],
                    'links': [],
                },
            },
        }

        payload = services.apply_page_detail_product_area_colors(self.project.id, cached_payload)

        self.assertEqual(payload['page']['productAreaColor'], '#123456')
        self.assertEqual(payload['flow']['previousPages'][0]['productAreaName'], 'Core')
        self.assertEqual(payload['flow']['previousPages'][0]['productAreaColor'], '#654321')
        self.assertEqual(payload['flow']['nextPages'][0]['productAreaName'], 'Billing')
        self.assertEqual(payload['flow']['nextPages'][0]['productAreaColor'], '#123456')
        self.assertEqual(payload['flow']['links'][0]['source_product_area_color'], '#654321')
        self.assertEqual(payload['flow']['links'][0]['target_product_area_color'], '#123456')
        self.assertEqual(
            {node['name']: node['product_area_color'] for node in payload['flow']['sankey']['nodes']},
            {
                'Dashboard': '#654321',
                'Billing': '#123456',
                'Invoices': '#123456',
            },
        )

    def test_filter_overview_payload_by_product_area_filters_page_sections(self):
        payload = {
            'schema_version': services.OVERVIEW_PAYLOAD_SCHEMA_VERSION,
            'project': {
                'id': self.project.id,
                'name': self.project.name,
                'active_companies_total': 10,
                'active_users_total': 20,
            },
            'period': {'range_key': 'last_30_days'},
            'rows': [
                {
                    'page_rule_id': '1',
                    'product_area_key': 'billing',
                    'product_area_name': 'Billing',
                    'page_name': 'Invoices',
                    'page_group': 'Billing',
                    'companies_count': 5,
                    'previous_companies_count': 3,
                    'adoption_pct': 40,
                    'users_count': 6,
                    'penetration_pct': 60,
                    'visits_count': 12,
                    'engaged_seconds': 600,
                    'avg_visit_seconds': 50,
                    'interaction_pct': 75,
                    'clicks_per_visit': 2,
                    'companies_change_pct': 66.7,
                    'adoption_change_pp': 10,
                    'trend_values': [1, 2],
                    'trends': {
                        'companies': [1, 5],
                        'adoption': [30, 40],
                        'engaged': [120, 600],
                    },
                    'daily_kpi_trends': {
                        'adoption': {
                            'current': [20, 40],
                            'previous': [10, 30],
                        },
                        'companies': {
                            'current': [1, 2],
                            'previous': [0, 1],
                        },
                    },
                },
                {
                    'page_rule_id': '2',
                    'product_area_key': 'core',
                    'product_area_name': 'Core',
                    'page_name': 'Dashboard',
                    'page_group': 'Core',
                    'companies_count': 8,
                    'adoption_pct': 80,
                    'users_count': 12,
                    'penetration_pct': 70,
                    'visits_count': 30,
                    'engaged_seconds': 1200,
                    'avg_visit_seconds': 40,
                    'interaction_pct': 50,
                    'clicks_per_visit': 1,
                    'companies_change_pct': 20,
                    'adoption_change_pp': 5,
                    'trend_values': [3, 4],
                    'trends': {
                        'companies': [6, 8],
                        'adoption': [75, 80],
                        'engaged': [900, 1200],
                    },
                    'daily_kpi_trends': {
                        'adoption': {
                            'current': [70, 80],
                            'previous': [60, 70],
                        },
                        'companies': {
                            'current': [3, 4],
                            'previous': [2, 3],
                        },
                    },
                },
            ],
            'change_aware_rows': [
                {
                    'page_rule_id': '1',
                    'product_area_key': 'billing',
                    'product_area_name': 'Billing',
                    'page_name': 'Invoices',
                    'page_group': 'Billing',
                    'companies_count': 5,
                    'previous_companies_count': 3,
                    'adoption_pct': 40,
                    'users_count': 6,
                    'penetration_pct': 60,
                    'visits_count': 12,
                    'engaged_seconds': 600,
                    'avg_visit_seconds': 50,
                    'interaction_pct': 75,
                    'clicks_per_visit': 2,
                    'companies_change_pct': 66.7,
                    'adoption_change_pp': 10,
                    'trend_values': [1, 2],
                    'trends': {
                        'companies': [1, 5],
                        'adoption': [30, 40],
                        'engaged': [120, 600],
                    },
                    'daily_kpi_trends': {
                        'adoption': {
                            'current': [20, 40],
                            'previous': [10, 30],
                        },
                        'companies': {
                            'current': [1, 2],
                            'previous': [0, 1],
                        },
                    },
                },
                {
                    'page_rule_id': '2',
                    'product_area_key': 'core',
                    'product_area_name': 'Core',
                    'page_name': 'Dashboard',
                    'page_group': 'Core',
                    'companies_count': 8,
                    'adoption_pct': 80,
                    'users_count': 12,
                    'penetration_pct': 70,
                    'visits_count': 30,
                    'engaged_seconds': 1200,
                    'avg_visit_seconds': 40,
                    'interaction_pct': 50,
                    'clicks_per_visit': 1,
                    'companies_change_pct': 20,
                    'adoption_change_pp': 5,
                    'trend_values': [3, 4],
                    'trends': {
                        'companies': [6, 8],
                        'adoption': [75, 80],
                        'engaged': [900, 1200],
                    },
                    'daily_kpi_trends': {
                        'adoption': {
                            'current': [70, 80],
                            'previous': [60, 70],
                        },
                        'companies': {
                            'current': [3, 4],
                            'previous': [2, 3],
                        },
                    },
                },
            ],
            'product_area_summary': [
                {
                    'product_area_key': 'billing',
                    'product_area_name': 'Billing',
                    'page_name': 'Billing',
                    'page_group': 'Billing',
                    'page_count': 1,
                    'companies_count': 4,
                    'adoption_pct': 40,
                    'users_count': 6,
                    'visits_count': 12,
                    'engaged_seconds': 600,
                },
                {
                    'product_area_key': 'core',
                    'product_area_name': 'Core',
                    'page_name': 'Core',
                    'page_group': 'Core',
                    'page_count': 1,
                    'companies_count': 8,
                    'adoption_pct': 80,
                    'users_count': 12,
                    'visits_count': 30,
                    'engaged_seconds': 1200,
                },
            ],
            'top_pages_by_visits_over_time': {
                'granularity': 'day',
                'labels': ['2026-06-01'],
                'series': [
                    {'page_rule_id': '1', 'page_name': 'Invoices', 'page_group': 'Billing', 'values': [12]},
                    {'page_rule_id': '2', 'page_name': 'Dashboard', 'page_group': 'Core', 'values': [30]},
                ],
            },
            'top_pages_by_engaged_time_over_time': {
                'granularity': 'day',
                'labels': ['2026-06-01'],
                'series': [
                    {'page_rule_id': '1', 'page_name': 'Invoices', 'page_group': 'Billing', 'values': [600]},
                    {'page_rule_id': '2', 'page_name': 'Dashboard', 'page_group': 'Core', 'values': [1200]},
                ],
            },
            'engaged_time_treemap': {
                'total_engaged_seconds': 1800,
                'nodes': [
                    {'name': 'Billing', 'page_group': 'Billing', 'engaged_seconds': 600, 'value': 600, 'children': []},
                    {'name': 'Core', 'page_group': 'Core', 'engaged_seconds': 1200, 'value': 1200, 'children': []},
                ],
            },
            'sankey': {
                'nodes': [
                    {'name': 'Invoices', 'product_area_key': 'billing', 'product_area_name': 'Billing'},
                    {'name': 'Dashboard', 'product_area_key': 'core', 'product_area_name': 'Core'},
                ],
                'links': [
                    {'source': 'Invoices', 'target': 'Invoices', 'source_product_area': 'Billing', 'target_product_area': 'Billing', 'value': 3},
                    {'source': 'Invoices', 'target': 'Dashboard', 'source_product_area': 'Billing', 'target_product_area': 'Core', 'value': 2},
                ],
            },
            'top_actions_by_page': [
                {
                    'page_rule_id': '1',
                    'page_group': 'Billing',
                    'page_label': 'Invoices',
                    'visits_count': 12,
                    'actions': [{'element_key': 'Pay invoice', 'clicks_count': 5}],
                },
                {
                    'page_rule_id': '2',
                    'page_group': 'Core',
                    'page_label': 'Dashboard',
                    'visits_count': 30,
                    'actions': [{'element_key': 'Open dashboard', 'clicks_count': 9}],
                },
            ],
            'company_engagement_by_product_area': [
                {'product_area_key': 'billing', 'product_area_name': 'Billing', 'points': []},
                {'product_area_key': 'core', 'product_area_name': 'Core', 'points': []},
            ],
        }

        selected_keys = services.resolve_product_area_filter_keys(payload, ['Billing'])
        filtered = services.filter_overview_payload_by_product_areas(payload, selected_keys)

        self.assertEqual(selected_keys, ['billing'])
        self.assertEqual([row['page_name'] for row in filtered['change_aware_rows']], ['Invoices'])
        self.assertEqual([row['product_area_name'] for row in filtered['product_area_summary']], ['Billing'])
        self.assertEqual([row['page_name'] for row in filtered['top_pages_by_visits_over_time']['series']], ['Invoices'])
        self.assertEqual([row['name'] for row in filtered['engaged_time_treemap']['nodes']], ['Billing'])
        self.assertEqual(filtered['engaged_time_treemap']['total_engaged_seconds'], 600)
        self.assertEqual([link['target'] for link in filtered['sankey']['links']], ['Invoices'])
        self.assertEqual([row['page_group'] for row in filtered['top_actions_by_page']], ['Billing'])
        self.assertEqual([row['product_area_name'] for row in filtered['company_engagement_by_product_area']], ['Billing'])
        self.assertEqual(filtered['top_clicked_elements'][0]['element_key'], 'Pay invoice')
        self.assertEqual(filtered['kpis'][0]['label'], 'Avg daily adopted pages')
        self.assertEqual(filtered['kpis'][0]['value'], '1.0')
        self.assertEqual(filtered['kpis'][0]['delta'], '+0.5 vs previous')
        self.assertEqual(filtered['kpis'][0]['trend_values'], [1, 1])
        self.assertEqual(filtered['kpis'][0]['trend_scope'], 'daily')
        self.assertEqual(filtered['kpis'][1]['label'], 'Avg daily adoption')
        self.assertEqual(filtered['kpis'][1]['value'], '30%')
        self.assertEqual(filtered['kpis'][1]['delta'], '+10 pp')
        self.assertEqual(filtered['kpis'][1]['trend_values'], [20.0, 40.0])
        self.assertEqual(filtered['kpis'][1]['trend_scope'], 'daily')
        self.assertEqual(filtered['kpis'][2]['delta'], '5m 00s avg/day')
        self.assertEqual(filtered['kpis'][2]['trend_values'], [120.0, 480.0])
        self.assertEqual(filtered['kpis'][2]['trend_scope'], 'daily')
        self.assertEqual(filtered['kpis'][3]['value'], 'Invoices')
        self.assertEqual(filtered['kpis'][3]['delta'], '+67% companies')
        # Two bars, previous first, from the row's own period totals.
        self.assertEqual(filtered['kpis'][3]['trend_values'], [3, 5])
        self.assertEqual(filtered['kpis'][3]['trend_scope'], 'period_comparison')
        self.assertEqual(
            filtered['kpis'][3]['trend_delta_value'],
            filtered['kpis'][3]['delta_value'],
        )

    def test_company_attribute_cohort_filters_users_and_active_user_kpi(self):
        _start_date, end_date = services.resolve_period(
            self.project.timezone,
            range_key='last_30_days',
        )
        for company_id in ('acme', 'beta'):
            # An attribute cohort is drawn from the companies the project has
            # prepared company facts for, which real preparation always writes
            # alongside the user facts.
            PageCompanyDailyMetric.objects.create(
                project=self.project,
                date=end_date,
                product_area_key='core',
                product_area_name='Core',
                company_id=company_id,
                company_name_sample=company_id.title(),
                visits_count=2,
                engaged_seconds=180,
            )
            PageUserDailyMetric.objects.create(
                project=self.project,
                date=end_date,
                product_area_key='core',
                product_area_name='Core',
                company_id=company_id,
                user_id=f'{company_id}-user@example.com',
                user_name_sample=f'{company_id.title()} User',
                visits_count=2,
                engaged_seconds=180,
                click_count=1,
            )

        segment = CompanyAttribute.objects.create(
            project=self.project,
            name='Segment',
            attribute_type=CompanyAttributeType.TEXT,
        )
        CompanyAttributeValue.objects.create(
            attribute=segment,
            company_id='acme',
            text_value='Target',
        )
        state = parse_company_attribute_filters(
            self.project,
            QueryDict(f'ca.{segment.id}.op=eq&ca.{segment.id}.value=Target'),
        )

        payload = user_analytics.build_users_overview_payload(
            self.project,
            range_key='last_30_days',
            company_attribute_filter_state=state,
        )

        self.assertEqual(
            [row['id'] for row in payload['users']],
            ['acme-user@example.com'],
        )
        self.assertEqual(payload['kpis'][0]['value'], 0.03)

        # A request never builds a filtered variant; it reads one and asks a
        # worker for a rebuild. Build it here the way the queued task would, so
        # the view has something to serve.
        filtered_overview.build_variant(
            filtered_overview.USERS,
            self.project.id,
            state.canonical_pairs,
            state.filters_hash,
            'last_30_days',
        )

        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                'projects:project_users',
                kwargs={'project_id': self.project.id},
            ),
            QueryDict(
                f'ca.{segment.id}.op=eq&ca.{segment.id}.value=Target',
            ),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [
                row['id']
                for row in response.context['users_overview_payload']['users']
            ],
            ['acme-user@example.com'],
        )
        self.assertTrue(
            UsersOverviewCache.objects.filter(
                project=self.project,
                filters_hash=state.filters_hash,
            ).exists(),
        )
        self.assertEqual(
            UsersOverviewCache.objects.get(
                project=self.project,
                filters_hash=state.filters_hash,
            ).payload_json['freshness']['filtered_analytics_revision'],
            0,
        )

    def test_empty_attribute_filter_users_include_synthetic_company_not_unknown(self):
        attribute = CompanyAttribute.objects.create(
            project=self.project,
            name='Owner',
            attribute_type=CompanyAttributeType.TEXT,
        )
        product_area = ProductArea.objects.create(
            project=self.project,
            name='Workspace core',
            slug='workspace-core',
            short_name='Core',
            color='#4269D0',
        )
        _start_date, end_date = services.resolve_period(
            self.project.timezone,
            range_key='last_30_days',
        )
        # Company display names come from visits inside the period, and the
        # period ends on the last complete day, so visits stamped "now" are
        # never read and every name falls back to its raw company ID.
        day_start, _day_end = services._utc_bounds_for_local_dates(
            end_date,
            end_date,
            self.project.timezone,
        )
        now = day_start + timedelta(hours=12)
        for company_id, company_name, user_id, visits, engaged in (
            ('hymetry:workspace:none', 'No workspace selected', 'no-workspace-user', 1, 60),
            ('known-empty-company', 'Zeta known company', 'mixed-user', 2, 120),
        ):
            # The cohort universe is the project's prepared company facts, so an
            # "is empty" filter only reaches a company that has them.
            PageCompanyDailyMetric.objects.create(
                project=self.project,
                date=end_date,
                page_rule_id=10,
                product_area=product_area,
                product_area_key=product_area.slug,
                product_area_name=product_area.name,
                company_id=company_id,
                company_name_sample=company_name,
                visits_count=visits,
                engaged_seconds=engaged,
            )
            PageUserDailyMetric.objects.create(
                project=self.project,
                date=end_date,
                page_rule_id=10,
                product_area=product_area,
                product_area_key=product_area.slug,
                product_area_name=product_area.name,
                company_id=company_id,
                user_id=user_id,
                user_name_sample=user_id,
                visits_count=visits,
                engaged_seconds=engaged,
                click_count=visits,
            )
            PageVisit.objects.create(
                project=self.project,
                session_id=uuid4(),
                company_id=company_id,
                company_name_sample=company_name,
                user_id=user_id,
                user_name_sample=user_id,
                visit_start_ts=now - timedelta(minutes=2),
                visit_end_ts=now - timedelta(minutes=1),
                engaged_seconds=engaged,
                click_count=visits,
                product_area=product_area,
                product_area_key=product_area.slug,
                product_area_name=product_area.name,
                page_rule_id=10,
            )
        PageUserDailyMetric.objects.create(
            project=self.project,
            date=end_date,
            page_rule_id=10,
            product_area=product_area,
            product_area_key=product_area.slug,
            product_area_name=product_area.name,
            company_id='',
            user_id='unknown-user',
            user_name_sample='Unknown User',
            visits_count=1,
            engaged_seconds=60,
            click_count=1,
        )
        PageVisit.objects.create(
            project=self.project,
            session_id=uuid4(),
            company_id=None,
            company_name_sample='Unknown company',
            user_id='unknown-user',
            user_name_sample='Unknown User',
            visit_start_ts=now - timedelta(minutes=5),
            visit_end_ts=now - timedelta(minutes=4),
            engaged_seconds=60,
            click_count=1,
            product_area=product_area,
            product_area_key=product_area.slug,
            product_area_name=product_area.name,
            page_rule_id=10,
        )
        state = parse_company_attribute_filters(
            self.project,
            QueryDict(f'ca.{attribute.id}.op=empty'),
        )

        payload = user_analytics.build_users_overview_payload(
            self.project,
            range_key='last_30_days',
            company_attribute_filter_state=state,
        )

        self.assertEqual(
            [row['id'] for row in payload['users']],
            ['mixed-user', 'no-workspace-user'],
        )
        no_workspace_user = next(
            row for row in payload['users'] if row['id'] == 'no-workspace-user'
        )
        mixed_user = next(
            row for row in payload['users'] if row['id'] == 'mixed-user'
        )
        self.assertEqual(no_workspace_user['company'], 'No workspace selected')
        self.assertEqual(
            no_workspace_user['companyId'],
            'hymetry:workspace:none',
        )
        self.assertNotIn('isNoWorkspaceSelected', no_workspace_user)
        self.assertEqual(no_workspace_user['pageGroups'][0]['name'], product_area.name)
        self.assertEqual(no_workspace_user['topFeature'], product_area.name)
        self.assertEqual(mixed_user['company'], 'Zeta known company')
        self.assertEqual(mixed_user['visitsCount'], 2)
        self.assertEqual(mixed_user['engagedSeconds'], 120)
        self.assertEqual(mixed_user['clicksCount'], 2)
        self.assertEqual(mixed_user['activeDays'], 1)
        self.assertEqual(mixed_user['featuresCount'], 1)
        self.assertEqual(len(mixed_user['pageGroups']), 1)
        self.assertEqual(mixed_user['pageGroups'][0]['engagedSeconds'], 120)
        self.assertEqual(mixed_user['pageGroups'][0]['visits'], 2)
        self.assertEqual(len(mixed_user['topFeatures']), 1)
        self.assertEqual(mixed_user['topFeatures'][0]['engagedSeconds'], 120)
        self.assertEqual(mixed_user['topFeatures'][0]['visits'], 2)
        self.assertEqual(
            [item['name'] for item in payload['productAreas']],
            [product_area.name],
        )
        active_users = next(
            item for item in payload['kpis'] if item['key'] == 'activeUsers'
        )
        engaged_per_user = next(
            item for item in payload['kpis'] if item['key'] == 'engagedPerUser'
        )
        self.assertEqual(max(active_users['sparkline']), 2)
        self.assertEqual(
            max(
                point
                for point in engaged_per_user['sparkline']
                if point is not None
            ),
            90,
        )

    def test_build_users_overview_payload_aggregates_user_metrics(self):
        start_date, end_date = services.resolve_period(self.project.timezone, range_key='last_30_days')
        _previous_start, previous_end = services.previous_period(start_date, end_date)
        product_area = ProductArea.objects.create(
            project=self.project,
            name='Billing',
            slug='billing',
            short_name='Billing',
            color='#13579B',
        )
        developer_area = ProductArea.objects.create(
            project=self.project,
            name='Developer',
            slug='developer',
            short_name='Dev',
            color='#3CA951',
        )
        PageDailyMetric.objects.create(
            project=self.project,
            date=end_date,
            product_area=product_area,
            product_area_key='billing',
            product_area_name='Billing',
            visits_count=6,
            engaged_seconds=900,
            users_count_daily=1,
        )
        PageDailyMetric.objects.create(
            project=self.project,
            date=end_date,
            product_area=developer_area,
            product_area_key='developer',
            product_area_name='Developer',
            visits_count=1,
            engaged_seconds=60,
            users_count_daily=1,
        )
        for day_offset in range(6):
            metric_date = end_date - timedelta(days=day_offset)
            PageUserDailyMetric.objects.create(
                project=self.project,
                date=metric_date,
                product_area=product_area,
                product_area_key='billing',
                product_area_name='Billing',
                company_id='acme',
                user_id='sarah@example.com',
                user_name_sample='Sarah Chen',
                visits_count=3,
                engaged_seconds=450,
                click_count=3,
            )
            PageUserDailyMetric.objects.create(
                project=self.project,
                date=metric_date,
                product_area=developer_area,
                product_area_key='developer',
                product_area_name='Developer',
                company_id='acme',
                user_id='sarah@example.com',
                user_name_sample='Sarah Chen',
                visits_count=1,
                engaged_seconds=150,
                click_count=1,
            )
        PageUserDailyMetric.objects.create(
            project=self.project,
            date=previous_end,
            product_area=product_area,
            product_area_key='billing',
            product_area_name='Billing',
            company_id='acme',
            user_id='sarah@example.com',
            user_name_sample='Sarah Chen',
            visits_count=3,
            engaged_seconds=300,
            click_count=2,
        )
        PageUserDailyMetric.objects.create(
            project=self.project,
            date=previous_end,
            product_area=product_area,
            product_area_key='billing',
            product_area_name='Billing',
            company_id='acme',
            user_id='dropped@example.com',
            user_name_sample='Dropped User',
            visits_count=4,
            engaged_seconds=400,
            click_count=2,
        )
        # Visits carry the company display name, and only visits inside the
        # period are read, so they belong on the last complete day rather than
        # today.
        visit_day_start, _visit_day_end = services._utc_bounds_for_local_dates(
            end_date,
            end_date,
            self.project.timezone,
        )
        visit_base = visit_day_start + timedelta(hours=12)
        for index in range(3):
            PageVisit.objects.create(
                project=self.project,
                session_id=uuid4(),
                user_id='sarah@example.com',
                user_name_sample='Sarah Chen',
                company_id='acme',
                company_name_sample='Acme Corp',
                product_area=product_area,
                product_area_key='billing',
                product_area_name='Billing',
                visit_start_ts=visit_base - timedelta(minutes=index + 1),
                visit_end_ts=visit_base,
                engaged_seconds=300,
            )

        payload = user_analytics.build_users_overview_payload(self.project, range_key='last_30_days')
        users_by_id = {row['id']: row for row in payload['users']}
        status_counts = {row['status']: row['count'] for row in payload['statusDistribution']}

        self.assertEqual(payload['period']['days'], 30)
        self.assertEqual(payload['kpis'][0]['value'], 0.2)
        self.assertEqual(payload['users'][0]['name'], 'Sarah Chen')
        self.assertEqual(payload['users'][0]['company'], 'Acme Corp')
        self.assertEqual(payload['users'][0]['status'], 'Power')
        self.assertEqual(payload['users'][0]['sessionsCount'], 3)
        self.assertEqual(payload['users'][0]['engagedDeltaPct'], 1100.0)
        self.assertEqual(users_by_id['dropped@example.com']['status'], 'Dropped')
        self.assertEqual(users_by_id['dropped@example.com']['visitsCount'], 0)
        self.assertEqual(users_by_id['dropped@example.com']['engagedSeconds'], 0)
        self.assertEqual(users_by_id['dropped@example.com']['activeDays'], 0)
        # Ages are measured from the actual today, and the previous period ends
        # one day before a 30-day window starts, so this is 31 days back.
        self.assertEqual(users_by_id['dropped@example.com']['lastActive'], '31d ago')
        self.assertEqual(status_counts['Dropped'], 1)
        self.assertEqual(payload['productAreas'][0]['name'], 'Billing')
        self.assertEqual(payload['productAreas'][0]['color'], '#13579B')
        self.assertEqual(users_by_id['sarah@example.com']['pageGroups'][0]['color'], '#13579B')
        self.assertEqual(users_by_id['sarah@example.com']['pageGroups'][0]['productAreaColor'], '#13579B')
        # Each status-mix bar is classified against its own baseline. Both users
        # were active in the previous period, so that bar counts two and calls
        # neither of them Dropped, even though one of them has dropped out by
        # the selected period.
        previous_status_counts = {
            row['status']: row['count']
            for row in payload['previousStatusDistribution']
        }
        self.assertEqual(sum(previous_status_counts.values()), 2)
        self.assertEqual(previous_status_counts['Dropped'], 0)
        self.assertEqual(status_counts['Dropped'], 1)

    def test_user_payloads_use_email_trait_when_user_id_is_not_email(self):
        _start_date, end_date = services.resolve_period(self.project.timezone, range_key='last_30_days')
        event_ts = timezone.make_aware(datetime.combine(end_date, time(12)))
        product_area = ProductArea.objects.create(
            project=self.project,
            name='Core workspace',
            slug='core-workspace',
            short_name='Core',
            color='#4269D0',
        )
        PageUserDailyMetric.objects.create(
            project=self.project,
            date=end_date,
            product_area=product_area,
            product_area_key='core-workspace',
            product_area_name='Core workspace',
            company_id='acme',
            user_id='user-42',
            user_name_sample='Tyler Wang',
            visits_count=4,
            engaged_seconds=720,
            click_count=3,
        )
        session = AnalyticsSession.objects.create(
            project=self.project,
            user_id='user-42',
            company_id='acme',
            start_time=event_ts,
            last_activity=event_ts,
        )
        AnalyticsEvent.objects.create(
            session=session,
            event_type='click',
            timestamp=event_ts,
            user_id='user-42',
            company_id='acme',
            user_traits={
                'name': 'Tyler Wang',
                'email': 'tyler.wang@example.com',
            },
            company_traits={'name': 'Acme Corp'},
            url='https://example.com/workspace',
            url_normalized='https://example.com/workspace',
        )

        overview = user_analytics.build_users_overview_payload(self.project, range_key='last_30_days')
        overview_user = next(row for row in overview['users'] if row['id'] == 'user-42')
        detail = user_detail_analytics.build_user_detail_payload(self.project, 'user-42', range_key='last_30_days')
        switcher_user = next(row for row in detail['users'] if row['id'] == 'user-42')

        self.assertEqual(overview_user['email'], 'tyler.wang@example.com')
        self.assertEqual(detail['selectedUser']['email'], 'tyler.wang@example.com')
        self.assertEqual(switcher_user['email'], 'tyler.wang@example.com')

    def test_build_user_detail_payload_uses_grouped_pages_and_company_peers(self):
        start_date, end_date = services.resolve_period(self.project.timezone, range_key='last_30_days')
        previous_start, previous_end = services.previous_period(start_date, end_date)
        billing = ProductArea.objects.create(
            project=self.project,
            name='Billing',
            slug='billing',
            short_name='Billing',
            color='#13579B',
        )
        analytics = ProductArea.objects.create(
            project=self.project,
            name='Analytics',
            slug='analytics',
            short_name='Analytics',
            color='#2468AC',
        )
        automation = ProductArea.objects.create(
            project=self.project,
            name='Automation',
            slug='automation',
            short_name='Auto',
            color='#A1B2C3',
        )
        invoices = ProjectPageRule.objects.create(
            project=self.project,
            page_name='Invoices',
            product_area='Billing',
            pattern='/billing/invoices',
        )
        reports = ProjectPageRule.objects.create(
            project=self.project,
            page_name='Reports',
            product_area='Analytics',
            pattern='/reports',
        )
        workflows = ProjectPageRule.objects.create(
            project=self.project,
            page_name='Workflows',
            product_area='Automation',
            pattern='/workflows',
        )
        PageDailyMetric.objects.create(
            project=self.project,
            date=end_date,
            page_rule_id=invoices.id,
            product_area=billing,
            product_area_key='billing',
            product_area_name='Billing',
            visits_count=8,
            engaged_seconds=1800,
            users_count_daily=3,
        )
        PageDailyMetric.objects.create(
            project=self.project,
            date=end_date,
            page_rule_id=reports.id,
            product_area=analytics,
            product_area_key='analytics',
            product_area_name='Analytics',
            visits_count=12,
            engaged_seconds=2400,
            users_count_daily=2,
        )
        PageUserDailyMetric.objects.create(
            project=self.project,
            date=end_date,
            page_rule_id=invoices.id,
            product_area=billing,
            product_area_key='billing',
            product_area_name='Billing',
            company_id='acme',
            user_id='sarah@example.com',
            user_name_sample='Sarah Chen',
            visits_count=6,
            engaged_seconds=1200,
            click_count=3,
        )
        # This area intentionally has no PageDailyMetric row, so it is outside
        # the visible product-area options and must still use its persisted color.
        PageUserDailyMetric.objects.create(
            project=self.project,
            date=end_date,
            page_rule_id=workflows.id,
            product_area=automation,
            product_area_key='automation',
            product_area_name='Automation',
            company_id='acme',
            user_id='sarah@example.com',
            user_name_sample='Sarah Chen',
            visits_count=1,
            engaged_seconds=100,
            click_count=0,
        )
        PageUserDailyMetric.objects.create(
            project=self.project,
            date=previous_end,
            page_rule_id=invoices.id,
            product_area=billing,
            product_area_key='billing',
            product_area_name='Billing',
            company_id='acme',
            user_id='sarah@example.com',
            user_name_sample='Sarah Chen',
            visits_count=10,
            engaged_seconds=2400,
            click_count=8,
        )
        for user_id in ('peer-1@example.com', 'peer-2@example.com'):
            PageUserDailyMetric.objects.create(
                project=self.project,
                date=end_date,
                page_rule_id=reports.id,
                product_area=analytics,
                product_area_key='analytics',
                product_area_name='Analytics',
                company_id='acme',
                user_id=user_id,
                user_name_sample=user_id.split('@', 1)[0],
                visits_count=5,
                engaged_seconds=900,
                click_count=4,
            )
            PageUserDailyMetric.objects.create(
                project=self.project,
                date=end_date,
                page_rule_id=workflows.id,
                product_area=automation,
                product_area_key='automation',
                product_area_name='Automation',
                company_id='acme',
                user_id=user_id,
                user_name_sample=user_id.split('@', 1)[0],
                visits_count=6,
                engaged_seconds=1800,
                click_count=2,
            )
        visit_ts = timezone.make_aware(datetime.combine(end_date, time(hour=12)))
        for user_id in ('sarah@example.com', 'peer-1@example.com', 'peer-2@example.com'):
            PageVisit.objects.create(
                project=self.project,
                session_id=uuid4(),
                user_id=user_id,
                user_name_sample='Sarah Chen' if user_id == 'sarah@example.com' else user_id,
                company_id='acme',
                company_name_sample='Acme Corp',
                page_rule_id=invoices.id if user_id == 'sarah@example.com' else reports.id,
                product_area=billing if user_id == 'sarah@example.com' else analytics,
                product_area_key='billing' if user_id == 'sarah@example.com' else 'analytics',
                product_area_name='Billing' if user_id == 'sarah@example.com' else 'Analytics',
                visit_start_ts=visit_ts,
                visit_end_ts=visit_ts + timedelta(minutes=3),
                engaged_seconds=180,
                click_count=1,
                had_click=True,
            )

        payload = user_detail_analytics.build_user_detail_payload(
            self.project,
            'sarah@example.com',
            range_key='last_30_days',
        )

        self.assertEqual(payload['selectedUser']['companyName'], 'Acme Corp')
        # Eight cards in eight equal slots: Active days absorbed Consistency,
        # and Areas used took the column it stopped occupying twice over.
        self.assertEqual(
            [card['id'] for card in payload['metricCards']],
            [
                'engaged_time',
                'active_days',
                'intensity',
                'visits',
                'avg_visit',
                'pages_used',
                'areas_used',
                'interaction_rate',
            ],
        )
        self.assertEqual(len(payload['dailyUsage']), 30 * len(payload['productAreas']))
        self.assertTrue(any(row['isCurrentUser'] for row in payload['peerComparison']))
        self.assertTrue(all(row['userId'] != 'sarah@example.com' for row in payload['peerComparison'] if not row['isCurrentUser']))
        self.assertEqual(payload['pagesUsed'][0]['pageRuleId'], str(invoices.id))
        workflow_page = next(row for row in payload['pagesUsed'] if row['pageName'] == 'Workflows')
        automation_peer = next(row for row in payload['peerComparison'] if row['userId'] == 'peer-1@example.com')
        self.assertNotIn('Automation', {row['name'] for row in payload['productAreas']})
        self.assertEqual(workflow_page['productAreaColor'], '#A1B2C3')
        self.assertEqual(automation_peer['topArea'], 'Automation')
        self.assertEqual(automation_peer['topAreaColor'], '#A1B2C3')
        self.assertIn('Reports', {row['pageName'] for row in payload['underusedPages']})
        self.assertEqual(
            next(row for row in payload['underusedPages'] if row['pageName'] == 'Workflows')['productAreaColor'],
            '#A1B2C3',
        )
        self.assertTrue(all(action['evidence'] for action in payload['recommendedActions']))

        result = user_detail_analytics.build_user_detail_cache(
            self.project.id,
            'sarah@example.com',
            range_key='last_30_days',
        )
        self.assertEqual(result['status'], 'success')
        cache = UsersDetailCache.objects.get(project=self.project, user_id='sarah@example.com', range_key='last_30_days')
        self.assertEqual(cache.payload_json['schema_version'], user_detail_analytics.USER_DETAILS_PAYLOAD_SCHEMA_VERSION)

    def test_user_status_thresholds_scale_with_period(self):
        weekly_power_thresholds = services.power_user_thresholds(7)
        monthly_power_thresholds = services.power_user_thresholds(30)
        monthly_healthy_thresholds = services.healthy_user_thresholds(30)
        weekly_power = {
            'visits': weekly_power_thresholds['visits'],
            'engaged_seconds': weekly_power_thresholds['engaged_seconds'],
            'product_areas_used': weekly_power_thresholds['product_areas'],
            'click_count': weekly_power_thresholds['visits'],
            'active_days': weekly_power_thresholds['active_days'],
        }
        monthly_power = {
            'visits': monthly_power_thresholds['visits'],
            'engaged_seconds': monthly_power_thresholds['engaged_seconds'],
            'product_areas_used': monthly_power_thresholds['product_areas'],
            'click_count': monthly_power_thresholds['visits'],
            'active_days': monthly_power_thresholds['active_days'],
        }
        monthly_healthy = {
            'visits': monthly_power_thresholds['visits'] - 1,
            'engaged_seconds': monthly_power_thresholds['engaged_seconds'] - 1,
            'product_areas_used': 2,
            'click_count': monthly_power_thresholds['visits'] - 1,
            'active_days': monthly_power_thresholds['active_days'] - 1,
        }
        sparse_long_period_user = {
            'visits': 14,
            'engaged_seconds': 669,
            'product_areas_used': 2,
            'click_count': 14,
            'active_days': 4,
        }

        self.assertEqual(user_analytics._status_for_user(weekly_power, period_days=7), 'Power')
        self.assertEqual(weekly_power_thresholds, {
            'visits': 3,
            'engaged_seconds': 100,
            'active_days': 1,
            'product_areas': 2,
            'interaction': 0.2,
        })
        self.assertEqual(monthly_power_thresholds, {
            'visits': 13,
            'engaged_seconds': 429,
            'active_days': 4,
            'product_areas': 2,
            'interaction': 0.2,
        })
        self.assertEqual(monthly_healthy_thresholds, {
            'visits': 9,
            'engaged_seconds': 258,
            'active_days': 3,
            'product_areas': 1,
        })
        self.assertNotEqual(user_analytics._status_for_user(weekly_power, period_days=30), 'Power')
        self.assertEqual(user_analytics._status_for_user(monthly_power, period_days=30), 'Power')
        self.assertEqual(user_analytics._status_for_user(monthly_healthy, period_days=30), 'Healthy')
        self.assertNotEqual(user_analytics._status_for_user(sparse_long_period_user, period_days=90), 'Power')

    def test_power_user_thresholds_use_project_p90_for_large_cohorts(self):
        cohort = [
            {
                'visits': index,
                'engaged_seconds': index * 100,
                'click_count': index,
                'active_days': index,
            }
            for index in range(1, 31)
        ]

        self.assertEqual(
            services.power_user_thresholds(30, cohort),
            {
                'visits': 27,
                'engaged_seconds': 2700,
                'active_days': 27,
                'product_areas': 2,
                'interaction': 0.2,
            },
        )

    def test_power_user_thresholds_keep_floors_for_small_or_weak_cohorts(self):
        base_thresholds = services.power_user_thresholds(30)
        small_cohort = [
            {'visits': 100, 'engaged_seconds': 10000, 'click_count': 100, 'active_days': 30}
            for _index in range(services.POWER_USER_DYNAMIC_MIN_COHORT_SIZE - 1)
        ]
        weak_large_cohort = [
            {'visits': 1, 'engaged_seconds': 1, 'click_count': 1, 'active_days': 1}
            for _index in range(services.POWER_USER_DYNAMIC_MIN_COHORT_SIZE)
        ]

        self.assertEqual(services.power_user_thresholds(30, small_cohort), base_thresholds)
        self.assertEqual(services.power_user_thresholds(30, weak_large_cohort), base_thresholds)

    def test_user_status_uses_supplied_project_power_thresholds(self):
        base_power_user = {
            'visits': 13,
            'engaged_seconds': 429,
            'product_areas_used': 2,
            'click_count': 13,
            'active_days': 4,
        }
        project_thresholds = {
            **services.power_user_thresholds(30),
            'visits': 20,
            'engaged_seconds': 600,
            'active_days': 5,
        }

        self.assertEqual(user_analytics._status_for_user(base_power_user, period_days=30), 'Power')
        self.assertEqual(
            user_analytics._status_for_user(
                base_power_user,
                period_days=30,
                power_thresholds=project_thresholds,
            ),
            'Healthy',
        )
        self.assertEqual(
            user_detail_analytics._status_key(base_power_user, period_days=30),
            'power_user',
        )
        self.assertEqual(
            user_detail_analytics._status_key(
                base_power_user,
                period_days=30,
                power_thresholds=project_thresholds,
            ),
            'healthy',
        )

    def test_passive_engaged_floor_does_not_scale_with_period(self):
        low_engagement = {
            'visits': 20,
            'engaged_seconds': services.PASSIVE_USER_ENGAGED_SECONDS - 1,
            'product_areas_used': 2,
            'click_count': 20,
            'active_days': 5,
        }
        above_floor = {**low_engagement, 'engaged_seconds': services.PASSIVE_USER_ENGAGED_SECONDS}

        self.assertEqual(user_analytics._status_for_user(low_engagement, period_days=30), 'Passive')
        self.assertEqual(user_analytics._status_for_user(above_floor, period_days=30), 'Light')

    def test_build_users_overview_payload_does_not_limit_users_list_to_top_30(self):
        _start_date, end_date = services.resolve_period(self.project.timezone, range_key='last_90_days')

        for index in range(35):
            PageUserDailyMetric.objects.create(
                project=self.project,
                date=end_date,
                company_id='acme',
                user_id=f'user-{index:02d}@example.com',
                user_name_sample=f'User {index:02d}',
                visits_count=index + 1,
                engaged_seconds=(index + 1) * 60,
                click_count=1,
            )

        payload = user_analytics.build_users_overview_payload(self.project, range_key='last_90_days')

        self.assertEqual(len(payload['users']), 35)

    def test_users_scatter_sample_is_random_not_top_slice(self):
        users = [{'id': f'user-{index:03d}@example.com'} for index in range(user_analytics.SCATTER_VISIBLE_LIMIT + 5)]

        first_sample = user_analytics._random_scatter_sample(users, user_analytics.SCATTER_VISIBLE_LIMIT, 'test-salt')
        second_sample = user_analytics._random_scatter_sample(users, user_analytics.SCATTER_VISIBLE_LIMIT, 'test-salt')

        self.assertEqual(len(first_sample), user_analytics.SCATTER_VISIBLE_LIMIT)
        self.assertEqual(first_sample, second_sample)
        self.assertNotEqual(first_sample, users[:user_analytics.SCATTER_VISIBLE_LIMIT])

    def test_rebuild_project_pages_analytics_prepares_visits_metrics_and_cache(self):
        billing_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^app\.example\.com/billing$',
            product_area='Billing',
            page_name='Billing',
            priority=100,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )
        projects_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^app\.example\.com/projects$',
            product_area='Projects',
            page_name='Projects',
            priority=90,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )
        billing_history_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^app\.example\.com/billing/history$',
            product_area='Billing',
            page_name='Billing history',
            priority=80,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )
        analytics_session = AnalyticsSession.objects.create(
            project=self.project,
            user_id='user-1',
            company_id='acme',
            start_time=timezone.now(),
            last_activity=timezone.now(),
        )
        # Preparation covers whole days the analytics window can request, and
        # that window ends on the last complete day, so events stamped today
        # prepare nothing.
        _rebuild_start, rebuild_end = services.resolve_period(
            self.project.timezone,
            range_key='last_30_days',
        )
        base_ts = timezone.now().replace(
            year=rebuild_end.year,
            month=rebuild_end.month,
            day=rebuild_end.day,
            hour=12,
            minute=0,
            second=0,
            microsecond=0,
        )
        common = {
            'session': analytics_session,
            'visitor_guid': analytics_session.visitor_guid,
            'user_id': 'user-1',
            'user_traits': {'name': 'Jane Cooper'},
            'company_id': 'acme',
            'company_traits': {'name': 'Acme Inc.'},
        }
        AnalyticsEvent.objects.create(
            **common,
            timestamp=base_ts,
            event_type='click',
            element_key='billing-save',
            url='https://app.example.com/billing',
            url_normalized='app.example.com/billing',
            product_area='Billing',
            page_name='Billing',
            page_rule=billing_rule,
        )
        AnalyticsEvent.objects.create(
            **common,
            timestamp=base_ts + timedelta(seconds=12),
            event_type='mouse_move',
            url='https://app.example.com/billing',
            url_normalized='app.example.com/billing',
            product_area='Billing',
            page_name='Billing',
            page_rule=billing_rule,
        )
        AnalyticsEvent.objects.create(
            **common,
            timestamp=base_ts + timedelta(seconds=24),
            event_type='click',
            element_key='billing-history',
            url='https://app.example.com/billing/history',
            url_normalized='app.example.com/billing/history',
            product_area='Billing',
            page_name='Billing history',
            page_rule=billing_history_rule,
        )
        AnalyticsEvent.objects.create(
            **common,
            timestamp=base_ts + timedelta(seconds=30),
            event_type='mouse_move',
            url='https://app.example.com/billing/history',
            url_normalized='app.example.com/billing/history',
            product_area='Billing',
            page_name='Billing history',
            page_rule=billing_history_rule,
        )
        AnalyticsEvent.objects.create(
            **common,
            timestamp=base_ts + timedelta(seconds=36),
            event_type='click',
            element_key='project-open',
            url='https://app.example.com/projects',
            url_normalized='app.example.com/projects',
            product_area='Projects',
            page_name='Projects',
            page_rule=projects_rule,
        )
        alternate_session = AnalyticsSession.objects.create(
            project=self.project,
            user_id='user-2',
            company_id='acme',
            start_time=timezone.now(),
            last_activity=timezone.now(),
        )
        alternate_common = {
            'session': alternate_session,
            'visitor_guid': alternate_session.visitor_guid,
            'user_id': 'user-2',
            'user_traits': {'name': 'Ava Stone'},
            'company_id': 'acme',
            'company_traits': {'name': 'Acme Inc.'},
        }
        AnalyticsEvent.objects.create(
            **alternate_common,
            timestamp=base_ts + timedelta(minutes=1),
            event_type='click',
            element_key='billing-save',
            url='https://app.example.com/account/billing',
            url_normalized='app.example.com/account/billing',
            product_area='Billing',
            page_name='Billing',
            page_rule=billing_rule,
        )
        stale_from_visit = PageVisit.objects.create(
            project=self.project,
            session_id=analytics_session.session_id,
            url_normalized='app.example.com/stale-from',
            visit_start_ts=base_ts + timedelta(minutes=30),
            visit_end_ts=base_ts + timedelta(minutes=31),
        )
        stale_to_visit = PageVisit.objects.create(
            project=self.project,
            session_id=analytics_session.session_id,
            url_normalized='app.example.com/stale-to',
            visit_start_ts=base_ts + timedelta(minutes=31),
            visit_end_ts=base_ts + timedelta(minutes=32),
        )
        PageTransition.objects.create(
            project=self.project,
            session_id=analytics_session.session_id,
            from_visit=stale_from_visit,
            to_visit=stale_to_visit,
            transition_ts=base_ts - timedelta(days=2),
        )

        result = rebuild_project_pages_analytics(
            self.project.id,
            base_ts.date(),
            base_ts.date(),
            range_keys=('last_7_days',),
        )

        self.assertEqual(result['status'], 'success')
        self.project.refresh_from_db()
        self.assertEqual(result['analytics_facts_revision'], 1)
        self.assertEqual(self.project.analytics_facts_revision, 1)
        self.assertEqual(result['filtered_analytics_revision'], 1)
        self.assertEqual(self.project.filtered_analytics_revision, 1)
        self.assertEqual(ProductArea.objects.filter(project=self.project).count(), 2)
        self.assertEqual(
            set(ProductArea.objects.filter(project=self.project).values_list('color', flat=True)),
            {''},
        )
        self.assertEqual(PageVisit.objects.filter(project=self.project).count(), 4)
        self.assertEqual(PageTransition.objects.filter(project=self.project).count(), 2)
        self.assertEqual(PageDailyMetric.objects.filter(project=self.project).count(), 3)
        self.assertTrue(
            PageVisit.objects.filter(
                project=self.project,
                user_id='user-1',
                user_name_sample='Jane Cooper',
                company_name_sample='Acme Inc.',
            ).exists()
        )
        self.assertTrue(
            PageUserDailyMetric.objects.filter(
                project=self.project,
                user_id='user-1',
                user_name_sample='Jane Cooper',
            ).exists()
        )

        cache = PagesOverviewCache.objects.get(project=self.project, range_key='last_7_days')
        companies_cache = CompaniesOverviewCache.objects.get(project=self.project, range_key='last_7_days')
        users_cache = UsersOverviewCache.objects.get(project=self.project, range_key='last_7_days')
        detail_caches = PagesDetailCache.objects.filter(project=self.project, range_key='last_7_days')
        user_detail_caches = UsersDetailCache.objects.filter(project=self.project, range_key='last_7_days')
        expected_user_ids = {row['id'] for row in users_cache.payload_json['users']}

        self.assertEqual(cache.payload_json['project']['id'], self.project.id)
        self.assertEqual(companies_cache.payload_json['project']['id'], self.project.id)
        self.assertEqual(users_cache.payload_json['project']['id'], self.project.id)
        self.assertIn('companies', companies_cache.payload_json)
        self.assertIn('users', users_cache.payload_json)
        self.assertEqual(len(result['users_cache_results']), 1)
        self.assertEqual(result['users_cache_results'][0]['detail_cache_status'], 'skipped')
        self.assertEqual(result['users_cache_results'][0]['detail_cache_count'], 0)
        self.assertEqual(detail_caches.count(), 3)
        self.assertFalse(user_detail_caches.exists())
        self.assertTrue(detail_caches.filter(page_rule_id=str(billing_rule.id)).exists())
        self.assertEqual(len(cache.payload_json['change_aware_rows']), 3)
        self.assertEqual(len(cache.payload_json['rows']), 3)
        self.assertEqual(len(cache.payload_json['page_metrics_rows']), 3)
        self.assertEqual(len(cache.payload_json['kpi_daily_rows']), 3)
        self.assertEqual(len(cache.payload_json['product_area_summary']), 2)
        self.assertNotIn('relative_change_series', cache.payload_json['change_aware_rows'][0])
        self.assertNotIn('relative_change_series', cache.payload_json['rows'][0])
        self.assertNotIn('relative_change_series', cache.payload_json['page_metrics_rows'][0])
        self.assertNotIn('relative_change_series', cache.payload_json['product_area_summary'][0])
        self.assertIn('trends', cache.payload_json['change_aware_rows'][0])
        self.assertIn('adoption', cache.payload_json['change_aware_rows'][0]['trends'])
        self.assertIn('engaged', cache.payload_json['change_aware_rows'][0]['trends'])
        self.assertIn('daily_kpi_trends', cache.payload_json['change_aware_rows'][0])
        self.assertIn(
            'adoption',
            cache.payload_json['change_aware_rows'][0]['daily_kpi_trends'],
        )
        self.assertIn(
            'current',
            cache.payload_json['change_aware_rows'][0]['daily_kpi_trends']['adoption'],
        )
        self.assertIn(
            'previous',
            cache.payload_json['change_aware_rows'][0]['daily_kpi_trends']['adoption'],
        )
        self.assertIn(
            'companies',
            cache.payload_json['change_aware_rows'][0]['daily_kpi_trends'],
        )
        # The fastest-growing card compares two period totals it can read off
        # the row, so no per-day aligned prefixes are stored for it any more.
        self.assertNotIn(
            'aligned_company_prefixes',
            cache.payload_json['kpi_daily_rows'][0]['daily_kpi_trends'],
        )
        self.assertNotIn(
            '_aligned_company_prefixes',
            cache.payload_json['kpi_daily_rows'][0],
        )
        self.assertIn('trends', cache.payload_json['product_area_summary'][0])
        self.assertIn('companies', cache.payload_json['product_area_summary'][0]['trends'])
        self.assertEqual(
            {row['page_name'] for row in cache.payload_json['change_aware_rows']},
            {'Billing', 'Billing history', 'Projects'},
        )
        self.assertEqual(
            {row['page_name'] for row in cache.payload_json['page_metrics_rows']},
            {'Billing', 'Billing history', 'Projects'},
        )
        self.assertEqual(
            {row['product_area_name'] for row in cache.payload_json['product_area_summary']},
            {'Billing', 'Projects'},
        )
        billing_summary = next(
            row for row in cache.payload_json['product_area_summary']
            if row['product_area_name'] == 'Billing'
        )
        self.assertEqual(billing_summary['companies_count'], 1)
        self.assertEqual(billing_summary['users_count'], 2)
        self.assertEqual(max(billing_summary['trends']['companies']), 1)
        self.assertEqual(max(billing_summary['trends']['adoption']), 100)
        self.assertEqual(max(billing_summary['trends']['users']), 2)
        self.assertIn('labels', cache.payload_json['top_pages_by_visits_over_time'])
        self.assertIn('values', cache.payload_json['top_pages_by_visits_over_time']['series'][0])
        self.assertIn('page_group', cache.payload_json['engaged_time_treemap']['nodes'][0])
        billing_treemap_node = next(
            node
            for node in cache.payload_json['engaged_time_treemap']['nodes']
            if node['name'] == 'Billing'
        )
        self.assertEqual(billing_treemap_node['page_count'], 2)
        self.assertEqual(
            {child['name'] for child in billing_treemap_node['children']},
            {'Billing', 'Billing history'},
        )
        billing_actions = next(
            page for page in cache.payload_json['top_actions_by_page']
            if page['page_label'] == 'Billing'
        )
        self.assertEqual(billing_actions['visits_count'], 2)
        self.assertEqual(billing_actions['actions'][0]['element_key'], 'billing-save')
        self.assertEqual(billing_actions['actions'][0]['clicks_count'], 2)
        self.assertEqual(cache.payload_json['top_actions_by_page_group'][0]['actions'][0]['clicks'], 2)
        self.assertIn('company_engagement_by_page_group', cache.payload_json)
        self.assertIn('top_clicked_elements', cache.payload_json)

        detail_result = services.rebuild_project_analytics_caches(
            self.project.id,
            range_keys=('last_7_days',),
            include_user_details=True,
        )
        user_detail_caches = UsersDetailCache.objects.filter(project=self.project, range_key='last_7_days')
        self.assertEqual(detail_result['users_cache_results'][0]['detail_cache_status'], 'success')
        self.assertEqual(detail_result['users_cache_results'][0]['detail_cache_count'], len(expected_user_ids))
        self.assertEqual(user_detail_caches.count(), len(expected_user_ids))
        self.assertTrue(user_detail_caches.filter(user_id='user-1').exists())

    def test_rebuild_project_pages_analytics_groups_user_metrics_across_companies(self):
        pages_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^app\.example\.com/pages$',
            product_area='Pages',
            page_name='Pages',
            priority=100,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )
        base_ts = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)

        for offset, company_id in enumerate(('acme', 'hymetry')):
            analytics_session = AnalyticsSession.objects.create(
                project=self.project,
                user_id='user-1',
                company_id=company_id,
                start_time=base_ts + timedelta(minutes=offset),
                last_activity=base_ts + timedelta(minutes=offset),
            )
            AnalyticsEvent.objects.create(
                session=analytics_session,
                timestamp=base_ts + timedelta(minutes=offset),
                event_type='click',
                visitor_guid=analytics_session.visitor_guid,
                user_id='user-1',
                user_traits={'name': 'Jane Cooper'},
                company_id=company_id,
                company_traits={'name': company_id.title()},
                element_key='pages-open',
                url='https://app.example.com/pages',
                url_normalized='app.example.com/pages',
                product_area='Pages',
                page_name='Pages',
                page_rule=pages_rule,
            )

        result = rebuild_project_pages_analytics(
            self.project.id,
            base_ts.date(),
            base_ts.date(),
            range_keys=(),
        )

        self.assertEqual(result['status'], 'success')
        user_metric = PageUserDailyMetric.objects.get(
            project=self.project,
            date=base_ts.date(),
            page_rule_id=pages_rule.id,
            product_area_key='pages',
            user_id='user-1',
        )
        self.assertEqual(user_metric.visits_count, 2)
        self.assertEqual(user_metric.company_id, 'acme')

    def test_aggregate_page_daily_metrics_collapses_area_display_variants(self):
        pages_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^app\.example\.com/pages$',
            product_area='Pages',
            page_name='Pages',
            priority=100,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )
        pages_area = ProductArea.objects.create(
            project=self.project,
            name='Pages',
            slug='pages',
            short_name='Pages',
            color='#4269D0',
        )
        base_ts = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)
        common = {
            'project': self.project,
            'session_id': uuid4(),
            'user_id': 'user-1',
            'user_name_sample': 'Jane Cooper',
            'company_id': 'acme',
            'company_name_sample': 'Acme Inc.',
            'url_normalized': 'app.example.com/pages',
            'page_rule_id': pages_rule.id,
            'product_area_key': 'pages',
            'visit_start_ts': base_ts,
            'visit_end_ts': base_ts + timedelta(minutes=1),
            'had_click': True,
        }
        PageVisit.objects.create(
            **common,
            product_area=pages_area,
            product_area_name='Pages',
            engaged_seconds=20,
            click_count=1,
        )
        PageVisit.objects.create(
            **{**common, 'session_id': uuid4(), 'visit_start_ts': base_ts + timedelta(minutes=5)},
            product_area=None,
            product_area_name='pages',
            engaged_seconds=40,
            click_count=2,
        )

        result = services.aggregate_page_daily_metrics(
            self.project.id,
            base_ts.date(),
            base_ts.date(),
            self.project.timezone,
        )

        self.assertEqual(result['status'], 'success')
        self.project.refresh_from_db()
        self.assertEqual(result['analytics_facts_revision'], 1)
        self.assertEqual(self.project.analytics_facts_revision, 1)
        self.assertEqual(result['filtered_analytics_revision'], 1)
        self.assertEqual(self.project.filtered_analytics_revision, 1)
        daily_metric = PageDailyMetric.objects.get(
            project=self.project,
            date=base_ts.date(),
            page_rule_id=pages_rule.id,
            product_area_key='pages',
        )
        company_metric = PageCompanyDailyMetric.objects.get(
            project=self.project,
            date=base_ts.date(),
            page_rule_id=pages_rule.id,
            product_area_key='pages',
            company_id='acme',
        )
        user_metric = PageUserDailyMetric.objects.get(
            project=self.project,
            date=base_ts.date(),
            page_rule_id=pages_rule.id,
            product_area_key='pages',
            user_id='user-1',
        )

        self.assertEqual(PageDailyMetric.objects.filter(project=self.project).count(), 1)
        self.assertEqual(PageCompanyDailyMetric.objects.filter(project=self.project).count(), 1)
        self.assertEqual(PageUserDailyMetric.objects.filter(project=self.project).count(), 1)
        self.assertEqual(daily_metric.product_area_id, pages_area.id)
        self.assertEqual(daily_metric.visits_count, 2)
        self.assertEqual(daily_metric.engaged_seconds, 60)
        self.assertEqual(daily_metric.click_count, 3)
        self.assertEqual(daily_metric.visits_with_click_count, 2)
        self.assertEqual(daily_metric.companies_count_daily, 1)
        self.assertEqual(daily_metric.users_count_daily, 1)
        self.assertEqual(company_metric.visits_count, 2)
        self.assertEqual(company_metric.active_users_count_daily, 1)
        self.assertEqual(user_metric.visits_count, 2)
        self.assertEqual(user_metric.engaged_seconds, 60)
        self.assertEqual(user_metric.click_count, 3)

    def test_adoption_delta_is_not_new_when_previous_row_has_companies(self):
        previous_date = date(2026, 5, 1)
        current_date = date(2026, 5, 2)
        dashboard_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^app\.example\.com/dashboard$',
            product_area='Core',
            page_name='Dashboard',
            priority=100,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )

        for metric_date in (previous_date, current_date):
            PageDailyMetric.objects.create(
                project=self.project,
                date=metric_date,
                page_rule_id=dashboard_rule.id,
                product_area_key='core',
                product_area_name='Core',
                visits_count=10,
                engaged_seconds=600,
                click_count=2,
                visits_with_click_count=1,
                companies_count_daily=1,
            )
            PageCompanyDailyMetric.objects.create(
                project=self.project,
                date=metric_date,
                page_rule_id=dashboard_rule.id,
                product_area_key='core',
                product_area_name='Core',
                company_id='acme',
                company_name_sample='Acme',
                visits_count=10,
                engaged_seconds=600,
                click_count=2,
                visits_with_click_count=1,
            )

        with patch(
            'apps.pages.services._project_distinct_counts',
            side_effect=[
                {'active_companies_count': 1, 'active_users_count': 0},
                {'active_companies_count': 0, 'active_users_count': 0},
            ],
        ):
            rows, _current_counts, _previous_counts = services._build_change_rows(
                self.project.id,
                current_date,
                current_date,
                previous_date,
                previous_date,
            )

        row = rows[0]

        self.assertEqual(row['companies_count'], 1)
        self.assertEqual(row['companies_change_pct'], 0)
        self.assertEqual(row['adoption_pct'], 100)
        self.assertEqual(row['adoption_change_pp'], 0)
        self.assertTrue(row['comparison_available'])
        self.assertEqual(row['relative_change_series']['adoption'][0]['current'], 100)
        self.assertEqual(row['relative_change_series']['adoption'][0]['previous'], 100)

    def test_company_engagement_scatter_uses_average_active_users(self):
        first_date = date(2026, 5, 1)
        second_date = date(2026, 5, 2)

        for metric_date, engaged, users in (
            (first_date, 500, 5),
            (second_date, 600, 6),
        ):
            PageDailyMetric.objects.create(
                project=self.project,
                date=metric_date,
                page_rule_id=1,
                product_area_key='core',
                product_area_name='Core',
                visits_count=users,
                engaged_seconds=engaged,
                click_count=users,
                visits_with_click_count=users,
                companies_count_daily=1,
                users_count_daily=users,
            )
            PageCompanyDailyMetric.objects.create(
                project=self.project,
                date=metric_date,
                page_rule_id=1,
                product_area_key='core',
                product_area_name='Core',
                company_id='acme',
                company_name_sample='Acme Inc.',
                visits_count=users,
                engaged_seconds=engaged,
                click_count=users,
                visits_with_click_count=users,
                active_users_count_daily=users,
            )
            for index in range(users):
                PageUserDailyMetric.objects.create(
                    project=self.project,
                    date=metric_date,
                    page_rule_id=1,
                    product_area_key='core',
                    product_area_name='Core',
                    company_id='acme',
                    user_id=f'user-{index}',
                    visits_count=1,
                    engaged_seconds=100,
                    click_count=1,
                )

        groups = services._build_scatter(self.project.id, first_date, second_date)
        core_group = next(group for group in groups if group['product_area_key'] == 'core')
        point = next(item for item in core_group['points'] if item['company_id'] == 'acme')

        self.assertEqual(point['active_users'], 5.5)
        self.assertEqual(point['avg_engaged_seconds_per_user'], 200.0)

    def test_comparison_is_unavailable_when_previous_period_has_no_data(self):
        previous_date = date(2026, 5, 1)
        current_date = date(2026, 5, 2)
        dashboard_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^app\.example\.com/dashboard$',
            product_area='Core',
            page_name='Dashboard',
            priority=100,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )
        PageDailyMetric.objects.create(
            project=self.project,
            date=current_date,
            page_rule_id=dashboard_rule.id,
            product_area_key='core',
            product_area_name='Core',
            visits_count=10,
            engaged_seconds=600,
            click_count=2,
            visits_with_click_count=1,
            companies_count_daily=1,
        )
        PageCompanyDailyMetric.objects.create(
            project=self.project,
            date=current_date,
            page_rule_id=dashboard_rule.id,
            product_area_key='core',
            product_area_name='Core',
            company_id='acme',
            company_name_sample='Acme',
            visits_count=10,
            engaged_seconds=600,
            click_count=2,
            visits_with_click_count=1,
        )

        with patch(
            'apps.pages.services._project_distinct_counts',
            side_effect=[
                {'active_companies_count': 1, 'active_users_count': 0},
                {'active_companies_count': 0, 'active_users_count': 0},
            ],
        ):
            rows, _current_counts, _previous_counts = services._build_change_rows(
                self.project.id,
                current_date,
                current_date,
                previous_date,
                previous_date,
            )

        row = rows[0]
        adoption_metric = next(metric for metric in services.PAGE_DETAIL_METRICS if metric['key'] == 'adoption')
        detail_metric = services._detail_metric_payload(
            row,
            [],
            [],
            adoption_metric,
            current_date,
            current_date,
        )

        self.assertFalse(row['comparison_available'])
        self.assertFalse(detail_metric['comparisonAvailable'])
        self.assertIsNone(detail_metric['previousValue'])
        self.assertIsNone(detail_metric['deltaValue'])
        self.assertEqual(detail_metric['formattedDelta'], 'n/a')

    def test_product_area_summary_trends_are_daily_not_period_to_date(self):
        """
        The summary sparklines show activity per day, so they may fall.

        A running distinct count only rises, which made every company and user
        line grow regardless of what happened. Differencing that running count
        would not fix it either: the difference is companies seen for the first
        time, which is zero on a day when every active company is a returning
        one. The per-day counts come from the daily rows instead.
        """

        day_one = date(2026, 6, 1)
        day_two = day_one + timedelta(days=1)
        day_three = day_one + timedelta(days=2)

        # acme is active on all three days, beta only on day two, so the count
        # of companies active per day rises and then falls back.
        daily_rows = {
            (day_one, 'core'): {
                'visits_count': 10, 'engaged_seconds': 100,
                'click_count': 2, 'visits_with_click_count': 2,
                'companies_count_daily': 1, 'users_count_daily': 1,
                'active_companies_count': 1,
            },
            (day_two, 'core'): {
                'visits_count': 10, 'engaged_seconds': 50,
                'click_count': 2, 'visits_with_click_count': 2,
                'companies_count_daily': 2, 'users_count_daily': 2,
                'active_companies_count': 2,
            },
            (day_three, 'core'): {
                'visits_count': 10, 'engaged_seconds': 200,
                'click_count': 2, 'visits_with_click_count': 2,
                'companies_count_daily': 1, 'users_count_daily': 1,
                'active_companies_count': 1,
            },
        }
        identity_events = {
            'company': {'core': {day_one: 1, day_two: 1}},
            'user': {'core': {day_one: 1, day_two: 1}},
            'penetration': {'core': {day_one: 1, day_two: 1}},
            'project_company': {'': {day_one: 1, day_two: 1}},
        }

        row = {'row_key': 'core', 'product_area_key': 'core'}
        with patch.object(
            services,
            '_period_to_date_identity_events',
            return_value=identity_events,
        ):
            services._attach_period_to_date_trends(
                [row],
                self.project.id,
                day_one,
                day_three,
                daily_rows,
                grain='product_area',
            )

        summary_row = services._strip_for_product_area_summary(row)

        self.assertEqual(summary_row['trends']['companies'], [1, 2, 1])
        self.assertEqual(summary_row['trends']['users'], [1, 2, 1])
        self.assertEqual(summary_row['trends']['engaged'], [100, 50, 200])

        # The period-to-date series is untouched, and the rows built from it
        # keep rising, so the surfaces that rely on it are unaffected.
        self.assertEqual(row['_period_to_date_trends']['companies'], [1, 2, 2])
        self.assertEqual(row['_period_to_date_trends']['engaged'], [100, 150, 350])
        self.assertEqual(
            services._strip_for_overview_row(dict(row))['trends']['companies'],
            [1, 2, 2],
        )

        # Internal working keys must not reach the stored payload.
        self.assertNotIn('_daily_trends', summary_row)
        self.assertNotIn('_period_to_date_trends', summary_row)

    def test_period_to_date_rows_stay_cumulative_while_overview_kpis_are_daily(self):
        current_start = date(2026, 6, 1)
        current_end = date(2026, 6, 3)
        previous_start = date(2026, 5, 29)
        previous_end = date(2026, 5, 31)
        primary_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^app\.example\.com/primary$',
            product_area='Core',
            page_name='Primary',
            priority=100,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )
        secondary_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^app\.example\.com/secondary$',
            product_area='Core',
            page_name='Secondary',
            priority=90,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )
        zero_adoption_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^app\.example\.com/zero-adoption$',
            product_area='Core',
            page_name='Zero adoption',
            priority=80,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )
        day_one, day_two, day_three = (
            current_start,
            current_start + timedelta(days=1),
            current_end,
        )

        def add_page(rule, metric_date, visits, engaged, clicks=0, visits_with_click=0):
            PageDailyMetric.objects.create(
                project=self.project,
                date=metric_date,
                page_rule_id=rule.id,
                product_area_key='core',
                product_area_name='Core',
                visits_count=visits,
                engaged_seconds=engaged,
                click_count=clicks,
                visits_with_click_count=visits_with_click,
            )

        add_page(primary_rule, day_one, 2, 120, clicks=1, visits_with_click=1)
        add_page(primary_rule, day_two, 3, 90, clicks=5, visits_with_click=2)
        add_page(primary_rule, day_three, 1, 150)
        add_page(secondary_rule, day_one, 1, 30)
        add_page(zero_adoption_rule, day_one, 1, 10)

        def add_company(rule, metric_date, company_id):
            PageCompanyDailyMetric.objects.create(
                project=self.project,
                date=metric_date,
                page_rule_id=rule.id,
                product_area_key='core',
                product_area_name='Core',
                company_id=company_id,
                company_name_sample=company_id.title(),
                visits_count=1,
                engaged_seconds=30,
            )

        add_company(primary_rule, day_one, 'acme')
        add_company(primary_rule, day_two, 'acme')
        add_company(primary_rule, day_two, 'beta')
        add_company(primary_rule, day_three, 'beta')
        add_company(secondary_rule, day_one, 'gamma')
        add_company(primary_rule, day_one, '')
        add_company(primary_rule, previous_start, 'legacy-a')
        add_company(primary_rule, previous_end, 'legacy-b')

        def add_user(metric_date, user_id, company_id):
            PageUserDailyMetric.objects.create(
                project=self.project,
                date=metric_date,
                page_rule_id=primary_rule.id,
                product_area_key='core',
                product_area_name='Core',
                company_id=company_id,
                user_id=user_id,
                visits_count=1,
                engaged_seconds=30,
            )

        add_user(day_one, 'user-1', 'acme')
        add_user(day_two, 'user-1', 'acme')
        add_user(day_two, 'user-2', 'beta')
        add_user(day_three, 'user-3', 'outside-adopted-companies')
        add_user(day_one, '', '')

        for metric_date, active_companies, active_users in (
            (day_one, 2, 1),
            (day_two, 2, 2),
            (day_three, 1, 1),
        ):
            ProjectDailyMetric.objects.create(
                project=self.project,
                date=metric_date,
                active_companies_count=active_companies,
                active_users_count=active_users,
            )

        rows, current_counts, previous_counts = services._build_change_rows(
            self.project.id,
            current_start,
            current_end,
            previous_start,
            previous_end,
        )
        primary_row = next(row for row in rows if str(row['page_rule_id']) == str(primary_rule.id))
        trends = primary_row['_period_to_date_trends']

        self.assertEqual(trends['companies'], [2, 3, 3])
        self.assertEqual(trends['adoption'], [66.7, 75.0, 75.0])
        self.assertEqual(trends['users'], [2, 3, 4])
        self.assertEqual(trends['penetration'], [100.0, 100.0, 133.3])
        self.assertEqual(trends['visits'], [2, 5, 6])
        self.assertEqual(trends['engaged'], [120, 210, 360])
        self.assertEqual(trends['avg_visit'], [60.0, 42.0, 60.0])
        self.assertEqual(trends['interaction'], [50.0, 60.0, 50.0])
        self.assertEqual(trends['clicks_per_visit'], [0.5, 1.2, 1.0])

        metric_sources = {
            'companies': 'companies_count',
            'adoption': 'adoption_pct',
            'users': 'users_count',
            'penetration': 'penetration_pct',
            'visits': 'visits_count',
            'engaged': 'engaged_seconds',
            'avg_visit': 'avg_visit_seconds',
            'interaction': 'interaction_pct',
            'clicks_per_visit': 'clicks_per_visit',
        }
        for metric_key, source in metric_sources.items():
            with self.subTest(metric=metric_key):
                self.assertEqual(trends[metric_key][-1], primary_row[source])
        overview_row = services._strip_for_overview_row(primary_row)
        self.assertNotIn('_period_to_date_trends', overview_row)
        self.assertEqual(overview_row['trend_values'][-1], overview_row['companies_count'])
        self.assertEqual(overview_row['trends']['visits'][-1], overview_row['visits_count'])

        display_rows, _, _ = services._build_change_rows(
            self.project.id,
            current_start,
            current_end,
            previous_start,
            previous_end,
            grain='display_page',
        )
        primary_display_row = next(
            row
            for row in display_rows
            if str(row['page_rule_id']) == str(primary_rule.id)
        )
        self.assertEqual(primary_display_row['_period_to_date_trends']['companies'], [1, 2, 2])
        self.assertEqual(primary_display_row['_period_to_date_trends']['adoption'], [33.3, 50.0, 50.0])
        self.assertEqual(primary_display_row['_period_to_date_trends']['users'], [1, 2, 3])
        self.assertEqual(primary_display_row['_period_to_date_trends']['penetration'], [100.0, 100.0, 150.0])
        kpis = services._build_kpis(
            display_rows,
            {},
            current_counts['active_companies_count'],
            previous_counts['active_companies_count'],
            comparison_available=False,
        )
        self.assertEqual(kpis[0]['label'], 'Avg daily adopted pages')
        self.assertEqual(kpis[0]['value'], '1.3')
        self.assertEqual(kpis[0]['trend_values'], [2, 1, 1])
        self.assertEqual(kpis[0]['trend_scope'], 'daily')
        self.assertEqual(kpis[1]['label'], 'Avg daily adoption')
        self.assertEqual(kpis[1]['value'], '78%')
        self.assertEqual(kpis[1]['trend_values'], [33.3, 100.0, 100.0])
        self.assertEqual(kpis[1]['trend_scope'], 'daily')
        self.assertEqual(kpis[2]['value'], 'Primary')
        self.assertEqual(kpis[2]['delta'], '2m 00s avg/day')
        self.assertEqual(kpis[2]['trend_values'], [120.0, 90.0, 150.0])
        self.assertEqual(kpis[2]['trend_scope'], 'daily')
        self.assertNotIn('trend_values', kpis[3])

        area_rows, _, _ = services._build_change_rows(
            self.project.id,
            current_start,
            current_end,
            previous_start,
            previous_end,
            grain='product_area',
        )
        area_row = area_rows[0]
        area_summary = services._strip_for_product_area_summary(area_row)
        self.assertNotIn('_period_to_date_trends', area_summary)
        self.assertNotIn('_daily_trends', area_summary)
        # The summary sparklines are per-day, so their last point is the value on
        # the final date, not the row's period total. Only beta was active on day
        # three, recording 150 engaged seconds, while the period as a whole saw
        # four companies and 400 seconds.
        self.assertEqual(area_summary['trends']['companies'][-1], 1)
        self.assertEqual(area_summary['trends']['users'][-1], 1)
        self.assertEqual(area_summary['trends']['engaged'][-1], 150)
        self.assertEqual(area_summary['companies_count'], 4)
        self.assertEqual(area_summary['engaged_seconds'], 400)
        for metric_key in ('companies', 'adoption', 'users', 'engaged'):
            with self.subTest(area_metric=metric_key):
                self.assertEqual(len(area_summary['trends'][metric_key]), 3)
        # Engaged time is additive, so the daily points must add up to the period
        # total; a distinct count cannot exceed it on any single day.
        self.assertEqual(sum(area_summary['trends']['engaged']), area_summary['engaged_seconds'])
        self.assertLessEqual(
            max(area_summary['trends']['companies']),
            area_summary['companies_count'],
        )
        self.assertLessEqual(
            max(area_summary['trends']['users']),
            area_summary['users_count'],
        )
        # The period-to-date series is what still reconciles with the headline,
        # and the rows built from it are unchanged. Overview rows carry their own
        # metric set, which is why this loop is not the summary's.
        overview_area_row = services._strip_for_overview_row(dict(area_row))
        for metric_key, source in {
            'companies': 'companies_count',
            'adoption': 'adoption_pct',
            'engaged': 'engaged_seconds',
            'visits': 'visits_count',
        }.items():
            with self.subTest(overview_area_metric=metric_key):
                self.assertEqual(
                    overview_area_row['trends'][metric_key][-1],
                    overview_area_row[source],
                )

        detail = build_page_detail_payload(
            self.project.id,
            str(primary_rule.id),
            start_date=current_start,
            end_date=current_end,
        )
        detail_metrics = [
            *detail['metrics'],
            detail['combinedInteractionClicksMetric']['interaction'],
            detail['combinedInteractionClicksMetric']['clicksPerVisit'],
        ]
        rows_by_rule_id = {
            str(row['page_rule_id']): row
            for row in rows
        }
        benchmark_rows = [
            row
            for row in rows
            if str(row['page_rule_id']) != str(primary_rule.id)
        ]
        self.assertEqual({metric['key'] for metric in detail_metrics}, set(metric_sources))
        for metric in detail_metrics:
            with self.subTest(detail_metric=metric['key']):
                self.assertEqual(metric['dailySeries'][-1]['value'], metric['value'])
                for peer in metric['peerSeries']:
                    self.assertEqual(
                        peer['dailySeries'][-1]['value'],
                        rows_by_rule_id[str(peer['pageId'])][metric_sources[metric['key']]],
                    )
                self.assertEqual(
                    metric['benchmarkSeries'][-1]['value'],
                    services._median([
                        row[metric_sources[metric['key']]]
                        for row in benchmark_rows
                    ]),
                )

    def test_build_page_detail_payload_uses_actual_totals_peers_and_zero_ratio_prefix(self):
        current_start = date(2026, 5, 1)
        current_end = date(2026, 5, 2)
        previous_start = date(2026, 4, 29)
        previous_end = date(2026, 4, 30)
        billing_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^app\.example\.com/billing$',
            product_area='Billing',
            page_name='Billing',
            priority=100,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )
        invoices_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^app\.example\.com/invoices$',
            product_area='Billing',
            page_name='Invoices',
            priority=90,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )
        dashboard_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^app\.example\.com/dashboard$',
            product_area='Core',
            page_name='Dashboard',
            priority=80,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )

        for metric_date in (previous_start, previous_end, current_start, current_end):
            ProjectDailyMetric.objects.create(
                project=self.project,
                date=metric_date,
                active_companies_count=10,
                active_users_count=20,
            )

        def create_page_metric(rule, metric_date, visits, engaged, clicks, visits_with_clicks, area='Billing'):
            PageDailyMetric.objects.create(
                project=self.project,
                date=metric_date,
                page_rule_id=rule.id,
                product_area_key=area.lower(),
                product_area_name=area,
                visits_count=visits,
                engaged_seconds=engaged,
                click_count=clicks,
                visits_with_click_count=visits_with_clicks,
                companies_count_daily=2 if visits else 0,
                users_count_daily=3 if visits else 0,
            )

        create_page_metric(billing_rule, previous_start, 5, 250, 5, 2)
        create_page_metric(billing_rule, current_start, 0, 0, 0, 0)
        create_page_metric(billing_rule, current_end, 10, 1000, 20, 5)
        create_page_metric(invoices_rule, current_end, 8, 400, 8, 4)
        create_page_metric(dashboard_rule, current_end, 20, 600, 10, 3, area='Core')

        for company_id in ('acme', 'globex'):
            PageCompanyDailyMetric.objects.create(
                project=self.project,
                date=current_end,
                page_rule_id=billing_rule.id,
                product_area_key='billing',
                product_area_name='Billing',
                company_id=company_id,
                company_name_sample=company_id.title(),
                visits_count=5,
                engaged_seconds=500,
                click_count=10,
                visits_with_click_count=3,
                active_users_count_daily=2,
            )
        PageCompanyDailyMetric.objects.create(
            project=self.project,
            date=previous_start,
            page_rule_id=billing_rule.id,
            product_area_key='billing',
            product_area_name='Billing',
            company_id='acme',
            company_name_sample='Acme',
            visits_count=5,
            engaged_seconds=250,
            click_count=5,
            visits_with_click_count=2,
            active_users_count_daily=1,
        )
        PageCompanyDailyMetric.objects.create(
            project=self.project,
            date=current_end,
            page_rule_id=invoices_rule.id,
            product_area_key='billing',
            product_area_name='Billing',
            company_id='acme',
            visits_count=8,
            engaged_seconds=400,
            active_users_count_daily=1,
        )
        PageCompanyDailyMetric.objects.create(
            project=self.project,
            date=current_end,
            page_rule_id=dashboard_rule.id,
            product_area_key='core',
            product_area_name='Core',
            company_id='acme',
            visits_count=20,
            engaged_seconds=600,
            active_users_count_daily=1,
        )
        PageUserDailyMetric.objects.create(
            project=self.project,
            date=current_end,
            page_rule_id=billing_rule.id,
            product_area_key='billing',
            product_area_name='Billing',
            company_id='acme',
            user_id='user-1',
            user_name_sample='User One',
            visits_count=10,
            engaged_seconds=1000,
            click_count=20,
        )

        payload = build_page_detail_payload(
            self.project.id,
            str(billing_rule.id),
            start_date=current_start,
            end_date=current_end,
        )
        visits_metric = next(metric for metric in payload['metrics'] if metric['key'] == 'visits')
        avg_visit_metric = next(metric for metric in payload['metrics'] if metric['key'] == 'avg_visit')

        self.assertEqual(visits_metric['value'], 10)
        self.assertEqual(visits_metric['dailySeries'], [
            {'date': '2026-05-01', 'value': 0},
            {'date': '2026-05-02', 'value': 10},
        ])
        self.assertEqual(avg_visit_metric['dailySeries'][0]['value'], 0)
        self.assertEqual(avg_visit_metric['dailySeries'][1]['value'], 100.0)
        self.assertEqual(
            [peer['pageName'] for peer in visits_metric['peerSeries']],
            ['Invoices', 'Dashboard'],
        )
        self.assertEqual(payload['relatedPages'][0]['pageName'], 'Billing')
        self.assertEqual(payload['companies'][0]['company'], 'Acme')
        self.assertEqual(payload['champions'][0]['user'], 'User One')
        self.assertEqual(payload['champions'][0]['company'], 'Acme')

        slug_payload = build_page_detail_payload(
            self.project.id,
            'billing',
            start_date=current_start,
            end_date=current_end,
        )
        row_key_payload = build_page_detail_payload(
            self.project.id,
            f'billing::{billing_rule.id}',
            start_date=current_start,
            end_date=current_end,
        )

        self.assertEqual(str(slug_payload['page']['pageRuleId']), str(billing_rule.id))
        self.assertEqual(str(row_key_payload['page']['pageRuleId']), str(billing_rule.id))

        empty_period_payload = build_page_detail_payload(
            self.project.id,
            str(billing_rule.id),
            start_date=date(2026, 5, 3),
            end_date=date(2026, 5, 4),
        )
        empty_visits_metric = next(
            metric for metric in empty_period_payload['metrics'] if metric['key'] == 'visits'
        )
        empty_avg_visit_metric = next(
            metric for metric in empty_period_payload['metrics'] if metric['key'] == 'avg_visit'
        )

        self.assertEqual(empty_period_payload['page']['displayName'], 'Billing')
        self.assertEqual(empty_visits_metric['value'], 0)
        self.assertEqual(empty_visits_metric['dailySeries'], [
            {'date': '2026-05-03', 'value': 0},
            {'date': '2026-05-04', 'value': 0},
        ])
        self.assertEqual(empty_avg_visit_metric['dailySeries'], [
            {'date': '2026-05-03', 'value': 0},
            {'date': '2026-05-04', 'value': 0},
        ])

    def test_build_page_detail_payload_returns_all_company_and_champion_table_rows(self):
        current_date = date(2026, 5, 2)
        previous_date = date(2026, 5, 1)
        dashboard_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^app\.example\.com/dashboard$',
            product_area='Core',
            page_name='Dashboard',
            priority=100,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )

        for metric_date in (previous_date, current_date):
            ProjectDailyMetric.objects.create(
                project=self.project,
                date=metric_date,
                active_companies_count=30,
                active_users_count=30,
            )

        PageDailyMetric.objects.create(
            project=self.project,
            date=current_date,
            page_rule_id=dashboard_rule.id,
            product_area_key='core',
            product_area_name='Core',
            visits_count=210,
            engaged_seconds=21000,
            click_count=210,
            visits_with_click_count=210,
            companies_count_daily=21,
            users_count_daily=21,
        )
        PageCompanyDailyMetric.objects.bulk_create([
            PageCompanyDailyMetric(
                project=self.project,
                date=current_date,
                page_rule_id=dashboard_rule.id,
                product_area_key='core',
                product_area_name='Core',
                company_id=f'company-{index:02d}',
                company_name_sample=f'Company {index:02d}',
                visits_count=index + 1,
                engaged_seconds=(index + 1) * 100,
                click_count=index + 1,
                visits_with_click_count=index + 1,
                active_users_count_daily=1,
            )
            for index in range(21)
        ])
        PageUserDailyMetric.objects.bulk_create([
            PageUserDailyMetric(
                project=self.project,
                date=current_date,
                page_rule_id=dashboard_rule.id,
                product_area_key='core',
                product_area_name='Core',
                company_id=f'company-{index:02d}',
                user_id=f'user-{index:02d}',
                user_name_sample=f'User {index:02d}',
                visits_count=index + 1,
                engaged_seconds=(index + 1) * 100,
                click_count=index + 1,
            )
            for index in range(21)
        ])

        payload = build_page_detail_payload(
            self.project.id,
            str(dashboard_rule.id),
            start_date=current_date,
            end_date=current_date,
        )

        self.assertEqual(len(payload['companies']), 21)
        self.assertEqual(len(payload['champions']), 21)
        self.assertEqual(payload['companies'][0]['company'], 'Company 20')
        self.assertEqual(payload['companies'][-1]['company'], 'Company 00')
        self.assertEqual(payload['champions'][0]['user'], 'User 20')
        self.assertEqual(payload['champions'][-1]['user'], 'User 00')

    def test_build_page_detail_payload_dedupes_related_pages_by_display_name(self):
        current_date = date(2026, 5, 2)
        previous_date = date(2026, 5, 1)
        dashboard_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^app\.example\.com/dashboard$',
            product_area='Core',
            page_name='Dashboard',
            priority=100,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )
        dashboard_variant_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^app\.example\.com/home$',
            product_area='Core',
            page_name='Dashboard',
            priority=90,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )
        my_work_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^app\.example\.com/my-work$',
            product_area='Core',
            page_name='My work',
            priority=80,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )

        for metric_date in (previous_date, current_date):
            ProjectDailyMetric.objects.create(
                project=self.project,
                date=metric_date,
                active_companies_count=10,
                active_users_count=20,
            )

        def create_page_metric(rule, visits, engaged, companies=2, users=3):
            PageDailyMetric.objects.create(
                project=self.project,
                date=current_date,
                page_rule_id=rule.id,
                product_area_key='core',
                product_area_name='Core',
                visits_count=visits,
                engaged_seconds=engaged,
                click_count=visits,
                visits_with_click_count=max(1, visits // 2),
                companies_count_daily=companies,
                users_count_daily=users,
            )

        create_page_metric(dashboard_rule, 10, 600)
        create_page_metric(dashboard_variant_rule, 7, 300)
        create_page_metric(my_work_rule, 4, 120)

        payload = build_page_detail_payload(
            self.project.id,
            str(dashboard_rule.id),
            start_date=current_date,
            end_date=current_date,
        )

        related_page_names = [row['pageName'] for row in payload['relatedPages']]
        dashboard_row = next(row for row in payload['relatedPages'] if row['pageName'] == 'Dashboard')

        self.assertEqual(related_page_names.count('Dashboard'), 1)
        self.assertIn('My work', related_page_names)
        self.assertEqual(dashboard_row['pageId'], str(dashboard_rule.id))
        self.assertEqual(dashboard_row['pageIds'], [str(dashboard_rule.id), str(dashboard_variant_rule.id)])
        self.assertTrue(dashboard_row['isCurrent'])
        self.assertEqual(dashboard_row['visits'], 17)
        self.assertEqual(dashboard_row['engaged'], 900)
        self.assertEqual(dashboard_row['engagedLabel'], '15m 00s')
