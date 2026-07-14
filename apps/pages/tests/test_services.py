from datetime import date, datetime, time, timedelta
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase
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
from apps.pages import services, user_analytics, user_detail_analytics
from apps.pages.services import build_page_detail_payload, rebuild_project_pages_analytics
from apps.projects.models import (
    Project,
    Workspace,
    WorkspaceMemberRole,
    WorkspaceMemberStatus,
    WorkspaceMembership,
)
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

    def test_build_series_merges_duplicate_page_names(self):
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
        ]

        result = services._build_series(rows, 'visits_count')

        self.assertEqual(result['labels'], ['2026-05-01', '2026-05-02'])
        self.assertEqual([row['page_name'] for row in result['series']], ['Dashboard', 'My work'])
        self.assertEqual(result['series'][0]['total'], 17)
        self.assertEqual(result['series'][0]['values'], [12.0, 5.0])
        self.assertEqual(result['series'][0]['page_rule_ids'], [1, 2])

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

    def test_normalize_overview_payload_collapses_legacy_page_metric_rows(self):
        payload = services.normalize_overview_payload({
            'change_aware_rows': [
                {
                    'page_rule_id': 1,
                    'page_name': ' All companies ',
                    'visits_count': 2,
                    'engaged_seconds': 30,
                    'companies_count': 1,
                },
                {
                    'page_rule_id': 2,
                    'page_name': 'all COMPANIES',
                    'visits_count': 5,
                    'engaged_seconds': 60,
                    'companies_count': 1,
                },
            ],
        })

        self.assertEqual(len(payload['change_aware_rows']), 2)
        self.assertEqual(len(payload['page_metrics_rows']), 1)
        self.assertEqual(payload['page_metrics_rows'][0]['page_rule_id'], '2')
        self.assertEqual(payload['page_metrics_rows'][0]['page_rule_ids'], ['1', '2'])
        self.assertEqual(payload['page_metrics_rows'][0]['visits_count'], 5)

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
                    'companies_count': 4,
                    'adoption_pct': 40,
                    'users_count': 6,
                    'penetration_pct': 60,
                    'visits_count': 12,
                    'engaged_seconds': 600,
                    'avg_visit_seconds': 50,
                    'interaction_pct': 75,
                    'clicks_per_visit': 2,
                    'companies_change_pct': 100,
                    'adoption_change_pp': 10,
                    'trend_values': [1, 2],
                    'trends': {
                        'companies': [1, 4],
                        'adoption': [30, 40],
                        'engaged': [120, 600],
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
                },
            ],
            'change_aware_rows': [
                {
                    'page_rule_id': '1',
                    'product_area_key': 'billing',
                    'product_area_name': 'Billing',
                    'page_name': 'Invoices',
                    'page_group': 'Billing',
                    'companies_count': 4,
                    'adoption_pct': 40,
                    'users_count': 6,
                    'penetration_pct': 60,
                    'visits_count': 12,
                    'engaged_seconds': 600,
                    'avg_visit_seconds': 50,
                    'interaction_pct': 75,
                    'clicks_per_visit': 2,
                    'companies_change_pct': 100,
                    'adoption_change_pp': 10,
                    'trend_values': [1, 2],
                    'trends': {
                        'companies': [1, 4],
                        'adoption': [30, 40],
                        'engaged': [120, 600],
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
        self.assertEqual(filtered['kpis'][0]['value'], '1')
        self.assertEqual(filtered['kpis'][1]['trend_values'], [30.0, 40.0])
        self.assertEqual(filtered['kpis'][2]['trend_values'], [120.0, 600.0])
        self.assertEqual(filtered['kpis'][3]['trend_values'], [1.0, 4.0])

    def test_build_users_overview_payload_aggregates_user_metrics(self):
        start_date, end_date = services.resolve_period(self.project.timezone, range_key='last_30_days')
        _previous_start, previous_end = services.previous_period(start_date, end_date)
        product_area = ProductArea.objects.create(
            project=self.project,
            name='Billing',
            slug='billing',
            short_name='Billing',
            color='#4269D0',
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
                visit_start_ts=timezone.now() - timedelta(minutes=index + 1),
                visit_end_ts=timezone.now(),
                engaged_seconds=300,
            )

        payload = user_analytics.build_users_overview_payload(self.project, range_key='last_30_days')
        users_by_id = {row['id']: row for row in payload['users']}
        status_counts = {row['status']: row['count'] for row in payload['statusDistribution']}

        self.assertEqual(payload['period']['days'], 30)
        self.assertEqual(payload['kpis'][0]['value'], 1)
        self.assertEqual(payload['users'][0]['name'], 'Sarah Chen')
        self.assertEqual(payload['users'][0]['company'], 'Acme Corp')
        self.assertEqual(payload['users'][0]['status'], 'Healthy')
        self.assertEqual(payload['users'][0]['sessionsCount'], 3)
        self.assertEqual(payload['users'][0]['engagedDeltaPct'], 1100.0)
        self.assertEqual(users_by_id['dropped@example.com']['status'], 'Dropped')
        self.assertEqual(users_by_id['dropped@example.com']['visitsCount'], 0)
        self.assertEqual(users_by_id['dropped@example.com']['engagedSeconds'], 0)
        self.assertEqual(users_by_id['dropped@example.com']['activeDays'], 0)
        self.assertEqual(users_by_id['dropped@example.com']['lastActive'], '30d ago')
        self.assertEqual(status_counts['Dropped'], 1)
        self.assertEqual(payload['productAreas'][0]['name'], 'Billing')
        last_status_mix = payload['statusMixByDate'][-1]
        for status, key in [
            ('Power', 'power'),
            ('Healthy', 'healthy'),
            ('Light', 'light'),
            ('Passive', 'passive'),
            ('Dropped', 'dropped'),
        ]:
            self.assertEqual(last_status_mix[key], status_counts.get(status, 0))

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
            color='#4269D0',
        )
        analytics = ProductArea.objects.create(
            project=self.project,
            name='Analytics',
            slug='analytics',
            short_name='Analytics',
            color='#3CA951',
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
        self.assertEqual(len(payload['metricCards']), 8)
        self.assertEqual(len(payload['dailyUsage']), 30 * len(payload['productAreas']))
        self.assertTrue(any(row['isCurrentUser'] for row in payload['peerComparison']))
        self.assertTrue(all(row['userId'] != 'sarah@example.com' for row in payload['peerComparison'] if not row['isCurrentUser']))
        self.assertEqual(payload['pagesUsed'][0]['pageRuleId'], str(invoices.id))
        self.assertIn('Reports', {row['pageName'] for row in payload['underusedPages']})
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
        formerly_monthly_power = {
            'visits': 24,
            'engaged_seconds': 3600,
            'product_areas_used': 2,
            'click_count': 24,
            'active_days': 6,
        }
        sparse_long_period_user = {
            'visits': 14,
            'engaged_seconds': 669,
            'product_areas_used': 2,
            'click_count': 14,
            'active_days': 4,
        }

        self.assertEqual(user_analytics._status_for_user(weekly_power, period_days=7), 'Power')
        self.assertEqual(user_analytics._status_for_user(weekly_power, period_days=30), 'Light')
        self.assertEqual(user_analytics._status_for_user(monthly_power, period_days=30), 'Power')
        self.assertEqual(user_analytics._status_for_user(formerly_monthly_power, period_days=30), 'Healthy')
        self.assertNotEqual(user_analytics._status_for_user(sparse_long_period_user, period_days=90), 'Power')

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
        base_ts = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)
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
        self.assertEqual(ProductArea.objects.filter(project=self.project).count(), 2)
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
        self.assertEqual(len(cache.payload_json['product_area_summary']), 2)
        self.assertNotIn('relative_change_series', cache.payload_json['change_aware_rows'][0])
        self.assertNotIn('relative_change_series', cache.payload_json['rows'][0])
        self.assertNotIn('relative_change_series', cache.payload_json['page_metrics_rows'][0])
        self.assertNotIn('relative_change_series', cache.payload_json['product_area_summary'][0])
        self.assertIn('trends', cache.payload_json['change_aware_rows'][0])
        self.assertIn('adoption', cache.payload_json['change_aware_rows'][0]['trends'])
        self.assertIn('engaged', cache.payload_json['change_aware_rows'][0]['trends'])
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
            {},
        )

        self.assertFalse(row['comparison_available'])
        self.assertFalse(detail_metric['comparisonAvailable'])
        self.assertIsNone(detail_metric['previousValue'])
        self.assertIsNone(detail_metric['deltaValue'])
        self.assertEqual(detail_metric['formattedDelta'], 'n/a')

    def test_build_page_detail_payload_uses_actual_totals_peers_and_null_ratio_days(self):
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
        self.assertEqual(avg_visit_metric['dailySeries'][0]['value'], None)
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
            {'date': '2026-05-03', 'value': None},
            {'date': '2026-05-04', 'value': None},
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
        self.assertEqual(dashboard_row['engagedLabel'], '15m')
