import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.pages.models import ProductArea
from apps.projects.models import Project
from apps.projects.tests.helpers import create_workspace_with_owner
from apps.tracker.analytics_replay_timeline import build_analytics_replay_timeline
from apps.tracker.analytics_visit_projection import (
    ANALYTICS_ACTIVE_GAP_CAP_MS,
    UNCLASSIFIED_COLOR,
    build_analytics_visit_projection,
    build_analytics_visit_projections,
)
from apps.tracker.models import (
    AnalyticsEvent,
    AnalyticsSession,
    Event,
    ProjectPageNamingRunMode,
    ProjectPageRule,
    Session,
    Visitor,
)
from apps.tracker.tools import get_consolidated_timeline_data


class AnalyticsVisitProjectionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='analytics-projection-owner',
            email='analytics-projection-owner@example.com',
            password='testpass123',
        )
        self.workspace = create_workspace_with_owner(
            self.user,
            name='Analytics projection workspace',
        )
        self.project = Project.objects.create(
            workspace=self.workspace,
            name='Analytics projection project',
            created_by=self.user,
            api_key='ANALYTICS_PROJECTION_PROJECT',
            timezone='UTC',
            tracking_capture='analytics,recording',
        )
        self.started_at = timezone.now().replace(microsecond=0)
        self.visitor = Visitor.objects.create(
            project=self.project,
            visitor_guid=uuid.uuid4(),
            first_visit=self.started_at,
            last_activity=self.started_at + timedelta(minutes=20),
        )
        self.recording = self._recording()
        ProductArea.objects.create(
            project=self.project,
            name='Core',
            slug='core',
            color='#4269D0',
        )
        ProductArea.objects.create(
            project=self.project,
            name='Projects',
            slug='projects',
            color='#EFB118',
        )
        self.dashboard_rule = self._rule(
            pattern='/dashboard',
            page_name='Dashboard',
            product_area='Core',
        )
        self.projects_rule = self._rule(
            pattern='/projects',
            page_name='Projects',
            product_area='Projects',
        )

    def _recording(self, *, offset=0):
        started_at = self.started_at + timedelta(seconds=offset)
        return Session.objects.create(
            visitor=self.visitor,
            start_time=started_at,
            last_activity=started_at + timedelta(minutes=20),
            ended_at=started_at + timedelta(minutes=20),
            identity_linkage_ready=True,
        )

    def _rule(self, *, pattern, page_name, product_area):
        return ProjectPageRule.objects.create(
            project=self.project,
            pattern=pattern,
            page_name=page_name,
            product_area=product_area,
            priority=100,
            created_by=ProjectPageNamingRunMode.HOURLY_UNSTABLE,
        )

    def _fragment(self, *, recording=None, offset=0, linked=True):
        start = self.started_at + timedelta(seconds=offset)
        return AnalyticsSession.objects.create(
            project=self.project,
            visit_session=(recording or self.recording) if linked else None,
            visitor_guid=self.visitor.visitor_guid,
            start_time=start,
            last_activity=start + timedelta(minutes=1),
            ended_at=start + timedelta(minutes=1),
        )

    def _event(self, fragment, seconds, rule, *, url=None, original_name=''):
        page_name = rule.page_name if rule is not None else 'Undefined'
        product_area = rule.product_area if rule is not None else ''
        url = url or (
            'https://example.com/dashboard'
            if rule == self.dashboard_rule
            else 'https://example.com/projects'
        )
        return AnalyticsEvent.objects.create(
            session=fragment,
            event_type='click',
            timestamp=self.started_at + timedelta(seconds=seconds),
            visitor_guid=self.visitor.visitor_guid,
            url=url,
            url_normalized=url,
            page_name=page_name,
            page_name_original=original_name,
            product_area=product_area,
            page_rule=rule,
        )

    def _rrweb_event(self, seconds, event_type, *, absolute_offset=0):
        timestamp = self.started_at + timedelta(
            seconds=absolute_offset + seconds,
        )
        return Event.objects.create(
            session=self.recording,
            url='https://rrweb.example.com/wrong-page',
            tab_id='tab-a',
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

    def test_uses_global_raw_event_clock_and_preserves_repeated_page_runs(self):
        first_fragment = self._fragment(offset=0)
        second_fragment = self._fragment(offset=8)
        unrelated_fragment = self._fragment(linked=False, offset=1)
        self._event(first_fragment, 0, self.dashboard_rule)
        self._event(unrelated_fragment, 1, self.projects_rule)
        self._event(first_fragment, 5, self.dashboard_rule)
        self._event(second_fragment, 40, self.projects_rule)
        self._event(first_fragment, 50, self.dashboard_rule)
        self._event(first_fragment, 90, self.dashboard_rule)

        projection = build_analytics_visit_projection(
            self.project,
            self.recording,
        )

        start_ms = int(self.started_at.timestamp() * 1000)
        self.assertEqual(projection['source'], 'analytics_events')
        self.assertEqual(projection['linkage'], 'canonical')
        self.assertEqual(projection['clockStartMs'], start_ms)
        self.assertEqual(projection['clockEndMs'], start_ms + 90_000)
        self.assertEqual(projection['durationMs'], 90_000)
        self.assertEqual(
            projection['inactivityThresholdMs'],
            ANALYTICS_ACTIVE_GAP_CAP_MS,
        )
        self.assertEqual(
            [
                (item['kind'], item['startMs'], item['endMs'], item['page'])
                for item in projection['segments']
            ],
            [
                ('page', 0, 35_000, 'Dashboard'),
                ('inactive', 35_000, 40_000, ''),
                ('page', 40_000, 50_000, 'Projects'),
                ('page', 50_000, 80_000, 'Dashboard'),
                ('inactive', 80_000, 89_999, ''),
                ('page', 89_999, 90_000, 'Dashboard'),
            ],
        )
        self.assertEqual(
            sum(item['durationMs'] for item in projection['segments']),
            projection['durationMs'],
        )

    def test_terminal_event_defines_end_and_keeps_a_page_marker(self):
        fragment = self._fragment()
        self._event(fragment, 0, self.dashboard_rule)
        self._event(fragment, 10, self.projects_rule)

        projection = build_analytics_visit_projection(
            self.project,
            self.recording,
        )

        self.assertEqual(projection['durationMs'], 10_000)
        self.assertEqual(
            [
                (item['page'], item['startMs'], item['endMs'])
                for item in projection['segments']
                if item['kind'] == 'page'
            ],
            [
                ('Dashboard', 0, 9_999),
                ('Projects', 9_999, 10_000),
            ],
        )

    def test_single_observation_has_a_visible_one_millisecond_clock(self):
        fragment = self._fragment()
        self._event(fragment, 0, self.dashboard_rule)

        projection = build_analytics_visit_projection(
            self.project,
            self.recording,
        )

        self.assertEqual(projection['durationMs'], 1)
        self.assertEqual(
            [
                (item['page'], item['startMs'], item['endMs'])
                for item in projection['segments']
            ],
            [('Dashboard', 0, 1)],
        )

    def test_distinct_pages_with_the_same_timestamp_each_get_a_marker(self):
        fragment = self._fragment()
        self._event(fragment, 0, self.dashboard_rule)
        self._event(fragment, 0, self.projects_rule)
        self._event(fragment, 0, self.dashboard_rule)

        projection = build_analytics_visit_projection(
            self.project,
            self.recording,
        )

        self.assertEqual(projection['durationMs'], 3)
        self.assertEqual(
            [
                (item['page'], item['startMs'], item['endMs'])
                for item in projection['segments']
            ],
            [
                ('Dashboard', 0, 1),
                ('Projects', 1, 2),
                ('Dashboard', 2, 3),
            ],
        )

    def test_fragment_bounds_do_not_change_raw_event_clock(self):
        fragment = self._fragment(offset=500)
        fragment.last_activity = self.started_at + timedelta(seconds=501)
        fragment.ended_at = self.started_at + timedelta(seconds=501)
        fragment.save(update_fields=['last_activity', 'ended_at'])
        self._event(fragment, 20, self.dashboard_rule)
        self._event(fragment, 80, self.projects_rule)

        projection = build_analytics_visit_projection(
            self.project,
            self.recording,
        )

        self.assertEqual(projection['durationMs'], 60_000)
        self.assertEqual(projection['segments'][0]['startMs'], 0)
        self.assertEqual(projection['segments'][-1]['endMs'], 60_000)

    def test_canonical_only_resolution_does_not_borrow_unlinked_analytics(self):
        self.recording.identity_linkage_ready = False
        self.recording.save(update_fields=['identity_linkage_ready'])
        fragment = self._fragment(linked=False)
        self._event(fragment, 0, self.dashboard_rule)
        self._event(fragment, 10, self.projects_rule)

        projection = build_analytics_visit_projection(
            self.project,
            self.recording,
        )

        self.assertEqual(projection['linkage'], 'none')
        self.assertIsNone(projection['clockStartMs'])
        self.assertIsNone(projection['clockEndMs'])
        self.assertEqual(projection['durationMs'], 0)
        self.assertEqual(projection['segments'], [])

    def test_linked_fragment_without_events_is_canonical_but_empty(self):
        self._fragment()

        projection = build_analytics_visit_projection(
            self.project,
            self.recording,
        )

        self.assertEqual(projection['linkage'], 'canonical')
        self.assertEqual(projection['durationMs'], 0)
        self.assertEqual(projection['segments'], [])

    def test_unclassified_page_uses_normalized_url_and_neutral_color(self):
        fragment = self._fragment()
        self._event(
            fragment,
            0,
            None,
            url='https://example.com/unknown?ignored=yes',
            original_name='Unknown screen',
        )
        self._event(fragment, 4, self.dashboard_rule)

        page = build_analytics_visit_projection(
            self.project,
            self.recording,
        )['segments'][0]

        self.assertEqual(page['kind'], 'page')
        self.assertEqual(page['page'], 'Unknown screen')
        self.assertEqual(page['pageKey'], 'url:example.com/unknown')
        self.assertEqual(page['productAreaKey'], 'unclassified')
        self.assertEqual(page['color'], UNCLASSIFIED_COLOR)
        self.assertEqual(page['pageRuleIds'], [])
        self.assertFalse(page['classified'])

    def test_batch_builder_loads_fragments_events_and_area_metadata_once(self):
        other_recording = self._recording(offset=100)
        first_fragment = self._fragment(recording=self.recording)
        second_fragment = self._fragment(recording=other_recording, offset=100)
        self._event(first_fragment, 0, self.dashboard_rule)
        self._event(first_fragment, 5, self.projects_rule)
        self._event(second_fragment, 100, self.projects_rule)
        self._event(second_fragment, 107, self.dashboard_rule)

        with self.assertNumQueries(3):
            projections = build_analytics_visit_projections(
                self.project,
                [self.recording, other_recording],
            )

        self.assertEqual(set(projections), {
            self.recording.session_id,
            other_recording.session_id,
        })
        self.assertEqual(projections[self.recording.session_id]['durationMs'], 5_000)
        self.assertEqual(projections[other_recording.session_id]['durationMs'], 7_000)

    def test_replay_entry_point_is_the_shared_projection(self):
        fragment = self._fragment()
        self._event(fragment, 0, self.dashboard_rule)
        self._event(fragment, 9, self.projects_rule)

        self.assertEqual(
            build_analytics_replay_timeline(self.project, self.recording),
            build_analytics_visit_projection(self.project, self.recording),
        )

    def test_consolidated_payload_keeps_short_rrweb_clock_separate(self):
        fragment = self._fragment()
        self._event(fragment, 0, self.dashboard_rule)
        self._event(fragment, 600, self.projects_rule)
        self._rrweb_event(0, 2, absolute_offset=86_400)
        self._rrweb_event(60, 3, absolute_offset=86_400)

        payload = get_consolidated_timeline_data(
            None,
            self.recording.session_id,
            allowed_project_ids=[self.project.id],
        )

        self.assertEqual(payload['total_duration'], 600_000)
        self.assertEqual(payload['rrweb_duration'], 60_000)
        self.assertEqual(payload['analytics_timeline']['durationMs'], 600_000)
        self.assertTrue(payload['replay_available'])
        self.assertEqual(
            payload['analytics_timeline']['clockStartMs'],
            int(self.started_at.timestamp() * 1000),
        )
        pages = [
            item['page']
            for item in payload['analytics_timeline']['segments']
            if item['kind'] == 'page'
        ]
        self.assertEqual(pages, ['Dashboard', 'Projects'])
        self.assertNotIn('wrong-page', pages)

    def test_consolidated_payload_keeps_long_rrweb_clock_separate(self):
        fragment = self._fragment()
        self._event(fragment, 0, self.dashboard_rule)
        self._event(fragment, 600, self.projects_rule)
        self._rrweb_event(0, 2)
        self._rrweb_event(1_200, 3)

        payload = get_consolidated_timeline_data(
            None,
            self.recording.session_id,
            allowed_project_ids=[self.project.id],
        )

        self.assertEqual(payload['total_duration'], 600_000)
        self.assertEqual(payload['rrweb_duration'], 1_200_000)
        self.assertEqual(payload['analytics_timeline']['durationMs'], 600_000)
        self.assertTrue(payload['replay_available'])

    def test_consolidated_payload_marks_mutation_only_stream_unavailable(self):
        fragment = self._fragment()
        self._event(fragment, 0, self.dashboard_rule)
        self._event(fragment, 60, self.projects_rule)
        self._rrweb_event(0, 3)
        self._rrweb_event(30, 3)

        payload = get_consolidated_timeline_data(
            None,
            self.recording.session_id,
            allowed_project_ids=[self.project.id],
        )

        self.assertFalse(payload['replay_available'])
        self.assertEqual(
            payload['replay_unavailable_reason'],
            'missing_full_snapshot',
        )
        self.assertEqual(payload['analytics_timeline']['durationMs'], 60_000)

    def test_consolidated_payload_rejects_invalid_full_snapshot_roots(self):
        for node in (None, 'not-a-node', {}):
            with self.subTest(node=node):
                snapshot = self._rrweb_event(0, 2)
                snapshot.data['data'] = {'node': node}
                snapshot.save(update_fields=['data'])

                payload = get_consolidated_timeline_data(
                    None,
                    self.recording.session_id,
                    allowed_project_ids=[self.project.id],
                )

                self.assertFalse(payload['replay_available'])
                snapshot.delete()
