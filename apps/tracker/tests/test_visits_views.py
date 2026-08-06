import uuid
from copy import deepcopy
from datetime import timedelta
from html.parser import HTMLParser
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.pages import company_analytics, user_analytics
from apps.pages.models import CompaniesOverviewCache, ProductArea, UsersOverviewCache
from apps.projects.models import (
    CompanyAttribute,
    CompanyAttributeOption,
    CompanyAttributeType,
    CompanyAttributeValue,
    Project,
)
from apps.projects.tests.helpers import create_workspace_with_owner
from apps.tracker.models import (
    AnalyticsEvent,
    AnalyticsSession,
    Event,
    ProjectPageRule,
    Session,
    Visitor,
)


_VOID_HTML_TAGS = {
    'area',
    'base',
    'br',
    'col',
    'embed',
    'hr',
    'img',
    'input',
    'link',
    'meta',
    'param',
    'source',
    'track',
    'wbr',
}


class _HtmlNode:
    def __init__(self, tag, attrs=None, *, parent=None):
        self.tag = tag
        self.attrs = dict(attrs or ())
        self.parent = parent
        self.children = []

    @property
    def classes(self):
        return set((self.attrs.get('class') or '').split())

    @property
    def text(self):
        parts = []
        for child in self.children:
            parts.append(child if isinstance(child, str) else child.text)
        return ' '.join(''.join(parts).split())

    @property
    def direct_text(self):
        return ' '.join(
            ''.join(child for child in self.children if isinstance(child, str)).split()
        )


