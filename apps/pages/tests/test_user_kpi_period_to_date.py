from datetime import datetime, time, timedelta, timezone as datetime_timezone
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.pages import services, user_analytics, user_detail_analytics
from apps.pages.models import PageUserDailyMetric, PageVisit, ProductArea
from apps.projects.models import (
    Project,
    Workspace,
    WorkspaceMemberRole,
    WorkspaceMemberStatus,
    WorkspaceMembership,
)
from apps.tracker.models import ProjectPageRule


class UserKpiPeriodToDateTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            username='user-kpi-owner',
            email='user-kpi-owner@example.com',
            password='testpass123',
        )
        self.workspace = Workspace.objects.create(
            name='User KPI Workspace',
            website_url='example.com',
            created_by=self.owner,
        )
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=self.owner,
            role=WorkspaceMemberRole.OWNER,
            status=WorkspaceMemberStatus.ACTIVE,
        )
        self.project = Project.objects.create(
            workspace=self.workspace,
            name='User KPI Project',
            created_by=self.owner,
            timezone='UTC',
        )
        self.start_date, self.end_date = services.resolve_period(
            self.project.timezone,
            range_key='last_30_days',
        )

    def _daily_metric(
        self,
        *,
        day,
        user_id,
        page_rule_id,
        area,
        visits,
        engaged,
        clicks,
    ):
        return PageUserDailyMetric.objects.create(
            project=self.project,
            date=day,
            page_rule_id=page_rule_id,
            product_area_key=area,
            product_area_name=area.title(),
            company_id='acme',
            user_id=user_id,
            user_name_sample=user_id,
            visits_count=visits,
            engaged_seconds=engaged,
            click_count=clicks,
        )

    def _page_visit(self, *, day, user_id, page_rule_id, area, had_click):
        started_at = datetime.combine(
            day,
            time(hour=12),
            tzinfo=datetime_timezone.utc,
        )
        return PageVisit.objects.create(
            project=self.project,
            session_id=uuid4(),
            user_id=user_id,
            user_name_sample=user_id,
            company_id='acme',
            company_name_sample='Acme',
            page_rule_id=page_rule_id,
            product_area_key=area,
            product_area_name=area.title(),
            visit_start_ts=started_at,
            visit_end_ts=started_at + timedelta(minutes=1),
            click_count=1 if had_click else 0,
            had_click=had_click,
        )

    def test_overview_kpis_use_daily_values_and_period_status_mix(self):
        power_days = [
            self.start_date,
            self.start_date + timedelta(days=5),
            self.start_date + timedelta(days=10),
            self.end_date,
        ]
        for index, day in enumerate(power_days):
            for area_index, area in enumerate(('', 'core')):
                self._daily_metric(
                    day=day,
                    user_id='power@example.com',
                    page_rule_id=101 + area_index,
                    # Empty keys are legacy-but-counted distinct values in the
                    # period aggregate and the single-day classifier.
                    area=area,
                    visits=2,
                    engaged=100,
                    clicks=1,
                )
        self._daily_metric(
            day=self.start_date + timedelta(days=7),
            user_id='low@example.com',
            page_rule_id=103,
            area='core',
            visits=1,
            engaged=20,
            clicks=0,
        )

        payload = user_analytics.build_users_overview_payload(
            self.project,
            range_key='last_30_days',
        )
        cards = {card['key']: card for card in payload['kpis']}

        active_users = cards['activeUsers']
        self.assertEqual(active_users['label'], 'Avg daily active users')
        self.assertEqual(active_users['value'], 0.17)
        self.assertEqual(active_users['sparklineScope'], 'daily')
        self.assertEqual(active_users['sparklineLabel'], 'Daily active users')
        self.assertEqual(active_users['sparkline'][-1], 1)
        self.assertEqual(max(active_users['sparkline']), 1)
        self.assertEqual(sum(active_users['sparkline']), 5)

        engaged_per_user = cards['engagedPerUser']
        self.assertEqual(engaged_per_user['label'], 'Avg daily engaged / user')
        self.assertEqual(engaged_per_user['value'], user_analytics._format_duration(164))
        self.assertEqual(engaged_per_user['sparklineScope'], 'daily')
        self.assertEqual(engaged_per_user['sparklineLabel'], 'Daily engaged / user')
        self.assertEqual(engaged_per_user['sparkline'][-1], 200)
        self.assertEqual(
            [
                point
                for point in engaged_per_user['sparkline']
                if point is not None
            ],
            [200, 200, 20, 200, 200],
        )
        self.assertIsNone(engaged_per_user['sparkline'][1])

        # Four of the five active user-days were Power days, so the share cards
        # read 80% and 20% rather than the fractional per-day averages the old
        # count cards showed.
        power_users = cards['powerUsers']
        self.assertEqual(power_users['label'], 'High-activity share')
        self.assertEqual(power_users['value'], '80.0%')
        self.assertNotIn('secondary', power_users)
        self.assertEqual(power_users['sparklineScope'], 'daily')
        self.assertEqual(power_users['sparklineValueType'], 'percent')
        self.assertEqual(power_users['sparklineRender'], 'line')
        self.assertEqual(power_users['sparklineLabel'], 'Daily high-activity share')
        self.assertEqual(power_users['sparkline'][-1], 100.0)
        # A day nobody was active on has no share, so it is left undefined
        # rather than counted as a day when nobody qualified.
        self.assertIsNone(power_users['sparkline'][1])
        self.assertEqual(
            [point for point in power_users['sparkline'] if point is not None],
            [100.0, 100.0, 0.0, 100.0, 100.0],
        )

        low_users = cards['lowEngagementUsers']
        self.assertEqual(low_users['label'], 'Light-activity share')
        self.assertEqual(low_users['value'], '20.0%')
        self.assertNotIn('secondary', low_users)
        self.assertEqual(low_users['sparklineScope'], 'daily')
        self.assertEqual(low_users['sparklineValueType'], 'percent')
        self.assertEqual(low_users['sparklineRender'], 'line')
        self.assertEqual(
            low_users['sparklineLabel'],
            'Daily light-activity share',
        )
        self.assertEqual(low_users['sparkline'][-1], 0.0)
        self.assertEqual(
            [point for point in low_users['sparkline'] if point is not None],
            [0.0, 0.0, 100.0, 0.0, 0.0],
        )

        self.assertEqual(
            payload['dailyActiveTrend']['activeUsers'],
            active_users['sparkline'],
        )
        # The status mix is now two period distributions rather than a daily
        # timeline, and the selected one still names one Power user.
        status_counts = {
            row['status']: row['count']
            for row in payload['statusDistribution']
        }
        self.assertEqual(status_counts['Power'], 1)
        self.assertEqual(
            sorted(row['status'] for row in payload['previousStatusDistribution']),
            sorted(row['status'] for row in payload['statusDistribution']),
        )

        self.assertEqual(user_analytics._format_duration(151), '2m 31s')
        self.assertEqual(user_analytics._format_duration(3580), '59m 40s')
        self.assertEqual(user_analytics._format_duration(7180), '1h 59m')
        self.assertEqual(user_analytics._format_duration(2.5), '3s')
        self.assertEqual(user_detail_analytics._format_duration(151), '2m 31s')
        self.assertEqual(user_detail_analytics._format_duration(3580), '59m 40s')
        self.assertEqual(user_detail_analytics._format_duration(7180), '1h 59m')
        self.assertEqual(user_detail_analytics._format_duration(2.5), '3s')
        self.assertEqual(user_detail_analytics._format_percent(3.33), '3.3%')
        self.assertEqual(user_detail_analytics._format_percent(12.5), '13%')

    def test_overview_daily_engaged_average_weights_active_user_days(self):
        previous_start, _previous_end = services.previous_period(
            self.start_date,
            self.end_date,
        )
        for index in range(2):
            self._daily_metric(
                day=previous_start + timedelta(days=index),
                user_id='previous@example.com',
                page_rule_id=400 + index,
                area='core',
                visits=1,
                engaged=100,
                clicks=1,
            )

        first_day = self.start_date
        second_day = self.start_date + timedelta(days=1)
        zero_engaged_day = self.start_date + timedelta(days=2)
        self._daily_metric(
            day=first_day,
            user_id='split@example.com',
            page_rule_id=410,
            area='core',
            visits=1,
            engaged=120,
            clicks=1,
        )
        self._daily_metric(
            day=first_day,
            user_id='split@example.com',
            page_rule_id=411,
            area='admin',
            visits=1,
            engaged=180,
            clicks=1,
        )
        for index, user_id in enumerate(('a@example.com', 'b@example.com', 'c@example.com')):
            self._daily_metric(
                day=second_day,
                user_id=user_id,
                page_rule_id=420 + index,
                area='core',
                visits=1,
                engaged=100,
                clicks=1,
            )
        self._daily_metric(
            day=zero_engaged_day,
            user_id='zero@example.com',
            page_rule_id=430,
            area='core',
            visits=1,
            engaged=0,
            clicks=0,
        )

        payload = user_analytics.build_users_overview_payload(
            self.project,
            range_key='last_30_days',
        )
        cards = {item['key']: item for item in payload['kpis']}
        card = cards['engagedPerUser']

        self.assertEqual(card['value'], user_analytics._format_duration(120))
        self.assertEqual(card['delta'], 20)
        self.assertEqual(card['deltaLabel'], '+20%')
        self.assertEqual(card['deltaType'], 'positive')
        self.assertEqual(card['sparkline'][:4], [300, 100, 0, None])
        self.assertEqual(
            payload['dailyActiveTrend']['engagedSeconds'],
            card['sparkline'],
        )

        active_users = cards['activeUsers']
        self.assertEqual(active_users['value'], 0.17)
        self.assertEqual(active_users['sparkline'][:4], [1, 3, 1, 0])
        self.assertEqual(active_users['delta'], 142.9)
        self.assertEqual(active_users['deltaLabel'], '+143%')
        self.assertEqual(active_users['deltaType'], 'positive')
        self.assertEqual(
            payload['dailyActiveTrend']['activeUsers'],
            active_users['sparkline'],
        )

        power_users = cards['powerUsers']
        self.assertEqual(power_users['value'], '0.0%')
        self.assertNotIn('secondary', power_users)
        self.assertEqual(power_users['sparkline'][:4], [0.0, 0.0, 0.0, None])
        self.assertEqual(power_users['delta'], 0.0)
        self.assertEqual(power_users['deltaLabel'], '0.0 pp')
        self.assertEqual(power_users['deltaType'], 'neutral')

        # Every active user-day in both periods was a light one, so the share
        # sits at 100% and has not moved, even though the head count tripled.
        # The old count card read that same period as +143%.
        low_users = cards['lowEngagementUsers']
        self.assertEqual(low_users['value'], '100.0%')
        self.assertNotIn('secondary', low_users)
        self.assertEqual(low_users['sparkline'][:4], [100.0, 100.0, 100.0, None])
        self.assertEqual(low_users['delta'], 0.0)
        self.assertEqual(low_users['deltaLabel'], '0.0 pp')
        self.assertEqual(low_users['deltaType'], 'neutral')

    def test_overview_engaged_denominator_includes_non_visit_active_days(self):
        first_day = self.start_date
        second_day = self.start_date + timedelta(days=1)
        self._daily_metric(
            day=first_day,
            user_id='engaged-only@example.com',
            page_rule_id=440,
            area='core',
            visits=0,
            engaged=120,
            clicks=0,
        )
        self._daily_metric(
            day=second_day,
            user_id='normal@example.com',
            page_rule_id=441,
            area='core',
            visits=1,
            engaged=60,
            clicks=1,
        )
        self._daily_metric(
            day=second_day,
            user_id='click-only@example.com',
            page_rule_id=442,
            area='core',
            visits=0,
            engaged=0,
            clicks=1,
        )

        payload = user_analytics.build_users_overview_payload(
            self.project,
            range_key='last_30_days',
        )
        cards = {item['key']: item for item in payload['kpis']}
        active_points = cards['activeUsers']['sparkline']
        engaged_points = cards['engagedPerUser']['sparkline']
        finite_engaged_points = [
            point
            for point in engaged_points
            if point is not None
        ]

        self.assertEqual(active_points[:3], [1, 2, 0])
        self.assertEqual(engaged_points[:3], [120, 30, None])
        weighted_engaged = round(
            sum(
                point * active
                for point, active in zip(engaged_points, active_points)
                if point is not None
            )
            / sum(active_points)
        )
        self.assertEqual(weighted_engaged, 60)
        self.assertEqual(
            cards['engagedPerUser']['value'],
            user_analytics._format_duration(weighted_engaged),
        )
        self.assertLessEqual(
            min(finite_engaged_points),
            weighted_engaged,
        )
        self.assertGreaterEqual(
            max(finite_engaged_points),
            weighted_engaged,
        )

    def test_empty_overview_kpis_expose_daily_contract(self):
        payload = user_analytics.empty_users_overview_payload(
            self.project,
            range_key='last_30_days',
        )
        cards = {item['key']: item for item in payload['kpis']}

        self.assertEqual(user_analytics.USERS_PAYLOAD_SCHEMA_VERSION, 16)
        self.assertEqual(payload['schema_version'], 16)
        self.assertEqual(
            {
                key: (
                    card['label'],
                    card['sparklineScope'],
                    card['sparklineLabel'],
                )
                for key, card in cards.items()
            },
            {
                'activeUsers': (
                    'Avg daily active users',
                    'daily',
                    'Daily active users',
                ),
                'engagedPerUser': (
                    'Avg daily engaged / user',
                    'daily',
                    'Daily engaged / user',
                ),
                'powerUsers': (
                    'High-activity share',
                    'daily',
                    'Daily high-activity share',
                ),
                'lowEngagementUsers': (
                    'Light-activity share',
                    'daily',
                    'Daily light-activity share',
                ),
            },
        )
        self.assertEqual(cards['powerUsers']['value'], '0.0%')
        self.assertEqual(cards['lowEngagementUsers']['value'], '0.0%')
        self.assertNotIn('secondary', cards['powerUsers'])
        self.assertNotIn('secondary', cards['lowEngagementUsers'])
        self.assertEqual(payload['previousStatusDistribution'], [])

    def test_detail_prefix_endpoints_match_and_returning_pages_are_distinct(self):
        user_id = 'detail@example.com'
        second_day = self.start_date + timedelta(days=8)
        self._daily_metric(
            day=self.start_date,
            user_id=user_id,
            page_rule_id=201,
            area='core',
            visits=2,
            engaged=120,
            clicks=5,
        )
        self._daily_metric(
            day=second_day,
            user_id=user_id,
            page_rule_id=201,
            area='core',
            visits=1,
            engaged=30,
            clicks=1,
        )
        self._daily_metric(
            day=second_day,
            user_id=user_id,
            page_rule_id=202,
            area='admin',
            visits=1,
            engaged=50,
            clicks=0,
        )
        for day, page_rule_id, had_click in (
            (self.start_date, 201, True),
            (self.start_date, 201, False),
            (second_day, 201, False),
            (second_day, 202, False),
        ):
            self._page_visit(
                day=day,
                user_id=user_id,
                page_rule_id=page_rule_id,
                area='core' if page_rule_id == 201 else 'admin',
                had_click=had_click,
            )

        current = user_detail_analytics._aggregate_user_metrics(
            self.project.id,
            self.start_date,
            self.end_date,
            user_ids=[user_id],
        )[user_id]
        current_visits = user_detail_analytics._visit_metrics(
            self.project,
            self.start_date,
            self.end_date,
            user_ids=[user_id],
        )[user_id]
        cards = user_detail_analytics._metric_cards(
            self.project,
            user_id,
            self.start_date,
            self.end_date,
            current,
            {},
            current_visits,
            {},
            30,
        )
        by_id = {card['id']: card for card in cards}

        for card_id in (
            'engaged_time',
            'intensity',
            'visits',
            'avg_visit',
            'pages_used',
            'areas_used',
        ):
            self.assertEqual(
                by_id[card_id]['dailySeries'][-1]['value'],
                by_id[card_id]['rawValue'],
                card_id,
            )
        self.assertEqual(
            by_id['interaction_rate']['dailySeries'][-1]['value'],
            by_id['interaction_rate']['rawValue'] * 100,
        )

        # Active days draws one cell per date instead of a line, so it carries a
        # strip rather than a daily series, and its own count has to agree with
        # the number of cells the strip marks active.
        active_days_card = by_id['active_days']
        self.assertNotIn('dailySeries', active_days_card)
        self.assertNotIn('consistency', by_id)
        self.assertEqual(len(active_days_card['activityStrip']), 30)
        self.assertEqual(
            sum(1 for day in active_days_card['activityStrip'] if day['active']),
            active_days_card['activeDays'],
        )
        self.assertEqual(active_days_card['periodDays'], 30)
        self.assertEqual(
            active_days_card['value'],
            f"{active_days_card['activeDays']} of 30 days",
        )

        self.assertEqual(by_id['pages_used']['rawValue'], 2)
        self.assertEqual(by_id['pages_used']['dailySeries'][-1]['value'], 2)

        # Areas used took the second column the merged Active days card handed
        # back. It counts distinct product areas, states its unit in both the
        # headline and the previous-period wording, and steps up on the date the
        # second area was first touched rather than at the period start.
        areas_card = by_id['areas_used']
        self.assertEqual(areas_card['label'], 'Areas used')
        self.assertEqual(areas_card['rawValue'], 2)
        self.assertEqual(areas_card['value'], '2 product areas')
        self.assertEqual(areas_card['deltaType'], 'absolute')
        self.assertEqual(areas_card['previousValue'], 0)
        self.assertEqual(areas_card['previousValueLabel'], '0 product areas')
        self.assertNotIn('render', areas_card)
        self.assertEqual(
            [point['value'] for point in areas_card['dailySeries'][:8]],
            [1] * 8,
        )
        self.assertEqual(areas_card['dailySeries'][8]['value'], 2)
        self.assertEqual(by_id['interaction_rate']['rawValue'], 0.25)
        self.assertLessEqual(
            max(point['value'] for point in by_id['interaction_rate']['dailySeries']),
            100,
        )

    def test_interaction_fallback_is_bounded_and_endpoint_aligned(self):
        user_id = 'fallback@example.com'
        self._daily_metric(
            day=self.end_date,
            user_id=user_id,
            page_rule_id=301,
            area='core',
            visits=1,
            engaged=30,
            clicks=5,
        )
        current = user_detail_analytics._aggregate_user_metrics(
            self.project.id,
            self.start_date,
            self.end_date,
            user_ids=[user_id],
        )[user_id]
        cards = user_detail_analytics._metric_cards(
            self.project,
            user_id,
            self.start_date,
            self.end_date,
            current,
            {},
            {},
            {},
            30,
        )
        interaction = next(card for card in cards if card['id'] == 'interaction_rate')

        self.assertEqual(interaction['rawValue'], 1)
        self.assertEqual(interaction['dailySeries'][-1]['value'], 100)
        self.assertLessEqual(
            max(point['value'] for point in interaction['dailySeries']),
            100,
        )
        visits = next(card for card in cards if card['id'] == 'visits')
        self.assertIsNone(visits['deltaValue'])
        self.assertEqual(visits['deltaLabel'], 'New')
        self.assertEqual(visits['previousValue'], 0)
        engaged = next(card for card in cards if card['id'] == 'engaged_time')
        self.assertIsNone(engaged['deltaValue'])
        self.assertEqual(engaged['deltaLabel'], 'New')

    def test_new_deltas_do_not_trigger_decline_recommendations_or_insights(self):
        metric_cards = [
            {'id': 'engaged_time', 'deltaValue': None},
            {'id': 'pages_used', 'deltaValue': None},
        ]

        actions = user_detail_analytics._recommended_actions(
            metric_cards,
            [],
            [],
            [],
            [],
            'new-user@example.com',
            {
                'visits': 1,
                'engagedSeconds': 120,
                'activeDays': 1,
                'consistency': 0,
                'pagesUsed': 1,
            },
        )
        insights = user_detail_analytics._insights(
            'new-user@example.com',
            metric_cards,
            [],
            [],
            [],
            '',
        )

        self.assertNotIn('usage_drop', {action['type'] for action in actions})
        self.assertFalse(any(insight.startswith('Usage dropped') for insight in insights))

    def test_interaction_exact_visit_facts_are_bounded_to_metric_visits(self):
        user_id = 'mixed-facts@example.com'
        self._daily_metric(
            day=self.end_date,
            user_id=user_id,
            page_rule_id=302,
            area='core',
            visits=1,
            engaged=30,
            clicks=2,
        )
        for _index in range(2):
            self._page_visit(
                day=self.end_date,
                user_id=user_id,
                page_rule_id=302,
                area='core',
                had_click=True,
            )

        current = user_detail_analytics._aggregate_user_metrics(
            self.project.id,
            self.start_date,
            self.end_date,
            user_ids=[user_id],
        )[user_id]
        current_visits = user_detail_analytics._visit_metrics(
            self.project,
            self.start_date,
            self.end_date,
            user_ids=[user_id],
        )[user_id]
        cards = user_detail_analytics._metric_cards(
            self.project,
            user_id,
            self.start_date,
            self.end_date,
            current,
            {},
            current_visits,
            {},
            30,
        )
        interaction = next(card for card in cards if card['id'] == 'interaction_rate')

        self.assertEqual(interaction['rawValue'], 1)
        self.assertEqual(interaction['dailySeries'][-1]['value'], 100)
        self.assertLessEqual(
            max(point['value'] for point in interaction['dailySeries']),
            100,
        )

    def test_page_row_interaction_uses_matching_visit_facts_for_both_periods(self):
        user_id = 'page-row@example.com'
        rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern='/billing',
            product_area='Billing',
            page_name='Billing',
        )
        area = ProductArea.objects.create(
            project=self.project,
            name='Billing',
            slug='billing',
        )
        previous_start, previous_end = services.previous_period(
            self.start_date,
            self.end_date,
        )
        self._daily_metric(
            day=self.end_date,
            user_id=user_id,
            page_rule_id=rule.id,
            area='billing',
            visits=2,
            engaged=60,
            clicks=5,
        )
        self._daily_metric(
            day=previous_end,
            user_id=user_id,
            page_rule_id=rule.id,
            area='billing',
            visits=2,
            engaged=60,
            clicks=0,
        )
        for day, had_click in (
            (self.end_date, False),
            (self.end_date, False),
            (previous_end, True),
            (previous_end, False),
        ):
            self._page_visit(
                day=day,
                user_id=user_id,
                page_rule_id=rule.id,
                area='billing',
                had_click=had_click,
            )

        rows, _underused = user_detail_analytics._page_usage_rows(
            self.project,
            user_id,
            'acme',
            self.start_date,
            self.end_date,
            previous_start,
            previous_end,
            [{'id': 'billing', 'name': 'Billing', 'color': area.color}],
        )

        self.assertEqual(rows[0]['interactionPct'], 0)
        self.assertEqual(rows[0]['previousInteractionPct'], 50)
        self.assertEqual(rows[0]['interactionDeltaPp'], -50)
        self.assertEqual(rows[0]['visitsDeltaLabel'], '0%')
        self.assertEqual(rows[0]['engagedDeltaLabel'], '0%')
