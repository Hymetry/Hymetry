"""Company segments that outlived a deleted company attribute.

The rule under test is that a deletion is a project-wide event with a personal
consequence: whoever deletes the attribute, every segment that referenced it is
flagged, and only its own owner can clear that flag by saving a definition that
no longer needs the attribute.
"""

import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.utils import timezone

from apps.projects.company_attribute_filter_support import (
    build_company_attribute_filter_context,
)
from apps.projects.company_segment_reviews import (
    actor_display_name,
    deletion_date_label,
    review_notice,
)
from apps.projects.company_segments import (
    company_segment_urls,
    create_company_segment,
    resolve_company_scope,
)
from apps.projects.models import (
    CompanyAttribute,
    CompanyAttributeType,
    CompanySegment,
    WorkspaceMemberRole,
    WorkspaceMemberStatus,
    WorkspaceMembership,
)
from apps.projects.tests.test_company_segments import CompanySegmentTestCase


OVERVIEW_ROUTES = ('project_pages', 'project_companies', 'project_users', 'recordings')


class CompanySegmentReviewTestCase(CompanySegmentTestCase):
    def arr_definition(self):
        return {str(self.arr.id): {'op': 'gte', 'value': '250000'}}

    def delete_attributes(self, *attribute_ids, attributes=None):
        return self.client.post(
            self.route('save_project_company_attributes'),
            data=json.dumps({
                'attributes': attributes or [],
                'deleted_ids': [int(attribute_id) for attribute_id in attribute_ids],
            }),
            content_type='application/json',
        )

    def today_label(self):
        return deletion_date_label(timezone.now(), self.project.timezone)


class CompanyAttributeDeletionTests(CompanySegmentReviewTestCase):
    def test_deleting_an_attribute_flags_every_referencing_segment_in_the_project(self):
        self.user.first_name = 'Alex'
        self.user.save(update_fields=['first_name'])
        mine = create_company_segment(
            self.project,
            self.user,
            'Enterprise Europe',
            self.enterprise_definition(),
        )
        theirs = create_company_segment(
            self.project,
            self.other_user,
            'Their enterprise view',
            self.enterprise_definition(),
        )
        seeded = CompanySegment.objects.create(
            project=self.project,
            user=None,
            name='Seeded enterprise',
            definition=self.enterprise_definition(),
        )
        untouched = create_company_segment(
            self.project,
            self.user,
            'Big spenders',
            self.arr_definition(),
        )

        response = self.delete_attributes(self.plan.id)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(CompanyAttribute.objects.filter(pk=self.plan.pk).exists())
        for segment in (mine, theirs, seeded):
            segment.refresh_from_db()
            with self.subTest(segment=segment.name):
                self.assertTrue(segment.needs_review)
                self.assertEqual(
                    segment.pending_attribute_deletions,
                    [{
                        'attribute_id': str(self.plan.id),
                        'attribute_name': 'Plan',
                        'deleted_by': 'Alex',
                        'deleted_at': segment.pending_attribute_deletions[0]['deleted_at'],
                    }],
                )
        untouched.refresh_from_db()
        self.assertFalse(untouched.needs_review)
        self.assertEqual(untouched.pending_attribute_deletions, [])

    def test_the_deleted_definition_and_the_segment_name_are_left_exactly_as_written(self):
        segment = create_company_segment(
            self.project,
            self.user,
            'Enterprise Europe',
            self.enterprise_definition(),
        )

        self.delete_attributes(self.plan.id)

        segment.refresh_from_db()
        self.assertEqual(segment.name, 'Enterprise Europe')
        self.assertEqual(segment.definition, self.enterprise_definition())

    def test_a_member_may_delete_an_attribute_and_is_named_in_the_record(self):
        segment = create_company_segment(
            self.project,
            self.user,
            'Enterprise Europe',
            self.enterprise_definition(),
        )
        self.client.force_login(self.other_user)

        response = self.delete_attributes(self.plan.id)

        self.assertEqual(response.status_code, 200)
        segment.refresh_from_db()
        self.assertTrue(segment.needs_review)
        # No name is set on this account, so the workspace shows the email.
        self.assertEqual(
            segment.pending_attribute_deletions[0]['deleted_by'],
            'segment-teammate@example.com',
        )

    def test_a_viewer_may_not_delete_an_attribute(self):
        user_model = get_user_model()
        viewer = user_model.objects.create_user(
            username='segment-viewer',
            email='segment-viewer@example.com',
            password='testpass123',
        )
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=viewer,
            role=WorkspaceMemberRole.VIEWER,
            status=WorkspaceMemberStatus.ACTIVE,
        )
        segment = create_company_segment(
            self.project,
            self.user,
            'Enterprise Europe',
            self.enterprise_definition(),
        )
        self.client.force_login(viewer)

        response = self.delete_attributes(self.plan.id)

        self.assertEqual(response.status_code, 403)
        segment.refresh_from_db()
        self.assertFalse(segment.needs_review)
        self.assertTrue(CompanyAttribute.objects.filter(pk=self.plan.pk).exists())

    def test_a_second_deletion_adds_a_record_without_losing_the_unreviewed_one(self):
        segment = create_company_segment(
            self.project,
            self.user,
            'Enterprise Europe',
            {**self.enterprise_definition(), **self.arr_definition()},
        )

        self.delete_attributes(self.plan.id)
        self.delete_attributes(self.arr.id)

        segment.refresh_from_db()
        self.assertTrue(segment.needs_review)
        self.assertEqual(
            [record['attribute_name'] for record in segment.pending_attribute_deletions],
            ['Plan', 'ARR'],
        )

    def test_the_display_name_falls_back_from_name_to_email(self):
        user_model = get_user_model()
        named = user_model.objects.create_user(
            username='named',
            email='named@example.com',
            password='testpass123',
            first_name='Alex',
        )
        anonymous = user_model.objects.create_user(
            username='no-name',
            email='no-name@example.com',
            password='testpass123',
        )

        self.assertEqual(actor_display_name(named), 'Alex')
        self.assertEqual(actor_display_name(anonymous), 'no-name@example.com')