class _HtmlTreeParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _HtmlNode('[document]')
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _HtmlNode(tag, attrs, parent=self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in _VOID_HTML_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = _HtmlNode(tag, attrs, parent=self.stack[-1])
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _parse_html_tree(content):
    parser = _HtmlTreeParser()
    parser.feed(content)
    parser.close()
    return parser.root


def _find_nodes(root, *, tag=None, class_name=None, attrs=None, direct=False):
    attrs = attrs or {}
    candidates = [child for child in root.children if isinstance(child, _HtmlNode)]
    matches = []
    for node in candidates:
        if (
            (tag is None or node.tag == tag)
            and (class_name is None or class_name in node.classes)
            and all(
                key in node.attrs if value is None else node.attrs.get(key) == value
                for key, value in attrs.items()
            )
        ):
            matches.append(node)
        if not direct:
            matches.extend(
                _find_nodes(
                    node,
                    tag=tag,
                    class_name=class_name,
                    attrs=attrs,
                )
            )
    return matches


def _single_node(root, **criteria):
    nodes = _find_nodes(root, **criteria)
    if len(nodes) != 1:
        raise AssertionError(f'Expected one HTML node for {criteria}, found {len(nodes)}')
    return nodes[0]


class VisitsViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='visits-view-owner',
            email='visits-view-owner@example.com',
            password='testpass123',
        )
        self.workspace = create_workspace_with_owner(self.user, name='Visits view workspace')
        self.project = Project.objects.create(
            workspace=self.workspace,
            name='Visits view project',
            created_by=self.user,
            api_key='VISITS_VIEW_PROJECT',
            timezone='UTC',
            tracking_capture='analytics,recording',
        )
        self.started_at = timezone.now() - timedelta(hours=1)
        self.visitor_guid = uuid.uuid4()
        visitor = Visitor.objects.create(
            project=self.project,
            visitor_guid=self.visitor_guid,
            first_visit=self.started_at,
            last_activity=self.started_at + timedelta(minutes=5),
        )
        self.recording = Session.objects.create(
            session_id=uuid.UUID('11111111-1111-4111-8111-111111111111'),
            visitor=visitor,
            start_time=self.started_at,
            last_activity=self.started_at + timedelta(minutes=5),
            ended_at=self.started_at + timedelta(minutes=5),
            identity_linkage_ready=True,
        )
        for timestamp, event_type in (
            (self.started_at, 2),
            (self.started_at + timedelta(minutes=5), 3),
        ):
            Event.objects.create(
                session=self.recording,
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
        self.analytics = AnalyticsSession.objects.create(
            session_id=uuid.UUID('22222222-2222-4222-8222-222222222222'),
            project=self.project,
            visit_session=self.recording,
            visitor_guid=self.visitor_guid,
            user_id='alice',
            company_id='acme',
            start_time=self.started_at,
            last_activity=self.started_at + timedelta(minutes=5),
            ended_at=self.started_at + timedelta(minutes=5),
        )
        AnalyticsEvent.objects.create(
            session=self.analytics,
            event_type='click',
            timestamp=self.started_at,
            visitor_guid=self.visitor_guid,
            user_id='alice',
            company_id='acme',
            user_traits={'name': 'Alice Example', 'email': 'alice@acme.test'},
            company_traits={'name': 'Acme Inc.', 'domain': 'acme.test'},
            url='https://example.com/dashboard',
            url_normalized='example.com/dashboard',
            page_name_original='Dashboard',
        )
        for offset_seconds in (30, 60, 300):
            AnalyticsEvent.objects.create(
                session=self.analytics,
                event_type='mouse_move',
                timestamp=self.started_at + timedelta(seconds=offset_seconds),
                visitor_guid=self.visitor_guid,
                user_id='alice',
                company_id='acme',
                user_traits={'name': 'Alice Example', 'email': 'alice@acme.test'},
                company_traits={'name': 'Acme Inc.', 'domain': 'acme.test'},
                url='https://example.com/dashboard',
                url_normalized='example.com/dashboard',
                page_name_original='Dashboard',
            )
        self.client.force_login(self.user)

    def _workspace_url(self, route_name, **kwargs):
        return reverse(
            f'w:{route_name}',
            kwargs={
                'workspace_slug': self.workspace.slug,
                'project_id': self.project.id,
                **kwargs,
            },
        )

    def test_visits_overview_canonicalizes_stale_attribute_url_state(self):
        url = self._workspace_url('recordings')

        response = self.client.get(
            url,
            QueryDict(
                'range=last_7_days&sort=duration&page=2'
                '&ca.9223372036854775807.op=empty',
            ),
        )

        self.assertRedirects(
            response,
            f'{url}?range=last_7_days&sort=duration',
            fetch_redirect_response=False,
        )

    def test_replay_uses_analytical_bar_control(self):
        response = self.client.get(
            self._workspace_url(
                'recording',
                session_id=self.recording.session_id,
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'tracker/recording.html')
        self.assertContains(response, 'id="timeline" class="replay-timeline"')
        self.assertContains(response, 'id="hoverPositionLine"')
        self.assertContains(response, "hoverMarker: $('hoverPositionLine')")
        self.assertContains(response, 'js/tracker/replay-timeline.js')
        self.assertContains(response, 'js/tracker/replay-stream.js')
        self.assertContains(response, 'js/tracker/replay-playback-feedback.js')
        self.assertContains(response, 'id="streamStatus"')
        self.assertContains(response, 'id="playbackFeedback"')
        self.assertContains(response, 'id="playbackFeedbackPlayIcon"')
        self.assertContains(response, 'id="playbackFeedbackPauseIcon"')
        self.assertContains(response, 'playbackFeedback.show(shouldPlay)')
        self.assertContains(response, 'togglePlayback(true)')
        self.assertContains(response, "streamController.start()")
        self.assertContains(response, "streamController.finish()")
        self.assertContains(response, "fetchSeekBootstrap")
        self.assertContains(response, "seek_cursor")
        self.assertContains(response, "onPlayerChange")
        self.assertContains(response, "toRecordingTime")
        self.assertContains(response, "teardownReplay")
        self.assertContains(response, 'skipInactive: false')
        self.assertContains(response, "ui-update-player-state")
        self.assertContains(response, 'window.ReplayTimeline.seekPlayer')
        self.assertContains(response, 'consolidatedData.replay_available === false')
        self.assertContains(response, 'initial page snapshot was not captured')
        self.assertNotContains(response, 'bubble-box')
        self.assertNotContains(response, 'progressSlider')
        self.assertNotContains(response, 'addTransitionLines')
        self.assertNotIn('session_bubbles_data', response.context)

    def test_row_links_to_recording_uuid_after_analytics_enrichment(self):
        response = self.client.get(
            self._workspace_url('recordings'),
            {'range': 'last_7_days'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'tracker/visits.html')
        row = response.context['visit_rows'][0]
        replay_url = self._workspace_url(
            'recording',
            session_id=self.recording.session_id,
        )
        analytics_shaped_url = self._workspace_url(
            'recording',
            session_id=self.analytics.session_id,
        )

        self.assertEqual(row['recording_session_id'], self.recording.session_id)
        self.assertEqual(row['analytics_session_id'], self.analytics.session_id)
        self.assertEqual(row['replay_url'], replay_url)
        self.assertContains(response, f'href="{replay_url}"')
        self.assertNotContains(response, 'data-visit-detail-href=')
        self.assertNotContains(response, analytics_shaped_url)
        self.assertContains(response, 'Alice Example')
        self.assertContains(response, 'Acme Inc.')
        self.assertContains(response, '5m')
        self.assertEqual(row['duration_label'], '5m')
        self.assertEqual(row['duration_seconds'], 300)
        self.assertEqual(row['recording_duration_seconds'], 300)
        self.assertAlmostEqual(row['observed_active_seconds'], 90.001)
        self.assertEqual(self.client.get(replay_url).status_code, 200)
        self.assertEqual(self.client.get(analytics_shaped_url).status_code, 404)

    def test_filters_sort_links_and_entity_links_preserve_selected_range(self):
        response = self.client.get(
            self._workspace_url('recordings'),
            {
                'range': 'last_90_days',
                'sort': 'duration',
                'direction': 'asc',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['visits_range_key'], 'last_90_days')
        self.assertEqual(response.context['visits_sort_key'], 'duration')
        self.assertEqual(response.context['visits_sort_direction'], 'asc')
        self.assertContains(
            response,
            '?range=last_90_days&amp;sort=duration&amp;direction=desc',
        )
        self.assertContains(
            response,
            f'{self._workspace_url("project_user_detail", user_id="alice")}?range=last_90_days',
        )
        self.assertContains(
            response,
            f'{self._workspace_url("project_company_detail", company_id="acme")}?range=last_90_days',
        )

    def test_sort_range_and_pagination_query_preserve_repeated_company_attribute_values(self):
        attribute = CompanyAttribute.objects.create(
            project=self.project,
            name='Plan',
            attribute_type=CompanyAttributeType.SINGLE_SELECT,
        )
        enterprise = CompanyAttributeOption.objects.create(
            attribute=attribute,
            label='Enterprise',
        )
        business = CompanyAttributeOption.objects.create(
            attribute=attribute,
            label='Business',
            position=1,
        )
        CompanyAttributeValue.objects.create(
            attribute=attribute,
            company_id='acme',
            option=enterprise,
        )
        value_key = f'ca.{attribute.id}.value'
        response = self.client.get(
            self._workspace_url('recordings'),
            {
                'range': 'last_30_days',
                'sort': 'date_time',
                'direction': 'desc',
                f'ca.{attribute.id}.op': 'in',
                value_key: [business.id, enterprise.id],
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.redirect_chain), 1)
        self.assertEqual(response.redirect_chain[0][1], 302)
        self.assertEqual(len(response.context['visit_rows']), 1)
        expected_values = [str(enterprise.id), str(business.id)]
        for url in (
            response.context['sort_urls']['duration'],
            response.context['visits_range_urls']['last_7_days'],
            f"?{response.context['pagination_query']}&page=2",
        ):
            with self.subTest(url=url):
                query = parse_qs(urlsplit(url).query)
                self.assertEqual(query[f'ca.{attribute.id}.op'], ['in'])
                self.assertEqual(query[value_key], expected_values)

    def test_company_attribute_preview_endpoint_uses_visits_company_scope(self):
        attribute = CompanyAttribute.objects.create(
            project=self.project,
            name='Lifecycle',
            attribute_type=CompanyAttributeType.TEXT,
        )
        CompanyAttributeValue.objects.create(
            attribute=attribute,
            company_id='acme',
            text_value='Customer',
        )

        response = self.client.get(
            self._workspace_url('project_company_attribute_filter_preview'),
            {
                'surface': 'visits',
                'range': 'last_30_days',
                f'ca.{attribute.id}.op': 'eq',
                f'ca.{attribute.id}.value': 'Customer',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                'surface': 'visits',
                'matching_count': 1,
                'eligible_count': 1,
                'percentage': 100.0,
                'canonicalPairs': [
                    [f'ca.{attribute.id}.op', 'eq'],
                    [f'ca.{attribute.id}.value', 'Customer'],
                ],
            },
        )

    def _create_identity_overview_caches(self, range_key='last_30_days'):
        generated_at = timezone.now()
        start_date = self.started_at.date()
        end_date = generated_at.date()
        CompaniesOverviewCache.objects.create(
            project=self.project,
            range_key=range_key,
            start_date=start_date,
            end_date=end_date,
            payload_json={
                'schema_version': company_analytics.COMPANIES_PAYLOAD_SCHEMA_VERSION,
                'companies': [
                    {
                        'companyId': 'acme',
                        'companyName': 'Acme Inc.',
                        'domain': 'acme.test',
                    },
                ],
            },
            generated_at=generated_at,
        )
        UsersOverviewCache.objects.create(
            project=self.project,
            range_key=range_key,
            start_date=start_date,
            end_date=end_date,
            payload_json={
                'schema_version': user_analytics.USERS_PAYLOAD_SCHEMA_VERSION,
                'users': [
                    {
                        'id': 'alice',
                        'name': 'Alice Example',
                        'email': 'alice@acme.test',
                        'companyId': 'acme',
                        'company': 'Acme Inc.',
                    },
                ],
            },
            generated_at=generated_at,
        )

    def test_entity_options_are_server_searched_by_names_domains_and_emails(self):
        self._create_identity_overview_caches()
        options_url = self._workspace_url('visits_filter_options')
        cases = (
            ('Acme Inc.', 'companies', 'acme'),
            ('acme.test', 'companies', 'acme'),
            ('Alice Example', 'users', 'alice'),
            ('alice@acme.test', 'users', 'alice'),
        )

        for query, section, expected_id in cases:
            with self.subTest(query=query):
                response = self.client.get(
                    options_url,
                    {'q': query, 'range': 'last_30_days'},
                )
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload['query'], query)
                self.assertEqual(payload['range_key'], 'last_30_days')
                self.assertFalse(payload['pending'])
                self.assertIn(expected_id, [option['id'] for option in payload[section]])
                self.assertIn('companies', payload)
                self.assertIn('users', payload)

    def test_entity_options_report_preparing_without_overview_caches(self):
        response = self.client.get(
            self._workspace_url('visits_filter_options'),
            {'q': 'Alice Example', 'range': 'last_30_days'},
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(
            response.json(),
            {
                'query': 'Alice Example',
                'range_key': 'last_30_days',
                'pending': True,
                'companiesPending': True,
                'usersPending': True,
                'companies': [],
                'users': [],
            },
        )

    def test_entity_filter_is_single_select_and_preserved_in_table_links(self):
        self._create_identity_overview_caches()
        response = self.client.get(
            self._workspace_url('recordings'),
            {
                'entity_type': 'user',
                'entity_id': 'alice',
                'range': 'last_30_days',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['paginator'].count, 1)
        self.assertEqual(response.context['visits_entity_type'], 'user')
        self.assertEqual(response.context['visits_entity_id'], 'alice')
        self.assertContains(response, 'User: Alice Example')
        self.assertContains(
            response,
            'entity_type=user&amp;entity_id=alice',
        )

        empty_response = self.client.get(
            self._workspace_url('recordings'),
            {'entity_type': 'company', 'entity_id': 'not-acme'},
        )
        self.assertEqual(empty_response.status_code, 200)
        self.assertEqual(empty_response.context['paginator'].count, 0)
        empty_root = _parse_html_tree(empty_response.content.decode())
        empty_state = _single_node(empty_root, class_name='visits-empty-state')
        self.assertIn('No visits found', empty_state.text)
        self.assertIn(
            'There are no recorded visits in the selected period.',
            empty_state.text,
        )
        self.assertFalse(_find_nodes(empty_root, class_name='visits-table-shell'))
        self.assertFalse(_find_nodes(empty_root, class_name='visits-table-heading-row'))
        self.assertFalse(_find_nodes(empty_root, attrs={'data-visits-session-list': None}))
        self.assertFalse(_find_nodes(empty_root, attrs={'id': 'pagination-bar'}))

    def test_page_and_area_filters_keep_the_complete_session_timeline(self):
        area = ProductArea.objects.create(
            project=self.project,
            name='Core product',
            slug='core',
        )
        dashboard_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern='/dashboard',
            product_area=area.name,
            page_name='Dashboard',
            is_active=True,
            created_by='daily_stable',
        )
        settings_rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern='/settings',
            product_area=area.name,
            page_name='Settings',
            is_active=True,
            created_by='daily_stable',
        )
        self.analytics.events.update(
            page_rule=dashboard_rule,
            page_name='Dashboard',
            product_area=area.name,
        )
        for offset_seconds in (100, 120):
            AnalyticsEvent.objects.create(
                session=self.analytics,
                event_type='mouse_move',
                timestamp=self.started_at + timedelta(seconds=offset_seconds),
                visitor_guid=self.visitor_guid,
                user_id='alice',
                company_id='acme',
                url='https://example.com/settings',
                url_normalized='example.com/settings',
                page_name='Settings',
                page_name_original='Settings',
                page_rule=settings_rule,
                product_area=area.name,
            )
        page_response = self.client.get(
            self._workspace_url('recordings'),
            {
                'page_filter_type': 'page',
                'page_filter_id': dashboard_rule.id,
            },
        )
        self.assertEqual(page_response.status_code, 200)
        self.assertEqual(page_response.context['paginator'].count, 1)
        self.assertContains(page_response, 'Page: Dashboard')
        self.assertEqual(
            [segment['page'] for segment in page_response.context['visit_rows'][0]['segments']],
            ['Dashboard', 'Settings'],
        )

        area_response = self.client.get(
            self._workspace_url('recordings'),
            {
                'page_filter_type': 'area',
                'page_filter_id': area.slug,
            },
        )
        self.assertEqual(area_response.status_code, 200)
        self.assertEqual(area_response.context['paginator'].count, 1)
        self.assertContains(area_response, 'Area: Core product')
        self.assertEqual(
            [segment['page'] for segment in area_response.context['visit_rows'][0]['segments']],
            ['Dashboard', 'Settings'],
        )

    def test_legacy_list_is_removed(self):
        canonical_url = self._workspace_url('recordings')
        legacy_url = f'/w/{self.workspace.slug}/projects/{self.project.id}/visits/legacy'

        canonical_response = self.client.get(canonical_url, follow=True)
        legacy_response = self.client.get(legacy_url)

        self.assertEqual(canonical_response.status_code, 200)
        self.assertEqual(legacy_response.status_code, 404)
        self.assertTemplateUsed(canonical_response, 'tracker/visits.html')
        self.assertNotContains(canonical_response, legacy_url)

    def test_rendered_visits_dom_uses_shared_page_and_card_structure(self):
        response = self.client.get(
            self._workspace_url('recordings'),
            {'range': 'last_30_days'},
        )

        self.assertEqual(response.status_code, 200)
        root = _parse_html_tree(response.content.decode())
        body = _single_node(root, tag='body')
        self.assertTrue(
            {'h-full', 'bg-slate-50', 'text-sm'}.issubset(body.classes),
            body.attrs.get('class'),
        )
        self.assertEqual(body.attrs.get('data-visits-view'), 'table')

        page_shell = _single_node(body, tag='main', class_name='page-shell')
        self.assertTrue(
            {'w-full', 'pb-12', 'pt-20'}.issubset(page_shell.classes),
            page_shell.attrs.get('class'),
        )
        self.assertFalse(_find_nodes(body, class_name='visits-page'))

        header = _single_node(body, tag='header', class_name='visits-page-header')
        self.assertIs(header.parent, page_shell)
        header_content = _single_node(
            header,
            tag='div',
            class_name='visits-page-header__content',
            direct=True,
        )
        intro = _single_node(
            header_content,
            tag='div',
            class_name='visits-page-header__intro',
            direct=True,
        )
        self.assertEqual(_single_node(intro, tag='h1').text, 'Visits')
        self.assertFalse(_find_nodes(intro, class_name='visits-page-description'))
        self.assertFalse(_find_nodes(header_content, class_name='visits-page-count'))

        filter_bar = _single_node(
            header_content,
            tag='section',
            class_name='visits-filter-bar',
            direct=True,
        )
        filter_children = [
            child for child in filter_bar.children if isinstance(child, _HtmlNode)
        ]
        self.assertEqual(len(filter_children), 4)
        filter_variants = [
            class_name
            for node in _find_nodes(filter_bar)
            for class_name in node.classes
            if class_name.startswith('visits-filter--')
        ]
        self.assertEqual(
            filter_variants,
            ['visits-filter--entity', 'visits-filter--page', 'visits-filter--range'],
        )
        # The Companies selector is the first filter on the bar.
        self.assertIn('Companies: All companies', filter_bar.text)
        company_scope = _single_node(filter_bar, attrs={'data-company-scope': None})
        self.assertIs(company_scope, filter_children[0])
        self.assertIn('Any company or user', filter_bar.text)
        self.assertIn('Any page', filter_bar.text)

        entity_filter = _single_node(
            filter_bar,
            class_name='visits-filter--entity',
        )
        entity_trigger = _single_node(
            entity_filter,
            attrs={'data-visits-filter-trigger': None},
        )
        self.assertEqual(entity_trigger.attrs.get('data-has-selection'), 'false')
        entity_search = _single_node(
            entity_filter,
            attrs={'data-visits-entity-search': None},
        )
        self.assertEqual(
            entity_search.attrs.get('placeholder'),
            'Search companies or users…',
        )
        self.assertIn(
            'hidden',
            _single_node(
                entity_filter,
                attrs={'data-visits-filter-clear': None},
            ).attrs,
        )

        page_filter = _single_node(
            filter_bar,
            class_name='visits-filter--page',
        )
        page_trigger = _single_node(
            page_filter,
            attrs={'data-visits-filter-trigger': None},
        )
        self.assertEqual(page_trigger.attrs.get('data-has-selection'), 'false')
        page_search = _single_node(
            page_filter,
            attrs={'data-visits-page-search': None},
        )
        self.assertEqual(
            page_search.attrs.get('placeholder'),
            'Search product areas or pages…',
        )

        period_selector = _single_node(
            filter_bar,
            class_name='visits-period-selector',
        )
        self.assertEqual(period_selector.attrs.get('aria-label'), 'Date range')
        range_controls = [
            node
            for node in _find_nodes(period_selector, direct=True)
            if node.tag in {'a', 'button'}
        ]
        self.assertEqual([node.text for node in range_controls], ['7d', '30d'])
        expected_range_keys = [
            'last_7_days',
            'last_30_days',
        ]
        actual_range_keys = []
        for control in range_controls:
            if control.tag == 'a':
                query = parse_qs(urlsplit(control.attrs.get('href', '')).query)
                actual_range_keys.append(query.get('range', [None])[0])
            else:
                value = control.attrs.get('data-visits-range')
                actual_range_keys.append(
                    value if value.startswith('last_') else f'last_{value[:-1]}_days'
                )
        self.assertEqual(actual_range_keys, expected_range_keys)

        card = _single_node(page_shell, tag='div', class_name='visits-card')
        self.assertTrue(
            {
                'overflow-hidden',
                'rounded-xl',
                'border',
                'border-slate-200',
                'bg-white',
                'pt-2',
                'shadow-sm',
            }.issubset(card.classes),
            card.attrs.get('class'),
        )
        self.assertIs(card.parent, page_shell)

        layout = _single_node(card, tag='div', class_name='visits-layout')
        self.assertIs(layout.parent, card)
        shell = _single_node(layout, tag='div', class_name='visits-table-shell')
        self.assertIn('visits-table-shell--with-play', shell.classes)
        self.assertTrue(
            {
                'flex-1',
                'min-w-0',
                'flex',
                'flex-col',
                '-mt-4',
                'pr-2',
                'pl-4',
                'bg-white',
            }.issubset(shell.classes),
            shell.attrs.get('class'),
        )
        self.assertNotIn(
            'min-h-[calc(100vh-theme(spacing.32))]',
            shell.classes,
        )

        heading_row = _single_node(shell, class_name='visits-table-heading-row')
        self.assertTrue({'flex', 'items-start', 'mb-2'}.issubset(heading_row.classes))
        session_header = _single_node(heading_row, class_name='visits-session-header')
        self.assertIn('ml-4', session_header.classes)
        play_column_header = _single_node(
            session_header,
            class_name='visits-play-column-header',
            direct=True,
        )
        self.assertEqual(play_column_header.attrs.get('aria-hidden'), 'true')
        self.assertNotIn('role', play_column_header.attrs)
        chart_header = _single_node(heading_row, class_name='visits-chart-header')
        self.assertTrue({'flex-1', 'pl-2', 'py-2'}.issubset(chart_header.classes))

        column_headers = _find_nodes(session_header, attrs={'role': 'columnheader'})
        self.assertEqual(len(column_headers), 5)
        sort_controls = _find_nodes(session_header, class_name='visits-table-sort-button')
        timeline_label = _single_node(
            chart_header,
            attrs={'aria-describedby': 'visits-header-tooltip-active-time-by-page'},
        )
        self.assertEqual(
            [control.text for control in sort_controls] + [timeline_label.direct_text],
            [
                'User',
                'Company',
                'Date / time',
                'Duration',
                'Unique pages',
                'Observed active time by page (doesn’t include inactivity)',
            ],
        )
        duration_tooltip = _single_node(
            session_header,
            attrs={'id': 'visits-header-tooltip-duration'},
        )
        self.assertEqual(
            duration_tooltip.text,
            'Elapsed analytical time from the first observed event to the last. '
            'Inactive periods are included; '
            'the bar shows observed active time.',
        )
        timeline_tooltip = _single_node(
            chart_header,
            attrs={'id': 'visits-header-tooltip-active-time-by-page'},
        )
        self.assertIn(
            'Product areas with the most active time come first; '
            'within each area, pages with the most active time come first.',
            timeline_tooltip.text,
        )

        session_list = _single_node(shell, attrs={'data-visits-session-list': None})
        replay_url = self._workspace_url(
            'recording',
            session_id=self.recording.session_id,
        )
        visit_item = _single_node(session_list, tag='li', direct=True)
        row = _single_node(
            visit_item,
            tag='a',
            class_name='visits-session-link',
            attrs={'href': replay_url},
            direct=True,
        )
        self.assertEqual(row.attrs.get('aria-label'), 'Open replay for Alice Example')
        for manual_link_attribute in ('data-visit-detail-href', 'role', 'tabindex'):
            self.assertNotIn(manual_link_attribute, row.attrs)
        self.assertTrue(
            {
                'flex',
                'cursor-pointer',
                'items-start',
                'outline',
                'outline-transparent',
                'transition-colors',
                'duration-150',
                'hover:outline-1',
                'hover:outline-slate-200',
                'hover:bg-slate-50',
            }.issubset(row.classes),
            row.attrs.get('class'),
        )
        self.assertFalse(_find_nodes(row, tag='a'), 'The row anchor must not nest entity anchors')
        play_button = _single_node(
            visit_item,
            tag='a',
            class_name='visits-play-button',
            attrs={'href': replay_url},
            direct=True,
        )
        self.assertEqual(play_button.attrs.get('title'), 'Play recording')
        self.assertEqual(
            play_button.attrs.get('aria-label'),
            'Play recording for Alice Example',
        )
        play_icon = _single_node(play_button, tag='svg', direct=True)
        self.assertEqual(play_icon.attrs.get('viewbox'), '0 -960 960 960')
        self.assertEqual(play_icon.attrs.get('fill'), 'currentColor')
        self.assertTrue(_find_nodes(play_icon, tag='path', direct=True))
        meta = _single_node(row, tag='p', class_name='visits-session-meta')
        self.assertTrue(
            {'py-2', 'ml-4', 'mt-0.5', 'font-medium', 'text-slate-800'}.issubset(meta.classes),
            meta.attrs.get('class'),
        )
        meta_cells = [
            child
            for child in meta.children
            if isinstance(child, _HtmlNode) and child.tag == 'span'
        ]
        self.assertEqual(len(meta_cells), 6)
        self.assertEqual(meta_cells[0].attrs.get('aria-hidden'), 'true')
        self.assertEqual(meta_cells[1].text, 'Alice Example')
        self.assertEqual(meta_cells[2].text, 'Acme Inc.')
        self.assertEqual(meta_cells[4].text, '5m')
        self.assertEqual(meta_cells[5].text, '1 page')

        entity_overlay = _single_node(
            visit_item,
            tag='div',
            class_name='visits-session-entity-links',
            direct=True,
        )
        self.assertIs(entity_overlay.parent, row.parent)
        entity_links = _find_nodes(entity_overlay, tag='a', direct=True)
        self.assertEqual(
            [(link.text, link.attrs.get('href')) for link in entity_links],
            [
                (
                    'Alice Example',
                    f'{self._workspace_url("project_user_detail", user_id="alice")}?range=last_30_days',
                ),
                (
                    'Acme Inc.',
                    f'{self._workspace_url("project_company_detail", company_id="acme")}?range=last_30_days',
                ),
            ],
        )

        chart_hosts = [
            node
            for node in _find_nodes(row)
            if 'data-visits-chart' in node.attrs
        ]
        self.assertEqual(len(chart_hosts), 1)
        chart_host = chart_hosts[0]
        self.assertTrue(
            {
                'chart-container',
                'visits-stacked-chart-container',
                'pl-2',
                'py-2',
                'dragscroll',
                'overflow-x-auto',
                'custom-scroll',
            }.issubset(chart_host.classes),
            chart_host.attrs.get('class'),
        )
        chart_data = _single_node(
            chart_host,
            tag='script',
            attrs={'type': 'application/json'},
        )
        self.assertTrue(chart_data.text.startswith('['), chart_data.text)

        stylesheet_urls = [
            node.attrs.get('href', '')
            for node in _find_nodes(root, tag='link')
            if node.attrs.get('rel') == 'stylesheet'
        ]
        visits_stylesheet_urls = [
            url
            for url in stylesheet_urls
            if urlsplit(url).path.endswith('/css/tracker/visits.css')
        ]
        self.assertEqual(len(visits_stylesheet_urls), 1)
        self.assertIn('v', parse_qs(urlsplit(visits_stylesheet_urls[0]).query))
        script_urls = [
            node.attrs.get('src', '')
            for node in _find_nodes(root, tag='script')
            if node.attrs.get('src')
        ]
        echarts_index = next(i for i, url in enumerate(script_urls) if 'echarts.min.js' in url)
        helpers_index = next(i for i, url in enumerate(script_urls) if 'visits-chart-helpers.js' in url)
        charts_index = next(i for i, url in enumerate(script_urls) if 'visits-charts.js' in url)
        filters_index = next(i for i, url in enumerate(script_urls) if 'visits-filters.js' in url)
        self.assertLess(echarts_index, charts_index)
        self.assertLess(helpers_index, charts_index)
        self.assertLess(filters_index, charts_index)

    def test_rows_without_entity_urls_keep_plain_text_overlay_labels(self):
        initial_response = self.client.get(self._workspace_url('recordings'), follow=True)
        source_row = deepcopy(initial_response.context['visit_rows'][0])
        source_row.update({
            'user_id': '',
            'company_id': '',
            'user_name': 'Anonymous visitor',
            'company_name': 'Unknown company',
        })
        paginator = Paginator([source_row], 1)
        context = {
            'visit_rows': [source_row],
            'page_obj': paginator.page(1),
            'paginator': paginator,
            'project_timezone': 'UTC',
            'visits_range_key': 'last_30_days',
            'visits_range_options': (
                ('last_7_days', 'Last 7 days'),
                ('last_30_days', 'Last 30 days'),
                ('last_90_days', 'Last 90 days'),
                ('last_180_days', 'Last 180 days'),
            ),
            'visits_range_query_suffix': '&sort=date_time&direction=desc',
            'visits_sort_key': 'date_time',
            'visits_sort_direction': 'desc',
        }

        with patch('apps.tracker.views.build_visits_context', return_value=context):
            response = self.client.get(self._workspace_url('recordings'), follow=True)

        self.assertEqual(response.status_code, 200)
        root = _parse_html_tree(response.content.decode())
        session_list = _single_node(root, attrs={'data-visits-session-list': None})
        visit_item = _single_node(session_list, tag='li', direct=True)
        row = _single_node(
            visit_item,
            tag='a',
            class_name='visits-session-link',
            direct=True,
        )
        self.assertEqual(
            row.attrs.get('href'),
            self._workspace_url('recording', session_id=self.recording.session_id),
        )
        self.assertFalse(_find_nodes(row, tag='a'))

        entity_overlay = _single_node(
            visit_item,
            tag='div',
            class_name='visits-session-entity-links',
            direct=True,
        )
        self.assertFalse(_find_nodes(entity_overlay, tag='a'))
        fallback_labels = [
            child
            for child in entity_overlay.children
            if isinstance(child, _HtmlNode) and child.tag == 'span'
        ]
        self.assertEqual(
            [label.text for label in fallback_labels],
            ['Anonymous visitor', 'Unknown company'],
        )

    def test_synthetic_company_id_uses_the_standard_company_detail_link(self):
        company_id = 'hymetry:workspace:none'
        self.analytics.company_id = company_id
        self.analytics.save(update_fields=['company_id'])
        self.analytics.events.update(
            company_id=company_id,
            company_traits={'name': 'No workspace selected'},
        )

        response = self.client.get(self._workspace_url('recordings'), follow=True)

        self.assertEqual(response.status_code, 200)
        root = _parse_html_tree(response.content.decode())
        entity_overlay = _single_node(
            root,
            tag='div',
            class_name='visits-session-entity-links',
        )
        company_link = next(
            link
            for link in _find_nodes(entity_overlay, tag='a', direct=True)
            if link.text == 'No workspace selected'
        )
        self.assertEqual(
            company_link.attrs.get('href'),
            (
                f'{self._workspace_url("project_company_detail", company_id=company_id)}'
                '?range=last_30_days'
            ),
        )

    def test_rendered_pagination_keeps_reference_structure(self):
        initial_response = self.client.get(self._workspace_url('recordings'), follow=True)
        source_row = deepcopy(initial_response.context['visit_rows'][0])
        paginator = Paginator([source_row, deepcopy(source_row)], 1)
        context = {
            'visit_rows': [source_row],
            'page_obj': paginator.page(1),
            'paginator': paginator,
            'project_timezone': 'UTC',
            'visits_range_key': 'last_30_days',
            'visits_range_options': (
                ('last_7_days', 'Last 7 days'),
                ('last_30_days', 'Last 30 days'),
                ('last_90_days', 'Last 90 days'),
                ('last_180_days', 'Last 180 days'),
            ),
            'visits_range_query_suffix': '&sort=date_time&direction=desc',
            'visits_sort_key': 'date_time',
            'visits_sort_direction': 'desc',
        }

        with patch('apps.tracker.views.build_visits_context', return_value=context):
            response = self.client.get(self._workspace_url('recordings'), follow=True)

        self.assertEqual(response.status_code, 200)
        root = _parse_html_tree(response.content.decode())
        pagination_bar = _single_node(root, tag='div', attrs={'id': 'pagination-bar'})
        self.assertIn('margin-top: 60px', pagination_bar.attrs.get('style', ''))
        pagination = _single_node(pagination_bar, tag='nav', class_name='visits-pagination')
        self.assertTrue(
            {
                'mb-6',
                'flex',
                'flex-col',
                'gap-4',
                'px-6',
                'sm:flex-row',
                'sm:items-center',
                'sm:justify-between',
            }.issubset(pagination.classes),
            pagination.attrs.get('class'),
        )
        pagination_meta = _single_node(pagination, class_name='visits-pagination-meta')
        self.assertIn('2', pagination_meta.text)
        refresh = _single_node(
            pagination_meta,
            tag='button',
            class_name='visits-page-refresh',
        )
        self.assertEqual(refresh.attrs.get('aria-label'), 'Refresh visits')

        next_link = _single_node(
            pagination,
            tag='a',
            attrs={'data-visits-pagination-link': None},
        )
        self.assertIn('Continue to next page', next_link.text)
        next_query = parse_qs(urlsplit(next_link.attrs.get('href', '')).query)
        self.assertEqual(next_query.get('page'), ['2'])
        self.assertEqual(next_query.get('range'), ['last_30_days'])
        self.assertIn('Page 1/2', pagination.text)
