"""Visits-side coverage for the low-confidence anonymous session rule.

Every case builds a completed recording that fails all four conditions and
then changes exactly one of them, so a failure names the condition that broke.
See :mod:`apps.tracker.analytics_eligibility`.
"""

import importlib
import uuid
from datetime import datetime, timedelta, timezone as datetime_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.projects.models import Project
from apps.projects.tests.helpers import create_workspace_with_owner
from apps.tracker.analytics_eligibility import (
    LOW_CONFIDENCE_MAX_DURATION_SECONDS,
    MEANINGFUL_EVENT_MIN_OFFSET_SECONDS,
    completion_cutoff,
    is_meaningful,
)
from apps.tracker.models import (
    AnalyticsEvent,
    AnalyticsSession,
    Event,
    ProjectPageRule,
    Session,
    Visitor,
)
from apps.tracker.visits_scope import (
    mark_meaningful_analytics_sessions,
    meaningful_analytics_session_ids,
    refresh_meaningful_analytics_flags,
    refresh_visits_scope,
)
from apps.tracker.visits_table import build_visits_context

UTC = datetime_timezone.utc


class LowConfidenceFixtures:
    """Shared fixtures. Not a TestCase, so suites below stay independent."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='low-confidence-owner',
            email='low-confidence-owner@example.com',
            password='testpass123',
        )
        self.workspace = create_workspace_with_owner(self.user, name='Low confidence workspace')
        self.project = Project.objects.create(
            workspace=self.workspace,
            name='Low confidence project',
            created_by=self.user,
            api_key='LOW_CONFIDENCE_PROJECT',
            timezone='UTC',
            tracking_capture='analytics,recording',
        )
        self.now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
        # Comfortably older than the completion cutoff, so every fixture below
        # counts as a session that is over unless a case says otherwise.
        self.started_at = self.now - timedelta(hours=6)

    # ------------------------------------------------------------------
    # fixtures
    # ------------------------------------------------------------------

    def _recording(self, started_at, *, duration_seconds=30):
        ended_at = started_at + timedelta(seconds=duration_seconds)
        visitor = Visitor.objects.create(
            project=self.project,
            visitor_guid=uuid.uuid4(),
            first_visit=started_at,
            last_activity=ended_at,
        )
        session = Session.objects.create(
            visitor=visitor,
            start_time=started_at,
            last_activity=ended_at,
            ended_at=ended_at,
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

    def _fragment(self, session, *, start, user_id=None, company_id=None):
        return AnalyticsSession.objects.create(
            project=self.project,
            visit_session=session,
            visitor_guid=session.visitor.visitor_guid,
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
        url='example.com/landing',
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
            url=f'https://{url}',
            url_normalized=url,
            page_name='Landing',
            page_name_original='Landing',
        )

    def _bounced_recording(
        self,
        *,
        started_at=None,
        event_types=('mouse_move', 'mouse_move'),
        spacing_seconds=1,
    ):
        """One completed, anonymous, single-page, sub-ten-second recording.

        ``spacing_seconds`` has to keep the whole recording inside
        ``LOW_CONFIDENCE_MAX_DURATION_SECONDS``, or the span alone qualifies it
        whatever the event types are.  A case about a click or scroll should
        also keep it clear of ``MEANINGFUL_EVENT_MIN_OFFSET_SECONDS``, so the
        interaction is what the case turns on rather than the boundary.
        """

        started_at = started_at or self.started_at
        session = self._recording(started_at)
        fragment = self._fragment(session, start=started_at)
        for index, event_type in enumerate(event_types):
            self._event(
                fragment,
                at=started_at + timedelta(seconds=index * spacing_seconds),
                event_type=event_type,
            )
        return session, fragment

    def _visible_session_ids(self):
        context = build_visits_context(self.project, now=self.now)
        visible = {str(row['session_id']) for row in context['visits']}
        return visible, context['total_visits']


class LowConfidenceVisitsTests(LowConfidenceFixtures, TestCase):
    # ------------------------------------------------------------------
    # the rule itself
    # ------------------------------------------------------------------

    def test_bounced_anonymous_recording_is_hidden_from_visits(self):
        session, _fragment = self._bounced_recording()

        session.refresh_from_db()
        self.assertFalse(session.has_meaningful_analytics)

        visible, total = self._visible_session_ids()
        self.assertNotIn(str(session.session_id), visible)
        self.assertEqual(total, 0)

    def test_click_keeps_the_recording(self):
        session, _fragment = self._bounced_recording(
            event_types=('mouse_move', 'click'),
            spacing_seconds=2,
        )

        session.refresh_from_db()
        self.assertTrue(session.has_meaningful_analytics)

        visible, total = self._visible_session_ids()
        self.assertIn(str(session.session_id), visible)
        self.assertEqual(total, 1)

    def test_scroll_keeps_the_recording(self):
        session, _fragment = self._bounced_recording(
            event_types=('mouse_move', 'scroll'),
            spacing_seconds=2,
        )

        visible, total = self._visible_session_ids()
        self.assertIn(str(session.session_id), visible)
        self.assertEqual(total, 1)

    def test_touch_move_keeps_the_recording(self):
        """A finger dragging across glass cannot happen by accident."""

        session, _fragment = self._bounced_recording(
            event_types=('mouse_move', 'touch_move'),
            spacing_seconds=2,
        )

        visible, total = self._visible_session_ids()
        self.assertIn(str(session.session_id), visible)
        self.assertEqual(total, 1)

    def test_key_press_keeps_the_recording(self):
        """Typing is sampled like pointer movement but is still deliberate."""

        session, _fragment = self._bounced_recording(
            event_types=('mouse_move', 'key_press'),
            spacing_seconds=2,
        )

        visible, total = self._visible_session_ids()
        self.assertIn(str(session.session_id), visible)
        self.assertEqual(total, 1)

    def test_mouse_move_alone_is_not_enough_however_many_there_are(self):
        session, _fragment = self._bounced_recording(
            event_types=('mouse_move',) * 8,
        )

        visible, _total = self._visible_session_ids()
        self.assertNotIn(str(session.session_id), visible)

    def test_second_page_keeps_the_recording(self):
        session = self._recording(self.started_at)
        fragment = self._fragment(session, start=self.started_at)
        self._event(fragment, at=self.started_at, url='example.com/landing')
        self._event(
            fragment,
            at=self.started_at + timedelta(seconds=2),
            url='example.com/pricing',
        )

        visible, total = self._visible_session_ids()
        self.assertIn(str(session.session_id), visible)
        self.assertEqual(total, 1)

    def test_identity_on_the_fragment_keeps_the_recording(self):
        session = self._recording(self.started_at)
        fragment = self._fragment(session, start=self.started_at, user_id='user-1')
        self._event(fragment, at=self.started_at)

        visible, _total = self._visible_session_ids()
        self.assertIn(str(session.session_id), visible)

    def test_company_only_identity_keeps_the_recording(self):
        session = self._recording(self.started_at)
        fragment = self._fragment(session, start=self.started_at, company_id='acme')
        self._event(fragment, at=self.started_at)

        visible, _total = self._visible_session_ids()
        self.assertIn(str(session.session_id), visible)

    def test_identity_carried_only_by_the_event_keeps_the_recording(self):
        """The rollup reads identity from the event or the fragment, so this does too."""

        session = self._recording(self.started_at)
        fragment = self._fragment(session, start=self.started_at)
        self._event(fragment, at=self.started_at, user_id='user-2')

        visible, _total = self._visible_session_ids()
        self.assertIn(str(session.session_id), visible)

    def test_anonymous_opening_of_an_identified_visit_is_kept(self):
        """Identity fragments are judged together, not one at a time."""

        session = self._recording(self.started_at, duration_seconds=600)
        anonymous = self._fragment(session, start=self.started_at)
        self._event(anonymous, at=self.started_at)
        identified = self._fragment(
            session,
            start=self.started_at + timedelta(minutes=4),
            user_id='user-3',
        )
        self._event(identified, at=self.started_at + timedelta(minutes=4))

        visible, total = self._visible_session_ids()
        self.assertIn(str(session.session_id), visible)
        self.assertEqual(total, 1)

    def test_session_still_in_flight_is_kept(self):
        """A live session can still earn its click, so it is not judged yet."""

        recent = self.now - timedelta(seconds=30)
        session, _fragment = self._bounced_recording(started_at=recent)

        session.refresh_from_db()
        self.assertFalse(session.has_meaningful_analytics)
        self.assertGreater(session.analytics_event_end, completion_cutoff(self.now))

        visible, total = self._visible_session_ids()
        self.assertIn(str(session.session_id), visible)
        self.assertEqual(total, 1)

    # ------------------------------------------------------------------
    # opening-second boundary
    # ------------------------------------------------------------------

    def test_click_inside_the_opening_second_is_ignored(self):
        """The shape this rule was tightened for: a bounce with one load click."""

        session, _fragment = self._bounced_recording(
            event_types=('mouse_move', 'click'),
            spacing_seconds=0.5,
        )

        session.refresh_from_db()
        self.assertFalse(session.has_meaningful_analytics)

        visible, total = self._visible_session_ids()
        self.assertNotIn(str(session.session_id), visible)
        self.assertEqual(total, 0)

    def test_scroll_as_the_first_event_is_ignored(self):
        """A single restored-scroll event is a zero-second session, not a read."""

        session, _fragment = self._bounced_recording(event_types=('scroll',))

        visible, _total = self._visible_session_ids()
        self.assertNotIn(str(session.session_id), visible)

    def test_click_exactly_at_the_offset_is_kept(self):
        session = self._recording(self.started_at)
        fragment = self._fragment(session, start=self.started_at)
        self._event(fragment, at=self.started_at)
        self._event(
            fragment,
            at=self.started_at + timedelta(seconds=MEANINGFUL_EVENT_MIN_OFFSET_SECONDS),
            event_type='click',
        )

        visible, _total = self._visible_session_ids()
        self.assertIn(str(session.session_id), visible)

    def test_click_a_millisecond_early_is_ignored(self):
        session = self._recording(self.started_at)
        fragment = self._fragment(session, start=self.started_at)
        self._event(fragment, at=self.started_at)
        self._event(
            fragment,
            at=self.started_at
            + timedelta(seconds=MEANINGFUL_EVENT_MIN_OFFSET_SECONDS)
            - timedelta(milliseconds=1),
            event_type='click',
        )

        visible, _total = self._visible_session_ids()
        self.assertNotIn(str(session.session_id), visible)

    def test_a_late_click_qualifies_a_session_an_early_one_did_not(self):
        """Only the latest interaction has to clear the offset, not every one."""

        session = self._recording(self.started_at)
        fragment = self._fragment(session, start=self.started_at)
        self._event(fragment, at=self.started_at)
        self._event(
            fragment,
            at=self.started_at + timedelta(milliseconds=200),
            event_type='click',
        )

        session.refresh_from_db()
        self.assertFalse(session.has_meaningful_analytics)

        self._event(
            fragment,
            at=self.started_at + timedelta(seconds=3),
            event_type='click',
        )

        visible, total = self._visible_session_ids()
        self.assertIn(str(session.session_id), visible)
        self.assertEqual(total, 1)

    # ------------------------------------------------------------------
    # duration boundary
    # ------------------------------------------------------------------

    def test_span_just_under_the_threshold_is_excluded(self):
        session = self._recording(self.started_at)
        fragment = self._fragment(session, start=self.started_at)
        self._event(fragment, at=self.started_at)
        self._event(
            fragment,
            at=self.started_at
            + timedelta(seconds=LOW_CONFIDENCE_MAX_DURATION_SECONDS)
            - timedelta(milliseconds=1),
        )

        visible, _total = self._visible_session_ids()
        self.assertNotIn(str(session.session_id), visible)

    def test_span_exactly_at_the_threshold_is_kept(self):
        session = self._recording(self.started_at)
        fragment = self._fragment(session, start=self.started_at)
        self._event(fragment, at=self.started_at)
        self._event(
            fragment,
            at=self.started_at + timedelta(seconds=LOW_CONFIDENCE_MAX_DURATION_SECONDS),
        )

        visible, _total = self._visible_session_ids()
        self.assertIn(str(session.session_id), visible)

    def test_single_event_session_has_a_zero_span_and_is_excluded(self):
        session = self._recording(self.started_at)
        fragment = self._fragment(session, start=self.started_at)
        self._event(fragment, at=self.started_at)

        session.refresh_from_db()
        self.assertEqual(session.analytics_event_start, session.analytics_event_end)

        visible, _total = self._visible_session_ids()
        self.assertNotIn(str(session.session_id), visible)

    # ------------------------------------------------------------------
    # flag maintenance
    # ------------------------------------------------------------------

    def test_flag_is_set_once_evidence_arrives_and_never_withdrawn(self):
        session, fragment = self._bounced_recording()
        session.refresh_from_db()
        self.assertFalse(session.has_meaningful_analytics)

        self._event(fragment, at=self.started_at + timedelta(seconds=3), event_type='click')
        session.refresh_from_db()
        self.assertTrue(session.has_meaningful_analytics)

        # A later batch carrying nothing meaningful cannot take it back.
        self._event(fragment, at=self.started_at + timedelta(seconds=4))
        mark_meaningful_analytics_sessions([session.pk])
        session.refresh_from_db()
        self.assertTrue(session.has_meaningful_analytics)

    def test_marking_is_idempotent(self):
        session, _fragment = self._bounced_recording(
            event_types=('mouse_move', 'click'),
            spacing_seconds=2,
        )
        for _ in range(3):
            mark_meaningful_analytics_sessions([session.pk])
        session.refresh_from_db()
        self.assertTrue(session.has_meaningful_analytics)

    def test_refresh_visits_scope_recomputes_the_flag_in_both_directions(self):
        """Offline writers get an authoritative recompute, not a widen-only one."""

        session, _fragment = self._bounced_recording()
        Session.objects.filter(pk=session.pk).update(has_meaningful_analytics=True)

        refresh_visits_scope([session.pk])

        session.refresh_from_db()
        self.assertFalse(session.has_meaningful_analytics)

    def test_recording_without_analytics_events_stays_out_of_scope(self):
        session = self._recording(self.started_at)

        session.refresh_from_db()
        self.assertIsNone(session.analytics_event_start)
        self.assertFalse(session.has_meaningful_analytics)

        visible, total = self._visible_session_ids()
        self.assertNotIn(str(session.session_id), visible)
        self.assertEqual(total, 0)



class StaleFlagTests(LowConfidenceFixtures, TestCase):
    """Evidence can be withdrawn by writers that rewrite stored events.

    Page naming rewrites ``url_normalized`` and ``page_rule_id`` on events that
    are already stored, so a session that qualified on two distinct pages can
    collapse to one.  Ingest's set-only marking cannot lower the flag, and the
    Pages rollup recomputes from events on every rebuild — so without an
    authoritative refresh the two surfaces disagree permanently.
    """

    def _two_rule_session(self):
        first_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^example\.com/landing$',
            product_area='Landing',
            page_name='Landing',
            priority=100,
        )
        second_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^example\.com/landing$',
            product_area='Landing',
            page_name='Landing renamed',
            priority=90,
        )
        session = self._recording(self.started_at)
        fragment = self._fragment(session, start=self.started_at)
        first = self._event(fragment, at=self.started_at)
        second = self._event(fragment, at=self.started_at + timedelta(seconds=3))
        AnalyticsEvent.objects.filter(pk=first.pk).update(page_rule=first_rule)
        AnalyticsEvent.objects.filter(pk=second.pk).update(page_rule=second_rule)
        return session, fragment, first_rule

    def test_collapsing_two_rules_into_one_lowers_the_flag(self):
        session, _fragment, first_rule = self._two_rule_session()
        refresh_meaningful_analytics_flags([session.pk])
        session.refresh_from_db()
        # Two distinct (url, rule) keys, so the session reads as meaningful.
        self.assertTrue(session.has_meaningful_analytics)

        AnalyticsEvent.objects.filter(session__visit_session_id=session.pk).update(
            page_rule=first_rule,
        )
        refresh_meaningful_analytics_flags([session.pk])

        session.refresh_from_db()
        self.assertFalse(session.has_meaningful_analytics)

    def test_set_only_marking_cannot_lower_the_flag_on_its_own(self):
        """Pins why the authoritative refresh has to exist."""

        session, _fragment, first_rule = self._two_rule_session()
        refresh_meaningful_analytics_flags([session.pk])
        AnalyticsEvent.objects.filter(session__visit_session_id=session.pk).update(
            page_rule=first_rule,
        )

        mark_meaningful_analytics_sessions([session.pk])

        session.refresh_from_db()
        self.assertTrue(session.has_meaningful_analytics)

    def test_removing_the_only_click_lowers_the_flag(self):
        session, _fragment = self._bounced_recording(
            event_types=('mouse_move', 'click'),
            spacing_seconds=2,
        )
        session.refresh_from_db()
        self.assertTrue(session.has_meaningful_analytics)

        AnalyticsEvent.objects.filter(
            session__visit_session_id=session.pk,
            event_type='click',
        ).delete()
        refresh_meaningful_analytics_flags([session.pk])

        session.refresh_from_db()
        self.assertFalse(session.has_meaningful_analytics)

        visible, total = self._visible_session_ids()
        self.assertNotIn(str(session.session_id), visible)
        self.assertEqual(total, 0)


class BackfillJudgementMigrationTests(LowConfidenceFixtures, TestCase):
    """Drive the backfill migration's judgement against real rows.

    Running it during test-database setup proves nothing, because the tables
    are empty then.  The migration re-implements the rule rather than importing
    it — a migration has to keep describing the rule as it stood when it ran —
    so this is what catches the two drifting apart.

    This target adopts the denormalized flag in one step, so there is no older
    verdict to overwrite: the single backfill judges under the current rule and
    runs in both directions, which is what the cases below assert.
    """

    def _backfill(self):
        from django.apps import apps as installed_apps

        module = importlib.import_module(
            'apps.tracker.migrations.0004_backfill_visits_scope',
        )
        module.backfill_visits_scope(installed_apps, None)

    def _fixtures(self):
        """One recording per verdict the rule can reach, plus the empty case."""

        bounced, _fragment = self._bounced_recording()
        late_click, _fragment = self._bounced_recording(
            started_at=self.started_at + timedelta(hours=1),
            event_types=('mouse_move', 'click'),
            spacing_seconds=2,
        )
        early_click, _fragment = self._bounced_recording(
            started_at=self.started_at + timedelta(hours=2),
            event_types=('mouse_move', 'click'),
            spacing_seconds=0.5,
        )
        empty = self._recording(self.started_at + timedelta(hours=3))
        return bounced, late_click, early_click, empty

    def test_backfill_agrees_with_the_runtime_helper(self):
        bounced, late_click, early_click, empty = self._fixtures()
        # Scramble first, so agreement is the migration's doing rather than the
        # ingest receiver's.
        Session.objects.all().update(has_meaningful_analytics=True)

        self._backfill()

        for session, expected in (
            (bounced, False),
            (late_click, True),
            (early_click, False),
            (empty, False),
        ):
            with self.subTest(session=session.pk):
                session.refresh_from_db()
                self.assertEqual(session.has_meaningful_analytics, expected)

        self.assertEqual(
            meaningful_analytics_session_ids(
                [bounced.pk, late_click.pk, early_click.pk, empty.pk],
            ),
            {late_click.pk},
        )

    def test_backfill_lowers_a_flag_that_should_not_be_set(self):
        """The reason it runs in both directions: ingest marking cannot lower it."""

        _bounced, _late_click, early_click, _empty = self._fixtures()
        Session.objects.filter(pk=early_click.pk).update(has_meaningful_analytics=True)

        mark_meaningful_analytics_sessions([early_click.pk])
        early_click.refresh_from_db()
        self.assertTrue(early_click.has_meaningful_analytics)

        self._backfill()

        early_click.refresh_from_db()
        self.assertFalse(early_click.has_meaningful_analytics)

    def test_backfill_is_safe_to_repeat(self):
        _bounced, late_click, _early_click, _empty = self._fixtures()

        self._backfill()
        first = set(
            Session.objects
            .filter(has_meaningful_analytics=True)
            .values_list('pk', flat=True)
        )
        # A second pass must not widen or narrow the result.
        self._backfill()
        second = set(
            Session.objects
            .filter(has_meaningful_analytics=True)
            .values_list('pk', flat=True)
        )

        self.assertEqual(first, {late_click.pk})
        self.assertEqual(first, second)


class MeaningfulPredicateTests(TestCase):
    """Direct coverage of the shared predicate's boundaries."""

    def _facts(self, **overrides):
        facts = {
            'has_identity': False,
            'page_count': 1,
            'span_seconds': 0.0,
            'meaningful_event_offset_seconds': None,
        }
        facts.update(overrides)
        return facts

    def test_all_conditions_failing_is_not_meaningful(self):
        self.assertFalse(is_meaningful(**self._facts()))

    def test_any_single_condition_is_enough(self):
        for override in (
            {'has_identity': True},
            {
                'meaningful_event_offset_seconds': float(
                    MEANINGFUL_EVENT_MIN_OFFSET_SECONDS,
                ),
            },
            {'page_count': 2},
            {'span_seconds': float(LOW_CONFIDENCE_MAX_DURATION_SECONDS)},
        ):
            with self.subTest(**override):
                self.assertTrue(is_meaningful(**self._facts(**override)))

    def test_span_boundary_is_inclusive_at_the_threshold(self):
        just_under = LOW_CONFIDENCE_MAX_DURATION_SECONDS - 0.001
        self.assertFalse(is_meaningful(**self._facts(span_seconds=just_under)))
        self.assertTrue(
            is_meaningful(**self._facts(span_seconds=float(LOW_CONFIDENCE_MAX_DURATION_SECONDS))),
        )

    def test_interaction_offset_boundary_is_inclusive_at_the_threshold(self):
        just_under = MEANINGFUL_EVENT_MIN_OFFSET_SECONDS - 0.001
        self.assertFalse(
            is_meaningful(**self._facts(meaningful_event_offset_seconds=just_under)),
        )
        self.assertTrue(
            is_meaningful(
                **self._facts(
                    meaningful_event_offset_seconds=float(
                        MEANINGFUL_EVENT_MIN_OFFSET_SECONDS,
                    ),
                ),
            ),
        )

    def test_an_interaction_at_the_first_event_is_no_interaction_at_all(self):
        self.assertFalse(
            is_meaningful(**self._facts(meaningful_event_offset_seconds=0.0)),
        )

    def test_no_interaction_reads_as_none_rather_than_zero(self):
        """``None`` and ``0.0`` mean different things and must not be conflated."""

        self.assertFalse(
            is_meaningful(**self._facts(meaningful_event_offset_seconds=None)),
        )
