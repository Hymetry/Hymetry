import uuid
from datetime import datetime, timedelta, timezone as datetime_timezone

from django.contrib.auth import get_user_model
from django.http import QueryDict
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.pages.models import ProductArea
from apps.projects.company_attribute_filters import parse_company_attribute_filters
from apps.projects.models import (
    CompanyAttribute,
    CompanyAttributeType,
    CompanyAttributeValue,
    Project,
)
from apps.projects.tests.helpers import create_workspace_with_owner
from apps.tracker.analytics_replay_timeline import build_analytics_replay_timeline
from apps.tracker.models import (
    AnalyticsEvent,
    AnalyticsSession,
    Event,
    ProjectPageRule,
    Session,
    Visitor,
)
from apps.tracker.visits_table import (
    UNCLASSIFIED_COLOR,
    _recorded_sessions_queryset,
    build_visits_context,
    company_attribute_preview_counts,
)


UTC = datetime_timezone.utc


class VisitsTableServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='visits-table-owner',
            email='visits-table-owner@example.com',
            password='testpass123',
        )
        self.workspace = create_workspace_with_owner(self.user, name='Visits table workspace')
        self.project = Project.objects.create(
            workspace=self.workspace,
            name='Visits table project',
            created_by=self.user,
            api_key='VISITS_TABLE_PROJECT',
            timezone='UTC',
            tracking_capture='analytics,recording',
        )
        self.now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)

    def _recording(
        self,
        started_at,
        *,
        visitor_guid=None,
        identity_ready=True,
        duration_seconds=600,
    ):
        ended_at = started_at + timedelta(seconds=duration_seconds)
        visitor = Visitor.objects.create(
            project=self.project,
            visitor_guid=visitor_guid or uuid.uuid4(),
            first_visit=started_at,
            last_activity=ended_at,
        )
        session = Session.objects.create(
            visitor=visitor,
            start_time=started_at,
            last_activity=ended_at,
            ended_at=ended_at,
            identity_linkage_ready=identity_ready,
        )
        for timestamp, event_type in ((started_at, 2), (ended_at, 3)):
            Event.objects.create(
                session=session,
                event_type=event_type,
                timestamp=timestamp,
                data={
                    'type': event_type,
                    'timestamp': int(timestamp.timestamp() * 1000),
                    'data': (
                        {'source': 2}
                        if event_type == 3
                        else {'node': {'type': 0, 'id': 1, 'childNodes': []}}
                    ),
                },
            )
        return session

    def _projection(
        self,
        session,
        *,
        sequence,
        start,
        seconds,
        url,
        page_name,
        area_name='Unclassified',
        area_key='unclassified',
        color=UNCLASSIFIED_COLOR,
        page_rule_id=None,
        tab_id='tab-1',
    ):
        return None

    def _identity(
        self,
        session,
        *,
        start,
        end,
        user_id=None,
        company_id=None,
        user_name='',
        company_name='',
        url='example.com/page',
        page_name='Page',
        page_rule=None,
    ):
        fragment = AnalyticsSession.objects.create(
            project=self.project,
            visit_session=session,
            visitor_guid=session.visitor.visitor_guid,
            user_id=user_id,
            company_id=company_id,
            start_time=start,
            last_activity=end,
            ended_at=end,
        )
        AnalyticsEvent.objects.create(
            session=fragment,
            event_type='click',
            timestamp=start,
            visitor_guid=session.visitor.visitor_guid,
            user_id=user_id,
            company_id=company_id,
            user_traits={'name': user_name} if user_name else {},
            company_traits={'name': company_name} if company_name else {},
            url=f'https://{url}',
            url_normalized=url,
            page_name=page_name,
            page_name_original=page_name,
            page_rule=page_rule,
            product_area=page_rule.product_area if page_rule is not None else '',
        )
        return fragment

    def _analytics_event(self, fragment, *, at, url, page_name, page_rule=None):
        return AnalyticsEvent.objects.create(
            session=fragment,
            event_type='mouse_move',
            timestamp=at,
            visitor_guid=fragment.visitor_guid,
            user_id=fragment.user_id,
            company_id=fragment.company_id,
            url=f'https://{url}',
            url_normalized=url,
            page_name=page_name,
            page_name_original=page_name,
            page_rule=page_rule,
            product_area=page_rule.product_area if page_rule is not None else '',
        )

    def _page_rule(self, *, area, page_name, pattern):
        return ProjectPageRule.objects.create(
            project=self.project,
            pattern=pattern,
            product_area=area.name,
            page_name=page_name,
            is_active=True,
            created_by='daily_stable',
        )

    def _text_attribute(self, name='Lifecycle'):
        return CompanyAttribute.objects.create(
            project=self.project,
            name=name,
            attribute_type=CompanyAttributeType.TEXT,
        )

    def _attribute_state(self, attribute, operator, **fields):
        params = QueryDict('', mutable=True)
        params[f'ca.{attribute.id}.op'] = operator
        for field_name, raw_value in fields.items():
            key = f'ca.{attribute.id}.{field_name}'
            values = raw_value if isinstance(raw_value, (list, tuple)) else (raw_value,)
            for value in values:
                params.appendlist(key, str(value))
        return parse_company_attribute_filters(self.project, params, strict=True)

    def test_visits_scope_reads_stored_columns_without_aggregating(self):
        """The row scope must stay proportional to the page, not the history.

        Replayability and the analytical clock are denormalized onto Session at
        ingest.  Re-deriving either here would put the selected date range in a
        HAVING clause over MIN(timestamp) and re-aggregate every analytics
        event the project has ever recorded on every request.
        """

        sql = str(_recorded_sessions_queryset(self.project).query)

        self.assertNotIn('MIN(', sql)
        self.assertNotIn('MAX(', sql)
        self.assertNotIn('GROUP BY', sql)
        self.assertNotIn('EXISTS', sql)
        self.assertIn('"analytics_event_start"', sql)
        self.assertIn('"has_replay_snapshot"', sql)

    def test_analytics_events_are_the_only_visits_metric_source(self):
        session = self._recording(self.now - timedelta(hours=1))
        core = ProductArea.objects.create(
            project=self.project,
            name='Core',
            slug='core',
            color='#4269D0',
        )
        billing = ProductArea.objects.create(
            project=self.project,
            name='Billing',
            slug='billing',
            color='#EFB118',
        )
        core_rule = self._page_rule(area=core, page_name='Core page', pattern='/core')
        billing_rule = self._page_rule(area=billing, page_name='Invoices', pattern='/billing')
        analytics_start = session.start_time + timedelta(minutes=2)
        fragment = self._identity(
            session,
            start=analytics_start,
            end=analytics_start + timedelta(seconds=110),
            url='example.com/core',
            page_name='Core page',
            page_rule=core_rule,
        )
        self._analytics_event(
            fragment,
            at=analytics_start + timedelta(seconds=100),
            url='example.com/billing',
            page_name='Invoices',
            page_rule=billing_rule,
        )
        self._analytics_event(
            fragment,
            at=analytics_start + timedelta(seconds=110),
            url='example.com/billing',
            page_name='Invoices',
            page_rule=billing_rule,
        )

        # Deliberately contradictory rrweb materialization must not affect the
        # analytical Visits row.
        self._projection(
            session,
            sequence=0,
            start=session.start_time,
            seconds=100,
            url='example.com/rrweb-only',
            page_name='rrweb-only',
        )

        row = build_visits_context(self.project, now=self.now)['visits'][0]

        self.assertEqual(row['data_source'], 'analytics_events')
        self.assertEqual(row['started_at'], analytics_start)
        self.assertEqual(row['duration_seconds'], 110)
        self.assertEqual(row['recording_duration_seconds'], 600)
        self.assertEqual(row['observed_active_seconds'], 40)
        self.assertEqual(
            sum(segment['seconds'] for segment in row['segments']),
            row['observed_active_seconds'],
        )
        self.assertEqual(row['unique_pages'], 2)
        self.assertEqual(
            [(segment['productArea'], segment['page'], segment['seconds']) for segment in row['segments']],
            [('Core', 'Core page', 30), ('Billing', 'Invoices', 10)],
        )
        self.assertNotEqual(row['observed_active_seconds'], 999)
        self.assertNotIn('rrweb-only', [segment['page'] for segment in row['segments']])

        replay_timeline = build_analytics_replay_timeline(self.project, session)
        replay_seconds_by_page = {}
        for segment in replay_timeline['segments']:
            if segment['kind'] != 'page':
                continue
            replay_seconds_by_page[segment['page']] = (
                replay_seconds_by_page.get(segment['page'], 0)
                + segment['durationMs'] / 1000
            )
        self.assertEqual(replay_timeline['durationMs'] / 1000, row['duration_seconds'])
        self.assertEqual(
            replay_seconds_by_page,
            {segment['page']: segment['seconds'] for segment in row['segments']},
        )

    def test_subsecond_analytical_pages_remain_visible_in_visits(self):
        session = self._recording(self.now - timedelta(hours=1))
        fragment = self._identity(
            session,
            start=session.start_time,
            end=session.start_time + timedelta(seconds=1),
            url='example.com/page-a',
            page_name='Page A',
        )
        self._analytics_event(
            fragment,
            at=session.start_time + timedelta(milliseconds=500),
            url='example.com/page-b',
            page_name='Page B',
        )
        self._analytics_event(
            fragment,
            at=session.start_time + timedelta(seconds=1),
            url='example.com/page-c',
            page_name='Page C',
        )

        row = build_visits_context(self.project, now=self.now)['visits'][0]

        self.assertEqual(row['duration_seconds'], 1)
        self.assertEqual(row['observed_active_seconds'], 1)
        self.assertEqual(row['unique_pages'], 3)
        self.assertEqual(
            [(segment['page'], segment['seconds']) for segment in row['segments']],
            [('Page A', 0.5), ('Page B', 0.499), ('Page C', 0.001)],
        )

    def test_analytical_segments_sort_areas_and_pages_by_active_time(self):
        session = self._recording(self.now - timedelta(hours=1))
        work = ProductArea.objects.create(
            project=self.project,
            name='Work management',
            slug='work-management',
            color='#4269D0',
        )
        authentication = ProductArea.objects.create(
            project=self.project,
            name='Authentication',
            slug='authentication',
            color='#A463F2',
        )
        overview_rule = self._page_rule(area=work, page_name='Overview', pattern='/overview')
        boards_rule = self._page_rule(area=work, page_name='Boards', pattern='/boards')
        login_rule = self._page_rule(area=authentication, page_name='Login', pattern='/login')
        fragment = self._identity(
            session,
            start=session.start_time,
            end=session.start_time + timedelta(seconds=85),
            url='example.com/overview',
            page_name='Overview',
            page_rule=overview_rule,
        )
        self._analytics_event(
            fragment,
            at=session.start_time + timedelta(seconds=10),
            url='example.com/login',
            page_name='Login',
            page_rule=login_rule,
        )
        self._analytics_event(
            fragment,
            at=session.start_time + timedelta(seconds=50),
            url='example.com/boards',
            page_name='Boards',
            page_rule=boards_rule,
        )
        self._analytics_event(
            fragment,
            at=session.start_time + timedelta(seconds=80),
            url='example.com/overview',
            page_name='Overview',
            page_rule=overview_rule,
        )
        self._analytics_event(
            fragment,
            at=session.start_time + timedelta(seconds=85),
            url='example.com/overview',
            page_name='Overview',
            page_rule=overview_rule,
        )

        row = build_visits_context(self.project, now=self.now)['visits'][0]

        self.assertEqual(row['duration_seconds'], 85)
        self.assertEqual(row['observed_active_seconds'], 75)
        self.assertEqual(row['unique_pages'], 3)
        self.assertEqual(
            [
                (
                    segment['productArea'],
                    segment['page'],
                    segment['seconds'],
                    segment['color'],
                )
                for segment in row['segments']
            ],
            [
                ('Work management', 'Boards', 30, '#4269D0'),
                ('Work management', 'Overview', 15, '#4269D0'),
                ('Authentication', 'Login', 30, '#A463F2'),
            ],
        )
        self.assertFalse(any('preserveSequence' in segment for segment in row['segments']))

    def test_linked_analytical_events_populate_the_visit(self):
        session = self._recording(self.now - timedelta(hours=1))
        fragment = self._identity(
            session,
            start=session.start_time,
            end=session.start_time + timedelta(seconds=60),
            url='example.com/dashboard',
            page_name='Dashboard',
        )
        self._analytics_event(
            fragment,
            at=session.start_time + timedelta(seconds=60),
            url='example.com/dashboard',
            page_name='Dashboard',
        )

        row = build_visits_context(self.project, now=self.now)['visits'][0]

        self.assertEqual(row['recording_session_id'], session.session_id)
        self.assertEqual(row['data_source'], 'analytics_events')
        self.assertFalse(row['data_preparing'])
        self.assertEqual(row['duration_seconds'], 60)
        self.assertAlmostEqual(row['observed_active_seconds'], 30.001)
        self.assertEqual([segment['page'] for segment in row['segments']], ['Dashboard'])

    def test_recording_without_linked_analytical_events_is_excluded(self):
        self._recording(self.now - timedelta(hours=1))

        context = build_visits_context(self.project, now=self.now)

        self.assertEqual(context['visits'], [])

    def test_rrweb_active_seconds_do_not_control_analytical_visit_eligibility(self):
        sessions = []
        for index, seconds in enumerate((0, 2, 3), start=1):
            session = self._recording(self.now - timedelta(hours=index))
            self._projection(
                session,
                sequence=0,
                start=session.start_time,
                seconds=seconds,
                url=f'example.com/activity-{seconds}',
                page_name=f'Activity {seconds}',
            )
            fragment = self._identity(
                session,
                start=session.start_time,
                end=session.start_time + timedelta(seconds=10),
                url=f'example.com/analytics-{seconds}',
                page_name=f'Analytics {seconds}',
            )
            self._analytics_event(
                fragment,
                at=session.start_time + timedelta(seconds=10),
                url=f'example.com/analytics-{seconds}',
                page_name=f'Analytics {seconds}',
            )
            sessions.append(session)

        context = build_visits_context(self.project, now=self.now)

        self.assertEqual(
            [row['session_id'] for row in context['visits']],
            [session.session_id for session in sessions],
        )
        self.assertEqual([row['duration_seconds'] for row in context['visits']], [10, 10, 10])
        self.assertEqual([row['observed_active_seconds'] for row in context['visits']], [10, 10, 10])

    def test_identity_is_temporal_and_is_not_backfilled_before_login(self):
        session = self._recording(self.now - timedelta(hours=1))
        start = session.start_time
        self._projection(
            session,
            sequence=0,
            start=start,
            seconds=60,
            url='example.com/profile',
            page_name='Profile',
        )
        self._projection(
            session,
            sequence=1,
            start=start + timedelta(seconds=60),
            seconds=60,
            url='example.com/workspace-a',
            page_name='Workspace A',
        )
        self._projection(
            session,
            sequence=2,
            start=start + timedelta(seconds=120),
            seconds=60,
            url='example.com/workspace-b',
            page_name='Workspace B',
        )
        self._identity(
            session,
            start=start + timedelta(seconds=30),
            end=start + timedelta(seconds=90),
        )
        self._identity(
            session,
            start=start + timedelta(seconds=90),
            end=start + timedelta(seconds=150),
            user_id='jane',
            user_name='Jane',
            company_id='acme',
            company_name='Acme',
        )
        self._identity(
            session,
            start=start + timedelta(seconds=150),
            end=session.ended_at,
            user_id='jane',
            user_name='Jane',
            company_id='beta',
            company_name='Beta',
        )

        row = build_visits_context(self.project, now=self.now)['visits'][0]

        self.assertEqual(row['user_name'], 'Jane')
        self.assertEqual(row['company_name'], 'Beta')
        self.assertEqual(row['user_id'], 'jane')
        self.assertEqual(row['company_id'], 'beta')
        self.assertEqual(
            [(item['user_id'], item['company_id']) for item in row['identity_intervals']],
            [
                ('', ''),
                ('jane', 'acme'),
                ('jane', 'beta'),
            ],
        )

    def test_visit_without_known_identity_uses_anonymous_fallbacks(self):
        session = self._recording(self.now - timedelta(hours=1))
        self._projection(
            session,
            sequence=0,
            start=session.start_time,
            seconds=30,
            url='example.com/login',
            page_name='Login',
        )
        fragment = self._identity(
            session,
            start=session.start_time,
            end=session.start_time + timedelta(seconds=30),
            url='example.com/login',
            page_name='Login',
        )
        self._analytics_event(
            fragment,
            at=session.start_time + timedelta(seconds=30),
            url='example.com/login',
            page_name='Login',
        )

        row = build_visits_context(self.project, now=self.now)['visits'][0]

        self.assertEqual(row['user_name'], 'Anonymous')
        self.assertEqual(row['company_name'], 'Unknown')
        self.assertEqual(row['user_id'], '')
        self.assertEqual(row['company_id'], '')

    def test_visit_with_user_but_no_company_uses_unknown_company(self):
        session = self._recording(self.now - timedelta(hours=1))
        self._projection(
            session,
            sequence=0,
            start=session.start_time,
            seconds=30,
            url='example.com/profile',
            page_name='Profile',
        )
        self._identity(
            session,
            start=session.start_time,
            end=session.start_time + timedelta(seconds=30),
            user_id='jane',
            user_name='Jane',
            url='example.com/profile',
            page_name='Profile',
        )

        row = build_visits_context(self.project, now=self.now)['visits'][0]

        self.assertEqual(row['user_name'], 'Jane')
        self.assertEqual(row['company_name'], 'Unknown')
        self.assertEqual(row['company_id'], '')

    def test_visit_with_company_name_but_no_id_uses_trait_label(self):
        session = self._recording(self.now - timedelta(hours=1))
        self._projection(
            session,
            sequence=0,
            start=session.start_time,
            seconds=30,
            url='example.com/projects',
            page_name='All projects',
        )
        self._identity(
            session,
            start=session.start_time,
            end=session.start_time + timedelta(seconds=30),
            user_id='jane',
            user_name='Jane',
            company_name='No shop selected',
            url='example.com/projects',
            page_name='All projects',
        )

        row = build_visits_context(self.project, now=self.now)['visits'][0]

        self.assertEqual(row['user_name'], 'Jane')
        self.assertEqual(row['company_name'], 'No shop selected')
        self.assertEqual(row['company_id'], '')

    def test_company_attributes_qualify_on_any_linked_company_and_keep_full_timeline(self):
        attribute = self._text_attribute()
        CompanyAttributeValue.objects.create(
            attribute=attribute,
            company_id='acme',
            text_value='Customer',
        )
        CompanyAttributeValue.objects.create(
            attribute=attribute,
            company_id='beta',
            text_value='Prospect',
        )

        matching = self._recording(self.now - timedelta(hours=1))
        midpoint = matching.start_time + timedelta(minutes=5)
        self._identity(
            matching,
            start=matching.start_time,
            end=midpoint,
            company_id='acme',
            company_name='Acme',
        )
        self._identity(
            matching,
            start=midpoint,
            end=matching.ended_at,
            company_id='beta',
            company_name='Beta',
        )
        excluded = self._recording(self.now - timedelta(hours=2))
        self._identity(
            excluded,
            start=excluded.start_time,
            end=excluded.ended_at,
            company_id='beta',
            company_name='Beta',
        )

        state = self._attribute_state(attribute, 'eq', value='customer')
        context = build_visits_context(
            self.project,
            company_attribute_state=state,
            now=self.now,
        )

        self.assertEqual(
            [row['session_id'] for row in context['visits']],
            [matching.session_id],
        )
        self.assertEqual(
            [interval['company_id'] for interval in context['visits'][0]['identity_intervals']],
            ['acme', 'beta'],
        )
        self.assertEqual(context['visits'][0]['company_name'], 'Beta')

    def test_selected_company_and_attribute_filter_are_correlated_to_the_same_company(self):
        attribute = self._text_attribute()
        CompanyAttributeValue.objects.create(
            attribute=attribute,
            company_id='acme',
            text_value='Customer',
        )
        CompanyAttributeValue.objects.create(
            attribute=attribute,
            company_id='beta',
            text_value='Prospect',
        )
        recording = self._recording(self.now - timedelta(hours=1))
        midpoint = recording.start_time + timedelta(minutes=5)
        self._identity(
            recording,
            start=recording.start_time,
            end=midpoint,
            company_id='acme',
            company_name='Acme',
        )
        self._identity(
            recording,
            start=midpoint,
            end=recording.ended_at,
            company_id='beta',
            company_name='Beta',
        )
        state = self._attribute_state(attribute, 'eq', value='Customer')

        acme_context = build_visits_context(
            self.project,
            entity_type='company',
            entity_id='acme',
            company_attribute_state=state,
            now=self.now,
        )
        beta_context = build_visits_context(
            self.project,
            entity_type='company',
            entity_id='beta',
            company_attribute_state=state,
            now=self.now,
        )

        self.assertEqual(
            [row['session_id'] for row in acme_context['visits']],
            [recording.session_id],
        )
        self.assertEqual(list(beta_context['visits']), [])

        preview_url = '/visits'
        acme_request = RequestFactory().get(
            preview_url,
            {
                'range': 'last_30_days',
                'entity_type': 'company',
                'entity_id': 'acme',
            },
        )
        beta_request = RequestFactory().get(
            preview_url,
            {
                'range': 'last_30_days',
                'entity_type': 'company',
                'entity_id': 'beta',
            },
        )
        self.assertEqual(
            company_attribute_preview_counts(self.project, acme_request, state, now=self.now),
            {'matching_count': 1, 'eligible_count': 1},
        )
        self.assertEqual(
            company_attribute_preview_counts(self.project, beta_request, state, now=self.now),
            {'matching_count': 0, 'eligible_count': 1},
        )

    def test_selected_user_attributes_and_synthetic_company_are_correlated_to_that_user(self):
        attribute = self._text_attribute()
        CompanyAttributeValue.objects.create(
            attribute=attribute,
            company_id='acme',
            text_value='Customer',
        )
        CompanyAttributeValue.objects.create(
            attribute=attribute,
            company_id='beta',
            text_value='Prospect',
        )
        recording = self._recording(self.now - timedelta(hours=1))
        first_split = recording.start_time + timedelta(minutes=3)
        second_split = recording.start_time + timedelta(minutes=6)
        self._identity(
            recording,
            start=recording.start_time,
            end=first_split,
            user_id='alice',
            company_id='beta',
            company_name='Beta',
        )
        self._identity(
            recording,
            start=first_split,
            end=second_split,
            user_id='bob',
            company_id='acme',
            company_name='Acme',
        )
        self._identity(
            recording,
            start=second_split,
            end=recording.ended_at,
            user_id='bob',
            company_id='hymetry:workspace:none',
            company_name='No workspace selected',
        )
        customer_state = self._attribute_state(
            attribute,
            'eq',
            value='Customer',
        )
        empty_state = self._attribute_state(attribute, 'empty')

        alice_customer = build_visits_context(
            self.project,
            entity_type='user',
            entity_id='alice',
            company_attribute_state=customer_state,
            now=self.now,
        )
        bob_customer = build_visits_context(
            self.project,
            entity_type='user',
            entity_id='bob',
            company_attribute_state=customer_state,
            now=self.now,
        )
        alice_empty = build_visits_context(
            self.project,
            entity_type='user',
            entity_id='alice',
            company_attribute_state=empty_state,
            now=self.now,
        )
        bob_empty = build_visits_context(
            self.project,
            entity_type='user',
            entity_id='bob',
            company_attribute_state=empty_state,
            now=self.now,
        )

        self.assertEqual(list(alice_customer['visits']), [])
        self.assertEqual(
            [row['session_id'] for row in bob_customer['visits']],
            [recording.session_id],
        )
        self.assertEqual(list(alice_empty['visits']), [])
        self.assertEqual(
            [row['session_id'] for row in bob_empty['visits']],
            [recording.session_id],
        )

        request_factory = RequestFactory()
        alice_request = request_factory.get(
            '/visits',
            {
                'range': 'last_30_days',
                'entity_type': 'user',
                'entity_id': 'alice',
            },
        )
        bob_request = request_factory.get(
            '/visits',
            {
                'range': 'last_30_days',
                'entity_type': 'user',
                'entity_id': 'bob',
            },
        )
        self.assertEqual(
            company_attribute_preview_counts(
                self.project,
                alice_request,
                customer_state,
                now=self.now,
            ),
            {'matching_count': 0, 'eligible_count': 1},
        )
        self.assertEqual(
            company_attribute_preview_counts(
                self.project,
                bob_request,
                customer_state,
                now=self.now,
            ),
            {'matching_count': 1, 'eligible_count': 2},
        )
        self.assertEqual(
            company_attribute_preview_counts(
                self.project,
                alice_request,
                empty_state,
                now=self.now,
            ),
            {'matching_count': 0, 'eligible_count': 1},
        )
        self.assertEqual(
            company_attribute_preview_counts(
                self.project,
                bob_request,
                empty_state,
                now=self.now,
            ),
            {'matching_count': 1, 'eligible_count': 2},
        )

    def test_empty_attributes_include_synthetic_company_but_exclude_unknown_identity(self):
        attribute = self._text_attribute()
        CompanyAttributeValue.objects.create(
            attribute=attribute,
            company_id='configured',
            text_value='Customer',
        )

        missing = self._recording(self.now - timedelta(hours=1))
        self._identity(
            missing,
            start=missing.start_time,
            end=missing.ended_at,
            company_id='missing',
            company_name='Missing value',
        )
        configured = self._recording(self.now - timedelta(hours=2))
        self._identity(
            configured,
            start=configured.start_time,
            end=configured.ended_at,
            company_id='configured',
            company_name='Configured',
        )
        synthetic = self._recording(self.now - timedelta(hours=3))
        self._identity(
            synthetic,
            start=synthetic.start_time,
            end=synthetic.ended_at,
            user_id='global-user',
            company_id='hymetry:workspace:none',
            company_name='No workspace selected',
        )
        unknown = self._recording(self.now - timedelta(hours=4))
        self._identity(
            unknown,
            start=unknown.start_time,
            end=unknown.ended_at,
            user_id='unknown-company-user',
        )
        near_match = self._recording(self.now - timedelta(hours=5))
        self._identity(
            near_match,
            start=near_match.start_time,
            end=near_match.ended_at,
            user_id='near-match-user',
            company_name='no workspace selected',
        )

        empty_state = self._attribute_state(attribute, 'empty')
        empty_context = build_visits_context(
            self.project,
            company_attribute_state=empty_state,
            now=self.now,
        )
        not_empty_context = build_visits_context(
            self.project,
            company_attribute_state=self._attribute_state(attribute, 'not_empty'),
            now=self.now,
        )

        self.assertEqual(
            {row['session_id'] for row in empty_context['visits']},
            {missing.session_id, synthetic.session_id},
        )
        self.assertEqual(
            [row['session_id'] for row in not_empty_context['visits']],
            [configured.session_id],
        )

    def test_company_attributes_are_applied_before_date_pagination(self):
        attribute = self._text_attribute()
        CompanyAttributeValue.objects.create(
            attribute=attribute,
            company_id='matching',
            text_value='Customer',
        )
        newest = self._recording(self.now - timedelta(minutes=30))
        self._identity(
            newest,
            start=newest.start_time,
            end=newest.ended_at,
            company_id='excluded',
        )
        older = self._recording(self.now - timedelta(hours=2))
        self._identity(
            older,
            start=older.start_time,
            end=older.ended_at,
            company_id='matching',
        )

        context = build_visits_context(
            self.project,
            company_attribute_state=self._attribute_state(
                attribute,
                'eq',
                value='Customer',
            ),
            page_size=1,
            page_number=1,
            now=self.now,
        )

        # The total counts the filtered scope, not the unfiltered range.
        self.assertEqual(context['paginator'].count, 1)
        self.assertFalse(context['page_obj'].has_next())
        self.assertEqual(
            [row['session_id'] for row in context['visits']],
            [older.session_id],
        )

    def test_date_pages_report_both_a_next_page_and_the_range_total(self):
        """The page window and the range total are answered separately.

        Whether another page exists comes from one extra fetched row, so the
        page never depends on the counted total, which the pagination bar
        reports alongside it.
        """

        for index in range(1, 4):
            session = self._recording(
                self.now - timedelta(hours=index),
                visitor_guid=uuid.uuid4(),
            )
            fragment = self._identity(session, start=session.start_time, end=session.ended_at)
            # A second event puts the analytical span clear of the
            # low-confidence rule, which this case is not about.  Without it
            # these are one-click anonymous sessions and the scope is empty.
            self._analytics_event(
                fragment,
                at=session.start_time + timedelta(minutes=1),
                url='example.com/page',
                page_name='Page',
            )

        first_page = build_visits_context(self.project, page_size=2, page_number=1, now=self.now)
        second_page = build_visits_context(self.project, page_size=2, page_number=2, now=self.now)

        self.assertEqual(first_page['paginator'].count, 3)
        self.assertEqual(first_page['paginator'].num_pages, 2)
        self.assertEqual(len(first_page['visits']), 2)
        self.assertTrue(first_page['page_obj'].has_next())
        self.assertFalse(first_page['page_obj'].has_previous())

        self.assertEqual(len(second_page['visits']), 1)
        self.assertFalse(second_page['page_obj'].has_next())
        self.assertTrue(second_page['page_obj'].has_previous())

    def test_duration_sort_is_paginated_in_the_database(self):
        """Duration ranks by the stored analytical interval.

        Ordering it in Python meant projecting every visit in the range before
        the first page could be sliced.
        """

        expected_order = []
        for index, active_seconds in enumerate((30, 300, 120), start=1):
            session = self._recording(
                self.now - timedelta(hours=index),
                visitor_guid=uuid.uuid4(),
            )
            fragment = self._identity(
                session,
                start=session.start_time,
                end=session.ended_at,
            )
            self._analytics_event(
                fragment,
                at=session.start_time + timedelta(seconds=active_seconds),
                url='example.com/page',
                page_name='Page',
            )
            expected_order.append((active_seconds, session.session_id))
        expected_order.sort(reverse=True)

        context = build_visits_context(
            self.project,
            sort_key='duration',
            sort_direction='desc',
            page_size=1,
            page_number=1,
            now=self.now,
        )

        self.assertEqual(context['paginator'].count, 3)
        self.assertTrue(context['page_obj'].has_next())
        self.assertEqual(
            [row['session_id'] for row in context['visits']],
            [expected_order[0][1]],
        )

    def test_identity_sorts_still_report_an_exact_total(self):
        """Sorts that rank on projected facts already hold every row."""

        for index in range(1, 4):
            session = self._recording(
                self.now - timedelta(hours=index),
                visitor_guid=uuid.uuid4(),
            )
            self._identity(
                session,
                start=session.start_time,
                end=session.ended_at,
                user_id=f'user-{index}',
                user_name=f'User {index}',
            )

        context = build_visits_context(
            self.project,
            sort_key='user',
            page_size=2,
            page_number=1,
            now=self.now,
        )

        self.assertEqual(context['paginator'].count, 3)
        self.assertEqual(context['paginator'].num_pages, 2)
        self.assertTrue(context['page_obj'].has_next())

    def test_company_attribute_preview_uses_the_same_visits_scope(self):
        attribute = self._text_attribute()
        CompanyAttributeValue.objects.create(
            attribute=attribute,
            company_id='acme',
            text_value='Customer',
        )
        CompanyAttributeValue.objects.create(
            attribute=attribute,
            company_id='beta',
            text_value='Prospect',
        )
        fragments = {}
        for offset, company_id, company_name in (
            (1, 'acme', 'Acme'),
            (2, 'beta', 'Beta'),
            (3, 'hymetry:workspace:none', 'No workspace selected'),
            (4, None, ''),
        ):
            recording = self._recording(self.now - timedelta(hours=offset))
            fragments[offset] = self._identity(
                recording,
                start=recording.start_time,
                end=recording.ended_at,
                user_id=f'user-{offset}',
                company_id=company_id,
                company_name=company_name,
            )

        request = RequestFactory().get('/visits', {'range': 'last_30_days'})
        customer_state = self._attribute_state(
            attribute,
            'eq',
            value='Customer',
        )
        empty_state = self._attribute_state(attribute, 'empty')

        self.assertEqual(
            company_attribute_preview_counts(self.project, request, customer_state, now=self.now),
            {'matching_count': 1, 'eligible_count': 3},
        )
        self.assertEqual(
            company_attribute_preview_counts(self.project, request, empty_state, now=self.now),
            {'matching_count': 1, 'eligible_count': 3},
        )

        area = ProductArea.objects.create(
            project=self.project,
            name='Core',
            slug='core',
        )
        rule = self._page_rule(
            area=area,
            page_name='Dashboard',
            pattern='/dashboard',
        )
        fragments[1].events.update(
            page_rule=rule,
            page_name='Dashboard',
            product_area=area.name,
        )
        scoped_request = RequestFactory().get(
            '/visits',
            {
                'range': 'last_30_days',
                'entity_type': 'user',
                'entity_id': 'user-1',
                'page_filter_type': 'page',
                'page_filter_id': rule.id,
            },
        )
        self.assertEqual(
            company_attribute_preview_counts(
                self.project,
                scoped_request,
                customer_state,
                now=self.now,
            ),
            {'matching_count': 1, 'eligible_count': 1},
        )

    def test_unlinked_analytics_does_not_create_a_recording_backed_visit(self):
        visitor_guid = uuid.uuid4()
        session = self._recording(
            self.now - timedelta(hours=1),
            visitor_guid=visitor_guid,
            identity_ready=False,
        )
        self._projection(
            session,
            sequence=0,
            start=session.start_time,
            seconds=30,
            url='example.com/page',
            page_name='Page',
        )
        AnalyticsSession.objects.create(
            project=self.project,
            visitor_guid=visitor_guid,
            user_id='legacy-user',
            company_id='legacy-company',
            start_time=session.start_time,
            last_activity=session.last_activity,
            ended_at=session.ended_at,
        )

        context = build_visits_context(self.project, now=self.now)

        self.assertEqual(context['visits'], [])

    def test_recording_without_rrweb_events_is_not_a_replayable_visit(self):
        session = self._recording(self.now - timedelta(hours=1))
        fragment = self._identity(
            session,
            start=session.start_time,
            end=session.ended_at,
        )
        self._analytics_event(
            fragment,
            at=session.start_time + timedelta(seconds=10),
            url='example.com/page',
            page_name='Page',
        )
        session.events.all().delete()

        context = build_visits_context(self.project, now=self.now)

        self.assertEqual(context['visits'], [])

    def test_recording_without_full_snapshot_is_not_a_replayable_visit(self):
        session = self._recording(self.now - timedelta(hours=1))
        fragment = self._identity(
            session,
            start=session.start_time,
            end=session.ended_at,
        )
        self._analytics_event(
            fragment,
            at=session.start_time + timedelta(seconds=10),
            url='example.com/page',
            page_name='Page',
        )
        session.events.filter(event_type=2).delete()

        context = build_visits_context(self.project, now=self.now)

        self.assertEqual(context['visits'], [])

    def test_full_snapshot_without_dom_root_is_not_a_replayable_visit(self):
        session = self._recording(self.now - timedelta(hours=1))
        fragment = self._identity(
            session,
            start=session.start_time,
            end=session.ended_at,
        )
        self._analytics_event(
            fragment,
            at=session.start_time + timedelta(seconds=10),
            url='example.com/page',
            page_name='Page',
        )
        snapshot = session.events.get(event_type=2)
        snapshot.data['data'] = {}
        snapshot.save(update_fields=['data'])

        context = build_visits_context(self.project, now=self.now)

        self.assertEqual(context['visits'], [])

    def test_full_snapshot_with_invalid_dom_root_is_not_a_replayable_visit(self):
        for index, node in enumerate((None, 'not-a-node', {}), start=1):
            with self.subTest(node=node):
                session = self._recording(
                    self.now - timedelta(hours=index),
                    visitor_guid=uuid.uuid4(),
                )
                fragment = self._identity(
                    session,
                    start=session.start_time,
                    end=session.ended_at,
                )
                self._analytics_event(
                    fragment,
                    at=session.start_time + timedelta(seconds=10),
                    url='example.com/page',
                    page_name='Page',
                )
                snapshot = session.events.get(event_type=2)
                snapshot.data['data'] = {'node': node}
                snapshot.save(update_fields=['data'])

        context = build_visits_context(self.project, now=self.now)

        self.assertEqual(context['visits'], [])

    def test_period_uses_analytical_event_start_in_project_calendar(self):
        self.project.timezone = 'America/New_York'
        self.project.save(update_fields=['timezone'])
        now = datetime(2026, 3, 10, 16, 0, tzinfo=UTC)
        included = self._recording(datetime(2026, 3, 4, 4, 0, tzinfo=UTC))
        excluded = self._recording(datetime(2026, 3, 4, 6, 0, tzinfo=UTC))
        included_start = datetime(2026, 3, 4, 5, 0, tzinfo=UTC)
        excluded_start = datetime(2026, 3, 4, 4, 59, 59, tzinfo=UTC)
        included_fragment = self._identity(
            included,
            start=included_start,
            end=included_start + timedelta(seconds=10),
            url='example.com/included',
            page_name='Included',
        )
        self._analytics_event(
            included_fragment,
            at=included_start + timedelta(seconds=10),
            url='example.com/included',
            page_name='Included',
        )
        excluded_fragment = self._identity(
            excluded,
            start=excluded_start,
            end=excluded_start + timedelta(seconds=10),
            url='example.com/excluded',
            page_name='Excluded',
        )
        self._analytics_event(
            excluded_fragment,
            at=excluded_start + timedelta(seconds=10),
            url='example.com/excluded',
            page_name='Excluded',
        )

        context = build_visits_context(self.project, range_key='last_7_days', now=now)

        self.assertEqual(context['start_ts'], datetime(2026, 3, 4, 5, 0, tzinfo=UTC))
        self.assertEqual([row['session_id'] for row in context['visits']], [included.session_id])

    def test_duration_sort_and_pagination_use_analytical_event_span(self):
        sessions = []
        durations = (
            (10, 100),
            (200, 40),
            (20, 70),
        )
        for index, (recording_seconds, analytics_seconds) in enumerate(durations):
            session = self._recording(
                self.now - timedelta(hours=index + 1),
                duration_seconds=recording_seconds,
            )
            fragment = self._identity(
                session,
                start=session.start_time,
                end=session.start_time + timedelta(seconds=analytics_seconds),
                url=f'example.com/page-{index}',
                page_name=f'Page {index}',
            )
            for offset in range(30, analytics_seconds, 30):
                self._analytics_event(
                    fragment,
                    at=session.start_time + timedelta(seconds=offset),
                    url=f'example.com/page-{index}',
                    page_name=f'Page {index}',
                )
            self._analytics_event(
                fragment,
                at=session.start_time + timedelta(seconds=analytics_seconds),
                url=f'example.com/page-{index}',
                page_name=f'Page {index}',
            )
            sessions.append(session)

        first_page = build_visits_context(
            self.project,
            now=self.now,
            sort_key='duration',
            sort_direction='desc',
            page_size=2,
            page_number=1,
        )
        second_page = build_visits_context(
            self.project,
            now=self.now,
            sort_key='duration',
            sort_direction='desc',
            page_size=2,
            page_number=2,
        )

        self.assertEqual([row['duration_seconds'] for row in first_page['visits']], [100, 70])
        self.assertEqual([row['observed_active_seconds'] for row in first_page['visits']], [100, 70])
        self.assertEqual([row['recording_duration_seconds'] for row in first_page['visits']], [10, 20])
        self.assertEqual([row['duration_seconds'] for row in second_page['visits']], [40])
        self.assertEqual([row['observed_active_seconds'] for row in second_page['visits']], [40])
        self.assertEqual(second_page['visits'][0]['recording_duration_seconds'], 200)
        self.assertEqual(second_page['visits'][0]['session_id'], sessions[1].session_id)
