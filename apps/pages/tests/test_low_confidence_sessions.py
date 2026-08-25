"""Pages-rollup coverage for the low-confidence anonymous session rule.

The rollup is exercised end to end — events in, prepared daily facts out — so
these assert the outcome the rule exists for rather than the flag that carries
it.  See :mod:`apps.tracker.analytics_eligibility`.
"""

import uuid
from datetime import datetime, timedelta, timezone as datetime_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.pages.models import (
    PageCompanyDailyMetric,
    PageDailyMetric,
    PageTransition,
    PageUserDailyMetric,
    PageVisit,
    ProjectDailyMetric,
    RawPageActionDailyMetric,
    RawPageDailyMetric,
)
from apps.pages.services import rebuild_project_pages_analytics
from apps.projects.models import (
    Project,
    Workspace,
    WorkspaceMemberRole,
    WorkspaceMemberStatus,
    WorkspaceMembership,
)
from apps.tracker.analytics_eligibility import (
    LOW_CONFIDENCE_MAX_DURATION_SECONDS,
    MEANINGFUL_EVENT_MIN_OFFSET_SECONDS,
)
from apps.tracker.models import AnalyticsEvent, AnalyticsSession, Event, Session, Visitor
from apps.tracker.visits_scope import meaningful_analytics_session_ids

UTC = datetime_timezone.utc

LANDING = 'app.example.com/landing'
PRICING = 'app.example.com/pricing'


class LowConfidenceFixtures:
    """Shared fixtures. Not a TestCase, so suites below stay independent."""

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='low-confidence-pages-owner',
            email='low-confidence-pages-owner@example.com',
            password='testpass123',
        )
        self.workspace = Workspace.objects.create(
            name='Low confidence pages workspace',
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
            name='Low confidence pages project',
            created_by=self.user,
            timezone='UTC',
        )
        self.now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
        self.day = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)

    # ------------------------------------------------------------------
    # fixtures
    # ------------------------------------------------------------------

    def _fragment(
        self,
        *,
        start,
        user_id=None,
        company_id=None,
        recording=None,
        visitor_guid=None,
    ):
        if visitor_guid is None:
            visitor_guid = (
                uuid.uuid4() if recording is None else recording.visitor.visitor_guid
            )
        return AnalyticsSession.objects.create(
            project=self.project,
            visit_session=recording,
            visitor_guid=visitor_guid,
            user_id=user_id,
            company_id=company_id,
            start_time=start,
            last_activity=start,
            ended_at=start,
        )

    def _event(
        self,
        fragment,
        *,
        at,
        event_type='mouse_move',
        url=LANDING,
        user_id=None,
        company_id=None,
    ):
        return AnalyticsEvent.objects.create(
            session=fragment,
            event_type=event_type,
            timestamp=at,
            visitor_guid=fragment.visitor_guid,
            user_id=user_id,
            company_id=company_id,
            user_traits={},
            company_traits={},
            element_key='cta' if event_type == 'click' else None,
            url=f'https://{url}',
            url_normalized=url,
            page_name='Landing' if url == LANDING else 'Pricing',
            page_name_original='Landing' if url == LANDING else 'Pricing',
        )

    def _bounce(
        self,
        *,
        at=None,
        event_types=('mouse_move', 'mouse_move'),
        url=LANDING,
        spacing_seconds=3,
    ):
        """One anonymous, single-page, sub-ten-second, completed session.

        ``spacing_seconds`` has to keep the whole session inside
        ``LOW_CONFIDENCE_MAX_DURATION_SECONDS`` or the span alone qualifies
        it, whatever the event types are.  A case about a click or scroll
        should also keep it clear of ``MEANINGFUL_EVENT_MIN_OFFSET_SECONDS``,
        so the interaction is what the case turns on rather than the boundary.
        """

        at = at or self.day
        fragment = self._fragment(start=at)
        for index, event_type in enumerate(event_types):
            self._event(
                fragment,
                at=at + timedelta(seconds=index * spacing_seconds),
                event_type=event_type,
                url=url,
            )
        return fragment

    def _engaged_session(self, *, at=None, user_id='user-1', company_id='acme'):
        """A plainly meaningful session on the same page, as a control."""

        at = at or self.day + timedelta(minutes=5)
        fragment = self._fragment(start=at, user_id=user_id, company_id=company_id)
        for index, event_type in enumerate(('click', 'scroll', 'click')):
            self._event(
                fragment,
                at=at + timedelta(seconds=index * 5),
                event_type=event_type,
                user_id=user_id,
                company_id=company_id,
            )
        return fragment

    def _rebuild(self):
        return rebuild_project_pages_analytics(
            self.project.id,
            self.day.date(),
            self.day.date(),
            range_keys=('last_7_days',),
            now=self.now,
        )

    def _landing_metric(self):
        return PageDailyMetric.objects.filter(project=self.project).first()


