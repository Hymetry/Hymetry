"""What each person's analytical pages remember, and what they refuse to.

Visits is the surface these tests render, because it is the one that answers
without a prepared analytics cache. The other three resolve the same scope and
the same stored state before they read a cache, so they are asserted on the URL
they redirect to.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.pages.models import ProductArea
from apps.projects import analytics_filter_state
from apps.projects.company_segments import create_company_segment
from apps.projects.models import (
    AnalyticsFilterState,
    AnalyticsPageState,
    CompanyAttribute,
    CompanyAttributeOption,
    CompanyAttributeType,
    Project,
    Workspace,
    WorkspaceMemberRole,
    WorkspaceMemberStatus,
    WorkspaceMembership,
)
from apps.tracker.models import ProjectPageRule


class AnalyticsFilterStateTestCase(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='filter-state-owner',
            email='filter-state-owner@example.com',
            password='testpass123',
        )
        self.workspace = Workspace.objects.create(
            name='Filter State Workspace',
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
            name='Filter State Project',
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

    def enterprise_definition(self):
        return {str(self.plan.id): {'op': 'in', 'values': [str(self.enterprise.id)]}}

    def enterprise_parameters(self):
        return {
            f'ca.{self.plan.id}.op': 'in',
            f'ca.{self.plan.id}.value': str(self.enterprise.id),
        }

    def apply_enterprise_filter(self, route_name='recordings'):
        """Commit the Enterprise company filter the way the dialog does."""

        return self.client.get(
            self.route(route_name),
            {'range': 'last_30_days', **self.enterprise_parameters()},
            follow=True,
        )

    def project_state(self):
        return AnalyticsFilterState.objects.get(project=self.project, user=self.user)

    def page_state(self, page_key):
        return AnalyticsPageState.objects.get(
            project=self.project,
            user=self.user,
            page_key=page_key,
        )

    def page_rule(self, page_name='Billing'):
        return ProjectPageRule.objects.create(
            project=self.project,
            pattern='/' + page_name.lower(),
            page_name=page_name,
            product_area=page_name,
            is_active=True,
            created_by='daily_stable',
        )


class CommittedStateIsStoredTests(AnalyticsFilterStateTestCase):
    def test_an_applied_company_filter_is_stored_for_the_person_and_project(self):
        self.apply_enterprise_filter()

        state = self.project_state()
        self.assertEqual(state.definition, self.enterprise_definition())
        self.assertIsNone(state.segment_id)

    def test_stored_conditions_carry_ids_rather_than_labels(self):
        self.apply_enterprise_filter()

        stored = self.project_state().definition
        self.assertEqual(list(stored), [str(self.plan.id)])
        self.assertEqual(stored[str(self.plan.id)]['values'], [str(self.enterprise.id)])
        self.assertNotIn('Enterprise', str(stored))
        self.assertNotIn('Plan', str(stored))

    def test_an_applied_segment_is_stored_as_the_segment_it_is(self):
        segment = create_company_segment(
            self.project,
            self.user,
            'Enterprise accounts',
            self.enterprise_definition(),
        )

        self.client.get(
            self.route('recordings'),
            {'range': 'last_30_days', 'segment': str(segment.id)},
            follow=True,
        )

        state = self.project_state()
        self.assertEqual(state.segment_id, segment.id)
        self.assertEqual(state.definition, self.enterprise_definition())

    def test_a_page_filter_is_stored_under_its_own_page_key(self):
        page_rule = self.page_rule()

        self.client.get(
            self.route('recordings'),
            {
                'range': 'last_30_days',
                'page_filter_type': 'page',
                'page_filter_id': str(page_rule.id),
            },
            follow=True,
        )

        self.assertEqual(
            self.page_state(analytics_filter_state.VISITS).state,
            {'page_filter_type': ['page'], 'page_filter_id': [str(page_rule.id)]},
        )
        self.assertFalse(
            AnalyticsPageState.objects
            .filter(project=self.project, page_key=analytics_filter_state.COMPANIES_OVERVIEW)
            .exists()
        )

    def test_the_period_is_stored_for_the_project_rather_than_the_page(self):
        self.client.get(
            self.route('recordings'),
            {'range': 'last_7_days'},
            follow=True,
        )

        self.assertEqual(self.project_state().state, {'range': ['last_7_days']})
        self.assertFalse(
            AnalyticsPageState.objects
            .filter(project=self.project, user=self.user)
            .exclude(state={})
            .exists()
        )

    def test_only_the_conditions_the_page_applied_are_stored(self):
        # A condition naming an attribute that is not in this project never
        # becomes part of the cohort, so it never becomes part of what is
        # remembered either.
        self.client.get(
            self.route('recordings'),
            {
                'range': 'last_30_days',
                **self.enterprise_parameters(),
                'ca.9223372036854775807.op': 'empty',
            },
            follow=True,
        )

        self.assertEqual(self.project_state().definition, self.enterprise_definition())

    def test_transient_table_state_is_not_stored(self):
        self.client.get(
            self.route('recordings'),
            {'range': 'last_30_days', 'sort': 'company', 'direction': 'asc', 'page': '2'},
            follow=True,
        )

        self.assertEqual(self.project_state().state, {'range': ['last_30_days']})
        self.assertFalse(
            AnalyticsPageState.objects
            .filter(project=self.project, user=self.user)
            .exclude(state={})
            .exists()
        )


class RestoringStateTests(AnalyticsFilterStateTestCase):
    def test_a_bare_page_is_sent_to_a_url_that_states_its_filters(self):
        response = self.client.get(self.route('recordings'))

        self.assertEqual(response.status_code, 302)
        self.assertIn('range=last_30_days', response['Location'])

    def test_a_later_visit_restores_the_committed_company_filter(self):
        self.apply_enterprise_filter()

        response = self.client.get(self.route('recordings'))

        self.assertEqual(response.status_code, 302)
        self.assertIn(f'ca.{self.plan.id}.op=in', response['Location'])
        self.assertIn(f'ca.{self.plan.id}.value={self.enterprise.id}', response['Location'])

    def test_the_company_filter_is_shared_by_every_analytical_page(self):
        self.apply_enterprise_filter()

        for route_name in ('project_companies', 'project_users', 'project_pages'):
            with self.subTest(route=route_name):
                response = self.client.get(self.route(route_name))

                self.assertEqual(response.status_code, 302)
                self.assertIn(f'ca.{self.plan.id}.op=in', response['Location'])
                self.assertIn(
                    f'ca.{self.plan.id}.value={self.enterprise.id}',
                    response['Location'],
                )

    def test_an_applied_segment_comes_back_as_the_segment(self):
        segment = create_company_segment(
            self.project,
            self.user,
            'Enterprise accounts',
            self.enterprise_definition(),
        )
        self.client.get(
            self.route('recordings'),
            {'range': 'last_30_days', 'segment': str(segment.id)},
            follow=True,
        )

        response = self.client.get(self.route('recordings'))

        self.assertEqual(response.status_code, 302)
        self.assertIn(f'segment={segment.id}', response['Location'])
        self.assertIn(f'ca.{self.plan.id}.op=in', response['Location'])

    def test_the_period_is_shared_by_every_analytical_page(self):
        self.client.get(
            self.route('recordings'),
            {'range': 'last_7_days'},
            follow=True,
        )

        for route_name in ('recordings', 'project_companies', 'project_users', 'project_pages'):
            with self.subTest(route=route_name):
                response = self.client.get(self.route(route_name))

                self.assertEqual(response.status_code, 302)
                self.assertIn('range=last_7_days', response['Location'])

    def test_every_analytical_page_treats_the_period_as_project_level(self):
        for key, spec in analytics_filter_state.PAGE_STATE_SPECS.items():
            with self.subTest(page_key=key):
                self.assertIn('range', spec.project_level_parameters)
                self.assertNotIn('range', spec.page_level_parameters)

    def test_a_page_filter_is_restored_on_its_own_page_only(self):
        page_rule = self.page_rule()

        self.client.get(
            self.route('recordings'),
            {
                'range': 'last_30_days',
                'page_filter_type': 'page',
                'page_filter_id': str(page_rule.id),
            },
            follow=True,
        )

        visits = self.client.get(self.route('recordings'))
        companies = self.client.get(self.route('project_companies'))

        self.assertIn('page_filter_id=' + str(page_rule.id), visits['Location'])
        self.assertNotIn('page_filter_id', companies['Location'])

    def test_page_filters_are_never_copied_between_pages(self):
        page_rule = self.page_rule()
        self.client.get(
            self.route('recordings'),
            {
                'range': 'last_30_days',
                'page_filter_type': 'page',
                'page_filter_id': str(page_rule.id),
            },
            follow=True,
        )

        companies = self.client.get(self.route('project_companies'))

        self.assertNotIn('page_filter_type', companies['Location'])
        self.assertNotIn('page_filter_id', companies['Location'])

    def test_a_restored_url_is_not_redirected_again(self):
        self.apply_enterprise_filter()

        first = self.client.get(self.route('recordings'))
        second = self.client.get(first['Location'])

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 200)


class ExplicitUrlWinsTests(AnalyticsFilterStateTestCase):
    def test_a_url_that_states_a_period_overrides_the_stored_one(self):
        self.client.get(self.route('recordings'), {'range': 'last_7_days'}, follow=True)

        response = self.client.get(self.route('recordings'), {'range': 'last_30_days'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['visits_range_key'], 'last_30_days')
        self.assertEqual(self.project_state().state, {'range': ['last_30_days']})

    def test_a_url_that_states_the_page_and_no_company_filter_clears_the_stored_one(self):
        self.apply_enterprise_filter()

        cleared = self.client.get(self.route('recordings'), {'range': 'last_30_days'})

        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(self.project_state().definition, {})

        later = self.client.get(self.route('recordings'))
        self.assertNotIn('ca.', later['Location'])

    def test_a_url_that_states_only_a_company_filter_keeps_it(self):
        self.client.get(self.route('recordings'), {'range': 'last_7_days'}, follow=True)

        response = self.client.get(self.route('recordings'), self.enterprise_parameters())

        # The page's own filters are filled in; the company filter the URL
        # states is left exactly as it was sent.
        self.assertEqual(response.status_code, 302)
        self.assertIn('range=last_7_days', response['Location'])
        self.assertIn(f'ca.{self.plan.id}.value={self.enterprise.id}', response['Location'])


class StaleStateIsSanitizedTests(AnalyticsFilterStateTestCase):
    def remember_entity_filter(self):
        """Store an applied identity filter without rendering Visits for it.

        Rendering one asks the prepared Users overview for its label, which is
        not what these tests are about.
        """

        return AnalyticsPageState.objects.create(
            project=self.project,
            user=self.user,
            page_key=analytics_filter_state.VISITS,
            state={'entity_type': ['user'], 'entity_id': ['user-1']},
        )

    def test_a_deleted_attribute_stops_coming_back(self):
        self.apply_enterprise_filter()
        self.plan.delete()

        response = self.client.get(self.route('recordings'))

        self.assertEqual(response.status_code, 302)
        self.assertNotIn('ca.', response['Location'])

    def test_a_deleted_option_stops_coming_back(self):
        self.apply_enterprise_filter()
        self.enterprise.delete()

        response = self.client.get(self.route('recordings'))

        self.assertNotIn('ca.', response['Location'])

    def test_a_deleted_segment_leaves_its_conditions_as_a_custom_filter(self):
        segment = create_company_segment(
            self.project,
            self.user,
            'Enterprise accounts',
            self.enterprise_definition(),
        )
        self.client.get(
            self.route('recordings'),
            {'range': 'last_30_days', 'segment': str(segment.id)},
            follow=True,
        )
        segment.delete()

        response = self.client.get(self.route('recordings'))

        self.assertNotIn('segment=', response['Location'])
        self.assertIn(f'ca.{self.plan.id}.op=in', response['Location'])

    def test_a_segment_awaiting_review_comes_back_as_itself_and_filters_nothing(self):
        segment = create_company_segment(
            self.project,
            self.user,
            'Enterprise accounts',
            self.enterprise_definition(),
        )
        self.client.get(
            self.route('recordings'),
            {'range': 'last_30_days', 'segment': str(segment.id)},
            follow=True,
        )
        segment.needs_review = True
        segment.save(update_fields=['needs_review'])

        response = self.client.get(self.route('recordings'))

        self.assertIn(f'segment={segment.id}', response['Location'])
        self.assertNotIn('ca.', response['Location'])

    def test_a_deleted_product_area_stops_coming_back(self):
        area = ProductArea.objects.create(
            project=self.project,
            name='Billing',
            slug='billing',
        )
        spec = analytics_filter_state.PAGE_STATE_SPECS[analytics_filter_state.PAGES_OVERVIEW]
        AnalyticsPageState.objects.create(
            project=self.project,
            user=self.user,
            page_key=analytics_filter_state.PAGES_OVERVIEW,
            state={'product_area': ['billing', 'gone']},
        )

        with_area = analytics_filter_state.restored_page_parameters(self.project, self.user, spec)
        area.delete()
        without_area = analytics_filter_state.restored_page_parameters(self.project, self.user, spec)

        self.assertEqual(with_area['product_area'], ['billing'])
        self.assertNotIn('product_area', without_area)

    def test_a_deleted_page_rule_stops_coming_back(self):
        page_rule = self.page_rule()
        self.client.get(
            self.route('recordings'),
            {
                'range': 'last_30_days',
                'page_filter_type': 'page',
                'page_filter_id': str(page_rule.id),
            },
            follow=True,
        )
        restored = self.client.get(self.route('recordings'))
        self.assertIn(f'page_filter_id={page_rule.id}', restored['Location'])

        page_rule.delete()
        after_deletion = self.client.get(self.route('recordings'))

        self.assertNotIn('page_filter_id', after_deletion['Location'])
        self.assertNotIn('page_filter_type', after_deletion['Location'])

    def test_an_identity_the_project_no_longer_has_stops_coming_back(self):
        self.remember_entity_filter()

        with patch(
            'apps.tracker.visits_filters.visits_entity_is_known',
            return_value=False,
        ):
            response = self.client.get(self.route('recordings'))

        self.assertNotIn('entity_id', response['Location'])
        self.assertNotIn('entity_type', response['Location'])

    def test_an_identity_is_kept_while_the_overview_it_comes_from_is_unbuilt(self):
        self.remember_entity_filter()

        with patch(
            'apps.tracker.visits_filters.visits_entity_is_known',
            return_value=None,
        ):
            response = self.client.get(self.route('recordings'))

        self.assertIn('entity_id=user-1', response['Location'])

    def test_a_retired_period_stops_coming_back(self):
        AnalyticsFilterState.objects.create(
            project=self.project,
            user=self.user,
            state={'range': ['last_3_hours']},
        )

        response = self.client.get(self.route('recordings'))

        self.assertIn('range=last_30_days', response['Location'])
        self.assertNotIn('last_3_hours', response['Location'])


class StoredStateIsBoundedTests(AnalyticsFilterStateTestCase):
    def spec(self):
        return analytics_filter_state.PAGE_STATE_SPECS[analytics_filter_state.PAGES_OVERVIEW]

    def test_unknown_parameters_are_dropped(self):
        values = analytics_filter_state.normalize_page_state(
            {'range': 'last_7_days', 'token': 'anything'},
            self.spec(),
        )

        self.assertEqual(values, {'range': ['last_7_days']})

    def test_values_outside_a_parameter_choices_are_dropped(self):
        values = analytics_filter_state.normalize_page_state(
            {'range': 'yesterday'},
            self.spec(),
        )

        self.assertEqual(values, {})

    def test_value_counts_and_lengths_are_bounded(self):
        values = analytics_filter_state.normalize_page_state(
            {
                'product_area': (
                    ['area'] * 200
                    + ['x' * (analytics_filter_state.MAX_STORED_VALUE_LENGTH + 1)]
                    + ['billing']
                ),
            },
            self.spec(),
        )

        self.assertEqual(values['product_area'], ['area', 'billing'])

    def test_non_text_values_are_dropped(self):
        values = analytics_filter_state.normalize_page_state(
            {'product_area': [{'key': 'billing'}, True, None, 'billing']},
            self.spec(),
        )

        self.assertEqual(values['product_area'], ['billing'])


