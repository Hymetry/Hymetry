"""Rollup coverage for the ``key_press`` and ``touch_move`` event types.

Both are sampled rather than kept one for one, so their counts answer "was the
visitor typing / dragging during this flush" rather than "how many keystrokes".
They reach the prepared page visit as counts of their own, leaving
``click_count`` and everything built on it untouched.

``touchstart`` is deliberately not an event type: a touch device synthesizes a
click after a tap, so taps already arrive as clicks.  What ``touch_move`` adds
is the drag that never becomes a click -- panning a map, drawing on a canvas --
which otherwise leaves no event and reads as idle time.

See :mod:`apps.tracker.analytics_eligibility` for the separate question of
whether these count as deliberate interaction, which they do.
"""

import uuid
from datetime import datetime, timedelta, timezone as datetime_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.pages.models import PageDailyMetric, PageVisit
from apps.pages.services import rebuild_project_pages_analytics
from apps.projects.models import (
    Project,
    Workspace,
    WorkspaceMemberRole,
    WorkspaceMemberStatus,
    WorkspaceMembership,
)
from apps.tracker.models import AnalyticsEvent, AnalyticsSession

UTC = datetime_timezone.utc

LANDING = 'app.example.com/landing'


class SampledEventRollupTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='sampled-rollup-owner',
            email='sampled-rollup-owner@example.com',
            password='testpass123',
        )
        self.workspace = Workspace.objects.create(
            name='Sampled rollup workspace',
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
            name='Sampled rollup project',
            created_by=self.user,
            timezone='UTC',
        )
        self.now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
        self.day = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)

    # ------------------------------------------------------------------
    # fixtures
    # ------------------------------------------------------------------

    def _fragment(self, *, start):
        """An identified fragment, so the low-confidence rule never applies."""

        return AnalyticsSession.objects.create(
            project=self.project,
            visitor_guid=uuid.uuid4(),
            user_id='user-1',
            company_id='acme',
            start_time=start,
            last_activity=start,
            ended_at=start,
        )

    def _event(self, fragment, *, at, event_type):
        return AnalyticsEvent.objects.create(
            session=fragment,
            event_type=event_type,
            timestamp=at,
            visitor_guid=fragment.visitor_guid,
            user_id='user-1',
            company_id='acme',
            user_traits={},
            company_traits={},
            element_key='Button: Save' if event_type == 'click' else None,
            url=f'https://{LANDING}',
            url_normalized=LANDING,
            product_area='Landing',
            page_name='Landing',
            page_name_original='Landing',
        )

    def _visit(self, *, start, event_types, spacing_seconds=2):
        fragment = self._fragment(start=start)
        for index, event_type in enumerate(event_types):
            self._event(
                fragment,
                at=start + timedelta(seconds=index * spacing_seconds),
                event_type=event_type,
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

    # ------------------------------------------------------------------
    # prepared visits
    # ------------------------------------------------------------------

    def test_prepared_visit_counts_each_event_type_separately(self):
        self._visit(
            start=self.day,
            event_types=(
                'click',
                'scroll',
                'mouse_move',
                'key_press',
                'touch_move',
                'touch_move',
            ),
        )

        self._rebuild()

        visit = PageVisit.objects.get(project=self.project)
        self.assertEqual(visit.click_count, 1)
        self.assertEqual(visit.scroll_count, 1)
        self.assertEqual(visit.mouse_move_count, 1)
        self.assertEqual(visit.key_press_count, 1)
        self.assertEqual(visit.touch_move_count, 2)
        self.assertTrue(visit.had_click)
        self.assertTrue(visit.had_scroll)
        self.assertTrue(visit.had_mouse_move)
        self.assertTrue(visit.had_key_press)
        self.assertTrue(visit.had_touch_move)

    def test_a_visit_with_neither_records_zero(self):
        self._visit(start=self.day, event_types=('click', 'scroll'))

        self._rebuild()

        visit = PageVisit.objects.get(project=self.project)
        self.assertEqual(visit.key_press_count, 0)
        self.assertEqual(visit.touch_move_count, 0)
        self.assertFalse(visit.had_key_press)
        self.assertFalse(visit.had_touch_move)

    # ------------------------------------------------------------------
    # engaged time
    # ------------------------------------------------------------------

    def test_a_drag_that_never_clicks_is_engaged_rather_than_idle(self):
        """The case `touch_move` exists for.

        Without it a two-minute drag on a map leaves one event at each end and
        the gap between them caps at 30 seconds.  Sampled records land through
        the middle of it, so the visit is measured as the time it took.
        """

        self._visit(
            start=self.day,
            event_types=('click',) + ('touch_move',) * 12,
            spacing_seconds=10,
        )

        self._rebuild()

        visit = PageVisit.objects.get(project=self.project)
        # Twelve gaps of ten seconds, each under the thirty-second cap.
        self.assertEqual(visit.engaged_seconds, 120)
        self.assertEqual(visit.touch_move_count, 12)

    # ------------------------------------------------------------------
    # daily facts
    # ------------------------------------------------------------------

    def test_daily_metric_sums_key_press_and_touch_move_across_visits(self):
        self._visit(start=self.day, event_types=('key_press', 'touch_move', 'touch_move'))
        self._visit(
            start=self.day + timedelta(hours=1),
            event_types=('key_press', 'key_press', 'touch_move'),
        )

        self._rebuild()

        self.assertEqual(PageVisit.objects.filter(project=self.project).count(), 2)
        metric = PageDailyMetric.objects.get(project=self.project, date=self.day.date())
        self.assertEqual(metric.visits_count, 2)
        self.assertEqual(metric.key_press_count, 3)
        self.assertEqual(metric.touch_move_count, 3)
        self.assertEqual(metric.click_count, 0)