class LowConfidenceRollupTests(LowConfidenceFixtures, TestCase):
    # ------------------------------------------------------------------
    # the rule
    # ------------------------------------------------------------------

    def test_bounce_is_dropped_from_prepared_page_facts(self):
        self._bounce()
        self._engaged_session()

        self._rebuild()

        self.assertEqual(PageVisit.objects.filter(project=self.project).count(), 2)
        metric = self._landing_metric()
        self.assertIsNotNone(metric)
        self.assertEqual(metric.visits_count, 1)

    def test_page_visit_rows_survive_exclusion(self):
        """Nothing is deleted; only the eligibility flag moves."""

        self._bounce()
        self._engaged_session()

        self._rebuild()

        visits = PageVisit.objects.filter(project=self.project)
        self.assertEqual(visits.count(), 2)
        self.assertEqual(visits.filter(is_analytics_eligible=False).count(), 1)
        excluded = visits.get(is_analytics_eligible=False)
        self.assertEqual(excluded.mouse_move_count, 2)
        self.assertEqual(excluded.click_count, 0)
        self.assertEqual(excluded.scroll_count, 0)

    def test_bounce_leaves_engaged_time_and_interaction_alone(self):
        self._bounce()
        self._engaged_session()

        self._rebuild()

        metric = self._landing_metric()
        engaged_from_eligible = (
            PageVisit.objects
            .filter(project=self.project, is_analytics_eligible=True)
            .first()
            .engaged_seconds
        )
        self.assertEqual(metric.engaged_seconds, engaged_from_eligible)
        self.assertEqual(metric.visits_with_click_count, 1)
        self.assertEqual(metric.mouse_move_count, 0)

    def test_raw_page_and_project_facts_drop_it_too(self):
        self._bounce()
        self._engaged_session()

        self._rebuild()

        raw = RawPageDailyMetric.objects.get(project=self.project, url_normalized=LANDING)
        self.assertEqual(raw.visits_count, 1)
        project_metric = ProjectDailyMetric.objects.get(project=self.project)
        self.assertEqual(project_metric.visits_count, 1)

    def test_project_with_only_bounces_prepares_no_page_facts(self):
        self._bounce()
        self._bounce(at=self.day + timedelta(minutes=2))

        self._rebuild()

        self.assertEqual(PageVisit.objects.filter(project=self.project).count(), 2)
        self.assertEqual(PageDailyMetric.objects.filter(project=self.project).count(), 0)
        self.assertEqual(ProjectDailyMetric.objects.filter(project=self.project).count(), 0)

    # ------------------------------------------------------------------
    # one condition at a time
    # ------------------------------------------------------------------

    def _eligible_visit_count(self):
        return PageVisit.objects.filter(project=self.project, is_analytics_eligible=True).count()

    def test_click_keeps_the_session(self):
        self._bounce(event_types=('mouse_move', 'click'))
        self._rebuild()
        self.assertEqual(self._eligible_visit_count(), 1)

    def test_scroll_keeps_the_session(self):
        self._bounce(event_types=('mouse_move', 'scroll'))
        self._rebuild()
        self.assertEqual(self._eligible_visit_count(), 1)

    def test_touch_move_keeps_the_session(self):
        """A finger dragging across glass cannot happen by accident."""

        self._bounce(event_types=('mouse_move', 'touch_move'))
        self._rebuild()
        self.assertEqual(self._eligible_visit_count(), 1)

    def test_key_press_keeps_the_session(self):
        """Typing is sampled like pointer movement but is still deliberate."""

        self._bounce(event_types=('mouse_move', 'key_press'))
        self._rebuild()
        self.assertEqual(self._eligible_visit_count(), 1)

    def test_mouse_move_never_counts_as_interaction(self):
        self._bounce(event_types=('mouse_move',) * 6, spacing_seconds=1)
        self._rebuild()
        self.assertEqual(self._eligible_visit_count(), 0)

    def test_click_inside_the_opening_second_is_ignored(self):
        """The shape this rule was tightened for: a bounce with one load click."""

        self._bounce(event_types=('mouse_move', 'click'), spacing_seconds=0.5)
        self._rebuild()
        self.assertEqual(self._eligible_visit_count(), 0)

    def test_scroll_as_the_first_event_is_ignored(self):
        self._bounce(event_types=('scroll',))
        self._rebuild()
        self.assertEqual(self._eligible_visit_count(), 0)

    def test_click_exactly_at_the_offset_keeps_the_session(self):
        fragment = self._fragment(start=self.day)
        self._event(fragment, at=self.day)
        self._event(
            fragment,
            at=self.day + timedelta(seconds=MEANINGFUL_EVENT_MIN_OFFSET_SECONDS),
            event_type='click',
        )

        self._rebuild()

        self.assertEqual(self._eligible_visit_count(), 1)

    def test_click_a_millisecond_early_is_ignored(self):
        fragment = self._fragment(start=self.day)
        self._event(fragment, at=self.day)
        self._event(
            fragment,
            at=self.day
            + timedelta(seconds=MEANINGFUL_EVENT_MIN_OFFSET_SECONDS)
            - timedelta(milliseconds=1),
            event_type='click',
        )

        self._rebuild()

        self.assertEqual(self._eligible_visit_count(), 0)

    def test_a_late_click_qualifies_a_session_an_early_one_did_not(self):
        """Only the latest interaction has to clear the offset, not every one."""

        fragment = self._fragment(start=self.day)
        self._event(fragment, at=self.day)
        self._event(
            fragment,
            at=self.day + timedelta(milliseconds=200),
            event_type='click',
        )
        self._event(
            fragment,
            at=self.day + timedelta(seconds=3),
            event_type='click',
        )

        self._rebuild()

        self.assertEqual(self._eligible_visit_count(), 1)

    def test_an_ignored_click_is_kept_on_the_visit_row_but_counted_nowhere(self):
        """Nothing is deleted, and nothing excluded reaches a prepared fact."""

        self._bounce(event_types=('mouse_move', 'click'), spacing_seconds=0.5)

        self._rebuild()

        excluded = PageVisit.objects.get(project=self.project, is_analytics_eligible=False)
        self.assertEqual(excluded.click_count, 1)
        self.assertTrue(excluded.had_click)
        self.assertFalse(
            RawPageActionDailyMetric.objects.filter(project=self.project).exists(),
        )

    def test_a_qualifying_click_still_reaches_the_action_facts(self):
        """The control for the case above: the predicate drops only the excluded."""

        self._bounce(event_types=('mouse_move', 'click'), spacing_seconds=3)

        self._rebuild()

        action = RawPageActionDailyMetric.objects.get(project=self.project)
        self.assertEqual(action.element_key, 'cta')
        self.assertEqual(action.clicks_count, 1)

    def test_second_page_keeps_the_session(self):
        fragment = self._fragment(start=self.day)
        self._event(fragment, at=self.day, url=LANDING)
        self._event(fragment, at=self.day + timedelta(seconds=2), url=PRICING)

        self._rebuild()

        self.assertEqual(self._eligible_visit_count(), 2)

    def test_user_identity_keeps_the_session(self):
        fragment = self._fragment(start=self.day, user_id='user-9')
        self._event(fragment, at=self.day)
        self._rebuild()
        self.assertEqual(self._eligible_visit_count(), 1)

    def test_company_identity_keeps_the_session(self):
        fragment = self._fragment(start=self.day, company_id='acme')
        self._event(fragment, at=self.day)
        self._rebuild()
        self.assertEqual(self._eligible_visit_count(), 1)

    def test_identity_carried_only_by_the_event_keeps_the_session(self):
        fragment = self._fragment(start=self.day)
        self._event(fragment, at=self.day, user_id='user-10')
        self._rebuild()
        self.assertEqual(self._eligible_visit_count(), 1)

    def test_session_still_in_flight_is_kept(self):
        recent = self.now - timedelta(seconds=60)
        self._bounce(at=recent)

        rebuild_project_pages_analytics(
            self.project.id,
            recent.date(),
            recent.date(),
            range_keys=('last_7_days',),
            now=self.now,
        )

        self.assertEqual(self._eligible_visit_count(), 1)

    # ------------------------------------------------------------------
    # boundaries
    # ------------------------------------------------------------------

    def test_span_just_under_the_threshold_is_excluded(self):
        fragment = self._fragment(start=self.day)
        self._event(fragment, at=self.day)
        self._event(
            fragment,
            at=self.day
            + timedelta(seconds=LOW_CONFIDENCE_MAX_DURATION_SECONDS)
            - timedelta(milliseconds=1),
        )

        self._rebuild()

        self.assertEqual(self._eligible_visit_count(), 0)

    def test_span_exactly_at_the_threshold_is_kept(self):
        fragment = self._fragment(start=self.day)
        self._event(fragment, at=self.day)
        self._event(
            fragment,
            at=self.day + timedelta(seconds=LOW_CONFIDENCE_MAX_DURATION_SECONDS),
        )

        self._rebuild()

        self.assertEqual(self._eligible_visit_count(), 1)

    def test_single_event_session_is_excluded(self):
        fragment = self._fragment(start=self.day)
        self._event(fragment, at=self.day)

        self._rebuild()

        self.assertEqual(self._eligible_visit_count(), 0)

    # ------------------------------------------------------------------
    # page flows
    # ------------------------------------------------------------------

    def test_excluded_session_contributes_no_transition(self):
        self._bounce()
        self._engaged_session()

        self._rebuild()

        self.assertEqual(PageTransition.objects.filter(project=self.project).count(), 0)

    def test_anonymous_two_page_session_still_contributes_a_transition(self):
        """Only single-page sessions can be excluded, so flows keep their data."""

        fragment = self._fragment(start=self.day)
        self._event(fragment, at=self.day, url=LANDING)
        self._event(fragment, at=self.day + timedelta(seconds=2), url=PRICING)

        self._rebuild()

        self.assertEqual(PageTransition.objects.filter(project=self.project).count(), 1)

    # ------------------------------------------------------------------
    # rebuild contract
    # ------------------------------------------------------------------

    def test_rebuild_is_idempotent(self):
        self._bounce()
        self._engaged_session()

        self._rebuild()
        first = self._landing_metric().visits_count
        self._rebuild()
        second = self._landing_metric().visits_count

        self.assertEqual(first, second)
        self.assertEqual(PageVisit.objects.filter(project=self.project).count(), 2)
        self.assertEqual(
            PageVisit.objects.filter(project=self.project, is_analytics_eligible=False).count(),
            1,
        )

    def test_a_session_that_earns_a_click_later_is_restored_by_a_rebuild(self):
        fragment = self._bounce()
        self._rebuild()
        self.assertEqual(self._eligible_visit_count(), 0)

        self._event(fragment, at=self.day + timedelta(seconds=8), event_type='click')
        self._rebuild()

        self.assertEqual(self._eligible_visit_count(), 1)


