import json
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.pages import services as pages_services
from apps.pages.models import PageVisit
from apps.projects.company_segments import (
    CompanySegmentValidationError,
    company_segment_match_counts,
    create_company_segment,
    normalize_segment_definition,
)
from apps.projects.models import (
    CompanyAttribute,
    CompanyAttributeMoneyCurrency,
    CompanyAttributeMoneyDisplay,
    CompanyAttributeOption,
    CompanyAttributeType,
    CompanyAttributeValue,
    CompanySegment,
    Project,
    Workspace,
    WorkspaceMemberRole,
    WorkspaceMemberStatus,
    WorkspaceMembership,
)


class CompanySegmentTestCase(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='segment-owner',
            email='segment-owner@example.com',
            password='testpass123',
        )
        self.other_user = user_model.objects.create_user(
            username='segment-teammate',
            email='segment-teammate@example.com',
            password='testpass123',
        )
        self.workspace = Workspace.objects.create(
            name='Segment Workspace',
            website_url='example.com',
            created_by=self.user,
        )
        for member in (self.user, self.other_user):
            WorkspaceMembership.objects.create(
                workspace=self.workspace,
                user=member,
                role=WorkspaceMemberRole.OWNER if member is self.user else WorkspaceMemberRole.MEMBER,
                status=WorkspaceMemberStatus.ACTIVE,
            )
        self.project = Project.objects.create(
            workspace=self.workspace,
            name='Segment Project',
            created_by=self.user,
            timezone='UTC',
        )
        self.plan = CompanyAttribute.objects.create(
            project=self.project,
            name='Plan',
            attribute_type=CompanyAttributeType.SINGLE_SELECT,
            position=0,
        )
        self.enterprise = CompanyAttributeOption.objects.create(
            attribute=self.plan,
            label='Enterprise',
            position=0,
        )
        self.business = CompanyAttributeOption.objects.create(
            attribute=self.plan,
            label='Business',
            position=1,
        )
        self.arr = CompanyAttribute.objects.create(
            project=self.project,
            name='ARR',
            attribute_type=CompanyAttributeType.MONEY,
            position=1,
            currency=CompanyAttributeMoneyCurrency.USD,
            money_display=CompanyAttributeMoneyDisplay.COMPACT,
        )
        self.client.force_login(self.user)

    def route(self, name, **kwargs):
        return reverse(
            f'w:{name}',
            kwargs={
                'workspace_slug': self.workspace.slug,
                'project_id': self.project.id,
                **kwargs,
            },
        )

    def post_json(self, url, payload=None):
        return self.client.post(
            url,
            data=json.dumps(payload or {}),
            content_type='application/json',
        )

    def enterprise_definition(self):
        return {str(self.plan.id): {'op': 'in', 'values': [str(self.enterprise.id)]}}

    def visit(self, company_id):
        start_date, end_date = pages_services.resolve_period(
            self.project.timezone,
            range_key='last_30_days',
        )
        start_ts, _end_ts = pages_services._utc_bounds_for_local_dates(
            start_date,
            end_date,
            self.project.timezone,
        )
        visit_start = start_ts + timedelta(hours=1)
        return PageVisit.objects.create(
            project=self.project,
            session_id=uuid.uuid4(),
            company_id=company_id,
            company_name_sample=company_id,
            visit_start_ts=visit_start,
            visit_end_ts=visit_start + timedelta(minutes=5),
        )

    def set_plan(self, company_id, option):
        return CompanyAttributeValue.objects.create(
            attribute=self.plan,
            company_id=company_id,
            option=option,
        )