class BlockedSegmentApplicationTests(CompanySegmentReviewTestCase):
    def flagged_segment(self):
        segment = create_company_segment(
            self.project,
            self.user,
            'Enterprise Europe',
            self.enterprise_definition(),
        )
        self.delete_attributes(self.plan.id)
        segment.refresh_from_db()
        return segment

    def test_a_flagged_segment_is_refused_and_the_page_says_so(self):
        segment = self.flagged_segment()

        response = self.client.get(self.route('recordings'), {'segment': segment.id}, follow=True)

        self.assertEqual(response.status_code, 200)
        filter_context = response.context['company_attribute_filter']
        self.assertEqual(filter_context['scope_type'], 'all')
        self.assertEqual(filter_context['active_count'], 0)
        self.assertEqual(filter_context['blocked_segment_name'], 'Enterprise Europe')
        self.assertContains(response, 'must be reviewed first', html=False)
        self.assertContains(response, 'Edit segment', html=False)

    def test_every_surface_strips_the_conditions_sent_with_a_flagged_segment(self):
        segment = create_company_segment(
            self.project,
            self.user,
            'Enterprise Europe',
            {**self.enterprise_definition(), **self.arr_definition()},
        )
        self.delete_attributes(self.plan.id)

        for route_name in OVERVIEW_ROUTES:
            with self.subTest(route=route_name):
                # Whatever the client sends alongside the segment, the surviving
                # half of its definition never becomes the cohort.
                redirect = self.client.get(
                    self.route(route_name),
                    {
                        'segment': str(segment.id),
                        f'ca.{self.arr.id}.op': 'gte',
                        f'ca.{self.arr.id}.value': '250000',
                    },
                )

                self.assertEqual(redirect.status_code, 302)
                self.assertIn(f'segment={segment.id}', redirect['Location'])
                self.assertNotIn('ca.', redirect['Location'])

    def test_the_refused_segment_leaves_the_visits_cohort_unfiltered(self):
        segment = self.flagged_segment()

        redirect = self.client.get(
            self.route('recordings'),
            {
                'segment': str(segment.id),
                f'ca.{self.arr.id}.op': 'gte',
                f'ca.{self.arr.id}.value': '250000',
            },
        )
        applied = self.client.get(redirect['Location'], follow=True)

        self.assertEqual(applied.context['company_attribute_filter']['active_count'], 0)
        self.assertEqual(applied.context['company_attribute_filter']['scope_type'], 'all')

    def test_a_segment_that_needs_no_review_still_applies(self):
        self.flagged_segment()
        healthy = create_company_segment(
            self.project,
            self.user,
            'Big spenders',
            self.arr_definition(),
        )

        redirect = self.client.get(self.route('recordings'), {'segment': healthy.id})

        self.assertEqual(redirect.status_code, 302)
        response = self.client.get(redirect['Location'], follow=True)
        self.assertEqual(response.context['company_attribute_filter']['scope_type'], 'segment')
        self.assertEqual(response.context['company_attribute_filter']['scope_label'], 'Big spenders')

    def test_the_list_marks_the_segment_and_withholds_a_matching_count(self):
        segment = self.flagged_segment()

        response = self.client.get(self.route('project_company_segments'), {'surface': 'companies'})

        payload = response.json()['segments'][0]
        self.assertEqual(payload['id'], str(segment.id))
        self.assertEqual(payload['name'], 'Enterprise Europe')
        self.assertTrue(payload['needsReview'])
        self.assertNotIn('matchingCompanyCount', payload)
        self.assertEqual(
            payload['deletedAttributes'][0]['detail'],
            f'"Plan" was deleted by segment-owner@example.com on {self.today_label()}.',
        )