class UnlinkedFragmentTests(LowConfidenceFixtures, TestCase):
    """Fragments keep grouping into one visit after the recording is gone.

    Recording retention deletes ``Session`` rows after 30 days and
    ``AnalyticsSession.visit_session`` is ``SET_NULL``, so older fragments carry
    no link at all — and the nightly job re-judges 180 days of them.  Grouping
    has to survive that, or the anonymous opening of a visit that did identify
    itself gets dropped months after the fact.
    """

    def test_anonymous_opening_survives_when_the_recording_link_is_gone(self):
        visitor = uuid.uuid4()
        anonymous = self._fragment(start=self.day, visitor_guid=visitor)
        self._event(anonymous, at=self.day, url=LANDING)
        identified = self._fragment(
            start=self.day + timedelta(minutes=3),
            user_id='user-late',
            visitor_guid=visitor,
        )
        self._event(
            identified,
            at=self.day + timedelta(minutes=3),
            event_type='click',
            url=PRICING,
            user_id='user-late',
        )

        self.assertIsNone(anonymous.visit_session_id)
        self._rebuild()

        self.assertFalse(
            PageVisit.objects
            .filter(project=self.project, is_analytics_eligible=False)
            .exists(),
        )
        self.assertEqual(
            set(
                RawPageDailyMetric.objects
                .filter(project=self.project)
                .values_list('url_normalized', flat=True)
            ),
            {LANDING, PRICING},
        )

    def test_two_page_visit_split_across_unlinked_fragments_is_kept(self):
        """Neither half may look single-page just because it is its own row."""

        visitor = uuid.uuid4()
        first = self._fragment(start=self.day, visitor_guid=visitor)
        self._event(first, at=self.day, url=LANDING)
        second = self._fragment(
            start=self.day + timedelta(seconds=2),
            visitor_guid=visitor,
        )
        self._event(second, at=self.day + timedelta(seconds=2), url=PRICING)

        self._rebuild()

        self.assertEqual(
            PageVisit.objects.filter(project=self.project, is_analytics_eligible=True).count(),
            2,
        )

    def test_separate_visits_by_one_visitor_are_still_judged_apart(self):
        """The run split is the session timeout, so a later bounce is its own scope."""

        visitor = uuid.uuid4()
        engaged = self._fragment(start=self.day, visitor_guid=visitor)
        for index, event_type in enumerate(('click', 'click')):
            self._event(
                engaged,
                at=self.day + timedelta(seconds=index * 2),
                event_type=event_type,
                url=LANDING,
            )
        # Well beyond the 30-minute session timeout, so this is a new visit.
        bounce = self._fragment(
            start=self.day + timedelta(hours=3),
            visitor_guid=visitor,
        )
        self._event(bounce, at=self.day + timedelta(hours=3), url=PRICING)

        self._rebuild()

        self.assertEqual(
            PageVisit.objects.filter(project=self.project, is_analytics_eligible=False).count(),
            1,
        )
        excluded = PageVisit.objects.get(project=self.project, is_analytics_eligible=False)
        self.assertEqual(excluded.url_normalized, PRICING)


