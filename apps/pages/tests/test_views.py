import json
import re

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch

from apps.pages import services, user_analytics, user_detail_analytics, views as pages_views
from apps.pages.models import (
    PagesDetailCache,
    PagesOverviewCache,
    PagesScatterTooltipCache,
    ProductArea,
    UsersDetailCache,
    UsersOverviewCache,
)
from apps.projects.models import (
    Project,
    Workspace,
    WorkspaceMemberRole,
    WorkspaceMemberStatus,
    WorkspaceMembership,
)


@override_settings(PAGES_QUEUE_REBUILDS_ON_REQUEST=False)
class PagesOverviewViewTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='pages-view-owner',
            email='pages-view-owner@example.com',
            password='testpass123',
        )
        self.workspace = Workspace.objects.create(
            name='Pages View Workspace',
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
            name='Pages View Project',
            created_by=self.user,
        )
        self.client.force_login(self.user)

    def _embedded_json_payload(self, response, element_id):
        html = response.content.decode()
        match = re.search(
            rf'<script id="{re.escape(element_id)}" type="application/json">(.*?)</script>',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        return json.loads(match.group(1))

    def _project_route(self, route_name, **kwargs):
        return reverse(
            f'w:{route_name}',
            kwargs={'workspace_slug': self.workspace.slug, 'project_id': self.project.id, **kwargs},
        )

    def test_overview_uses_cached_payload(self):
        generated_at = timezone.now()
        PagesOverviewCache.objects.create(
            project=self.project,
            range_key='last_30_days',
            start_date=generated_at.date(),
            end_date=generated_at.date(),
            filters_hash='default',
            payload_json={
                'schema_version': services.OVERVIEW_PAYLOAD_SCHEMA_VERSION,
                'project': {'id': self.project.id, 'name': self.project.name},
                'period': {'range_key': 'last_30_days'},
                'freshness': {'generated_at': generated_at.isoformat(), 'is_stale': False},
                'kpis': [{'label': 'Avg daily adopted pages', 'value': '1.0', 'delta': 'ready', 'delta_value': 1}],
                'change_aware_rows': [],
                'top_pages_by_visits_over_time': {'series': []},
                'top_pages_by_engaged_time_over_time': {'series': []},
                'engaged_time_treemap': {'total_engaged_seconds': 0, 'nodes': []},
                'sankey': {'nodes': [], 'links': []},
                'top_actions_by_page': [],
                'company_engagement_by_product_area': [],
            },
            generated_at=generated_at,
        )

        response = self.client.get(
            reverse('projects:project_pages', kwargs={'project_id': self.project.id}),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Page metrics')
        self.assertContains(response, 'pages-overview-data')
        self.assertContains(response, 'css/pages/overview.css')
        self.assertContains(response, 'echarts/lib/echarts.min.js')
        self.assertContains(response, 'js/pages/django-pages-data.js')
        self.assertContains(response, 'js/pages/pages-analytics.js')
        self.assertContains(response, 'data-pages-view="overview"')
        self.assertContains(response, 'data-overview-title-group')
        self.assertContains(response, 'data-overview-quick-jumper')
        self.assertContains(response, 'data-overview-filters')
        self.assertContains(response, 'Find page')
        self.assertContains(response, 'Search pages')
        self.assertContains(response, 'css/overview-quick-jumper.css')
        self.assertContains(response, 'js/shared/overview-quick-jumper.js')
        self.assertContains(response, f'data-project-id="{self.project.id}"')
        self.assertContains(
            response,
            f'data-pages-detail-base-url="{self._project_route("project_page_detail", page_rule_id="__PAGE_RULE_ID__")}"',
        )
        self.assertNotContains(
            response,
            f'data-pages-detail-base-url="{self._project_route("project_pages")}/"',
        )
        self.assertContains(response, 'Product area summary')
        self.assertContains(response, 'product-area-summary-body')
        self.assertContains(response, 'pages-change-table-body')
        self.assertContains(response, 'data-page-metrics-scroll')
        self.assertContains(response, 'top-pages-visits-time-chart')
        self.assertContains(response, 'engaged-time-treemap-chart')
        self.assertContains(response, 'company-engagement-page-group-grid')
        self.assertContains(response, 'Avg daily adopted pages')
        self.assertContains(response, 'pages-period-selector')
        self.assertContains(response, 'href="?range=last_7_days"')
        self.assertContains(response, 'href="?range=last_30_days"')
        self.assertContains(response, 'href="?range=last_90_days"')
        self.assertContains(response, 'href="?range=last_180_days"')
        self.assertContains(response, 'aria-current="page"')
        self.assertNotContains(response, 'pages-date-range-menu')
        self.assertNotContains(response, 'Last 7 days')
        self.assertNotContains(response, 'Last 30 days')
        self.assertNotContains(response, 'Last 90 days')
        self.assertNotContains(response, 'Last 180 days')
        self.assertNotContains(response, 'This quarter')
        self.assertNotContains(response, 'Custom range')
        self.assertNotContains(response, 'style=')

    def test_overview_embeds_first_table_page_and_table_data_serves_remaining_rows(self):
        generated_at = timezone.now()
        rows = [
            {
                'page_rule_id': str(index),
                'page_name': f'Page {index:02d}',
                'page_group': 'Core',
                'product_area_name': 'Core',
                'companies_count': index + 1,
                'users_count': index + 1,
                'visits_count': index + 1,
                'engaged_seconds': (index + 1) * 60,
            }
            for index in range(12)
        ]
        PagesOverviewCache.objects.create(
            project=self.project,
            range_key='last_30_days',
            start_date=generated_at.date(),
            end_date=generated_at.date(),
            filters_hash='default',
            payload_json={
                'schema_version': services.OVERVIEW_PAYLOAD_SCHEMA_VERSION,
                'project': {'id': self.project.id, 'name': self.project.name},
                'period': {'range_key': 'last_30_days'},
                'freshness': {'generated_at': generated_at.isoformat(), 'is_stale': False},
                'kpis': [{'label': 'Avg daily adopted pages', 'value': '12.0'}],
                'rows': rows,
                'change_aware_rows': rows,
            },
            generated_at=generated_at,
        )

        response = self.client.get(
            reverse('projects:project_pages', kwargs={'project_id': self.project.id}),
            follow=True,
        )
        payload = self._embedded_json_payload(response, 'pages-overview-data')
        table_response = self.client.get(
            reverse('projects:project_pages_table_data', kwargs={'project_id': self.project.id}),
            {'page': 2, 'page_size': 10, 'sort': 'companies', 'direction': 'desc'},
        )
        table_payload = table_response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(payload['change_aware_rows']), 10)
        self.assertEqual(payload['change_aware_rows'][0]['page_name'], 'Page 11')
        self.assertEqual(len(payload['page_selector_rows']), 12)
        self.assertNotIn('rows', payload)
        self.assertNotIn('page_metrics_rows', payload)
        self.assertNotIn('company_engagement_by_product_area', payload)
        self.assertNotIn('rows', payload['tableData']['pageMetrics'])
        self.assertEqual(payload['tableData']['pageMetrics']['pagination']['totalRows'], 12)
        self.assertEqual(table_response.status_code, 200)
        self.assertEqual(table_payload['pagination']['page'], 2)
        self.assertEqual(table_payload['pagination']['totalRows'], 12)
        self.assertEqual([row['page_name'] for row in table_payload['rows']], ['Page 01', 'Page 00'])

    def test_overview_projects_only_visible_top_actions_without_mutating_cache(self):
        generated_at = timezone.now()
        action_clicks = [1, 9, 3, 7, 5, 11, 0]
        top_actions_by_page = [
            {
                'page_key': f'page-{page_index}',
                'page_label': f'Page {page_index}',
                'page_group': 'Core',
                'product_area_key': 'core',
                'product_area_name': 'Core',
                'visits_count': 100 - page_index,
                'actions': [
                    {
                        'element_key': f'Action {clicks}',
                        'clicks_count': clicks,
                    }
                    for clicks in action_clicks
                ],
            }
            for page_index in range(10)
        ]
        top_actions_by_page_group = [
            {
                'page_group': f'Page {page_index}',
                'page_name': f'Page {page_index}',
                'product_area_key': 'core',
                'product_area_name': 'Core',
                'page_rule_id': str(page_index),
                'actions': [
                    {
                        'element_key': f'Action {clicks}',
                        'clicks': clicks,
                    }
                    for clicks in action_clicks
                ],
            }
            for page_index in range(10)
        ]
        cache = PagesOverviewCache.objects.create(
            project=self.project,
            range_key='last_30_days',
            start_date=generated_at.date(),
            end_date=generated_at.date(),
            filters_hash='default',
            payload_json={
                'schema_version': services.OVERVIEW_PAYLOAD_SCHEMA_VERSION,
                'project': {'id': self.project.id, 'name': self.project.name},
                'period': {'range_key': 'last_30_days'},
                'freshness': {'generated_at': generated_at.isoformat(), 'is_stale': False},
                'kpis': [{'label': 'Avg daily adopted pages', 'value': '1.0'}],
                'rows': [],
                'change_aware_rows': [],
                'top_actions_by_page': top_actions_by_page,
                'top_actions_by_page_group': top_actions_by_page_group,
                'company_engagement_by_product_area': [
                    {'product_area_name': f'Area {index}', 'points': []}
                    for index in range(10)
                ],
                'company_engagement_by_page_group': [
                    {'page_group': f'Page {index}', 'points': []}
                    for index in range(10)
                ],
            },
            generated_at=generated_at,
        )

        response = self.client.get(
            reverse('projects:project_pages', kwargs={'project_id': self.project.id}),
            follow=True,
        )
        payload = self._embedded_json_payload(response, 'pages-overview-data')

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('top_actions_by_page', payload)
        self.assertNotIn('company_engagement_by_product_area', payload)
        self.assertEqual(len(payload['company_engagement_by_page_group']), 8)
        self.assertEqual(
            [group['page_name'] for group in payload['top_actions_by_page_group']],
            [f'Page {index}' for index in range(8)],
        )
        self.assertTrue(
            all(
                [action['clicks'] for action in group['actions']]
                == [11, 9, 7, 5, 3]
                for group in payload['top_actions_by_page_group']
            )
        )

        cache.refresh_from_db()
        self.assertEqual(len(cache.payload_json['top_actions_by_page']), 10)
        self.assertEqual(len(cache.payload_json['top_actions_by_page_group']), 10)
        self.assertEqual(
            [
                action['clicks']
                for action in cache.payload_json['top_actions_by_page_group'][0]['actions']
            ],
            action_clicks,
        )

    def test_overview_projects_only_the_visible_acyclic_sankey(self):
        nodes = [
            {'name': f'Node {index}', 'label': f'Node {index}'}
            for index in range(15)
        ]
        links = [
            {
                'source': f'Node {index}',
                'target': f'Node {index + 1}',
                'value': 100 - index,
            }
            for index in range(14)
        ]
        links.insert(
            1,
            {'source': 'Node 1', 'target': 'Node 0', 'value': 99.5},
        )
        links.extend(
            [
                {'source': 'Node 0', 'target': 'Node 2', 'value': 90.5},
                {'source': 'Node 0', 'target': 'Node 3', 'value': 90.4},
                {'source': 'Node 1', 'target': 'Node 3', 'value': 90.3},
            ],
        )
        sankey = {'nodes': nodes, 'links': links}

        projected = pages_views._project_sankey_for_client(sankey)

        self.assertEqual(len(projected['links']), 12)
        self.assertEqual(len(projected['nodes']), 10)
        self.assertNotIn(
            ('Node 1', 'Node 0'),
            {
                (link['source'], link['target'])
                for link in projected['links']
            },
        )
        self.assertEqual(len(sankey['links']), 18)
        self.assertEqual(len(sankey['nodes']), 15)

    def test_page_selector_rows_preserve_backend_identity_keys(self):
        rows = [
            {
                'page_rule_id': '101',
                'page_name': 'Accounts',
                'page_group': 'Core',
                'product_area_key': 'core-v2',
                'page_display_key': 'core-v2::accounts',
                'companies_count': 10,
            },
        ]

        selector_rows = pages_views._page_selector_rows(rows)

        self.assertEqual(
            selector_rows,
            [
                {
                    'page_rule_id': '101',
                    'pageRuleId': '101',
                    'page_name': 'Accounts',
                    'pageName': 'Accounts',
                    'displayName': 'Accounts',
                    'page_group': 'Core',
                    'productAreaName': 'Core',
                    'product_area_key': 'core-v2',
                    'productAreaKey': 'core-v2',
                    'page_display_key': 'core-v2::accounts',
                    'pageDisplayKey': 'core-v2::accounts',
                    'companies_count': 10,
                    'visits_count': 0,
                    'engaged_seconds': 0,
                },
            ],
        )

    def test_overview_page_metrics_uses_display_rows_before_pagination(self):
        generated_at = timezone.now()
        raw_rows = [
            {
                'page_rule_id': '101',
                'page_name': 'All companies',
                'page_group': 'CRM',
                'product_area_name': 'CRM',
                'companies_count': 1,
                'visits_count': 2,
            },
            {
                'page_rule_id': '102',
                'page_name': 'All companies',
                'page_group': 'CRM',
                'product_area_name': 'CRM',
                'companies_count': 1,
                'visits_count': 3,
            },
            {
                'page_rule_id': '103',
                'page_name': 'Account settings',
                'page_group': 'CRM',
                'product_area_name': 'CRM',
                'companies_count': 1,
                'visits_count': 1,
            },
        ]
        display_rows = [
            {
                'page_rule_id': '102',
                'page_rule_ids': ['101', '102'],
                'page_name': 'All companies',
                'page_group': 'CRM',
                'product_area_name': 'CRM',
                'companies_count': 1,
                'visits_count': 5,
            },
            raw_rows[2],
        ]
        PagesOverviewCache.objects.create(
            project=self.project,
            range_key='last_30_days',
            start_date=generated_at.date(),
            end_date=generated_at.date(),
            filters_hash='default',
            payload_json={
                'schema_version': services.OVERVIEW_PAYLOAD_SCHEMA_VERSION,
                'project': {'id': self.project.id, 'name': self.project.name},
                'period': {'range_key': 'last_30_days'},
                'rows': raw_rows,
                'change_aware_rows': raw_rows,
                'page_metrics_rows': display_rows,
            },
            generated_at=generated_at,
        )

        response = self.client.get(
            reverse('projects:project_pages', kwargs={'project_id': self.project.id}),
            follow=True,
        )
        embedded = self._embedded_json_payload(response, 'pages-overview-data')
        table_response = self.client.get(
            reverse('projects:project_pages_table_data', kwargs={'project_id': self.project.id}),
            {'page': 1, 'page_size': 10, 'sort': 'page', 'direction': 'asc'},
        )
        table_payload = table_response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['page_name'] for row in embedded['change_aware_rows']].count('All companies'), 1)
        self.assertEqual(embedded['tableData']['pageMetrics']['pagination']['totalRows'], 2)
        self.assertEqual(table_response.status_code, 200)
        self.assertEqual(table_payload['pagination']['totalRows'], 2)
        self.assertEqual(
            [row['page_name'] for row in table_payload['rows']],
            ['Account settings', 'All companies'],
        )
        all_companies = next(row for row in table_payload['rows'] if row['page_name'] == 'All companies')
        self.assertEqual(all_companies['page_rule_id'], '102')
        self.assertEqual(all_companies['page_rule_ids'], ['101', '102'])
        self.assertEqual(all_companies['visits_count'], 5)

    def test_overview_missing_cache_is_fast_empty_state(self):
        response = self.client.get(
            reverse('projects:project_pages', kwargs={'project_id': self.project.id}),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Pages')
        self.assertContains(response, 'No data were found in the last 30 complete days.')
        self.assertContains(
            response,
            'Recently collected events may take a little time to appear while we prepare your analytics.',
        )
        self.assertNotContains(response, 'pages-overview-data')
        self.assertNotContains(response, 'js/pages/pages-analytics.js')
        self.assertNotContains(response, 'style=')

    def test_overview_product_area_filter_uses_query_param(self):
        generated_at = timezone.now()
        PagesOverviewCache.objects.create(
            project=self.project,
            range_key='last_30_days',
            start_date=generated_at.date(),
            end_date=generated_at.date(),
            filters_hash='default',
            payload_json={
                'schema_version': services.OVERVIEW_PAYLOAD_SCHEMA_VERSION,
                'project': {
                    'id': self.project.id,
                    'name': self.project.name,
                    'active_companies_total': 10,
                    'active_users_total': 20,
                },
                'period': {'range_key': 'last_30_days'},
                'freshness': {'generated_at': generated_at.isoformat(), 'is_stale': False},
                'kpis': [{'label': 'Avg daily adopted pages', 'value': '2.0', 'delta': 'ready', 'delta_value': 1}],
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
                        'visits_count': 12,
                        'engaged_seconds': 600,
                        'companies_change_pct': 66.7,
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
                        'visits_count': 30,
                        'engaged_seconds': 1200,
                        'companies_change_pct': 20,
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
                        'visits_count': 12,
                        'engaged_seconds': 600,
                        'companies_change_pct': 66.7,
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
                        'visits_count': 30,
                        'engaged_seconds': 1200,
                        'companies_change_pct': 20,
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
                'top_pages_by_engaged_time_over_time': {'granularity': 'day', 'labels': [], 'series': []},
                'engaged_time_treemap': {'total_engaged_seconds': 0, 'nodes': []},
                'sankey': {'nodes': [], 'links': []},
                'top_actions_by_page': [
                    {
                        'page_key': 'billing::invoices',
                        'page_label': 'Invoices',
                        'page_group': 'Billing',
                        'product_area_key': 'billing',
                        'product_area_name': 'Billing',
                        'visits_count': 12,
                        'actions': [
                            {
                                'element_key': f'Billing action {clicks}',
                                'clicks_count': clicks,
                            }
                            for clicks in (1, 6, 2, 5, 3, 4)
                        ],
                    },
                    {
                        'page_key': 'core::dashboard',
                        'page_label': 'Dashboard',
                        'page_group': 'Core',
                        'product_area_key': 'core',
                        'product_area_name': 'Core',
                        'visits_count': 30,
                        'actions': [
                            {
                                'element_key': 'Core action',
                                'clicks_count': 10,
                            }
                        ],
                    },
                ],
                'company_engagement_by_product_area': [],
            },
            generated_at=generated_at,
        )

        response = self.client.get(
            reverse('projects:project_pages', kwargs={'project_id': self.project.id}),
            {'product_area': 'billing'},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'product-area-filter')
        self.assertContains(response, 'data-has-selection="true"')
        self.assertContains(response, 'href="?range=last_7_days&amp;product_area=billing"')
        self.assertContains(response, 'href="?range=last_30_days&amp;product_area=billing"')
        html = response.content.decode()
        self.assertIn('value="billing"', html)
        self.assertIn('checked', html)
        payload = self._embedded_json_payload(response, 'pages-overview-data')
        self.assertEqual([row['page_name'] for row in payload['change_aware_rows']], ['Invoices'])
        self.assertEqual([row['product_area_name'] for row in payload['product_area_summary']], ['Billing'])
        self.assertEqual([row['page_name'] for row in payload['top_pages_by_visits_over_time']['series']], ['Invoices'])
        self.assertEqual(payload['kpis'][0]['label'], 'Avg daily adopted pages')
        self.assertEqual(payload['kpis'][0]['value'], '1.0')
        self.assertEqual(payload['kpis'][0]['trend_values'], [1, 1])
        self.assertEqual(payload['kpis'][1]['label'], 'Avg daily adoption')
        self.assertEqual(payload['kpis'][1]['trend_values'], [20.0, 40.0])
        self.assertEqual(payload['kpis'][2]['delta'], '5m 00s avg/day')
        self.assertEqual(payload['kpis'][2]['trend_values'], [120.0, 480.0])
        self.assertEqual(payload['kpis'][3]['trend_values'], [3, 5])
        self.assertEqual(payload['kpis'][3]['trend_scope'], 'period_comparison')
        self.assertEqual(
            payload['kpis'][3]['trend_delta_value'],
            payload['kpis'][3]['delta_value'],
        )
        self.assertNotIn('kpi_daily_rows', payload)
        self.assertNotIn('daily_kpi_trends', payload['change_aware_rows'][0])
        self.assertNotIn('top_actions_by_page', payload)
        self.assertEqual(
            [group['page_name'] for group in payload['top_actions_by_page_group']],
            ['Invoices'],
        )
        self.assertEqual(
            [
                action['clicks']
                for action in payload['top_actions_by_page_group'][0]['actions']
            ],
            [6, 5, 4, 3, 2],
        )

        multi_response = self.client.get(
            reverse('projects:project_pages', kwargs={'project_id': self.project.id}),
            {'product_area': ['billing', 'core']},
            follow=True,
        )

        self.assertEqual(multi_response.status_code, 200)
        self.assertContains(multi_response, 'Billing, Core')
        self.assertNotContains(multi_response, '2 product areas')
        self.assertContains(
            multi_response,
            'href="?range=last_7_days&amp;product_area=billing&amp;product_area=core"',
        )

    def test_users_overview_uses_cached_payload(self):
        generated_at = timezone.now()
        UsersOverviewCache.objects.create(
            project=self.project,
            range_key='last_30_days',
            start_date=generated_at.date(),
            end_date=generated_at.date(),
            filters_hash='default',
            payload_json={
                'schema_version': user_analytics.USERS_PAYLOAD_SCHEMA_VERSION,
                'project': {'id': self.project.id, 'name': self.project.name},
                'period': {'range_key': 'last_30_days', 'days': 30},
                'kpis': [{'key': 'activeUsers', 'label': 'Active users', 'value': 1}],
                'users': [],
                'scatter': [],
            },
            generated_at=generated_at,
        )

        response = self.client.get(
            reverse('projects:project_users', kwargs={'project_id': self.project.id}),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Users')
        self.assertNotContains(
            response,
            'User-level adoption, engagement, and product usage across B2B accounts.',
        )
        self.assertContains(response, 'users-overview-data')
        self.assertContains(response, 'css/users/overview.css')
        self.assertContains(response, 'js/users/django-users-data.js')
        self.assertContains(response, 'js/users/users-analytics.js')
        self.assertContains(response, 'data-users-view="overview"')
        self.assertContains(response, 'data-overview-title-group')
        self.assertContains(response, 'data-overview-quick-jumper')
        self.assertContains(response, 'data-overview-filters')
        self.assertContains(response, 'Find user')
        self.assertContains(response, 'Search users')
        self.assertContains(response, 'css/overview-quick-jumper.css')
        self.assertContains(response, 'js/shared/overview-quick-jumper.js')
        self.assertContains(response, 'data-user-detail-base-url')
        self.assertContains(response, 'Engagement distribution')
        self.assertContains(response, 'User consistency vs intensity')
        self.assertContains(response, 'Users list')
        self.assertContains(response, 'Return frequency and session depth are calculated from distinct sessions in the selected period.')
        # The legacy company and feature dropdowns are gone; the control ids
        # are what says so. "All companies" is no longer evidence either way,
        # because the Companies scope selector renders it as its own label.
        self.assertNotContains(response, 'users-company-filter')
        self.assertNotContains(response, 'users-feature-filter')
        self.assertNotContains(response, 'All pages')

    def test_user_detail_uses_cached_detail_payload(self):
        generated_at = timezone.now()
        UsersDetailCache.objects.create(
            project=self.project,
            range_key='last_30_days',
            start_date=generated_at.date(),
            end_date=generated_at.date(),
            filters_hash='default',
            payload_json={
                'schema_version': user_detail_analytics.USER_DETAILS_PAYLOAD_SCHEMA_VERSION,
                'project': {'id': self.project.id, 'name': self.project.name},
                'period': {'range_key': 'last_30_days', 'days': 30},
                'periodDays': 30,
                'selectedUser': {
                    'id': 'user-1@example.com',
                    'name': 'Ada Lovelace',
                    'email': 'user-1@example.com',
                    'companyId': 'acme',
                    'companyName': 'Acme Corp',
                    'status': 'healthy',
                    'firstSeenAt': generated_at.isoformat(),
                    'lastActiveAt': generated_at.isoformat(),
                },
                'users': [
                    {
                        'id': 'other-user@example.com',
                        'name': 'Other User',
                        'email': 'other-user@example.com',
                        'companyId': 'acme',
                        'companyName': 'Acme Corp',
                    }
                ],
                'productAreas': [],
                'metricCards': [{'key': 'engaged', 'label': 'Engaged time', 'currentValue': 120}],
                'userMetrics': {
                    'engagedSeconds': 120,
                    'visits': 3,
                    'activeDays': 1,
                    'pagesUsed': 1,
                    'visitsWithClick': 1,
                },
                'dailyUsage': [{'date': generated_at.date().isoformat(), 'visits': 3, 'engagedSeconds': 120}],
                'productAreaMix': [],
                'peerComparison': [],
                'companyPeerComparison': [],
                'pagesUsed': [{'pageName': 'Dashboard', 'visits': 3, 'engagedSeconds': 120}],
                'underusedPages': [],
                'recommendedActions': [],
                'emptyState': {'peers': 'No peers', 'pages': 'No pages', 'actions': 'No actions'},
            },
            generated_at=generated_at,
            user_id='user-1@example.com',
        )

        response = self.client.get(
            reverse('projects:project_user_detail', kwargs={'project_id': self.project.id, 'user_id': 'user-1@example.com'}),
            {'range': 'last_30_days'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'user-details-data')
        self.assertContains(response, 'css/users/detail.css')
        self.assertContains(response, 'js/users/django-user-details-data.js')
        self.assertContains(response, 'js/users/user-detail.js')
        self.assertContains(response, 'User metric dynamics')
        self.assertContains(response, 'Daily activity by product area')
        payload = self._embedded_json_payload(response, 'user-details-data')
        self.assertEqual(payload['selectedUser']['name'], 'Ada Lovelace')
        self.assertEqual(payload['urls']['usersOverviewUrl'], self._project_route('project_users'))
        self.assertNotIn('users', payload)

    def test_user_detail_embeds_first_pages_used_page_and_table_data_serves_remaining_rows(self):
        generated_at = timezone.now()
        pages_used = [
            {
                'pageRuleId': str(index),
                'pageName': f'Page {index:02d}',
                'productAreaId': 'core',
                'productArea': 'Core',
                'productAreaName': 'Core',
                'visits': index + 1,
                'shareOfUserTimePct': index,
                'engagedSeconds': (index + 1) * 60,
                'avgVisitSeconds': index + 1,
                'interactionPct': index,
                'peerUsagePct': index,
                'lastUsedAt': generated_at.date().isoformat(),
            }
            for index in range(18)
        ]
        UsersDetailCache.objects.create(
            project=self.project,
            range_key='last_30_days',
            start_date=generated_at.date(),
            end_date=generated_at.date(),
            filters_hash='default',
            user_id='user-1@example.com',
            payload_json={
                'schema_version': user_detail_analytics.USER_DETAILS_PAYLOAD_SCHEMA_VERSION,
                'project': {'id': self.project.id, 'name': self.project.name},
                'period': {'range_key': 'last_30_days', 'days': 30},
                'periodDays': 30,
                'selectedUser': {
                    'id': 'user-1@example.com',
                    'name': 'Ada Lovelace',
                    'email': 'user-1@example.com',
                    'companyId': 'acme',
                    'companyName': 'Acme Corp',
                    'status': 'healthy',
                },
                'users': [],
                'productAreas': [{'id': 'core', 'name': 'Core', 'color': '#4269D0'}],
                'metricCards': [{'key': 'engaged', 'label': 'Engaged time', 'currentValue': 120}],
                'userMetrics': {'engagedSeconds': 120, 'visits': 3, 'activeDays': 1, 'pagesUsed': 18},
                'dailyUsage': [{'date': generated_at.date().isoformat(), 'visits': 3, 'engagedSeconds': 120}],
                'productAreaMix': [],
                'peerComparison': [],
                'companyPeerComparison': [],
                'pagesUsed': pages_used,
                'underusedPages': [],
                'recommendedActions': [],
                'emptyState': {'peers': 'No peers', 'pages': 'No pages', 'actions': 'No actions'},
            },
            generated_at=generated_at,
        )

        response = self.client.get(
            reverse('projects:project_user_detail', kwargs={'project_id': self.project.id, 'user_id': 'user-1@example.com'}),
            {'range': 'last_30_days'},
        )
        payload = self._embedded_json_payload(response, 'user-details-data')
        table_response = self.client.get(
            reverse('projects:project_user_detail_table_data', kwargs={'project_id': self.project.id, 'user_id': 'user-1@example.com'}),
            {'table': 'pagesUsed', 'page': 2, 'page_size': 15, 'sort': 'engagedSeconds', 'direction': 'desc'},
        )
        table_payload = table_response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(payload['pagesUsed']), 15)
        self.assertEqual(payload['pagesUsed'][0]['pageName'], 'Page 17')
        self.assertEqual(payload['tableData']['pagesUsed']['pagination']['totalRows'], 18)
        self.assertEqual(table_response.status_code, 200)
        self.assertEqual(table_payload['pagination']['page'], 2)
        self.assertEqual(table_payload['pagination']['totalRows'], 18)
        self.assertEqual([row['pageName'] for row in table_payload['rows']], ['Page 02', 'Page 01', 'Page 00'])

    def test_users_overview_embeds_compact_scatter_and_first_table_page(self):
        generated_at = timezone.now()
        users = [
            {
                'id': f'user-{index}@example.com',
                'userId': f'user-{index}@example.com',
                'name': f'User {index}',
                'email': f'user-{index}@example.com',
                'company': 'Acme Corp',
                'status': 'Healthy',
                'identified': True,
                'engagedSeconds': 120 - index,
                'visitsCount': 7,
                'avgVisitSeconds': 17,
                'pageGroups': [{
                    'key': 'core',
                    'name': 'Core product',
                    'productArea': 'Core product',
                    'productAreaId': 'core',
                    'color': '#4269d0',
                    'productAreaColor': '#4269d0',
                    'product_area_color': '#4269d0',
                    'engagedSeconds': 120,
                    'visits': 7,
                    'clicks': 3,
                }],
                'topFeatures': [{
                    'feature': 'Dashboard',
                    'productArea': 'Core product',
                    'engagedSeconds': 120,
                    'visits': 7,
                    'clicks': 3,
                }],
            }
            for index in range(user_analytics.SCATTER_VISIBLE_LIMIT + 5)
        ]
        UsersOverviewCache.objects.create(
            project=self.project,
            range_key='last_30_days',
            start_date=generated_at.date(),
            end_date=generated_at.date(),
            filters_hash='default',
            payload_json={
                'schema_version': user_analytics.USERS_PAYLOAD_SCHEMA_VERSION,
                'project': {'id': self.project.id, 'name': self.project.name},
                'period': {'range_key': 'last_30_days', 'days': 30},
                'kpis': [{'key': 'activeUsers', 'label': 'Active users', 'value': len(users)}],
                'users': users,
                'scatter': users[:user_analytics.SCATTER_VISIBLE_LIMIT],
                'scatterMeta': {
                    'visibleLimit': user_analytics.SCATTER_VISIBLE_LIMIT,
                    'totalUsers': len(users),
                    'shownUsers': user_analytics.SCATTER_VISIBLE_LIMIT,
                    'isLimited': True,
                },
            },
            generated_at=generated_at,
        )

        response = self.client.get(
            reverse('projects:project_users', kwargs={'project_id': self.project.id}),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        payload = self._embedded_json_payload(response, 'users-overview-data')
        self.assertEqual(len(payload['users']), user_analytics.USERS_TABLE_PAGE_SIZE)
        self.assertEqual(len(payload['scatter']), user_analytics.SCATTER_VISIBLE_LIMIT)
        self.assertFalse(payload['usersDeferred']['isPartial'])
        self.assertEqual(payload['usersDeferred']['initialScatter'], user_analytics.SCATTER_VISIBLE_LIMIT)
        self.assertEqual(payload['usersDeferred']['totalUsers'], len(users))
        self.assertEqual(payload['tableData']['users']['pagination']['totalRows'], len(users))
        self.assertContains(response, 'user-19@example.com')
        self.assertNotIn('user-20@example.com', [row['email'] for row in payload['users']])
        self.assertNotIn('email', payload['scatter'][0])
        self.assertEqual(
            payload['scatter'][0]['pageGroups'][0],
            {
                'name': 'Core product',
                'color': '#4269d0',
                'engagedSeconds': 120,
                'visits': 7,
                'clicks': 3,
            },
        )
        self.assertContains(response, self._project_route('project_users_data'))
        self.assertEqual(response.context['users_table_url'], self._project_route('project_users_table_data'))

        table_response = self.client.get(
            reverse('projects:project_users_table_data', kwargs={'project_id': self.project.id}),
            {
                'page': 2,
                'page_size': user_analytics.USERS_TABLE_PAGE_SIZE,
                'sort': 'engagedSeconds',
                'direction': 'desc',
            },
        )
        table_payload = table_response.json()

        self.assertEqual(table_response.status_code, 200)
        self.assertEqual(table_payload['pagination']['page'], 2)
        self.assertEqual(table_payload['pagination']['totalRows'], len(users))
        self.assertEqual(table_payload['rows'][0]['email'], 'user-20@example.com')
        self.assertEqual(table_payload['rows'][-1]['email'], 'user-39@example.com')
        self.assertEqual(table_payload['filterOptions']['companies'], ['Acme Corp'])
        self.assertEqual(table_payload['filterOptions']['statuses'], ['Healthy'])

        filtered_response = self.client.get(
            reverse('projects:project_users_table_data', kwargs={'project_id': self.project.id}),
            {
                'q': 'user-304@example.com',
                'company': 'Acme Corp',
                'status': 'Healthy',
            },
        )
        self.assertEqual(filtered_response.status_code, 200)
        self.assertEqual(filtered_response.json()['pagination']['totalRows'], 1)
        self.assertEqual(filtered_response.json()['rows'][0]['email'], 'user-304@example.com')

        data_response = self.client.get(reverse('projects:project_users_data', kwargs={'project_id': self.project.id}))

        self.assertEqual(data_response.status_code, 200)
        deferred_payload = data_response.json()
        self.assertNotIn('users', deferred_payload)
        self.assertEqual(len(deferred_payload['scatter']), user_analytics.SCATTER_VISIBLE_LIMIT)
        self.assertNotIn('email', deferred_payload['scatter'][0])
        self.assertFalse(deferred_payload['usersDeferred']['isPartial'])
        self.assertEqual(deferred_payload['usersDeferred']['totalUsers'], len(users))

    def test_users_overview_missing_cache_is_fast_empty_state(self):
        response = self.client.get(
            reverse('projects:project_users', kwargs={'project_id': self.project.id}),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Users')
        self.assertContains(response, 'No data were found in the last 30 complete days.')
        self.assertNotContains(response, 'users-overview-data')
        self.assertNotContains(response, 'js/users/users-analytics.js')

    @override_settings(
        COMPANIES_QUEUE_REBUILDS_ON_REQUEST=True,
        USERS_QUEUE_REBUILDS_ON_REQUEST=True,
    )
    @patch('apps.projects.views.threading.Thread')
    @patch('apps.pages.tasks.build_users_overview_cache_task.apply_async')
    @patch('apps.pages.tasks.build_companies_overview_cache_task.apply_async')
    def test_overview_cache_misses_do_not_queue_request_rebuilds(
        self,
        companies_apply_async,
        users_apply_async,
        thread,
    ):
        companies_response = self.client.get(
            reverse('projects:project_companies', kwargs={'project_id': self.project.id}),
            follow=True,
        )
        companies_table_response = self.client.get(
            reverse('projects:project_companies_table_data', kwargs={'project_id': self.project.id})
        )
        companies_options_response = self.client.get(
            reverse('projects:project_company_options', kwargs={'project_id': self.project.id})
        )
        users_response = self.client.get(
            reverse('projects:project_users', kwargs={'project_id': self.project.id}),
            follow=True,
        )
        users_data_response = self.client.get(
            reverse('projects:project_users_data', kwargs={'project_id': self.project.id})
        )
        users_options_response = self.client.get(
            reverse('projects:project_user_options', kwargs={'project_id': self.project.id})
        )

        self.assertEqual(companies_response.status_code, 200)
        self.assertEqual(companies_table_response.status_code, 202)
        self.assertFalse(companies_table_response.json()['queued'])
        self.assertEqual(companies_options_response.status_code, 202)
        self.assertFalse(companies_options_response.json()['queued'])
        self.assertEqual(users_response.status_code, 200)
        self.assertEqual(users_data_response.status_code, 202)
        self.assertFalse(users_data_response.json()['queued'])
        # The user selector gates only filtered variants: without an active
        # filter it answers from its own query, which reports an empty project
        # as an ordinary empty result rather than a pending one.
        self.assertEqual(users_options_response.status_code, 200)
        self.assertEqual(users_options_response.json()['results'], [])
        thread.assert_not_called()
        companies_apply_async.assert_not_called()
        users_apply_async.assert_not_called()

    def test_users_overview_stale_schema_is_not_served(self):
        generated_at = timezone.now()
        UsersOverviewCache.objects.create(
            project=self.project,
            range_key='last_30_days',
            start_date=generated_at.date(),
            end_date=generated_at.date(),
            filters_hash='default',
            payload_json={
                'schema_version': user_analytics.USERS_PAYLOAD_SCHEMA_VERSION - 1,
                'project': {'id': self.project.id, 'name': self.project.name},
                'period': {'range_key': 'last_30_days', 'days': 30},
                'kpis': [{'key': 'activeUsers', 'label': 'Active users', 'value': 1}],
                'users': [
                    {
                        'id': 'stale@example.com',
                        'name': 'Stale Cached User',
                        'email': 'stale@example.com',
                        'company': 'Acme Corp',
                        'status': 'Healthy',
                        'identified': True,
                        'engagedSeconds': 120,
                        'visitsCount': 7,
                        'avgVisitSeconds': 17,
                    },
                ],
                'scatter': [],
            },
            generated_at=generated_at,
        )

        response = self.client.get(
            reverse('projects:project_users', kwargs={'project_id': self.project.id}),
            follow=True,
        )

        # A payload written by an older builder is not safe to render, so the
        # page shows its pending state instead of the row it holds. The
        # Companies surface treats a superseded schema the same way.
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Stale Cached User')

    def test_detail_page_embeds_cached_payload(self):
        generated_at = timezone.now()
        ProductArea.objects.create(
            project=self.project,
            name='Administration',
            slug='administration',
            color='#A1B2C3',
        )
        PagesOverviewCache.objects.create(
            project=self.project,
            range_key='last_30_days',
            start_date=generated_at.date(),
            end_date=generated_at.date(),
            filters_hash='default',
            payload_json={
                'schema_version': services.OVERVIEW_PAYLOAD_SCHEMA_VERSION,
                'project': {
                    'id': self.project.id,
                    'name': self.project.name,
                    'active_companies_total': 2,
                    'active_users_total': 5,
                },
                'change_aware_rows': [
                    {
                        'page_rule_id': '123',
                        'page_name': 'Billing',
                        'page_group': 'Administration',
                        'companies_count': 2,
                        'visits_count': 10,
                        'engaged_seconds': 360,
                    },
                    {
                        'page_rule_id': '456',
                        'page_name': 'Settings',
                        'page_group': 'Administration',
                        'companies_count': 1,
                        'visits_count': 4,
                        'engaged_seconds': 120,
                    },
                ],
            },
            generated_at=generated_at,
        )
        PagesDetailCache.objects.create(
            project=self.project,
            range_key='last_30_days',
            page_rule_id='123',
            start_date=generated_at.date(),
            end_date=generated_at.date(),
            filters_hash='default',
            payload_json={
                'schema_version': services.OVERVIEW_PAYLOAD_SCHEMA_VERSION,
                'project': {'id': self.project.id, 'name': self.project.name},
                'page': {
                    'id': '123',
                    'displayName': 'Billing',
                    'productAreaId': 'administration',
                    'productAreaName': 'Administration',
                },
                'period': {'range_key': 'last_30_days', 'days': 30},
                'metrics': [{'key': 'visits', 'label': 'Visits', 'currentValue': 10}],
                'combinedInteractionClicksMetric': {},
                'relatedPages': [],
                'champions': [],
                'companies': [],
                'actions': [],
                'flow': {'sankey': {'nodes': [], 'links': []}},
            },
            generated_at=generated_at,
        )

        response = self.client.get(
            reverse(
                'projects:project_page_detail',
                kwargs={'project_id': self.project.id, 'page_rule_id': '123'},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Page metric dynamics')
        self.assertContains(response, 'pages-detail-data')
        self.assertContains(response, 'js/pages/page-details-helpers.js')
        self.assertContains(response, 'js/shared/product-area-colors.js')
        self.assertContains(response, 'data-pages-view="detail"')
        self.assertContains(response, 'data-page-rule-id="123"')
        self.assertContains(
            response,
            f'data-pages-detail-base-url="{self._project_route("project_page_detail", page_rule_id="__PAGE_RULE_ID__")}"',
        )
        self.assertNotContains(
            response,
            f'data-pages-detail-base-url="{self._project_route("project_pages")}/"',
        )
        self.assertContains(response, '"selected_period_days":30')
        self.assertContains(response, '"period_payloads":{}')
        self.assertContains(response, '"page_selector_rows":[{')
        self.assertContains(response, '"page_name":"Billing"')
        self.assertContains(response, '"page_name":"Settings"')
        embedded_payload = self._embedded_json_payload(response, 'pages-detail-data')['payload']
        self.assertEqual(embedded_payload['page']['productAreaColor'], '#A1B2C3')

    def test_detail_page_embeds_first_table_pages_and_table_data_serves_remaining_rows(self):
        generated_at = timezone.now()
        companies = [
            {
                'company': f'Company {index:02d}',
                'users': index + 1,
                'pagePenetration': index + 1,
                'visits': index + 1,
                'engagedSeconds': (index + 1) * 60,
                'interaction': index,
            }
            for index in range(21)
        ]
        champions = [
            {
                'user': f'User {index:02d}',
                'company': f'Company {index:02d}',
                'visits': index + 1,
                'engagedSeconds': (index + 1) * 60,
                'clicks': index + 1,
            }
            for index in range(21)
        ]
        PagesOverviewCache.objects.create(
            project=self.project,
            range_key='last_30_days',
            start_date=generated_at.date(),
            end_date=generated_at.date(),
            filters_hash='default',
            payload_json={
                'schema_version': services.OVERVIEW_PAYLOAD_SCHEMA_VERSION,
                'project': {'id': self.project.id, 'name': self.project.name},
                'change_aware_rows': [{'page_rule_id': '123', 'page_name': 'Billing', 'companies_count': 1}],
            },
            generated_at=generated_at,
        )
        PagesDetailCache.objects.create(
            project=self.project,
            range_key='last_30_days',
            page_rule_id='123',
            start_date=generated_at.date(),
            end_date=generated_at.date(),
            filters_hash='default',
            payload_json={
                'schema_version': services.OVERVIEW_PAYLOAD_SCHEMA_VERSION,
                'project': {'id': self.project.id, 'name': self.project.name},
                'page': {'id': '123', 'displayName': 'Billing'},
                'period': {'range_key': 'last_30_days', 'days': 30},
                'metrics': [{'key': 'visits', 'label': 'Visits', 'currentValue': 1}],
                'combinedInteractionClicksMetric': {},
                'relatedPages': [],
                'champions': champions,
                'companies': companies,
                'actions': [],
                'flow': {'sankey': {'nodes': [], 'links': []}},
            },
            generated_at=generated_at,
        )

        response = self.client.get(
            reverse('projects:project_page_detail', kwargs={'project_id': self.project.id, 'page_rule_id': '123'})
        )
        bundle = self._embedded_json_payload(response, 'pages-detail-data')
        payload = bundle['payload']
        companies_response = self.client.get(
            reverse('projects:project_page_detail_table_data', kwargs={'project_id': self.project.id, 'page_rule_id': '123'}),
            {'table': 'companies', 'page': 2, 'page_size': 20, 'sort': 'engaged', 'direction': 'desc'},
        )
        champions_response = self.client.get(
            reverse('projects:project_page_detail_table_data', kwargs={'project_id': self.project.id, 'page_rule_id': '123'}),
            {'table': 'champions', 'page': 2, 'page_size': 20, 'sort': 'engaged', 'direction': 'desc'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(payload['companies']), 20)
        self.assertEqual(len(payload['champions']), 20)
        self.assertEqual(payload['tableData']['companies']['pagination']['totalRows'], 21)
        self.assertEqual(payload['tableData']['champions']['pagination']['totalRows'], 21)
        self.assertEqual(companies_response.status_code, 200)
        self.assertEqual(champions_response.status_code, 200)
        self.assertEqual([row['company'] for row in companies_response.json()['rows']], ['Company 00'])
        self.assertEqual([row['user'] for row in champions_response.json()['rows']], ['User 00'])

    @patch('apps.pages.views.services.build_page_detail_payload')
    def test_detail_page_missing_cache_does_not_build_payload_synchronously(self, mock_build_detail_payload):
        response = self.client.get(
            reverse(
                'projects:project_page_detail',
                kwargs={'project_id': self.project.id, 'page_rule_id': 'missing'},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '"payload":null')
        mock_build_detail_payload.assert_not_called()

    def test_overview_current_schema_payload_is_script_escaped(self):
        generated_at = timezone.now()
        PagesOverviewCache.objects.create(
            project=self.project,
            range_key='last_30_days',
            start_date=generated_at.date(),
            end_date=generated_at.date(),
            filters_hash='default',
            payload_json={
                'schema_version': services.OVERVIEW_PAYLOAD_SCHEMA_VERSION,
                'project': {'id': self.project.id, 'name': self.project.name},
                'period': {'range_key': 'last_30_days'},
                'freshness': {'generated_at': generated_at.isoformat(), 'is_stale': False},
                'kpis': [{'label': '</script><div>', 'value': '1'}],
                'rows': [],
                'change_aware_rows': [],
            },
            generated_at=generated_at,
        )

        response = self.client.get(
            reverse('projects:project_pages', kwargs={'project_id': self.project.id}),
            follow=True,
        )
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn('\\u003C/script\\u003E\\u003Cdiv\\u003E', html)
        self.assertNotIn('</script><div>', html)

    def test_scatter_tooltips_returns_cached_payload(self):
        generated_at = timezone.now()
        PagesScatterTooltipCache.objects.create(
            project=self.project,
            range_key='last_30_days',
            start_date=generated_at.date(),
            end_date=generated_at.date(),
            filters_hash='default',
            payload_json={
                'generated_at': generated_at.isoformat(),
                'items': [
                    {
                        'product_area_key': 'billing',
                        'company_id': 'acme',
                        'company_name': 'Acme Inc.',
                    }
                ],
            },
            generated_at=generated_at,
        )

        response = self.client.get(
            reverse('projects:project_pages_scatter_tooltips', kwargs={'project_id': self.project.id})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['items'][0]['product_area_key'], 'billing')

    def test_scatter_tooltips_missing_cache_returns_pending(self):
        response = self.client.get(
            reverse('projects:project_pages_scatter_tooltips', kwargs={'project_id': self.project.id})
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['items'], [])
        self.assertFalse(response.json()['queued'])
