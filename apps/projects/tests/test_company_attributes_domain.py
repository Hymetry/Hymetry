from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.pages.models import PagesOverviewCache
from apps.projects.company_attributes import (
    CompanyAttributeValidationError,
    display_company_attribute_value,
    save_attribute_definitions,
    save_company_attribute_values,
    serialize_attributes,
    serialize_company_attribute_value,
    sort_company_attribute_value,
)
from apps.projects.models import (
    COMPANY_ATTRIBUTE_OPTION_COLOR_PALETTE,
    CompanyAttribute,
    CompanyAttributeMoneyCurrency,
    CompanyAttributeOption,
    CompanyAttributeOptionColor,
    CompanyAttributeType,
    CompanyAttributeValue,
    Project,
    Workspace,
)


class CompanyAttributeDomainTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='attribute-owner',
            email='attributes@example.com',
            password='testpass123',
        )
        self.workspace = Workspace.objects.create(
            name='Attribute Workspace',
            website_url='example.com',
            created_by=self.user,
        )
        self.project = Project.objects.create(
            workspace=self.workspace,
            name='Attribute Project',
            created_by=self.user,
        )
        self.other_project = Project.objects.create(
            workspace=self.workspace,
            name='Other Project',
            created_by=self.user,
        )

    def _create(self, *attributes, project=None, deleted_ids=None):
        return save_attribute_definitions(
            project or self.project,
            {
                'attributes': list(attributes),
                'deleted_ids': deleted_ids or [],
            },
        )

    def _text(self, name='Notes', client_id='notes'):
        return {'client_id': client_id, 'name': name, 'type': 'text', 'settings': {}, 'options': []}

    def _number(self, name='Employees', client_id='employees'):
        return {
            'client_id': client_id,
            'name': name,
            'type': 'number',
            'settings': {'format': 'plain', 'decimal_places': 0},
            'options': [],
        }

    def _money(self, name='ARR', client_id='arr', currency='USD'):
        return {
            'client_id': client_id,
            'name': name,
            'type': 'money',
            'settings': {'currency': currency, 'display_format': 'compact'},
            'options': [],
        }

    def _single_select(self, name='Plan', client_id='plan'):
        return {
            'client_id': client_id,
            'name': name,
            'type': 'single-select',
            'settings': {},
            'options': [
                {
                    'client_id': 'free',
                    'label': 'Free',
                    'color': dict(COMPANY_ATTRIBUTE_OPTION_COLOR_PALETTE[CompanyAttributeOptionColor.CYAN]),
                },
                {'client_id': 'pro', 'label': 'Pro', 'color': 'violet'},
            ],
        }

    def test_creates_and_serializes_all_types_with_exact_settings_contract(self):
        result = self._create(
            self._text(),
            self._number(),
            self._money(),
            {
                'client_id': 'renewal',
                'name': 'Renewal',
                'type': 'date',
                'settings': {},
                'options': [],
            },
            {
                'client_id': 'strategic',
                'name': 'Strategic',
                'type': 'boolean',
                'settings': {'display_style': 'checkmark_dash'},
                'options': [],
            },
            self._single_select(),
        )

        self.assertEqual([item['position'] for item in result], list(range(6)))
        self.assertEqual(result[1]['settings'], {'format': 'plain', 'decimal_places': 0})
        self.assertEqual(result[2]['settings'], {'currency': 'USD', 'display_format': 'compact'})
        self.assertEqual(result[4]['settings'], {'display_style': 'checkmark_dash'})
        self.assertEqual(result[5]['type'], 'single_select')
        self.assertEqual(result[5]['options'][0]['color'], {
            'text': '#0E7490',
            'bg': '#CFFAFE',
            'border': '#A5F3FC',
        })
        self.assertEqual(CompanyAttribute.objects.filter(project=self.project).count(), 6)

    def test_supports_the_complete_ordered_money_currency_list(self):
        expected = [
            'USD', 'EUR', 'GBP', 'AED', 'AUD', 'BGN', 'BRL', 'CAD', 'CHF', 'CNY',
            'CZK', 'DKK', 'HKD', 'HUF', 'ILS', 'INR', 'JPY', 'KRW', 'MXN', 'NOK',
            'NZD', 'PLN', 'RON', 'SAR', 'SEK', 'SGD', 'TRY', 'UAH', 'ZAR',
        ]
        self.assertEqual(list(CompanyAttributeMoneyCurrency.values), expected)

        result = self._create(*[
            self._money(name=currency, client_id=currency.lower(), currency=currency)
            for currency in expected
        ])
        self.assertEqual([item['settings']['currency'] for item in result], expected)

        uah = CompanyAttribute.objects.get(project=self.project, name='UAH')
        value = save_company_attribute_values(self.project, 'acme', {uah.id: '1200'})[0]
        self.assertEqual(display_company_attribute_value(uah, value), 'UAH 1.2K')

    def test_validation_aggregates_multiple_attribute_errors_and_is_atomic(self):
        with self.assertRaises(CompanyAttributeValidationError) as raised:
            self._create(
                {'client_id': 'first', 'name': '', 'type': 'number', 'settings': {'format': 'wat'}},
                {'client_id': 'second', 'name': '', 'type': 'single_select', 'options': []},
            )

        self.assertIn('name', raised.exception.errors['first'])
        self.assertIn('settings.format', raised.exception.errors['first'])
        self.assertIn('name', raised.exception.errors['second'])
        self.assertIn('options', raised.exception.errors['second'])
        self.assertFalse(CompanyAttribute.objects.filter(project=self.project).exists())

    def test_decimal_places_rejects_fractional_and_boolean_json_values(self):
        for invalid_value in (1.5, True):
            with self.subTest(invalid_value=invalid_value):
                draft = self._number()
                draft['settings']['decimal_places'] = invalid_value
                with self.assertRaises(CompanyAttributeValidationError) as raised:
                    self._create(draft)
                self.assertIn('settings.decimal_places', raised.exception.errors['employees'])

    def test_names_are_case_insensitively_unique_within_project(self):
        with self.assertRaises(CompanyAttributeValidationError) as raised:
            self._create(self._text('Owner', 'one'), self._text(' owner ', 'two'))

        self.assertIn('name', raised.exception.errors['one'])
        self.assertIn('name', raised.exception.errors['two'])

        self._create(self._text('Owner'), project=self.project)
        self._create(self._text('owner'), project=self.other_project)
        self.assertEqual(CompanyAttribute.objects.filter(name__iexact='owner').count(), 2)

    def test_database_constraint_also_guards_case_insensitive_names(self):
        CompanyAttribute.objects.create(
            project=self.project,
            name='Region',
            attribute_type=CompanyAttributeType.TEXT,
        )
        with self.assertRaises(ValidationError):
            CompanyAttribute.objects.create(
                project=self.project,
                name='REGION',
                attribute_type=CompanyAttributeType.TEXT,
            )

    def test_type_is_immutable_in_domain_and_model_paths(self):
        created = self._create(self._text())[0]
        attribute = CompanyAttribute.objects.get(pk=created['id'])
        changed = dict(created)
        changed['type'] = 'date'

        with self.assertRaises(CompanyAttributeValidationError) as raised:
            self._create(changed)
        self.assertIn('type', raised.exception.errors[str(attribute.id)])

        attribute.attribute_type = CompanyAttributeType.DATE
        with self.assertRaises(ValidationError):
            attribute.save()
        attribute.refresh_from_db()
        self.assertEqual(attribute.attribute_type, CompanyAttributeType.TEXT)

    def test_cross_project_definition_and_delete_ids_are_rejected(self):
        foreign = self._create(self._text(), project=self.other_project)[0]
        with self.assertRaises(CompanyAttributeValidationError):
            self._create({'id': foreign['id'], 'name': 'Changed', 'type': 'text'})
        with self.assertRaises(CompanyAttributeValidationError):
            self._create(deleted_ids=[foreign['id']])
        self.assertTrue(CompanyAttribute.objects.filter(pk=foreign['id']).exists())

    def test_omitting_definition_preserves_it_and_explicit_delete_removes_it(self):
        created = self._create(self._text(), self._number())
        notes_id, employees_id = (item['id'] for item in created)

        save_attribute_definitions(self.project, {'attributes': [created[0]], 'deleted_ids': []})
        self.assertEqual(
            list(CompanyAttribute.objects.filter(project=self.project).values_list('id', flat=True)),
            [notes_id, employees_id],
        )

        save_attribute_definitions(self.project, {'attributes': [created[0]], 'deleted_ids': [employees_id]})
        self.assertEqual(
            list(CompanyAttribute.objects.filter(project=self.project).values_list('id', flat=True)),
            [notes_id],
        )

    def test_reorders_attributes_and_allows_atomic_name_swap(self):
        first, second = self._create(self._text('First', 'first'), self._text('Second', 'second'))
        first['name'] = 'Second'
        second['name'] = 'First'

        result = self._create(second, first)

        self.assertEqual([item['name'] for item in result], ['First', 'Second'])
        self.assertEqual([item['id'] for item in result], [second['id'], first['id']])
        self.assertEqual([item['position'] for item in result], [0, 1])

    def test_option_labels_are_unique_and_color_must_come_from_palette(self):
        draft = self._single_select()
        draft['options'][1]['label'] = ' free '
        draft['options'][1]['color'] = {'text': '#000', 'bg': '#fff', 'border': '#aaa'}

        with self.assertRaises(CompanyAttributeValidationError) as raised:
            self._create(draft)

        self.assertIn('options.1.label', raised.exception.errors['plan'])
        self.assertIn('options.1.color', raised.exception.errors['plan'])

    def test_removing_used_option_deletes_values_on_definition_save(self):
        serialized = self._create(self._single_select())[0]
        attribute = CompanyAttribute.objects.get(pk=serialized['id'])
        free_option, pro_option = attribute.options.all()
        save_company_attribute_values(self.project, 'acme', {attribute.id: pro_option.id})
        self.assertTrue(CompanyAttributeValue.objects.filter(attribute=attribute, company_id='acme').exists())

        serialized['options'] = [serialized['options'][0]]
        self._create(serialized)

        self.assertTrue(CompanyAttributeOption.objects.filter(pk=free_option.id).exists())
        self.assertFalse(CompanyAttributeOption.objects.filter(pk=pro_option.id).exists())
        self.assertFalse(CompanyAttributeValue.objects.filter(attribute=attribute, company_id='acme').exists())

    def test_changing_money_currency_does_not_convert_existing_amount(self):
        serialized = self._create(self._money())[0]
        save_company_attribute_values(self.project, 'acme', {serialized['id']: '1200.50'})
        serialized['settings']['currency'] = 'EUR'

        self._create(serialized)

        value = CompanyAttributeValue.objects.get(attribute_id=serialized['id'], company_id='acme')
        self.assertEqual(value.decimal_value, Decimal('1200.5000000000'))
        self.assertEqual(value.attribute.currency, 'EUR')

    def test_saves_and_serializes_each_typed_company_value(self):
        definitions = self._create(
            self._text(),
            {**self._number(), 'settings': {'format': 'percentage', 'decimal_places': 1}},
            self._money(),
            {'client_id': 'renewal', 'name': 'Renewal', 'type': 'date'},
            {
                'client_id': 'strategic',
                'name': 'Strategic',
                'type': 'boolean',
                'settings': {'display_style': 'yes_no'},
            },
            self._single_select(),
        )
        by_name = {item['name']: item for item in definitions}
        pro_id = by_name['Plan']['options'][1]['id']

        values = save_company_attribute_values(self.project, 'acme', {
            by_name['Notes']['id']: 'Important customer',
            by_name['Employees']['id']: '91.25',
            by_name['ARR']['id']: '1250000',
            by_name['Renewal']['id']: '2027-01-15',
            by_name['Strategic']['id']: False,
            by_name['Plan']['id']: pro_id,
        })

        self.assertEqual(len(values), 6)
        values_by_name = {value.attribute.name: value for value in values}
        self.assertEqual(values_by_name['Notes'].text_value, 'Important customer')
        self.assertEqual(values_by_name['Employees'].decimal_value, Decimal('91.2500000000'))
        self.assertEqual(values_by_name['Renewal'].date_value, date(2027, 1, 15))
        self.assertIs(values_by_name['Strategic'].boolean_value, False)
        self.assertEqual(values_by_name['Plan'].option_id, pro_id)

        self.assertEqual(serialize_company_attribute_value(values_by_name['Employees'])['raw'], '91.25')
        self.assertEqual(display_company_attribute_value(values_by_name['Employees'].attribute, values_by_name['Employees']), '91.3%')
        self.assertEqual(display_company_attribute_value(values_by_name['ARR'].attribute, values_by_name['ARR']), '$1.3M')
        self.assertEqual(serialize_company_attribute_value(values_by_name['Plan'])['color'], {
            'text': '#6D28D9',
            'bg': '#EDE9FE',
            'border': '#DDD6FE',
        })
        self.assertEqual(sort_company_attribute_value(values_by_name['Notes']), 'important customer')
        self.assertEqual(sort_company_attribute_value(values_by_name['Renewal']), date(2027, 1, 15))

    def test_blank_values_clear_existing_rows_including_whitespace(self):
        notes, strategic = self._create(
            self._text(),
            {
                'client_id': 'strategic',
                'name': 'Strategic',
                'type': 'boolean',
                'settings': {'display_style': 'yes_no'},
            },
        )
        save_company_attribute_values(self.project, 'acme', {
            notes['id']: 'hello',
            strategic['id']: True,
        })

        save_company_attribute_values(self.project, 'acme', {
            notes['id']: '   ',
            strategic['id']: None,
        })

        self.assertFalse(CompanyAttributeValue.objects.filter(company_id='acme').exists())

    def test_value_save_invalidates_only_filtered_overview_cache_variants(self):
        attribute = CompanyAttribute.objects.create(
            project=self.project,
            name='Owner',
            attribute_type=CompanyAttributeType.TEXT,
        )
        now = timezone.now()
        for filters_hash in ('default', 'filtered-cohort-hash'):
            PagesOverviewCache.objects.create(
                project=self.project,
                range_key='last_30_days',
                start_date=now.date() - timedelta(days=29),
                end_date=now.date(),
                filters_hash=filters_hash,
                payload_json={},
                generated_at=now,
                expires_at=now + timedelta(hours=1),
            )

        with self.captureOnCommitCallbacks(execute=True):
            save_company_attribute_values(
                self.project,
                'acme',
                {attribute.id: 'Ada'},
            )
        self.project.refresh_from_db()

        self.assertTrue(
            PagesOverviewCache.objects.filter(
                project=self.project,
                filters_hash='default',
            ).exists(),
        )
        self.assertEqual(self.project.filtered_analytics_revision, 1)
        self.assertFalse(
            PagesOverviewCache.objects.filter(
                project=self.project,
                filters_hash='filtered-cohort-hash',
            ).exists(),
        )

    def test_value_validation_is_aggregate_and_atomic(self):
        number, renewal = self._create(
            self._number(),
            {'client_id': 'renewal', 'name': 'Renewal', 'type': 'date'},
        )
        save_company_attribute_values(self.project, 'acme', {number['id']: '10'})
        self.project.refresh_from_db()
        revision_before_invalid_save = self.project.filtered_analytics_revision

        with self.assertRaises(CompanyAttributeValidationError) as raised:
            save_company_attribute_values(self.project, 'acme', {
                number['id']: 'not-a-number',
                renewal['id']: '31/12/2027',
            })

        self.assertIn('value', raised.exception.errors[str(number['id'])])
        self.assertIn('value', raised.exception.errors[str(renewal['id'])])
        self.assertEqual(
            CompanyAttributeValue.objects.get(attribute_id=number['id'], company_id='acme').decimal_value,
            Decimal('10.0000000000'),
        )
        self.project.refresh_from_db()
        self.assertEqual(
            self.project.filtered_analytics_revision,
            revision_before_invalid_save,
        )

    def test_value_save_rejects_cross_project_attribute_and_too_long_company_id(self):
        foreign = self._create(self._text(), project=self.other_project)[0]
        with self.assertRaises(CompanyAttributeValidationError) as raised:
            save_company_attribute_values(self.project, 'acme', {foreign['id']: 'secret'})
        self.assertIn('attribute_id', raised.exception.errors[str(foreign['id'])])

        with self.assertRaises(CompanyAttributeValidationError) as raised:
            save_company_attribute_values(self.project, 'x' * 256, {})
        self.assertIn('company_id', raised.exception.errors['_payload'])

    def test_model_rejects_wrong_typed_column_and_foreign_option(self):
        text = CompanyAttribute.objects.create(
            project=self.project,
            name='Notes',
            attribute_type=CompanyAttributeType.TEXT,
        )
        select = CompanyAttribute.objects.create(
            project=self.project,
            name='Plan',
            attribute_type=CompanyAttributeType.SINGLE_SELECT,
        )
        option = CompanyAttributeOption.objects.create(attribute=select, label='Pro', color='violet')

        with self.assertRaises(ValidationError):
            CompanyAttributeValue.objects.create(attribute=text, company_id='acme', decimal_value=Decimal('1'))
        with self.assertRaises(ValidationError):
            CompanyAttributeValue.objects.create(attribute=text, company_id='acme', option=option)

    def test_database_unique_value_constraint_prevents_duplicate_company_value(self):
        attribute = CompanyAttribute.objects.create(
            project=self.project,
            name='Notes',
            attribute_type=CompanyAttributeType.TEXT,
        )
        CompanyAttributeValue.objects.create(attribute=attribute, company_id='acme', text_value='one')
        with self.assertRaises(ValidationError):
            CompanyAttributeValue.objects.create(attribute=attribute, company_id='acme', text_value='two')

    def test_serialize_attributes_is_project_scoped(self):
        self._create(self._text('First'), project=self.project)
        self._create(self._text('Other'), project=self.other_project)

        self.assertEqual([item['name'] for item in serialize_attributes(self.project)], ['First'])