class ReviewBannerTests(CompanySegmentReviewTestCase):
    def test_the_banner_names_the_attribute_the_person_and_the_day(self):
        create_company_segment(
            self.project,
            self.user,
            'Enterprise Europe',
            self.enterprise_definition(),
        )
        self.client.force_login(self.other_user)
        self.delete_attributes(self.plan.id)
        self.client.force_login(self.user)

        response = self.client.get(self.route('recordings'), follow=True)

        self.assertEqual(response.status_code, 200)
        review = response.context['company_segment_review']
        self.assertTrue(review['active'])
        self.assertEqual(
            review['messages'],
            [
                f'The attribute "Plan" was deleted by segment-teammate@example.com'
                f' on {self.today_label()}. It was used in some of your segments.'
            ],
        )
        self.assertEqual(review['segmentCount'], 1)
        self.assertContains(response, 'Review segments', html=False)

    def test_every_analytics_surface_renders_the_banner_partial(self):
        # The four surfaces share one context builder, so what has to be checked
        # per surface is that each one actually renders the partial. Companies,
        # Users, and Pages cannot be rendered here without their analytics cache.
        templates = (
            'apps/pages/templates/pages/overview.html',
            'apps/projects/templates/projects/companies.html',
            'apps/projects/templates/projects/users.html',
            'apps/tracker/templates/tracker/visits.html',
        )
        for relative_path in templates:
            with self.subTest(template=relative_path):
                source = (Path(settings.BASE_DIR) / relative_path).read_text(encoding='utf-8')

                self.assertIn('partials/company_segment_review_banner.html', source)

    def test_the_shared_context_builder_carries_the_notice_to_any_surface(self):
        segment = create_company_segment(
            self.project,
            self.user,
            'Enterprise Europe',
            self.enterprise_definition(),
        )
        self.delete_attributes(self.plan.id)
        request = RequestFactory().get('/', {'segment': str(segment.id)})
        request.user = self.user
        scope = resolve_company_scope(request, self.project)

        for surface in ('pages', 'companies', 'users', 'visits'):
            with self.subTest(surface=surface):
                context = build_company_attribute_filter_context(
                    self.project,
                    scope.state,
                    surface=surface,
                    preview_url='/preview',
                    scope=scope,
                    segment_urls=company_segment_urls(self.project),
                )

                self.assertTrue(context['company_segment_review']['active'])
                self.assertEqual(
                    context['company_attribute_filter']['blocked_segment_name'],
                    'Enterprise Europe',
                )
                self.assertEqual(
                    context['company_attribute_filter_payload']['scope']['blockedSegmentId'],
                    str(segment.id),
                )

    def test_one_deletion_across_several_segments_says_it_once(self):
        for name in ('Enterprise Europe', 'Enterprise APAC'):
            create_company_segment(self.project, self.user, name, self.enterprise_definition())

        self.delete_attributes(self.plan.id)
        notice = review_notice(self.project, self.user)

        self.assertTrue(notice['active'])
        self.assertEqual(len(notice['messages']), 1)
        self.assertEqual(notice['segmentCount'], 2)

    def test_a_teammate_without_affected_segments_sees_nothing(self):
        create_company_segment(
            self.project,
            self.user,
            'Enterprise Europe',
            self.enterprise_definition(),
        )
        self.delete_attributes(self.plan.id)
        self.client.force_login(self.other_user)

        response = self.client.get(self.route('recordings'), follow=True)

        self.assertFalse(response.context['company_segment_review']['active'])
        self.assertNotContains(response, 'Review segments', html=False)


