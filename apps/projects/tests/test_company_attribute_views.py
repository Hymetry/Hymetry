import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.pages import services as pages_services
from apps.pages.models import PageCompanyDailyMetric
from apps.projects.models import (
    CompanyAttribute,
    CompanyAttributeBooleanDisplay,
    CompanyAttributeMoneyCurrency,
    CompanyAttributeMoneyDisplay,
    CompanyAttributeNumberFormat,
    CompanyAttributeOption,
    CompanyAttributeOptionColor,
    CompanyAttributeType,
    CompanyAttributeValue,
    Project,
    Workspace,
    WorkspaceMemberRole,
    WorkspaceMemberStatus,
    WorkspaceMembership,
)


class CompanyAttributeViewTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='company-attribute-owner',
            email='attribute-owner@example.com',
            password='testpass123',
        )
        self.workspace = Workspace.objects.create(
            name='Attribute Workspace',
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
            name='Attribute Project',
            created_by=self.user,
            timezone='UTC',
        )
        self.client.force_login(self.user)
        self.start_date, self.end_date = pages_services.resolve_period(
            self.project.timezone,
            range_key='last_180_days',
        )

    def _route(self, name, **kwargs):
        return reverse(
            f'w:{name}',
            kwargs={
                'workspace_slug': self.workspace.slug,
                'project_id': self.project.id,
                **kwargs,
            },
        )

    def _legacy_route(self, name, **kwargs):
        return reverse(
            f'projects:{name}',
            kwargs={'project_id': self.project.id, **kwargs},
        )

    def _metric(self, company_id, name=None, *, date=None):
        return PageCompanyDailyMetric.objects.create(
            project=self.project,
            date=date or self.end_date,
            company_id=company_id,
            company_name_sample=name if name is not None else company_id,
        )

    def _attribute(self, name, attribute_type, position, **settings):
        defaults = {
            'project': self.project,
            'name': name,
            'attribute_type': attribute_type,
            'position': position,
        }
        if attribute_type == CompanyAttributeType.NUMBER:
            defaults.update(number_format=CompanyAttributeNumberFormat.PLAIN, decimal_places=0)
        elif attribute_type == CompanyAttributeType.MONEY:
            defaults.update(
                currency=CompanyAttributeMoneyCurrency.USD,
                money_display=CompanyAttributeMoneyDisplay.COMPACT,
            )
        elif attribute_type == CompanyAttributeType.BOOLEAN:
            defaults.update(boolean_display=CompanyAttributeBooleanDisplay.YES_NO)
        defaults.update(settings)
        return CompanyAttribute.objects.create(**defaults)

    def _table(self, **params):
        response = self.client.get(self._route('project_company_attributes_table_data'), params)
        self.assertEqual(response.status_code, 200)
        return response.json()['table']

    def _post_json(self, route_name, payload, **kwargs):
        return self.client.post(
            self._route(route_name, **kwargs),
            data=json.dumps(payload),
            content_type='application/json',
        )

    def test_page_renders_real_manager_without_preview_state_picker(self):
        response = self.client.get(self._route('project_company_attributes'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Company attributes')
        self.assertContains(response, 'data-manage-attributes-open', html=False)
        self.assertContains(response, 'data-attributes-manager', html=False)
        self.assertContains(response, 'data-attributes-discard-modal', html=False)
        self.assertContains(response, 'role="alertdialog"', html=False)
        self.assertContains(response, 'Discard unsaved changes?')
        self.assertContains(response, 'data-attributes-keep-editing', html=False)
        self.assertContains(response, 'data-attributes-discard-changes', html=False)
        self.assertNotContains(response, 'Preview state')
        self.assertNotContains(response, 'data-manage-attributes-state', html=False)
        payload = json.loads(str(response.context['company_attributes_payload_json']))
        self.assertFalse(payload['state']['has_companies'])
        self.assertFalse(payload['state']['has_attributes'])

    def test_legacy_page_route_remains_available(self):
        response = self.client.get(self._legacy_route('project_company_attributes'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Company attributes')

    def test_viewer_cannot_access_page_or_mutations(self):
        viewer = get_user_model().objects.create_user(
            username='company-attribute-viewer',
            email='attribute-viewer@example.com',
            password='testpass123',
        )
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=viewer,
            role=WorkspaceMemberRole.VIEWER,
            status=WorkspaceMemberStatus.ACTIVE,
        )
        self.client.force_login(viewer)

        page_response = self.client.get(self._route('project_company_attributes'))
        save_response = self._post_json(
            'save_project_company_attributes',
            {'attributes': [], 'deleted_ids': []},
        )

        self.assertEqual(page_response.status_code, 403)
        self.assertEqual(save_response.status_code, 403)

    def test_member_can_access_and_save_project_attributes(self):
        member = get_user_model().objects.create_user(
            username='company-attribute-member',
            email='attribute-member@example.com',
            password='testpass123',
        )
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=member,
            role=WorkspaceMemberRole.MEMBER,
            status=WorkspaceMemberStatus.ACTIVE,
        )
        self.client.force_login(member)

        page_response = self.client.get(self._route('project_company_attributes'))
        save_response = self._post_json(
            'save_project_company_attributes',
            {
                'attributes': [
                    {
                        'client_id': 'draft-1',
                        'name': 'Owner',
                        'type': 'text',
                        'position': 0,
                        'settings': {},
                        'options': [],
                    },
                ],
                'deleted_ids': [],
            },
        )

        self.assertEqual(page_response.status_code, 200)
        self.assertEqual(save_response.status_code, 200)
        self.assertTrue(CompanyAttribute.objects.filter(project=self.project, name='Owner').exists())

    def test_table_uses_inclusive_last_180_project_days(self):
        self._metric('first-day', 'First day', date=self.start_date)
        self._metric('too-old', 'Too old', date=self.start_date - timedelta(days=1))
        self._metric('today', 'Today', date=self.end_date)

        table = self._table()

        self.assertEqual([row['id'] for row in table['companies']], ['first-day', 'today'])
        self.assertEqual(table['pagination']['total'], 2)

    def test_search_matches_only_display_company_name(self):
        self._metric('needle-id', 'Acme Health')
        attribute = self._attribute('Notes', CompanyAttributeType.TEXT, 0)
        CompanyAttributeValue.objects.create(
            attribute=attribute,
            company_id='needle-id',
            text_value='needle attribute value',
        )

        by_name = self._table(q='acme')
        by_id = self._table(q='needle-id')
        by_attribute = self._table(q='needle attribute')

        self.assertEqual([row['id'] for row in by_name['companies']], ['needle-id'])
        self.assertEqual(by_id['companies'], [])
        self.assertEqual(by_attribute['companies'], [])

    def test_company_sort_and_pagination_are_stable(self):
        for index in range(11):
            self._metric(f'company-{index:02d}', f'Company {index:02d}')

        first = self._table(sort='company', direction='desc', page=1)
        second = self._table(sort='company', direction='desc', page=2)

        self.assertEqual(first['pagination']['total'], 11)
        self.assertEqual(first['pagination']['total_pages'], 2)
        self.assertEqual(len(first['companies']), 10)
        self.assertEqual(first['companies'][0]['name'], 'Company 10')
        self.assertEqual([row['name'] for row in second['companies']], ['Company 00'])

    def test_every_attribute_type_sorts_natively_with_missing_values_last(self):
        for company_id, name in (
            ('company-low', 'Company low'),
            ('company-high', 'Company high'),
            ('company-empty', 'Company empty'),
        ):
            self._metric(company_id, name)

        text = self._attribute('Text', CompanyAttributeType.TEXT, 0)
        number = self._attribute('Number', CompanyAttributeType.NUMBER, 1)
        money = self._attribute('Money', CompanyAttributeType.MONEY, 2)
        date = self._attribute('Date', CompanyAttributeType.DATE, 3)
        boolean = self._attribute('Boolean', CompanyAttributeType.BOOLEAN, 4)
        select = self._attribute('Select', CompanyAttributeType.SINGLE_SELECT, 5)
        low_option = CompanyAttributeOption.objects.create(attribute=select, label='Alpha', position=0)
        high_option = CompanyAttributeOption.objects.create(attribute=select, label='Zulu', position=1)

        low_values = {
            text: {'text_value': 'alpha'},
            number: {'decimal_value': Decimal('2')},
            money: {'decimal_value': Decimal('10.25')},
            date: {'date_value': self.start_date},
            boolean: {'boolean_value': False},
            select: {'option': low_option},
        }
        high_values = {
            text: {'text_value': 'Zulu'},
            number: {'decimal_value': Decimal('20')},
            money: {'decimal_value': Decimal('100.25')},
            date: {'date_value': self.end_date},
            boolean: {'boolean_value': True},
            select: {'option': high_option},
        }
        for attribute, defaults in low_values.items():
            CompanyAttributeValue.objects.create(
                attribute=attribute,
                company_id='company-low',
                **defaults,
            )
        for attribute, defaults in high_values.items():
            CompanyAttributeValue.objects.create(
                attribute=attribute,
                company_id='company-high',
                **defaults,
            )

        for attribute in (text, number, money, date, boolean, select):
            with self.subTest(attribute=attribute.name, direction='asc'):
                ascending = self._table(sort=f'attr:{attribute.id}', direction='asc')
                self.assertEqual(
                    [row['id'] for row in ascending['companies']],
                    ['company-low', 'company-high', 'company-empty'],
                )
            with self.subTest(attribute=attribute.name, direction='desc'):
                descending = self._table(sort=f'attr:{attribute.id}', direction='desc')
                self.assertEqual(
                    [row['id'] for row in descending['companies']],
                    ['company-high', 'company-low', 'company-empty'],
                )

    def test_unknown_sort_falls_back_to_company(self):
        self._metric('b', 'Beta')
        self._metric('a', 'Alpha')

        table = self._table(sort='attr:999999', direction='sideways')

        self.assertEqual(table['sort'], {'key': 'company', 'direction': 'asc'})
        self.assertEqual([row['name'] for row in table['companies']], ['Alpha', 'Beta'])

    def test_definition_endpoint_returns_all_validation_errors_without_writes(self):
        response = self._post_json(
            'save_project_company_attributes',
            {
                'attributes': [
                    {'client_id': 'first', 'name': '', 'type': 'text', 'settings': {}, 'options': []},
                    {'client_id': 'second', 'name': '', 'type': 'single_select', 'settings': {}, 'options': []},
                ],
                'deleted_ids': [],
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('name', response.json()['errors']['first'])
        self.assertIn('name', response.json()['errors']['second'])
        self.assertIn('options', response.json()['errors']['second'])
        self.assertFalse(CompanyAttribute.objects.filter(project=self.project).exists())

    def test_definition_endpoint_rejects_invalid_json(self):
        response = self.client.post(
            self._route('save_project_company_attributes'),
            data='{not-json',
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('_payload', response.json()['errors'])

    def test_value_endpoint_saves_and_clears_a_value(self):
        self._metric('acme', 'Acme')
        attribute = self._attribute('Owner', CompanyAttributeType.TEXT, 0)

        save_response = self._post_json(
            'save_project_company_attribute_values',
            {'values': {str(attribute.id): 'Ada'}},
            company_id='acme',
        )

        self.assertEqual(save_response.status_code, 200)
        self.assertEqual(save_response.json()['values'][str(attribute.id)]['raw'], 'Ada')
        self.assertTrue(
            CompanyAttributeValue.objects.filter(
                attribute=attribute,
                company_id='acme',
                text_value='Ada',
            ).exists(),
        )

        clear_response = self._post_json(
            'save_project_company_attribute_values',
            {'values': {str(attribute.id): ''}},
            company_id='acme',
        )

        self.assertEqual(clear_response.status_code, 200)
        self.assertFalse(CompanyAttributeValue.objects.filter(attribute=attribute, company_id='acme').exists())
        self.assertTrue(clear_response.json()['values'][str(attribute.id)]['is_empty'])

    def test_value_endpoint_reports_typed_errors_by_attribute(self):
        self._metric('acme', 'Acme')
        number = self._attribute('Employees', CompanyAttributeType.NUMBER, 0)
        date = self._attribute('Renewal', CompanyAttributeType.DATE, 1)

        response = self._post_json(
            'save_project_company_attribute_values',
            {'values': {str(number.id): 'many', str(date.id): 'tomorrow'}},
            company_id='acme',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(str(number.id), response.json()['errors'])
        self.assertIn(str(date.id), response.json()['errors'])
        self.assertFalse(CompanyAttributeValue.objects.filter(attribute__project=self.project).exists())

    def test_value_endpoint_rejects_company_outside_visible_window(self):
        attribute = self._attribute('Owner', CompanyAttributeType.TEXT, 0)
        self._metric('old-company', 'Old company', date=self.start_date - timedelta(days=1))

        response = self._post_json(
            'save_project_company_attribute_values',
            {'values': {str(attribute.id): 'Ada'}},
            company_id='old-company',
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(CompanyAttributeValue.objects.filter(attribute=attribute).exists())