class CompanySegmentDomainTests(CompanySegmentTestCase):
    def test_definition_is_stored_in_the_existing_canonical_filter_format(self):
        segment = create_company_segment(
            self.project,
            self.user,
            '  Enterprise Europe  ',
            {
                str(self.plan.id): {
                    'op': 'in',
                    'values': [str(self.business.id), str(self.enterprise.id)],
                },
                str(self.arr.id): {'op': 'gte', 'value': '250000.00'},
            },
        )

        self.assertEqual(segment.name, 'Enterprise Europe')
        self.assertEqual(
            segment.definition,
            {
                str(self.plan.id): {
                    'op': 'in',
                    'values': sorted(
                        [str(self.business.id), str(self.enterprise.id)],
                        key=int,
                    ),
                },
                str(self.arr.id): {'op': 'gte', 'value': '250000'},
            },
        )

    def test_empty_and_invalid_definitions_are_rejected(self):
        with self.assertRaises(CompanySegmentValidationError):
            normalize_segment_definition(self.project, {})
        with self.assertRaises(CompanySegmentValidationError):
            normalize_segment_definition(
                self.project,
                {str(self.arr.id): {'op': 'gte', 'value': 'not-a-number'}},
            )
        with self.assertRaises(CompanySegmentValidationError):
            normalize_segment_definition(
                self.project,
                {str(self.plan.id): {'op': 'in', 'values': []}},
            )

    def test_names_are_unique_per_user_but_not_across_users(self):
        create_company_segment(self.project, self.user, 'Enterprise Europe', self.enterprise_definition())

        with self.assertRaises(CompanySegmentValidationError):
            create_company_segment(
                self.project,
                self.user,
                'enterprise europe',
                self.enterprise_definition(),
            )

        teammate_segment = create_company_segment(
            self.project,
            self.other_user,
            'Enterprise Europe',
            self.enterprise_definition(),
        )
        self.assertEqual(teammate_segment.name, 'Enterprise Europe')

    def test_match_counts_are_resolved_for_all_segments_at_once(self):
        self.set_plan('acme', self.enterprise)
        self.set_plan('globex', self.business)
        enterprise_segment = create_company_segment(
            self.project,
            self.user,
            'Enterprise',
            self.enterprise_definition(),
        )
        empty_segment = create_company_segment(
            self.project,
            self.user,
            'Never matches',
            {str(self.arr.id): {'op': 'gte', 'value': '999999999'}},
        )

        counts = company_segment_match_counts(
            self.project,
            [enterprise_segment, empty_segment],
            ['acme', 'globex', 'initech'],
        )

        self.assertEqual(counts[enterprise_segment.id], 1)
        self.assertEqual(counts[empty_segment.id], 0)

    def test_an_attribute_named_company_segment_stays_an_ordinary_attribute(self):
        literal = CompanyAttribute.objects.create(
            project=self.project,
            name='Company segment',
            attribute_type=CompanyAttributeType.SINGLE_SELECT,
            position=2,
        )
        option = CompanyAttributeOption.objects.create(attribute=literal, label='North', position=0)

        segment = create_company_segment(
            self.project,
            self.user,
            'North accounts',
            {str(literal.id): {'op': 'in', 'values': [str(option.id)]}},
        )

        self.assertEqual(
            segment.definition,
            {str(literal.id): {'op': 'in', 'values': [str(option.id)]}},
        )