class ReviewResolutionTests(CompanySegmentReviewTestCase):
    def setUp(self):
        super().setUp()
        self.segment = create_company_segment(
            self.project,
            self.user,
            'Enterprise Europe',
            {**self.enterprise_definition(), **self.arr_definition()},
        )
        self.delete_attributes(self.plan.id)
        self.segment.refresh_from_db()

    def test_saving_the_remaining_conditions_clears_the_review(self):
        response = self.post_json(
            self.route('update_project_company_segment', segment_id=str(self.segment.id)),
            {'definition': self.arr_definition()},
        )

        self.assertEqual(response.status_code, 200)
        self.segment.refresh_from_db()
        self.assertFalse(self.segment.needs_review)
        self.assertEqual(self.segment.pending_attribute_deletions, [])
        self.assertEqual(self.segment.definition, self.arr_definition())
        self.assertFalse(response.json()['segment']['needsReview'])
        self.assertFalse(review_notice(self.project, self.user)['active'])

    def test_a_definition_that_still_names_the_deleted_attribute_is_rejected(self):
        response = self.post_json(
            self.route('update_project_company_segment', segment_id=str(self.segment.id)),
            {'definition': {**self.enterprise_definition(), **self.arr_definition()}},
        )

        self.assertEqual(response.status_code, 400)
        self.segment.refresh_from_db()
        self.assertTrue(self.segment.needs_review)

    def test_renaming_alone_leaves_the_segment_in_review(self):
        response = self.post_json(
            self.route('update_project_company_segment', segment_id=str(self.segment.id)),
            {'name': 'Enterprise EMEA'},
        )

        self.assertEqual(response.status_code, 200)
        self.segment.refresh_from_db()
        self.assertEqual(self.segment.name, 'Enterprise EMEA')
        self.assertTrue(self.segment.needs_review)

    def test_leaving_the_editor_without_saving_leaves_the_segment_in_review(self):
        # Cancel sends nothing, so the segment is still exactly as the deletion
        # left it and the banner still has something to report.
        self.assertTrue(self.segment.needs_review)
        self.assertTrue(review_notice(self.project, self.user)['active'])

        listed = self.client.get(self.route('project_company_segments'))

        self.assertTrue(listed.json()['segments'][0]['needsReview'])

    def test_a_teammates_segment_is_not_cleared_by_someone_elses_review(self):
        # Written straight to the database: the attribute is already gone, so
        # the normal create path would refuse this definition.
        theirs = CompanySegment.objects.create(
            project=self.project,
            user=self.other_user,
            name='Their enterprise view',
            definition=self.enterprise_definition(),
            needs_review=True,
            pending_attribute_deletions=[{
                'attribute_id': str(self.plan.id),
                'attribute_name': 'Plan',
                'deleted_by': 'Alex',
                'deleted_at': timezone.now().isoformat(),
            }],
        )

        self.post_json(
            self.route('update_project_company_segment', segment_id=str(self.segment.id)),
            {'definition': self.arr_definition()},
        )

        theirs.refresh_from_db()
        self.assertTrue(theirs.needs_review)

    def test_recreating_an_attribute_with_a_new_id_does_not_clear_the_review(self):
        CompanyAttribute.objects.create(
            project=self.project,
            name='Plan',
            attribute_type=CompanyAttributeType.SINGLE_SELECT,
            position=0,
        )

        self.segment.refresh_from_db()
        self.assertTrue(self.segment.needs_review)
        self.assertTrue(review_notice(self.project, self.user)['active'])