class CompaniesAndUsersUnchangedTests(LowConfidenceFixtures, TestCase):
    """The rule must not reach the company or user rollups.

    Both already drop every visit without the matching identity, so a
    low-confidence session — anonymous by definition — cannot appear in them
    before or after the change.  These pin that, since the two statements
    deliberately carry no eligibility predicate.
    """

    def test_bounces_never_reach_company_or_user_facts(self):
        self._bounce()
        self._bounce(at=self.day + timedelta(minutes=1))
        self._engaged_session()

        self._rebuild()

        company_rows = PageCompanyDailyMetric.objects.filter(project=self.project)
        user_rows = PageUserDailyMetric.objects.filter(project=self.project)
        self.assertEqual(company_rows.count(), 1)
        self.assertEqual(user_rows.count(), 1)
        self.assertEqual(company_rows.first().company_id, 'acme')
        self.assertEqual(company_rows.first().visits_count, 1)
        self.assertEqual(user_rows.first().user_id, 'user-1')
        self.assertEqual(user_rows.first().visits_count, 1)

    def test_company_and_user_facts_are_identical_with_and_without_bounces(self):
        self._engaged_session()
        self._rebuild()
        without = {
            'company': list(
                PageCompanyDailyMetric.objects
                .filter(project=self.project)
                .values_list('company_id', 'visits_count', 'engaged_seconds', 'click_count')
                .order_by('company_id')
            ),
            'user': list(
                PageUserDailyMetric.objects
                .filter(project=self.project)
                .values_list('user_id', 'visits_count', 'engaged_seconds', 'click_count')
                .order_by('user_id')
            ),
        }

        self._bounce()
        self._bounce(at=self.day + timedelta(minutes=1), url=PRICING)
        self._rebuild()
        with_bounces = {
            'company': list(
                PageCompanyDailyMetric.objects
                .filter(project=self.project)
                .values_list('company_id', 'visits_count', 'engaged_seconds', 'click_count')
                .order_by('company_id')
            ),
            'user': list(
                PageUserDailyMetric.objects
                .filter(project=self.project)
                .values_list('user_id', 'visits_count', 'engaged_seconds', 'click_count')
                .order_by('user_id')
            ),
        }

        self.assertEqual(without, with_bounces)


