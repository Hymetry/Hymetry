import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.pages import company_analytics, company_detail_analytics, services
from apps.pages.models import (
    CompaniesDetailCache,
    CompaniesOverviewCache,
    PageCompanyDailyMetric,
    PageUserDailyMetric,
    ProductArea,
)
from apps.projects.models import (
    Project,
    Workspace,
    WorkspaceMemberRole,
    WorkspaceMemberStatus,
    WorkspaceMembership,
)
from apps.tracker.models import ProjectPageNamingRunMode, ProjectPageRule


@override_settings(COMPANIES_QUEUE_REBUILDS_ON_REQUEST=False)
class CompaniesOverviewViewTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='companies-view-owner',
            email='companies-view-owner@example.com',
            password='testpass123',
        )
        self.workspace = Workspace.objects.create(
            name='Companies View Workspace',
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
            name='Companies View Project',
            created_by=self.user,
            timezone='UTC',
        )
        self.client.force_login(self.user)

        self.start_date, self.end_date = services.resolve_period(self.project.timezone, range_key='last_30_days')
        self.previous_day = self.start_date - timedelta(days=1)
        self.core_area = ProductArea.objects.create(
            project=self.project,
            name='Core product',
            short_name='Core',
            slug='core',
        )
        self.billing_area = ProductArea.objects.create(
            project=self.project,
            name='Billing',
            short_name='Bill',
            slug='billing',
        )

    def _page_rule(self, *, pattern, page_name, area):
        return ProjectPageRule.objects.create(
            project=self.project,
            pattern=pattern,
            product_area=area.name,
            product_area_short_name=area.short_name,
            area_role=area.area_role,
            is_adoption_recommendable=area.is_adoption_recommendable,
            page_name=page_name,
            priority=100,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )

    def _product_area(self, area_key):
        return {
            'core': self.core_area,
            'billing': self.billing_area,
        }.get(area_key)

    def _company_metric(self, *, company_id, company_name, date, page_rule_id, area_key, area_name, visits, engaged, clicks=1):
        return PageCompanyDailyMetric.objects.create(
            project=self.project,
            date=date,
            page_rule_id=page_rule_id,
            product_area=self._product_area(area_key),
            product_area_key=area_key,
            product_area_name=area_name,
            company_id=company_id,
            company_name_sample=company_name,
            visits_count=visits,
            engaged_seconds=engaged,
            click_count=clicks,
            visits_with_click_count=min(visits, clicks),
        )

    def _user_metric(self, *, company_id, user_id, date, page_rule_id, area_key, area_name, engaged=300):
        return PageUserDailyMetric.objects.create(
            project=self.project,
            date=date,
            page_rule_id=page_rule_id,
            product_area=self._product_area(area_key),
            product_area_key=area_key,
            product_area_name=area_name,
            company_id=company_id,
            user_id=user_id,
            visits_count=1,
            engaged_seconds=engaged,
            click_count=1,
        )

    def _cache_companies_overview(self):
        payload = company_analytics.build_companies_overview_payload(self.project, range_key='last_30_days')
        now = timezone.now()
        CompaniesOverviewCache.objects.update_or_create(
            project=self.project,
            range_key='last_30_days',
            filters_hash=services.DEFAULT_FILTERS_HASH,
            defaults={
                'start_date': self.start_date,
                'end_date': self.end_date,
                'payload_json': payload,
                'generated_at': now,
                'expires_at': now + services.CACHE_TTL,
                'is_stale': False,
            },
        )
        return payload

    def _cache_company_detail(self, company_id, overview_payload=None):
        result = company_analytics.build_company_detail_cache(
            self.project.id,
            company_id,
            range_key='last_30_days',
            overview_payload=overview_payload,
        )
        self.assertEqual(result['status'], 'success')
        return CompaniesDetailCache.objects.get(
            project=self.project,
            range_key='last_30_days',
            company_id=company_id,
            filters_hash=services.DEFAULT_FILTERS_HASH,
        ).payload_json

    def test_companies_overview_uses_prepared_company_aggregates(self):
        self._company_metric(
            company_id='acme',
            company_name='Acme Inc.',
            date=self.end_date,
            page_rule_id=1,
            area_key='core',
            area_name='Core product',
            visits=10,
            engaged=4000,
        )
        self._company_metric(
            company_id='acme',
            company_name='Acme Inc.',
            date=self.end_date,
            page_rule_id=2,
            area_key='billing',
            area_name='Billing',
            visits=5,
            engaged=2000,
        )
        self._user_metric(company_id='acme', user_id='u1', date=self.end_date, page_rule_id=1, area_key='core', area_name='Core product')
        self._user_metric(company_id='acme', user_id='u2', date=self.end_date, page_rule_id=2, area_key='billing', area_name='Billing')

        self._company_metric(
            company_id='riskco',
            company_name='RiskCo',
            date=self.end_date,
            page_rule_id=1,
            area_key='core',
            area_name='Core product',
            visits=2,
            engaged=300,
        )
        self._user_metric(company_id='riskco', user_id='r1', date=self.end_date, page_rule_id=1, area_key='core', area_name='Core product')
        self._company_metric(
            company_id='riskco',
            company_name='RiskCo',
            date=self.previous_day,
            page_rule_id=1,
            area_key='core',
            area_name='Core product',
            visits=12,
            engaged=3000,
        )
        self._company_metric(
            company_id='riskco',
            company_name='RiskCo',
            date=self.previous_day,
            page_rule_id=2,
            area_key='billing',
            area_name='Billing',
            visits=8,
            engaged=1800,
        )
        for index in range(3):
            self._user_metric(
                company_id='riskco',
                user_id=f'r-prev-{index}',
                date=self.previous_day,
                page_rule_id=1,
                area_key='core',
                area_name='Core product',
            )

        company_analytics.build_companies_overview_cache(self.project.id, range_key='last_30_days')
        response = self.client.get(reverse('projects:project_companies', kwargs={'project_id': self.project.id}))
        html = response.content.decode()
        payload_json = html.split('<script id="companies-overview-data" type="application/json">', 1)[1].split('</script>', 1)[0]
        payload = json.loads(payload_json)
        company_names = {row['companyName'] for row in payload['companies']}
        company_statuses = {row['companyName']: row['status'] for row in payload['companies']}
        product_area_short_names = {row['name']: row['shortName'] for row in payload['productAreas']}

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'COMPANY ENGAGEMENT MAP')
        self.assertContains(response, 'companies-overview-data')
        self.assertContains(response, 'js/vendor/vega.min.js')
        self.assertContains(response, 'js/vendor/vega-embed.min.js')
        self.assertContains(response, 'js/companies/django-companies-data.js')
        self.assertContains(response, 'js/companies/companies-analytics.js')
        self.assertContains(response, 'css/companies/overview.css')
        self.assertContains(response, 'New &amp; reactivated adoption')
        self.assertContains(response, 'Product area adoption over time')
        self.assertContains(response, 'New-company adoption ramp')
        self.assertContains(response, 'Expansion opportunities')
        self.assertContains(response, 'company-health-distribution-echarts')
        self.assertContains(response, 'product-area-adoption-chart')
        self.assertContains(response, 'new-company-adoption-ramp-chart')
        self.assertContains(response, 'expansion-table-body')
        self.assertNotContains(response, 'company-engagement-scatter-filters')
        self.assertNotContains(response, 'scatter-status-filter')
        self.assertNotContains(response, 'scatter-product-area-filter')
        self.assertNotContains(response, 'scatter-min-active-users')
        self.assertNotContains(response, 'scatter-company-search')
        self.assertEqual(payload['scatter']['totalActiveCompanies'], 2)
        self.assertEqual(payload['scatter']['visibleLimit'], 500)
        self.assertEqual(len(payload['scatter']['points']), 2)
        self.assertEqual(product_area_short_names['Billing'], 'Bill')
        self.assertIn('Acme Inc.', company_names)
        self.assertIn('RiskCo', company_names)
        self.assertEqual(company_statuses['Acme Inc.'], 'new')
        self.assertEqual(company_statuses['RiskCo'], 'at_risk')
        acme_row = next(row for row in payload['companies'] if row['companyName'] == 'Acme Inc.')
        riskco_row = next(row for row in payload['companies'] if row['companyName'] == 'RiskCo')
        options_response = self.client.get(
            reverse('projects:project_company_options', kwargs={'project_id': self.project.id}),
            {'q': 'Acme', 'range': 'last_30_days'},
        )
        options_payload = json.loads(options_response.content.decode())
        acme_option = next(row for row in options_payload['companies'] if row['companyName'] == 'Acme Inc.')

        self.assertEqual(options_response.status_code, 200)
        self.assertEqual(acme_option['lastSeenDate'], acme_row['lastSeenDate'])
        self.assertEqual(acme_row['userHealthMix']['passive'], 2)
        self.assertEqual(riskco_row['userHealthMix']['passive'], 1)
        self.assertEqual(riskco_row['userHealthMix']['dropped'], 3)
        at_risk_kpi = next(kpi for kpi in payload['kpis'] if kpi['label'] == 'At-risk companies')
        self.assertEqual(len(at_risk_kpi['trend']), 30)
        self.assertGreater(sum(at_risk_kpi['trend']), 0)
        self.assertNotContains(response, 'being prepared for this project')

    def test_companies_overview_embeds_first_table_page_and_serves_remaining_rows(self):
        generated_at = timezone.now()
        rows = [
            {
                'id': f'company-{index:02d}',
                'companyId': f'company-{index:02d}',
                'name': f'Company {index:02d}',
                'companyName': f'Company {index:02d}',
                'status': 'healthy',
                'activeUsers': index + 1,
                'pagesUsed': index + 1,
                'visits': index + 1,
                'engagedSeconds': (index + 1) * 60,
                'avgEngagedSecondsPerUser': index + 1,
                'interactionPct': index,
                'productAreas': ['Core product'],
                'productAreaDistribution': [],
            }
            for index in range(25)
        ]
        CompaniesOverviewCache.objects.create(
            project=self.project,
            range_key='last_30_days',
            start_date=self.start_date,
            end_date=self.end_date,
            filters_hash=services.DEFAULT_FILTERS_HASH,
            payload_json={
                'schema_version': company_analytics.COMPANIES_PAYLOAD_SCHEMA_VERSION,
                'project': {'id': self.project.id, 'name': self.project.name},
                'period': {'range_key': 'last_30_days', 'days': 30},
                'freshness': {'generated_at': generated_at.isoformat(), 'is_stale': False},
                'kpis': [],
                'healthDistribution': [],
                'companies': rows,
                'scatter': {'visibleLimit': 500, 'totalActiveCompanies': 25, 'points': rows},
                'productAreas': [{'name': 'Core product', 'shortName': 'Core', 'color': '#4269D0'}],
                'newReactivatedCompanies': [],
                'productAreaAdoption': [],
                'newCompanyAdoptionRamp': [],
                'atRiskCompanies': [],
                'expansionOpportunities': [],
            },
            generated_at=generated_at,
        )

        response = self.client.get(reverse('projects:project_companies', kwargs={'project_id': self.project.id}))
        payload_json = response.content.decode().split('<script id="companies-overview-data" type="application/json">', 1)[1].split('</script>', 1)[0]
        payload = json.loads(payload_json)
        table_response = self.client.get(
            reverse('projects:project_companies_table_data', kwargs={'project_id': self.project.id}),
            {'page': 2, 'page_size': 20, 'sort': 'engagedSeconds', 'direction': 'desc'},
        )
        table_payload = table_response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(payload['companies']), 20)
        self.assertEqual(payload['companies'][0]['companyName'], 'Company 24')
        self.assertEqual(payload['tableData']['companies']['pagination']['totalRows'], 25)
        self.assertEqual(table_response.status_code, 200)
        self.assertEqual(table_payload['pagination']['page'], 2)
        self.assertEqual(table_payload['pagination']['totalRows'], 25)
        self.assertEqual([row['companyName'] for row in table_payload['rows']], [
            'Company 04',
            'Company 03',
            'Company 02',
            'Company 01',
            'Company 00',
        ])

    def test_companies_scatter_uses_average_active_users(self):
        dashboard_rule = self._page_rule(pattern=r'^example\.com/dashboard$', page_name='Dashboard', area=self.core_area)
        first_date = self.end_date - timedelta(days=1)
        second_date = self.end_date

        for metric_date, users in ((first_date, 5), (second_date, 6)):
            self._company_metric(
                company_id='acme',
                company_name='Acme Inc.',
                date=metric_date,
                page_rule_id=dashboard_rule.id,
                area_key='core',
                area_name='Core product',
                visits=users,
                engaged=users * 120,
            )
            for index in range(users):
                self._user_metric(
                    company_id='acme',
                    user_id=f'user-{index}',
                    date=metric_date,
                    page_rule_id=dashboard_rule.id,
                    area_key='core',
                    area_name='Core product',
                    engaged=120,
                )

        payload = company_analytics.build_companies_overview_payload(self.project, range_key='last_30_days')
        acme_row = next(row for row in payload['companies'] if row['companyId'] == 'acme')
        scatter_row = next(row for row in payload['scatter']['points'] if row['companyId'] == 'acme')

        self.assertEqual(acme_row['activeUsers'], 6)
        self.assertEqual(acme_row['averageActiveUsers'], 5.5)
        self.assertEqual(scatter_row['averageActiveUsers'], 5.5)

    def test_companies_overview_cache_hydrates_company_detail_cache(self):
        dashboard_rule = self._page_rule(pattern=r'^example\.com/dashboard$', page_name='Dashboard', area=self.core_area)
        self._company_metric(
            company_id='acme',
            company_name='Acme Inc.',
            date=self.end_date,
            page_rule_id=dashboard_rule.id,
            area_key='core',
            area_name='Core product',
            visits=6,
            engaged=1800,
        )
        self._user_metric(
            company_id='acme',
            user_id='u1',
            date=self.end_date,
            page_rule_id=dashboard_rule.id,
            area_key='core',
            area_name='Core product',
        )

        result = company_analytics.build_companies_overview_cache(self.project.id, range_key='last_30_days')
        detail_cache = CompaniesDetailCache.objects.get(
            project=self.project,
            range_key='last_30_days',
            company_id='acme',
            filters_hash=services.DEFAULT_FILTERS_HASH,
        )

        self.assertEqual(result['detail_cache_count'], 1)
        self.assertEqual(detail_cache.payload_json['company']['name'], 'Acme Inc.')
        self.assertEqual(detail_cache.payload_json['schema_version'], company_detail_analytics.COMPANY_DETAIL_PAYLOAD_SCHEMA_VERSION)

    def test_company_detail_payload_exposes_all_top_pages_for_paginated_table(self):
        for index in range(16):
            page_rule = self._page_rule(
                pattern=rf'^example\.com/page-{index}$',
                page_name=f'Page {index:02d}',
                area=self.core_area,
            )
            self._company_metric(
                company_id='acme',
                company_name='Acme Inc.',
                date=self.end_date,
                page_rule_id=page_rule.id,
                area_key='core',
                area_name='Core product',
                visits=index + 1,
                engaged=(index + 1) * 100,
            )
            self._user_metric(
                company_id='acme',
                user_id=f'u{index:02d}',
                date=self.end_date,
                page_rule_id=page_rule.id,
                area_key='core',
                area_name='Core product',
            )

        payload, _company_rows, _product_areas = company_detail_analytics.build_company_detail_payload(
            self.project,
            'acme',
            range_key='last_30_days',
        )

        self.assertEqual(len(payload['topPages']), 15)
        self.assertEqual(len(payload['allTopPages']), 16)
        self.assertEqual(payload['allTopPages'][0]['pageName'], 'Page 15')
        self.assertEqual(payload['allTopPages'][-1]['pageName'], 'Page 00')

    def test_company_detail_payload_returns_all_users_for_paginated_table(self):
        dashboard_rule = self._page_rule(pattern=r'^example\.com/dashboard$', page_name='Dashboard', area=self.core_area)
        self._company_metric(
            company_id='acme',
            company_name='Acme Inc.',
            date=self.end_date,
            page_rule_id=dashboard_rule.id,
            area_key='core',
            area_name='Core product',
            visits=301,
            engaged=30100,
        )
        PageUserDailyMetric.objects.bulk_create([
            PageUserDailyMetric(
                project=self.project,
                date=self.end_date,
                page_rule_id=dashboard_rule.id,
                product_area=self.core_area,
                product_area_key='core',
                product_area_name='Core product',
                company_id='acme',
                user_id=f'user-{index:03d}',
                user_name_sample=f'User {index:03d}',
                visits_count=1,
                engaged_seconds=index + 1,
                click_count=1,
            )
            for index in range(301)
        ])

        payload, _company_rows, _product_areas = company_detail_analytics.build_company_detail_payload(
            self.project,
            'acme',
            range_key='last_30_days',
        )

        self.assertEqual(len(payload['users']), 301)
        self.assertEqual(payload['users'][0]['name'], 'User 300')
        self.assertEqual(payload['users'][-1]['name'], 'User 000')

    def test_scatter_points_are_limited_by_relevance(self):
        rows = [
            {
                'companyId': f'company-{index}',
                'companyName': f'Company {index}',
                'status': 'healthy',
                'activeUsers': index % 12,
                'visits': index + 1,
                'engagedSeconds': index * 60,
                'avgEngagedSecondsPerUser': index % 300,
                'activeUsersDeltaPct': 0,
                'visitsDeltaPct': 0,
                'engagedDeltaPct': 0,
                'interactionDeltaPp': 0,
            }
            for index in range(560)
        ]
        rows.extend([
            {
                'companyId': 'risk-low-volume',
                'companyName': 'Risk Low Volume',
                'status': 'at_risk',
                'activeUsers': 1,
                'visits': 1,
                'engagedSeconds': 60,
                'avgEngagedSecondsPerUser': 60,
            },
            {
                'companyId': 'new-low-volume',
                'companyName': 'New Low Volume',
                'status': 'new',
                'isNew': True,
                'activeUsers': 1,
                'visits': 1,
                'engagedSeconds': 60,
                'avgEngagedSecondsPerUser': 60,
            },
            {
                'companyId': 'active-user-outlier',
                'companyName': 'Active User Outlier',
                'status': 'healthy',
                'activeUsers': 999,
                'visits': 2,
                'engagedSeconds': 120,
                'avgEngagedSecondsPerUser': 1,
            },
            {
                'companyId': 'engaged-outlier',
                'companyName': 'Engaged Outlier',
                'status': 'healthy',
                'activeUsers': 2,
                'visits': 2,
                'engagedSeconds': 999999,
                'avgEngagedSecondsPerUser': 499999,
            },
            {
                'companyId': 'delta-outlier',
                'companyName': 'Delta Outlier',
                'status': 'healthy',
                'activeUsers': 2,
                'visits': 2,
                'engagedSeconds': 120,
                'avgEngagedSecondsPerUser': 60,
                'engagedDeltaPct': -999,
            },
            {
                'companyId': 'dormant-empty',
                'companyName': 'Dormant Empty',
                'status': 'dormant',
                'activeUsers': 0,
                'visits': 0,
                'engagedSeconds': 0,
            },
        ])

        selected = company_analytics._select_relevant_scatter_points(rows, limit=500)
        selected_ids = {row['companyId'] for row in selected}

        self.assertEqual(len(selected), 500)
        self.assertIn('risk-low-volume', selected_ids)
        self.assertIn('new-low-volume', selected_ids)
        self.assertIn('active-user-outlier', selected_ids)
        self.assertIn('engaged-outlier', selected_ids)
        self.assertIn('delta-outlier', selected_ids)
        self.assertNotIn('dormant-empty', selected_ids)

    def test_company_detail_adoption_breadth_uses_page_rule_metadata_when_product_area_is_stale(self):
        dashboard_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^example\.com/dashboard$',
            product_area=self.core_area.name,
            product_area_short_name=self.core_area.short_name,
            area_role=ProductArea.AREA_ROLE_PRODUCT,
            is_adoption_recommendable=True,
            page_name='Dashboard',
            priority=100,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )
        settings_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^example\.com/settings$',
            product_area=self.billing_area.name,
            product_area_short_name=self.billing_area.short_name,
            area_role=ProductArea.AREA_ROLE_ADMIN,
            is_adoption_recommendable=False,
            page_name='Settings',
            priority=90,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )
        self._company_metric(
            company_id='acme',
            company_name='Acme Inc.',
            date=self.end_date,
            page_rule_id=dashboard_rule.id,
            area_key='legacy-core',
            area_name='Legacy core label',
            visits=3,
            engaged=900,
        )
        self._company_metric(
            company_id='acme',
            company_name='Acme Inc.',
            date=self.end_date,
            page_rule_id=settings_rule.id,
            area_key='legacy-billing',
            area_name='Legacy billing label',
            visits=4,
            engaged=1200,
        )
        overview_payload = self._cache_companies_overview()
        payload = self._cache_company_detail('acme', overview_payload=overview_payload)
        adoption_metric = next(metric for metric in payload['metricCards'] if metric['key'] == 'adoptionBreadth')

        self.assertEqual(self.core_area.area_role, ProductArea.AREA_ROLE_UNKNOWN)
        self.assertFalse(self.core_area.is_adoption_recommendable)
        self.assertEqual(adoption_metric['value'], 1)
        self.assertEqual(adoption_metric['secondaryText'], '1 areas · 1 pages')
        self.assertEqual(adoption_metric['dailySeries'][-1]['value'], 1)

    def test_company_detail_adoption_breadth_falls_back_to_observed_areas_without_metadata(self):
        dashboard_rule = self._page_rule(pattern=r'^example\.com/dashboard$', page_name='Dashboard', area=self.core_area)
        billing_rule = self._page_rule(pattern=r'^example\.com/billing$', page_name='Billing', area=self.billing_area)
        self._company_metric(
            company_id='acme',
            company_name='Acme Inc.',
            date=self.end_date,
            page_rule_id=dashboard_rule.id,
            area_key='core',
            area_name='Core product',
            visits=3,
            engaged=900,
        )
        self._company_metric(
            company_id='acme',
            company_name='Acme Inc.',
            date=self.end_date,
            page_rule_id=billing_rule.id,
            area_key='billing',
            area_name='Billing',
            visits=4,
            engaged=1200,
        )
        overview_payload = self._cache_companies_overview()
        payload = self._cache_company_detail('acme', overview_payload=overview_payload)
        adoption_metric = next(metric for metric in payload['metricCards'] if metric['key'] == 'adoptionBreadth')

        self.assertEqual(adoption_metric['value'], 2)
        self.assertEqual(adoption_metric['secondaryText'], '2 areas · 2 pages')
        self.assertEqual(adoption_metric['dailySeries'][-1]['value'], 2)

    def test_company_detail_builds_backend_payload_and_filters_adoption_metadata(self):
        self.core_area.area_role = ProductArea.AREA_ROLE_PRODUCT
        self.core_area.is_adoption_recommendable = True
        self.core_area.color = '#123456'
        self.core_area.save(update_fields=['area_role', 'is_adoption_recommendable', 'color'])
        self.billing_area.area_role = ProductArea.AREA_ROLE_ADMIN
        self.billing_area.is_adoption_recommendable = False
        self.billing_area.color = '#abcdef'
        self.billing_area.save(update_fields=['area_role', 'is_adoption_recommendable', 'color'])
        dashboard_rule = self._page_rule(pattern=r'^example\.com/dashboard$', page_name='Dashboard', area=self.core_area)
        billing_rule = self._page_rule(pattern=r'^example\.com/billing$', page_name='Billing settings', area=self.billing_area)

        self._company_metric(
            company_id='acme',
            company_name='Acme Inc.',
            date=self.end_date,
            page_rule_id=dashboard_rule.id,
            area_key='core',
            area_name='Core product',
            visits=10,
            engaged=3600,
            clicks=8,
        )
        self._company_metric(
            company_id='acme',
            company_name='Acme Inc.',
            date=self.end_date,
            page_rule_id=billing_rule.id,
            area_key='billing',
            area_name='Billing',
            visits=6,
            engaged=1800,
            clicks=3,
        )
        self._company_metric(
            company_id='acme',
            company_name='Acme Inc.',
            date=self.previous_day,
            page_rule_id=dashboard_rule.id,
            area_key='core',
            area_name='Core product',
            visits=5,
            engaged=1200,
            clicks=2,
        )
        self._company_metric(
            company_id='peerco',
            company_name='Peer Co',
            date=self.end_date,
            page_rule_id=dashboard_rule.id,
            area_key='core',
            area_name='Core product',
            visits=9,
            engaged=3000,
            clicks=5,
        )
        for user_id in ('u1', 'u2'):
            self._user_metric(company_id='acme', user_id=user_id, date=self.end_date, page_rule_id=dashboard_rule.id, area_key='core', area_name='Core product', engaged=900)
        self._user_metric(company_id='acme', user_id='u1', date=self.end_date, page_rule_id=billing_rule.id, area_key='billing', area_name='Billing', engaged=300)
        self._user_metric(company_id='acme', user_id='u-old', date=self.previous_day, page_rule_id=dashboard_rule.id, area_key='core', area_name='Core product', engaged=900)
        self._user_metric(company_id='acme', user_id='u-risk', date=self.end_date, page_rule_id=dashboard_rule.id, area_key='core', area_name='Core product', engaged=100)
        self._user_metric(company_id='acme', user_id='u-risk', date=self.previous_day, page_rule_id=dashboard_rule.id, area_key='core', area_name='Core product', engaged=900)
        self._user_metric(company_id='peerco', user_id='p1', date=self.end_date, page_rule_id=dashboard_rule.id, area_key='core', area_name='Core product', engaged=600)
        PageCompanyDailyMetric.objects.filter(company_id='acme', product_area_key='core').update(product_area=None)
        overview_payload = self._cache_companies_overview()
        overview_product_area_colors = {
            row['name']: row['color']
            for row in overview_payload['productAreas']
        }
        self.assertEqual(overview_product_area_colors['Core product'], '#123456')
        self.assertEqual(overview_product_area_colors['Billing'], '#abcdef')
        self._cache_company_detail('acme', overview_payload=overview_payload)

        response = self.client.get(
            reverse('projects:project_company_detail', kwargs={'project_id': self.project.id, 'company_id': 'acme'})
        )
        html = response.content.decode()
        bundle_json = html.split('<script id="company-detail-data" type="application/json">', 1)[1].split('</script>', 1)[0]
        bundle = json.loads(bundle_json)
        payload = bundle['payload']
        top_page_names = {row['pageName'] for row in payload['topPages']}
        billing_top_page = next(row for row in payload['topPages'] if row['pageName'] == 'Billing settings')
        billing_treemap_node = next(node for node in payload['areaTreemap']['nodes'] if node['productArea'] == 'Billing')
        core_series = next(row for row in payload['adoptionBreadthSeries']['series'] if row['productArea'] == 'Core product')
        product_area_colors = {row['name']: row['color'] for row in payload['productAreas']}
        active_users_metric = next(metric for metric in payload['metricCards'] if metric['key'] == 'activeUsers')
        new_reactivated_metric = next(metric for metric in payload['metricCards'] if metric['key'] == 'newReactivatedUsers')
        visits_metric = next(metric for metric in payload['metricCards'] if metric['key'] == 'visits')
        avg_per_user_metric = next(metric for metric in payload['metricCards'] if metric['key'] == 'avgPerUser')
        adoption_metric = next(metric for metric in payload['metricCards'] if metric['key'] == 'adoptionBreadth')
        at_risk_metric = next(metric for metric in payload['metricCards'] if metric['key'] == 'atRiskUsers')
        health_distribution = {row['status']: row['count'] for row in payload['companyHealthDistribution']}
        users_by_id = {row['id']: row for row in payload['users']}

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('companies', bundle)
        self.assertContains(response, 'Company metric dynamics')
        self.assertContains(response, 'User health distribution')
        self.assertContains(response, 'data-companies-view="detail"')
        self.assertContains(response, 'js/companies/django-company-detail-data.js')
        self.assertContains(response, 'js/companies/company-detail.js')
        self.assertEqual(payload['company']['name'], 'Acme Inc.')
        self.assertEqual(len(payload['metricCards']), 8)
        self.assertEqual(active_users_metric['peerSeries'][0]['companyId'], 'peerco')
        self.assertEqual(active_users_metric['peerSeries'][0]['dailySeries'][-1]['value'], 1)
        self.assertEqual(new_reactivated_metric['peerSeries'][0]['companyId'], 'peerco')
        self.assertEqual(new_reactivated_metric['peerSeries'][0]['dailySeries'][-1]['value'], 1)
        self.assertEqual(visits_metric['peerSeries'][0]['companyId'], 'peerco')
        self.assertEqual(visits_metric['peerSeries'][0]['dailySeries'][-1]['value'], 9)
        self.assertEqual(avg_per_user_metric['peerSeries'][0]['companyId'], 'peerco')
        self.assertEqual(avg_per_user_metric['peerSeries'][0]['dailySeries'][-1]['value'], 3000)
        self.assertEqual(adoption_metric['value'], 1)
        self.assertEqual(adoption_metric['peerSeries'][0]['dailySeries'][-1]['value'], 1)
        self.assertEqual(adoption_metric['secondaryText'], '1 areas · 1 pages')
        self.assertEqual(at_risk_metric['value'], 1)
        self.assertEqual(at_risk_metric['peerSeries'][0]['companyId'], 'peerco')
        self.assertEqual(at_risk_metric['peerSeries'][0]['dailySeries'][-1]['value'], 0)
        self.assertEqual(at_risk_metric['dailySeries'][0]['value'], 0)
        self.assertEqual(at_risk_metric['dailySeries'][-1]['value'], 1)
        self.assertIn('Dashboard', top_page_names)
        self.assertIn('Billing settings', top_page_names)
        self.assertEqual(product_area_colors['Core product'], '#123456')
        self.assertEqual(product_area_colors['Billing'], '#abcdef')
        self.assertEqual(billing_top_page['areaRole'], ProductArea.AREA_ROLE_ADMIN)
        self.assertEqual(billing_top_page['color'], '#abcdef')
        self.assertFalse(billing_top_page['isAdoptionRecommendable'])
        self.assertEqual(billing_treemap_node['color'], '#abcdef')
        self.assertEqual(core_series['color'], '#123456')
        self.assertTrue(payload['users'])
        self.assertTrue(all(user.get('status') in {'power', 'healthy', 'light', 'passive', 'dropped'} for user in payload['users']))
        self.assertEqual(users_by_id['u-old']['status'], 'dropped')
        self.assertEqual(users_by_id['u-old']['activeDays'], 0)
        self.assertEqual(users_by_id['u-old']['visits'], 0)
        self.assertEqual(users_by_id['u-old']['engagedSeconds'], 0)
        self.assertEqual(users_by_id['u-old']['lastActive'], '30d ago')
        self.assertEqual(users_by_id['u-risk']['riskStatus'], 'at_risk')
        self.assertEqual(health_distribution['passive'], 3)
        self.assertEqual(health_distribution['dropped'], 1)
        self.assertFalse(
            any(
                action['type'] == 'Adoption gap' and 'Billing' in action['reason']
                for action in payload['recommendedActions']
            )
        )

    def test_company_detail_at_risk_users_for_180_days_use_recent_90_day_window(self):
        dashboard_rule = self._page_rule(pattern=r'^example\.com/dashboard$', page_name='Dashboard', area=self.core_area)
        _start_180, end_date = services.resolve_period(self.project.timezone, range_key='last_180_days')
        current_day = end_date
        previous_risk_day = end_date - timedelta(days=90)

        self._company_metric(
            company_id='acme',
            company_name='Acme Inc.',
            date=current_day,
            page_rule_id=dashboard_rule.id,
            area_key='core',
            area_name='Core product',
            visits=4,
            engaged=1000,
        )
        self._company_metric(
            company_id='acme',
            company_name='Acme Inc.',
            date=previous_risk_day,
            page_rule_id=dashboard_rule.id,
            area_key='core',
            area_name='Core product',
            visits=10,
            engaged=2000,
        )
        self._user_metric(
            company_id='acme',
            user_id='u-risk',
            date=current_day,
            page_rule_id=dashboard_rule.id,
            area_key='core',
            area_name='Core product',
            engaged=100,
        )
        self._user_metric(
            company_id='acme',
            user_id='u-risk',
            date=previous_risk_day,
            page_rule_id=dashboard_rule.id,
            area_key='core',
            area_name='Core product',
            engaged=900,
        )

        payload_90, _company_rows_90, _product_areas_90 = company_detail_analytics.build_company_detail_payload(
            self.project,
            'acme',
            range_key='last_90_days',
        )
        payload_180, _company_rows_180, _product_areas_180 = company_detail_analytics.build_company_detail_payload(
            self.project,
            'acme',
            range_key='last_180_days',
        )
        at_risk_90 = next(metric for metric in payload_90['metricCards'] if metric['key'] == 'atRiskUsers')
        at_risk_180 = next(metric for metric in payload_180['metricCards'] if metric['key'] == 'atRiskUsers')

        self.assertEqual(at_risk_90['value'], 1)
        self.assertEqual(at_risk_180['value'], 1)
        self.assertEqual(at_risk_180['dailySeries'][-1]['value'], 1)

    def test_company_detail_reuses_cached_companies_overview_for_company_rows(self):
        self._company_metric(
            company_id='acme',
            company_name='Acme Inc.',
            date=self.end_date,
            page_rule_id=1,
            area_key='core',
            area_name='Core product',
            visits=6,
            engaged=1800,
        )
        self._user_metric(company_id='acme', user_id='u1', date=self.end_date, page_rule_id=1, area_key='core', area_name='Core product')
        overview_payload = self._cache_companies_overview()
        self._cache_company_detail('acme', overview_payload=overview_payload)

        with patch('apps.pages.company_detail_analytics._company_rows', side_effect=AssertionError('detail should use overview cache')):
            response = self.client.get(
                reverse('projects:project_company_detail', kwargs={'project_id': self.project.id, 'company_id': 'acme'})
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Acme Inc.')

    @patch('apps.pages.company_detail_analytics.build_company_detail_payload')
    def test_company_detail_missing_overview_cache_does_not_build_payload_synchronously(self, mock_build_payload):
        response = self.client.get(
            reverse('projects:project_company_detail', kwargs={'project_id': self.project.id, 'company_id': 'acme'})
        )
        bundle_json = response.content.decode().split('<script id="company-detail-data" type="application/json">', 1)[1].split('</script>', 1)[0]
        bundle = json.loads(bundle_json)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(bundle['status'], 'preparing')
        self.assertIsNone(bundle['payload'])
        mock_build_payload.assert_not_called()

    @patch('apps.pages.company_detail_analytics.build_company_detail_payload')
    def test_company_detail_missing_detail_cache_does_not_build_payload_synchronously(self, mock_build_payload):
        self._company_metric(
            company_id='acme',
            company_name='Acme Inc.',
            date=self.end_date,
            page_rule_id=1,
            area_key='core',
            area_name='Core product',
            visits=6,
            engaged=1800,
        )
        self._user_metric(company_id='acme', user_id='u1', date=self.end_date, page_rule_id=1, area_key='core', area_name='Core product')
        self._cache_companies_overview()

        response = self.client.get(
            reverse('projects:project_company_detail', kwargs={'project_id': self.project.id, 'company_id': 'acme'})
        )
        bundle_json = response.content.decode().split('<script id="company-detail-data" type="application/json">', 1)[1].split('</script>', 1)[0]
        bundle = json.loads(bundle_json)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(bundle['status'], 'preparing')
        self.assertIsNone(bundle['payload'])
        self.assertNotIn('companies', bundle)
        mock_build_payload.assert_not_called()

    def test_company_detail_embeds_first_users_page_and_serves_remaining_rows(self):
        dashboard_rule = self._page_rule(pattern=r'^example\.com/dashboard$', page_name='Dashboard', area=self.core_area)
        self._company_metric(
            company_id='largeco',
            company_name='LargeCo',
            date=self.end_date,
            page_rule_id=dashboard_rule.id,
            area_key='core',
            area_name='Core product',
            visits=305,
            engaged=46665,
            clicks=305,
        )
        PageUserDailyMetric.objects.bulk_create(
            [
                PageUserDailyMetric(
                    project=self.project,
                    date=self.end_date,
                    page_rule_id=dashboard_rule.id,
                    product_area=self.core_area,
                    product_area_key='core',
                    product_area_name='Core product',
                    company_id='largeco',
                    user_id=f'u{index:03d}',
                    visits_count=1,
                    engaged_seconds=index + 1,
                    click_count=1,
                )
                for index in range(305)
            ]
        )
        overview_payload = self._cache_companies_overview()
        self._cache_company_detail('largeco', overview_payload=overview_payload)

        response = self.client.get(
            reverse('projects:project_company_detail', kwargs={'project_id': self.project.id, 'company_id': 'largeco'})
        )
        bundle_json = response.content.decode().split('<script id="company-detail-data" type="application/json">', 1)[1].split('</script>', 1)[0]
        payload = json.loads(bundle_json)['payload']
        user_ids = [row['id'] for row in payload['users']]
        table_response = self.client.get(
            reverse('projects:project_company_detail_table_data', kwargs={'project_id': self.project.id, 'company_id': 'largeco'}),
            {'table': 'users', 'page': 16, 'page_size': 20, 'sort': 'engagedSeconds', 'direction': 'desc'},
        )
        table_payload = table_response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['company']['activeUsers'], 305)
        self.assertEqual(len(payload['users']), 20)
        self.assertEqual(len(payload['usersScatter']), 305)
        self.assertEqual(payload['tableData']['users']['pagination']['totalRows'], 305)
        self.assertEqual(user_ids[0], 'u304')
        self.assertEqual(user_ids[-1], 'u285')
        self.assertEqual(table_response.status_code, 200)
        self.assertEqual(table_payload['pagination']['page'], 16)
        self.assertEqual(table_payload['pagination']['totalRows'], 305)
        self.assertEqual([row['id'] for row in table_payload['rows']], ['u004', 'u003', 'u002', 'u001', 'u000'])

    def test_company_detail_peer_selection_uses_active_users_before_optional_dimensions(self):
        def company(company_id, active_users, known_users=None, first_seen=None):
            row = {
                'id': company_id,
                'companyId': company_id,
                'name': company_id,
                'companyName': company_id,
                'activeUsers': active_users,
                'avgEngagedSecondsPerUser': 900,
                'avgEngagedSecondsPerUserDeltaPct': 0,
                'productAreasUsed': 2,
                'pagesUsed': 3,
                'interactionPct': 50,
                'productAreaDistribution': [],
                'engagedSeconds': active_users * 900,
            }
            if known_users is not None:
                row['totalKnownUsers'] = known_users
            if first_seen is not None:
                row['firstSeenDate'] = first_seen
            return row

        current = company('current', 10, known_users=100, first_seen='2026-01-15')
        complete_candidates = [
            company(f'complete-{index}', 10 + index, known_users=100 + index, first_seen=f'2026-01-{15 + index:02d}')
            for index in range(1, 9)
        ]
        incomplete_candidates = [
            company('fill-active-10', 10, known_users=100),
            company('fill-active-09', 9, known_users=100),
            company('fill-active-11', 11, known_users=100),
            company('fill-active-20', 20, known_users=100),
        ]

        comparison = company_detail_analytics._peer_comparison(
            current,
            [current, *complete_candidates, *incomplete_candidates],
            [],
        )
        peer_ids = [row['id'] for row in comparison['rows'] if row.get('rowType') == 'peer']

        self.assertEqual(len(peer_ids), 10)
        self.assertEqual(peer_ids[:3], ['fill-active-10', 'fill-active-09', 'fill-active-11'])
        self.assertEqual(peer_ids[3:], [f'complete-{index}' for index in range(1, 8)])
        self.assertNotIn('complete-8', peer_ids)
        self.assertNotIn('fill-active-20', peer_ids)

    def test_company_detail_peer_median_includes_area_usage_distribution(self):
        def company(company_id, active_users, engaged_by_area):
            distribution = [
                {
                    'productArea': area,
                    'engagedSeconds': engaged,
                    'visits': visits,
                    'pagesUsed': pages,
                }
                for area, engaged, visits, pages in engaged_by_area
            ]
            return {
                'id': company_id,
                'companyId': company_id,
                'name': company_id,
                'companyName': company_id,
                'activeUsers': active_users,
                'avgEngagedSecondsPerUser': 900,
                'avgEngagedSecondsPerUserDeltaPct': 0,
                'productAreasUsed': len(distribution),
                'pagesUsed': sum(item['pagesUsed'] for item in distribution),
                'interactionPct': 50,
                'productAreaDistribution': distribution,
                'engagedSeconds': sum(item['engagedSeconds'] for item in distribution),
            }

        current = company('current', 10, [('Core workspace', 1200, 10, 8)])
        peers = [
            company('peer-1', 10, [('Core workspace', 1800, 20, 12), ('Project management', 1200, 12, 8)]),
            company('peer-2', 11, [('Core workspace', 2400, 22, 14), ('Project management', 1500, 13, 9)]),
            company('peer-3', 9, [('Core workspace', 3000, 24, 16), ('Project management', 1800, 14, 10)]),
        ]

        comparison = company_detail_analytics._peer_comparison(
            current,
            [current, *peers],
            ['Core workspace', 'Project management'],
            peers=peers,
        )
        median = next(row for row in comparison['rows'] if row.get('rowType') == 'median')

        self.assertEqual(
            [(item['productArea'], item['engagedSeconds'], item['visits'], item['pagesUsed']) for item in median['productAreaDistribution']],
            [('Core workspace', 2400, 22, 14), ('Project management', 1500, 13, 9)],
        )
        self.assertEqual(sum(item['percent'] for item in median['productAreaDistribution']), 100)
        self.assertTrue(all(cell['used'] for cell in median['productAreaAdoption']))

    @patch('apps.pages.company_analytics.build_companies_overview_payload')
    def test_companies_missing_cache_does_not_build_payload_synchronously(self, mock_build_payload):
        response = self.client.get(reverse('projects:project_companies', kwargs={'project_id': self.project.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Companies')
        self.assertContains(response, 'No data were found in the last 30 days.')
        self.assertNotContains(response, 'companies-overview-data')
        self.assertNotContains(response, 'js/companies/companies-analytics.js')
        mock_build_payload.assert_not_called()

    def test_expansion_opportunities_explain_distinct_signals(self):
        def row(name, active_users, avg_engaged, interaction, areas, distribution):
            return {
                'companyId': name.lower(),
                'companyName': name,
                'status': 'healthy',
                'activeUsers': active_users,
                'avgEngagedSecondsPerUser': avg_engaged,
                'interactionPct': interaction,
                'productAreasUsed': len(areas),
                'productAreas': areas,
                'productAreaDistribution': distribution,
                'engagedSeconds': active_users * avg_engaged,
            }

        rows = company_analytics._expansion_opportunities([
            row(
                'FocusedCo',
                20,
                1800,
                62,
                ['Projects', 'Workspace'],
                [{'product_area_name': 'Projects', 'percent': 78}],
            ),
            row(
                'GapCo',
                35,
                2200,
                58,
                ['Projects', 'Workspace'],
                [{'product_area_name': 'Projects', 'percent': 55}],
            ),
            row(
                'LargeCo',
                90,
                1700,
                56,
                ['Projects', 'Workspace', 'Reports', 'Admin'],
                [{'product_area_name': 'Workspace', 'percent': 35}],
            ),
            row(
                'DeepCo',
                30,
                5200,
                55,
                ['Projects', 'Workspace', 'Reports', 'Admin'],
                [{'product_area_name': 'Reports', 'percent': 40}],
            ),
        ])

        reasons = {item['companyName']: item['reason'] for item in rows}
        actions = {item['companyName']: item['suggestedAction'] for item in rows}

        self.assertEqual(reasons['FocusedCo'], 'Projects dominates usage')
        self.assertEqual(actions['FocusedCo'], 'Expand beyond Projects')
        self.assertEqual(reasons['GapCo'], 'No Reports adoption')
        self.assertEqual(actions['GapCo'], 'Introduce Reports workflow')
        self.assertEqual(reasons['LargeCo'], '90 active users')
        self.assertEqual(actions['LargeCo'], 'Identify team champions')
        self.assertGreaterEqual(len(set(reasons.values())), 4)
        self.assertGreaterEqual(len(set(actions.values())), 4)

    def test_expansion_recommendations_split_deep_usage_shapes(self):
        thresholds = {
            'p75_active_users': 25,
            'p50_active_users': 15,
            'p75_avg_engaged': 3600,
            'p50_avg_engaged': 1800,
        }
        common_areas = ['Projects', 'Workspace', 'Reports', 'Admin']

        def recommendation(active_users, avg_engaged, *, interaction=58, product_areas=4):
            row = {
                'activeUsers': active_users,
                'avgEngagedSecondsPerUser': avg_engaged,
                'interactionPct': interaction,
                'productAreasUsed': product_areas,
                'productAreas': common_areas[:product_areas],
                'productAreaDistribution': [{'product_area_name': 'Projects', 'percent': 40}],
            }
            return company_analytics._expansion_reason_and_action(row, thresholds, common_areas)

        recommendations = [
            recommendation(90, 14400),
            recommendation(55, 19000),
            recommendation(65, 12600),
            recommendation(45, 15000),
            recommendation(30, 7200, interaction=60),
        ]
        actions = [action for _reason, action in recommendations]

        self.assertEqual(recommendations[0], ('90 enterprise users engaged', 'Map executive expansion path'))
        self.assertEqual(recommendations[1], ('5h 17m/user depth', 'Design premium workflow rollout'))
        self.assertEqual(recommendations[2], ('4 areas broadly adopted', 'Package cross-area expansion'))
        self.assertEqual(recommendations[3], ('4h 10m/user engagement', 'Offer advanced workflow pilot'))
        self.assertEqual(recommendations[4], ('60% interaction rate', 'Target power-user workflows'))
        self.assertEqual(len(set(actions)), len(actions))

    def test_at_risk_suggested_actions_use_distinct_risk_signals(self):
        def action(reasons, *, current_users=4, previous_users=4, current_engaged=1200, previous_engaged=3600, current_areas=3, previous_areas=3):
            return company_analytics._suggested_action(
                reasons,
                {
                    'active_users': current_users,
                    'engaged_seconds': current_engaged,
                    'product_areas_used': current_areas,
                },
                {
                    'active_users': previous_users,
                    'engaged_seconds': previous_engaged,
                    'product_areas_used': previous_areas,
                },
            )

        suggestions = [
            action(['Only 1 active user'], current_users=1, previous_users=3),
            action(['Users dropped', 'Engaged drop'], current_users=2, previous_users=8, current_engaged=300, previous_engaged=4000),
            action(['Users dropped'], current_users=2, previous_users=8),
            action(['Engaged drop'], current_users=5, previous_users=5),
            action(['Product areas 4 -> 3'], current_engaged=1000, previous_engaged=3000, current_areas=3, previous_areas=4),
            action(['Product areas 4 -> 3'], current_engaged=4200, previous_engaged=3000, current_areas=3, previous_areas=4),
            action(['No activity 7d']),
        ]

        self.assertEqual(suggestions[0], 'Add backup champions')
        self.assertEqual(suggestions[1], 'Run user reactivation')
        self.assertEqual(suggestions[2], 'Rebuild active user base')
        self.assertEqual(suggestions[3], 'Review workflow value')
        self.assertEqual(suggestions[4], 'Restore lost workflows')
        self.assertEqual(suggestions[5], 'Expand adjacent workflows')
        self.assertEqual(suggestions[6], 'Schedule reactivation touchpoint')
        self.assertEqual(len(set(suggestions)), len(suggestions))

    def test_no_activity_suggested_actions_reflect_account_shape(self):
        def action(*, current_users, current_engaged, current_areas):
            return company_analytics._suggested_action(
                ['No activity 14d'],
                {
                    'active_users': current_users,
                    'engaged_seconds': current_engaged,
                    'product_areas_used': current_areas,
                },
                {},
            )

        suggestions = [
            action(current_users=89, current_engaged=864480, current_areas=4),
            action(current_users=18, current_engaged=123240, current_areas=3),
            action(current_users=23, current_engaged=21840, current_areas=2),
            action(current_users=6, current_engaged=31320, current_areas=2),
            action(current_users=8, current_engaged=30660, current_areas=2),
            action(current_users=4, current_engaged=1200, current_areas=1),
        ]

        self.assertEqual(suggestions[0], 'Reconnect recent power users')
        self.assertEqual(suggestions[1], 'Restart cross-area usage')
        self.assertEqual(suggestions[2], 'Re-engage active cohort')
        self.assertEqual(suggestions[3], 'Check account owner status')
        self.assertEqual(suggestions[4], 'Restart usage cadence')
        self.assertEqual(suggestions[5], 'Schedule reactivation touchpoint')
        self.assertEqual(len(set(suggestions)), len(suggestions))

    def test_new_and_reactivated_companies_keep_lifecycle_status(self):
        thresholds = {
            'start_date': self.start_date,
            'end_date': self.end_date,
            'p75_active_users': 2,
            'p75_avg_engaged': 300,
            'median_product_areas': 2,
        }
        new_row = {
            'company_id': 'newco',
            'active_users': 8,
            'engaged_seconds': 7200,
            'product_areas_used': 4,
            'last_seen_date': self.start_date,
            'selected_end_date': self.end_date,
        }
        reactivated_row = {
            'company_id': 'returnco',
            'active_users': 6,
            'engaged_seconds': 5400,
            'product_areas_used': 3,
            'last_seen_date': self.start_date,
            'selected_end_date': self.end_date,
        }

        new_status, new_reasons, is_new, is_reactivated = company_analytics._status_for_company(
            new_row,
            {},
            self.start_date,
            set(),
            set(),
            thresholds,
            30,
        )
        reactivated_status, reactivated_reasons, is_returning_new, is_returning_reactivated = company_analytics._status_for_company(
            reactivated_row,
            {},
            self.start_date - timedelta(days=60),
            set(),
            {'returnco'},
            thresholds,
            30,
        )

        self.assertEqual(new_status, 'new')
        self.assertEqual(new_reasons, [])
        self.assertEqual((is_new, is_reactivated), (True, False))
        self.assertEqual(reactivated_status, 'reactivated')
        self.assertEqual(reactivated_reasons, [])
        self.assertEqual((is_returning_new, is_returning_reactivated), (False, True))

    def test_power_company_requires_exceptional_usage_and_strong_user_mix(self):
        thresholds = {
            'start_date': self.start_date,
            'end_date': self.end_date,
            'p75_active_users': 4,
            'p90_active_users': 10,
            'p75_avg_engaged': 3000,
            'p90_avg_engaged': 6000,
            'median_product_areas': 2,
        }
        old_power_shape = {
            'company_id': 'old-powerco',
            'active_users': 5,
            'engaged_seconds': 5 * 4000,
            'product_areas_used': 2,
            'last_seen_date': self.end_date,
            'selected_end_date': self.end_date,
            'user_health_mix': {'power': 2, 'healthy': 3, 'light': 0, 'passive': 0, 'dropped': 0},
        }
        exceptional_shape = {
            'company_id': 'exceptionalco',
            'active_users': 12,
            'engaged_seconds': 12 * 7000,
            'product_areas_used': 3,
            'last_seen_date': self.end_date,
            'selected_end_date': self.end_date,
            'user_health_mix': {'power': 5, 'healthy': 4, 'light': 1, 'passive': 0, 'dropped': 0},
        }
        weak_mix_shape = {
            **exceptional_shape,
            'company_id': 'weakmixco',
            'user_health_mix': {'power': 1, 'healthy': 2, 'light': 7, 'passive': 0, 'dropped': 0},
        }

        old_status, *_ = company_analytics._status_for_company(
            old_power_shape,
            {},
            self.start_date - timedelta(days=60),
            set(),
            set(),
            thresholds,
            30,
        )
        exceptional_status, *_ = company_analytics._status_for_company(
            exceptional_shape,
            {},
            self.start_date - timedelta(days=60),
            set(),
            set(),
            thresholds,
            30,
        )
        weak_mix_status, *_ = company_analytics._status_for_company(
            weak_mix_shape,
            {},
            self.start_date - timedelta(days=60),
            set(),
            set(),
            thresholds,
            30,
        )

        self.assertEqual(old_status, 'healthy')
        self.assertEqual(exceptional_status, 'power')
        self.assertEqual(weak_mix_status, 'healthy')

    def test_company_user_health_thresholds_scale_with_period(self):
        weekly_power_thresholds = services.power_user_thresholds(7)
        monthly_power_thresholds = services.power_user_thresholds(30)
        weekly_power = {
            'visits': weekly_power_thresholds['visits'],
            'engaged': weekly_power_thresholds['engaged_seconds'],
            'areas': weekly_power_thresholds['product_areas'],
            'clicks': weekly_power_thresholds['visits'],
            'active_days': weekly_power_thresholds['active_days'],
        }
        monthly_power = {
            'visits': monthly_power_thresholds['visits'],
            'engaged': monthly_power_thresholds['engaged_seconds'],
            'areas': monthly_power_thresholds['product_areas'],
            'clicks': monthly_power_thresholds['visits'],
            'active_days': monthly_power_thresholds['active_days'],
        }

        self.assertEqual(
            company_analytics._user_health_status(
                weekly_power['visits'],
                weekly_power['engaged'],
                weekly_power['areas'],
                weekly_power['clicks'],
                weekly_power['active_days'],
                period_days=7,
            ),
            'power',
        )
        self.assertEqual(
            company_detail_analytics._company_user_health_status(
                weekly_power['visits'],
                weekly_power['engaged'],
                weekly_power['areas'],
                weekly_power['clicks'],
                weekly_power['active_days'],
                period_days=7,
            ),
            'power',
        )
        self.assertEqual(
            company_analytics._user_health_status(
                weekly_power['visits'],
                weekly_power['engaged'],
                weekly_power['areas'],
                weekly_power['clicks'],
                weekly_power['active_days'],
                period_days=30,
            ),
            'light',
        )
        self.assertEqual(
            company_detail_analytics._company_user_health_status(
                monthly_power['visits'],
                monthly_power['engaged'],
                monthly_power['areas'],
                monthly_power['clicks'],
                monthly_power['active_days'],
                period_days=30,
            ),
            'power',
        )

    def test_product_area_short_label_fallback_is_generic(self):
        compact = company_analytics._normalize_product_area_short_label

        self.assertEqual(compact('Core workspace', 'Core workspace'), 'CW')
        self.assertEqual(compact('Project management', 'Project management'), 'PM')
        self.assertEqual(compact('Workspace', 'Workspace'), 'Worksp.')
        self.assertEqual(compact('Reporting', 'Reports'), 'Reports')

    def test_existing_schema_one_cache_is_treated_as_stale(self):
        generated_at = timezone.now()
        CompaniesOverviewCache.objects.create(
            project=self.project,
            range_key='last_30_days',
            start_date=self.start_date,
            end_date=self.end_date,
            generated_at=generated_at,
            expires_at=generated_at + services.CACHE_TTL,
            payload_json={
                'schema_version': 1,
                'period': {
                    'range_key': 'last_30_days',
                    'start_date': self.start_date.isoformat(),
                    'end_date': self.end_date.isoformat(),
                    'days': 30,
                },
                'kpis': [{'label': 'Active companies', 'value': 1}],
                'productAreas': ['Billing'],
                'companies': [{'companyId': 'acme', 'companyName': 'Acme Inc.', 'productAreas': ['Billing']}],
            },
        )

        response = self.client.get(reverse('projects:project_companies', kwargs={'project_id': self.project.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No data were found in the last 30 days.')
        self.assertNotContains(response, 'companies-overview-data')

    def test_companies_period_query_selects_matching_range_without_client_redirect_roundtrip(self):
        response = self.client.get(
            reverse('projects:project_companies', kwargs={'project_id': self.project.id}),
            {'range': 'last_90_days', 'period': '180d'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No data were found in the last 180 days.')
        self.assertContains(response, 'href="?range=last_180_days"')

    def test_project_navigation_links_to_companies(self):
        response = self.client.get(reverse('projects:project_companies', kwargs={'project_id': self.project.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'/projects/{self.project.id}/companies/')
        self.assertContains(response, 'Companies')