class CompanySegmentScopeTests(CompanySegmentTestCase):
    """Scope resolution is shared by every overview; Visits renders it without
    depending on a prepared analytics cache."""

    def test_no_company_filter_renders_all_companies(self):
        response = self.client.get(self.route('recordings'), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['company_attribute_filter']['scope_type'], 'all')
        self.assertEqual(response.context['company_attribute_filter']['scope_label'], 'All companies')
        self.assertContains(response, 'data-company-scope-trigger', html=False)
        self.assertContains(response, 'Companies:', html=False)
        self.assertTrue(response.context['company_attribute_filter']['segments_enabled'])

    def test_unsaved_conditions_render_as_a_custom_filter(self):
        response = self.client.get(
            self.route('recordings'),
            {f'ca.{self.plan.id}.op': 'in', f'ca.{self.plan.id}.value': str(self.enterprise.id)},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['company_attribute_filter']['scope_type'], 'custom')
        self.assertEqual(response.context['company_attribute_filter']['scope_label'], 'Custom filter')

    def test_an_active_segment_labels_the_trigger_and_owns_the_ca_parameters(self):
        segment = create_company_segment(
            self.project,
            self.user,
            'Enterprise Europe',
            self.enterprise_definition(),
        )

        redirect = self.client.get(self.route('recordings'), {'segment': segment.id})
        self.assertEqual(redirect.status_code, 302)
        self.assertIn(f'segment={segment.id}', redirect['Location'])
        self.assertIn(f'ca.{self.plan.id}.op=in', redirect['Location'])

        response = self.client.get(redirect['Location'], follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['company_attribute_filter']['scope_type'], 'segment')
        self.assertEqual(response.context['company_attribute_filter']['scope_label'], 'Enterprise Europe')
        self.assertContains(response, 'Enterprise Europe', html=False)
        self.assertIn(f'segment={segment.id}', response.context['visits_range_urls']['last_7_days'])

    def test_stale_ca_parameters_are_rewritten_from_the_segment_definition(self):
        segment = create_company_segment(
            self.project,
            self.user,
            'Enterprise Europe',
            self.enterprise_definition(),
        )

        response = self.client.get(
            self.route('project_companies'),
            {
                'segment': str(segment.id),
                f'ca.{self.plan.id}.op': 'in',
                f'ca.{self.plan.id}.value': str(self.business.id),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(f'ca.{self.plan.id}.value={self.enterprise.id}', response['Location'])
        self.assertNotIn(f'ca.{self.plan.id}.value={self.business.id}', response['Location'])

    def test_another_users_segment_id_is_ignored_and_dropped(self):
        segment = create_company_segment(
            self.project,
            self.other_user,
            'Their segment',
            self.enterprise_definition(),
        )

        response = self.client.get(self.route('recordings'), {'segment': str(segment.id)})

        self.assertEqual(response.status_code, 302)
        self.assertNotIn('segment=', response['Location'])

    def test_every_overview_surface_resolves_the_same_segment_scope(self):
        segment = create_company_segment(
            self.project,
            self.user,
            'Enterprise Europe',
            self.enterprise_definition(),
        )

        for route_name in ('project_companies', 'project_users', 'project_pages', 'recordings'):
            with self.subTest(route=route_name):
                redirect = self.client.get(self.route(route_name), {'segment': segment.id})

                self.assertEqual(redirect.status_code, 302)
                self.assertIn(f'segment={segment.id}', redirect['Location'])
                self.assertIn(f'ca.{self.plan.id}.op=in', redirect['Location'])
                self.assertIn(f'ca.{self.plan.id}.value={self.enterprise.id}', redirect['Location'])


class CompanySegmentApiTests(CompanySegmentTestCase):
    def test_list_returns_segments_with_batched_matching_counts(self):
        self.visit('acme')
        self.visit('globex')
        self.set_plan('acme', self.enterprise)
        self.set_plan('globex', self.business)
        create_company_segment(self.project, self.user, 'Enterprise', self.enterprise_definition())
        create_company_segment(
            self.project,
            self.user,
            'Renewing this quarter',
            {str(self.arr.id): {'op': 'gte', 'value': '999999999'}},
        )

        response = self.client.get(self.route('project_company_segments'), {'surface': 'companies'})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        names = [segment['name'] for segment in payload['segments']]
        counts = {segment['name']: segment['matchingCompanyCount'] for segment in payload['segments']}
        self.assertEqual(names, ['Enterprise', 'Renewing this quarter'])
        self.assertEqual(counts['Enterprise'], 1)
        self.assertEqual(counts['Renewing this quarter'], 0)

    def test_create_validates_before_saving_and_returns_the_refreshed_list(self):
        blank = self.post_json(
            self.route('create_project_company_segment'),
            {'name': '   ', 'definition': self.enterprise_definition()},
        )
        self.assertEqual(blank.status_code, 400)
        self.assertIn('name', blank.json()['errors'])
        self.assertFalse(CompanySegment.objects.exists())

        empty_definition = self.post_json(
            self.route('create_project_company_segment'),
            {'name': 'Enterprise Europe', 'definition': {}},
        )
        self.assertEqual(empty_definition.status_code, 400)
        self.assertIn('definition', empty_definition.json()['errors'])

        created = self.post_json(
            self.route('create_project_company_segment'),
            {'name': 'Enterprise Europe', 'definition': self.enterprise_definition()},
        )
        self.assertEqual(created.status_code, 201)
        payload = created.json()
        self.assertEqual(payload['segment']['name'], 'Enterprise Europe')
        self.assertEqual(len(payload['segments']), 1)

        duplicate = self.post_json(
            self.route('create_project_company_segment'),
            {'name': 'enterprise europe', 'definition': self.enterprise_definition()},
        )
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn('name', duplicate.json()['errors'])

    def test_update_changes_the_definition_without_touching_the_name(self):
        segment = create_company_segment(
            self.project,
            self.user,
            'Enterprise Europe',
            self.enterprise_definition(),
        )

        response = self.post_json(
            self.route('update_project_company_segment', segment_id=str(segment.id)),
            {'definition': {str(self.plan.id): {'op': 'in', 'values': [str(self.business.id)]}}},
        )

        self.assertEqual(response.status_code, 200)
        segment.refresh_from_db()
        self.assertEqual(segment.name, 'Enterprise Europe')
        self.assertEqual(
            segment.definition,
            {str(self.plan.id): {'op': 'in', 'values': [str(self.business.id)]}},
        )

    def test_rename_keeps_the_definition_and_rejects_duplicates(self):
        segment = create_company_segment(
            self.project,
            self.user,
            'Enterprise Europe',
            self.enterprise_definition(),
        )
        create_company_segment(
            self.project,
            self.user,
            'Strategic accounts',
            {str(self.arr.id): {'op': 'gte', 'value': '1000'}},
        )

        duplicate = self.post_json(
            self.route('update_project_company_segment', segment_id=str(segment.id)),
            {'name': 'Strategic accounts'},
        )
        self.assertEqual(duplicate.status_code, 400)
        segment.refresh_from_db()
        self.assertEqual(segment.name, 'Enterprise Europe')

        renamed = self.post_json(
            self.route('update_project_company_segment', segment_id=str(segment.id)),
            {'name': '  Enterprise EMEA  '},
        )
        self.assertEqual(renamed.status_code, 200)
        segment.refresh_from_db()
        self.assertEqual(segment.name, 'Enterprise EMEA')
        self.assertEqual(segment.definition, self.enterprise_definition())

    def test_delete_removes_only_the_requested_segment(self):
        segment = create_company_segment(
            self.project,
            self.user,
            'Enterprise Europe',
            self.enterprise_definition(),
        )

        response = self.post_json(
            self.route('delete_project_company_segment', segment_id=str(segment.id))
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['deletedSegment']['name'], 'Enterprise Europe')
        self.assertFalse(CompanySegment.objects.filter(pk=segment.pk).exists())

    def test_segments_are_isolated_between_users(self):
        segment = create_company_segment(
            self.project,
            self.other_user,
            'Their segment',
            self.enterprise_definition(),
        )

        listed = self.client.get(self.route('project_company_segments'))
        self.assertEqual(listed.json()['segments'], [])

        rename = self.post_json(
            self.route('update_project_company_segment', segment_id=str(segment.id)),
            {'name': 'Stolen'},
        )
        self.assertEqual(rename.status_code, 404)

        delete = self.post_json(
            self.route('delete_project_company_segment', segment_id=str(segment.id))
        )
        self.assertEqual(delete.status_code, 404)
        self.assertTrue(CompanySegment.objects.filter(pk=segment.pk).exists())

    def test_project_access_is_required(self):
        user_model = get_user_model()
        outsider = user_model.objects.create_user(
            username='outsider',
            email='outsider@example.com',
            password='testpass123',
        )
        self.client.force_login(outsider)

        listed = self.client.get(self.route('project_company_segments'))
        self.assertEqual(listed.status_code, 403)

        created = self.post_json(
            self.route('create_project_company_segment'),
            {'name': 'Enterprise Europe', 'definition': self.enterprise_definition()},
        )
        self.assertEqual(created.status_code, 403)

    def test_anonymous_requests_are_redirected_to_login(self):
        self.client.logout()

        response = self.client.get(self.route('project_company_segments'))

        self.assertEqual(response.status_code, 302)
        self.assertIn('/sign-in/', response['Location'])