class LowConfidenceParityTests(LowConfidenceFixtures, TestCase):
    """The tracker flag and the Pages rollup must reach the same verdict.

    The rule is expressed twice — an ORM aggregate for the Visits scope and one
    SQL statement for the rollup — because each pipeline needs it in a
    different shape.  This drives both from the same fixtures.
    """

    def _recording(self, started_at):
        visitor = Visitor.objects.create(
            project=self.project,
            visitor_guid=uuid.uuid4(),
            first_visit=started_at,
            last_activity=started_at,
        )
        session = Session.objects.create(
            visitor=visitor,
            start_time=started_at,
            last_activity=started_at,
            ended_at=started_at,
            identity_linkage_ready=True,
        )
        Event.objects.create(
            session=session,
            event_type=2,
            timestamp=started_at,
            data={
                'type': 2,
                'timestamp': int(started_at.timestamp() * 1000),
                'data': {'node': {'type': 0, 'id': 1, 'childNodes': []}},
            },
        )
        return session

    def _scenarios(self):
        """Return ``(label, recording, fragment, expected_meaningful)`` per shape.

        The spacing column matters as much as the event types: it decides
        whether an interaction lands clear of
        ``MEANINGFUL_EVENT_MIN_OFFSET_SECONDS``, and both pipelines have to
        answer that the same way.
        """

        shapes = [
            ('bounce', ('mouse_move', 'mouse_move'), 2, None, None, LANDING, False),
            ('late-click', ('mouse_move', 'click'), 2, None, None, LANDING, True),
            ('early-click', ('mouse_move', 'click'), 0.5, None, None, LANDING, False),
            ('late-scroll', ('mouse_move', 'scroll'), 2, None, None, LANDING, True),
            ('late-touch-move', ('mouse_move', 'touch_move'), 2, None, None, LANDING, True),
            ('early-touch-move', ('mouse_move', 'touch_move'), 0.5, None, None, LANDING, False),
            ('late-key-press', ('mouse_move', 'key_press'), 2, None, None, LANDING, True),
            ('early-key-press', ('mouse_move', 'key_press'), 0.5, None, None, LANDING, False),
            ('scroll-at-open', ('scroll',), 2, None, None, LANDING, False),
            ('identified-user', ('mouse_move',), 2, 'user-x', None, LANDING, True),
            ('identified-company', ('mouse_move',), 2, None, 'acme-x', LANDING, True),
            ('single-event', ('mouse_move',), 2, None, None, LANDING, False),
        ]
        scenarios = []
        for index, shape in enumerate(shapes):
            label, event_types, spacing, user_id, company_id, url, expected = shape
            start = self.day + timedelta(minutes=index * 10)
            recording = self._recording(start)
            fragment = self._fragment(
                start=start,
                user_id=user_id,
                company_id=company_id,
                recording=recording,
            )
            for offset, event_type in enumerate(event_types):
                self._event(
                    fragment,
                    at=start + timedelta(seconds=offset * spacing),
                    event_type=event_type,
                    url=url,
                    user_id=user_id,
                    company_id=company_id,
                )
            scenarios.append((label, recording, fragment, expected))
        return scenarios

    def test_two_pipelines_agree_on_every_shape(self):
        scenarios = self._scenarios()
        # Add a multi-page anonymous session, which needs two events on
        # different URLs and so does not fit the table above.
        multi_start = self.day + timedelta(hours=2)
        multi_recording = self._recording(multi_start)
        multi_fragment = self._fragment(start=multi_start, recording=multi_recording)
        self._event(multi_fragment, at=multi_start, url=LANDING)
        self._event(multi_fragment, at=multi_start + timedelta(seconds=2), url=PRICING)
        scenarios.append(('multi-page', multi_recording, multi_fragment, True))

        self._rebuild()

        tracker_meaningful = meaningful_analytics_session_ids(
            [recording.pk for _label, recording, _fragment, _expected in scenarios]
        )

        for label, recording, fragment, expected in scenarios:
            with self.subTest(label=label):
                rollup_eligible = (
                    PageVisit.objects
                    .filter(project=self.project, session_id=fragment.session_id)
                    .exclude(is_analytics_eligible=False)
                    .exists()
                )
                self.assertEqual(recording.pk in tracker_meaningful, expected)
                self.assertEqual(rollup_eligible, expected)

    def test_anonymous_opening_of_an_identified_visit_is_kept_by_both(self):
        start = self.day
        recording = self._recording(start)
        anonymous = self._fragment(start=start, recording=recording)
        self._event(anonymous, at=start)
        identified = self._fragment(
            start=start + timedelta(minutes=3),
            user_id='user-late',
            recording=recording,
        )
        self._event(identified, at=start + timedelta(minutes=3), user_id='user-late')

        self._rebuild()

        self.assertIn(recording.pk, meaningful_analytics_session_ids([recording.pk]))
        self.assertFalse(
            PageVisit.objects
            .filter(project=self.project, is_analytics_eligible=False)
            .exists(),
        )
