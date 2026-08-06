from datetime import timedelta
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.pages.models import RawPageDailyMetric
from apps.projects.models import LifecycleStatus, Project, Workspace, WorkspaceMemberRole, WorkspaceMemberStatus, WorkspaceMembership
from apps.projects.utils import (
    TRACKING_MODE_ANALYTICS_AND_RECORDING,
    TRACKING_MODE_ANALYTICS_ONLY,
    generate_identify_settings_snippet,
    generate_tracking_script,
    get_tracking_mode_label,
    normalize_capture_modes,
    normalize_tracking_mode_choice,
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


class ProjectTrackingUtilsTests(SimpleTestCase):
    def test_normalize_capture_modes_defaults_to_analytics(self):
        self.assertEqual(normalize_capture_modes(None), TRACKING_MODE_ANALYTICS_ONLY)

    def test_normalize_tracking_mode_choice_maps_legacy_recording_to_supported_mode(self):
        self.assertEqual(
            normalize_tracking_mode_choice('recording'),
            TRACKING_MODE_ANALYTICS_AND_RECORDING,
        )

    def test_get_tracking_mode_label_returns_analytics_label(self):
        self.assertEqual(get_tracking_mode_label('analytics'), 'Analytics')

    def test_tracking_script_uses_settings_object_without_onload_handler(self):
        script = generate_tracking_script(
            'TRACKINGSETTINGSTEST123',
            {
                'capture': TRACKING_MODE_ANALYTICS_AND_RECORDING,
            },
        )

        self.assertIn('data-api-key="TRACKINGSETTINGSTEST123"', script)
        self.assertIn('data-capture="analytics,recording"', script)
        self.assertNotIn('onload=', script)

    def test_tracking_script_defaults_to_analytics_capture(self):
        script = generate_tracking_script('TRACKINGSETTINGSTEST123', {})

        self.assertIn('data-capture="analytics"', script)
        self.assertNotIn('data-capture="analytics,recording"', script)

    def test_identify_settings_snippet_uses_safe_placeholders(self):
        snippet = generate_identify_settings_snippet()

        self.assertIn('window.hymetrySettings', snippet)
        self.assertIn('identify', snippet)
        self.assertIn('"USER_ID"', snippet)
        self.assertIn('"COMPANY_ID"', snippet)
        self.assertIn('name: "Jane Cooper"', snippet)
        self.assertIn('email: "jane@example.com"', snippet)
        self.assertNotIn('user?.id', snippet)


class ProjectTrackingSettingsTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='project-owner',
            email='owner@example.com',
            password='testpass123',
        )
        self.workspace = Workspace.objects.create(
            name='Tracking Workspace',
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
            name='Tracking Settings Project',
            created_by=self.user,
            api_key='TRACKINGSETTINGSTEST123',
            tracking_capture='recording',
            product_url='https://app.example.com',
            allowed_domains=['example.com'],
        )
        self.client.force_login(self.user)

    def _project_route(self, route_name, **kwargs):
        return reverse(
            f'w:{route_name}',
            kwargs={'workspace_slug': self.workspace.slug, 'project_id': self.project.id, **kwargs},
        )

    def test_new_project_defaults_to_analytics(self):
        project = Project.objects.create(
            workspace=self.workspace,
            name='Default Tracking Project',
            created_by=self.user,
        )

        self.assertEqual(project.tracking_capture, TRACKING_MODE_ANALYTICS_ONLY)

    def test_update_project_tracking_saves_analytics_only_mode(self):
        response = self.client.post(
            reverse('projects:update_project_tracking', kwargs={'project_id': self.project.id}),
            {'tracking_mode': TRACKING_MODE_ANALYTICS_ONLY},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.project.refresh_from_db()
        self.assertEqual(self.project.tracking_capture, TRACKING_MODE_ANALYTICS_ONLY)
        messages = list(response.context['messages'])
        self.assertTrue(any('Update the script in your app' in str(message) for message in messages))

    def test_member_can_access_and_update_project_settings(self):
        user_model = get_user_model()
        member = user_model.objects.create_user(
            username='project-member',
            email='project-member@example.com',
            password='testpass123',
        )
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=member,
            role=WorkspaceMemberRole.MEMBER,
            status=WorkspaceMemberStatus.ACTIVE,
        )
        self.client.force_login(member)

        response = self.client.get(self._project_route('project_settings'))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            self._project_route('update_project_product_url'),
            {'product_url': 'https://member.acme.com'},
        )
        self.assertRedirects(response, self._project_route('project_settings'))
        self.project.refresh_from_db()
        self.assertEqual(self.project.product_url, 'acme.com')
        self.assertEqual(self.project.allowed_domains, ['acme.com'])

    def test_update_project_tracking_upgrades_legacy_recording_to_supported_combined_mode(self):
        response = self.client.post(
            reverse('projects:update_project_tracking', kwargs={'project_id': self.project.id}),
            {'tracking_mode': TRACKING_MODE_ANALYTICS_AND_RECORDING},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.project.refresh_from_db()
        self.assertEqual(self.project.tracking_capture, TRACKING_MODE_ANALYTICS_AND_RECORDING)

    def test_project_settings_maps_legacy_recording_to_combined_radio_option(self):
        response = self.client.get(
            reverse('projects:project_settings', kwargs={'project_id': self.project.id}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['tracking_mode'], TRACKING_MODE_ANALYTICS_AND_RECORDING)
        self.assertEqual(response.context['tracking_mode_label'], 'Analytics and screen recording')
        self.assertContains(response, 'type="radio"', count=2, html=False)

    def test_project_settings_renders_analytics_option_first_for_default_tracking(self):
        project = Project.objects.create(
            workspace=self.workspace,
            name='Analytics Default Project',
            created_by=self.user,
            product_url='https://analytics.example.com',
            allowed_domains=['analytics.example.com'],
        )

        response = self.client.get(
            self._project_route('project_settings', project_id=project.id),
        )

        content = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['tracking_mode'], TRACKING_MODE_ANALYTICS_ONLY)
        self.assertEqual(response.context['tracking_mode_label'], 'Analytics')
        self.assertLess(content.index('id="tracking-mode-analytics"'), content.index('id="tracking-mode-combined"'))
        self.assertContains(response, '<span class="block font-medium text-slate-900">Analytics</span>', html=False)
        self.assertNotContains(response, 'Analytics only')

    def test_project_settings_shows_timezone_and_change_trigger(self):
        response = self.client.get(
            reverse('projects:project_settings', kwargs={'project_id': self.project.id}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Time zone:')
        self.assertContains(response, "Defines when days start and end for this project's reports.")
        self.assertContains(response, self.project.timezone)
        self.assertContains(response, 'aria-controls="change-project-timezone"', html=False)
        self.assertContains(response, 'id="change-project-timezone"', html=False)
        self.assertContains(response, 'name="timezone"', html=False)

    @override_settings(OPENAI_API_KEY='test-key')
    def test_project_settings_does_not_render_chatgpt_api_key_block(self):
        response = self.client.get(
            reverse('projects:project_settings', kwargs={'project_id': self.project.id}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'ChatGPT API key')
        self.assertNotContains(response, 'Configured by workspace')
        self.assertNotContains(response, 'Not configured')

    def test_project_settings_warns_when_tracking_has_no_fresh_data(self):
        response = self.client.get(
            reverse('projects:project_settings', kwargs={'project_id': self.project.id}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['has_fresh_data'])
        self.assertEqual(response.context['project_status_key'], 'setup_required')
        self.assertContains(response, 'class="status-badge ', html=False)
        self.assertContains(response, 'data-status="setup_required"', html=False)
        self.assertContains(response, 'Setup required')
        self.assertContains(response, 'Analytics')
        self.assertContains(response, 'Session recording')
        self.assertContains(response, 'Not detected')

    def test_project_settings_installation_status_uses_tracking_events(self):
        now = timezone.now()
        self.project.first_production_event_at = now - timedelta(minutes=3)
        self.project.last_event_at = now - timedelta(minutes=2)
        self.project.save(update_fields=['first_production_event_at', 'last_event_at'])

        visitor = Visitor.objects.create(
            project=self.project,
            visitor_guid=uuid4(),
            first_visit=now - timedelta(minutes=3),
            last_activity=now - timedelta(minutes=2),
        )
        recording_session = Session.objects.create(
            visitor=visitor,
            start_time=now - timedelta(minutes=3),
            last_activity=now - timedelta(minutes=2),
        )
        Event.objects.create(
            session=recording_session,
            url='https://app.example.com/',
            event_type=2,
            timestamp=now - timedelta(minutes=2),
            data={},
        )

        analytics_session = AnalyticsSession.objects.create(
            project=self.project,
            visitor_guid=uuid4(),
            user_id='user-123',
            company_id='company-456',
            start_time=now - timedelta(minutes=3),
            last_activity=now - timedelta(minutes=2),
        )
        AnalyticsEvent.objects.create(
            session=analytics_session,
            timestamp=now - timedelta(minutes=2),
            visitor_guid=analytics_session.visitor_guid,
            user_id='user-123',
            company_id='company-456',
            url='https://app.example.com/',
        )

        response = self.client.get(
            reverse('projects:project_settings', kwargs={'project_id': self.project.id}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['has_fresh_data'])
        self.assertTrue(response.context['installation_status']['is_ready'])
        self.assertContains(response, 'Active')
        self.assertContains(response, 'Detected')
        self.assertContains(
            response,
            'Your setup is ready. Companies, Users, Pages, and Visits analytics will become more useful as more production data is collected.',
        )

    def test_project_settings_installation_status_shows_no_recent_data_for_stale_tracking_events(self):
        stale_at = timezone.now() - timedelta(days=4)
        self.project.allowed_domains = []
        self.project.first_production_event_at = stale_at - timedelta(minutes=1)
        self.project.last_event_at = stale_at
        self.project.save(update_fields=['allowed_domains', 'first_production_event_at', 'last_event_at'])

        visitor = Visitor.objects.create(
            project=self.project,
            visitor_guid=uuid4(),
            first_visit=stale_at - timedelta(minutes=1),
            last_activity=stale_at,
        )
        recording_session = Session.objects.create(
            visitor=visitor,
            start_time=stale_at - timedelta(minutes=1),
            last_activity=stale_at,
        )
        Event.objects.create(
            session=recording_session,
            url='https://app.example.com/',
            event_type=2,
            timestamp=stale_at,
            data={},
        )

        analytics_session = AnalyticsSession.objects.create(
            project=self.project,
            visitor_guid=uuid4(),
            user_id='user-123',
            company_id='company-456',
            start_time=stale_at - timedelta(minutes=1),
            last_activity=stale_at,
        )
        AnalyticsEvent.objects.create(
            session=analytics_session,
            timestamp=stale_at,
            visitor_guid=analytics_session.visitor_guid,
            user_id='user-123',
            company_id='company-456',
            url='https://app.example.com/',
        )

        response = self.client.get(
            reverse('projects:project_settings', kwargs={'project_id': self.project.id}),
        )

        installation_status = response.context['installation_status']
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['has_fresh_data'])
        self.assertTrue(installation_status['has_no_recent_data'])
        self.assertTrue(installation_status['requires_setup'])
        self.assertFalse(installation_status['is_active'])
        self.assertFalse(installation_status['is_ready'])
        self.assertContains(response, 'No recent data')
        self.assertContains(
            response,
            'Product URL / allowed domain is missing. Add the product URL in Data collection to finish setup.',
        )
        self.assertNotContains(
            response,
            'Your setup is ready. Companies, Users, Pages, and Visits analytics will become more useful as more production data is collected.',
        )

    def test_project_settings_installation_status_requires_allowed_domain(self):
        now = timezone.now()
        self.workspace.website_url = ''
        self.workspace.save(update_fields=['website_url'])
        self.project.allowed_domains = []
        self.project.first_production_event_at = now - timedelta(minutes=3)
        self.project.last_event_at = now - timedelta(minutes=2)
        self.project.save(update_fields=['allowed_domains', 'first_production_event_at', 'last_event_at'])

        visitor = Visitor.objects.create(
            project=self.project,
            visitor_guid=uuid4(),
            first_visit=now - timedelta(minutes=3),
            last_activity=now - timedelta(minutes=2),
        )
        recording_session = Session.objects.create(
            visitor=visitor,
            start_time=now - timedelta(minutes=3),
            last_activity=now - timedelta(minutes=2),
        )
        Event.objects.create(
            session=recording_session,
            url='https://app.example.com/',
            event_type=2,
            timestamp=now - timedelta(minutes=2),
            data={},
        )
        analytics_session = AnalyticsSession.objects.create(
            project=self.project,
            visitor_guid=uuid4(),
            user_id='user-123',
            company_id='company-456',
            start_time=now - timedelta(minutes=3),
            last_activity=now - timedelta(minutes=2),
        )
        AnalyticsEvent.objects.create(
            session=analytics_session,
            timestamp=now - timedelta(minutes=2),
            visitor_guid=analytics_session.visitor_guid,
            user_id='user-123',
            company_id='company-456',
            url='https://app.example.com/',
        )

        response = self.client.get(
            reverse('projects:project_settings', kwargs={'project_id': self.project.id}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['installation_status']['is_ready'])
        self.assertTrue(response.context['installation_status']['requires_setup'])
        self.assertContains(response, 'Setup required')
        self.assertContains(
            response,
            'Product URL / allowed domain is missing. Add the product URL in Data collection to finish setup.',
        )
        self.assertNotContains(
            response,
            'Your setup is ready. Companies, Users, Pages, and Visits analytics will become more useful as more production data is collected.',
        )

    def test_project_settings_recording_mode_shows_privacy_settings(self):
        response = self.client.get(
            reverse('projects:project_settings', kwargs={'project_id': self.project.id}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Privacy settings')
        self.assertContains(response, '.rr-block')
        self.assertContains(response, '.rr-ignore')
        self.assertContains(response, '.rr-mask')

    def test_project_settings_analytics_mode_hides_privacy_settings(self):
        self.project.tracking_capture = TRACKING_MODE_ANALYTICS_ONLY
        self.project.save(update_fields=['tracking_capture'])

        response = self.client.get(
            reverse('projects:project_settings', kwargs={'project_id': self.project.id}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['show_privacy_settings'])
        self.assertNotContains(response, 'Privacy settings')
        self.assertNotContains(response, '.rr-block')
        self.assertNotContains(response, '.rr-ignore')
        self.assertNotContains(response, '.rr-mask')

    def test_project_settings_shows_delete_project_for_owner(self):
        response = self.client.get(self._project_route('project_settings'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'DELETE PROJECT')
        self.assertContains(response, 'aria-controls="delete-project"', html=False)

    def test_project_settings_hides_delete_project_for_admin(self):
        user_model = get_user_model()
        admin = user_model.objects.create_user(
            username='project-admin',
            email='project-admin@example.com',
            password='testpass123',
        )
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=admin,
            role=WorkspaceMemberRole.ADMIN,
            status=WorkspaceMemberStatus.ACTIVE,
        )
        self.client.force_login(admin)

        response = self.client.get(self._project_route('project_settings'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'DELETE PROJECT')
        self.assertNotContains(response, 'aria-controls="delete-project"', html=False)

        delete_response = self.client.post(
            reverse('w:project_delete', kwargs={'workspace_slug': self.workspace.slug, 'pk': self.project.id}),
        )
        self.assertEqual(delete_response.status_code, 403)
        self.project.refresh_from_db()
        self.assertEqual(self.project.lifecycle_status, LifecycleStatus.ACTIVE)

    def test_project_delete_archives_project(self):
        response = self.client.post(
            reverse('w:project_delete', kwargs={'workspace_slug': self.workspace.slug, 'pk': self.project.id}),
        )

        self.assertRedirects(response, reverse('projects:project_list'))
        self.project.refresh_from_db()
        self.assertEqual(self.project.lifecycle_status, LifecycleStatus.ARCHIVED)
        self.assertIsNotNone(self.project.archived_at)
        self.assertIsNotNone(self.project.delete_after)

        archived_response = self.client.get(self._project_route('project_settings'))
        self.assertEqual(archived_response.status_code, 404)

    def test_project_settings_name_modal_has_duplicate_validation_target(self):
        response = self.client.get(
            self._project_route('project_settings'),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="change-project-name-error"', html=False)
        self.assertContains(response, 'data-existing-project-names=', html=False)

    def test_update_project_name_rejects_duplicate_in_same_workspace(self):
        Project.objects.create(
            workspace=self.workspace,
            name='Existing Project',
            created_by=self.user,
            product_url='example.com',
            allowed_domains=['example.com'],
        )

        response = self.client.post(
            self._project_route('update_project_name'),
            {'name': 'existing project'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(
            response.json()['error'],
            'A project with this name already exists in this workspace.',
        )
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, 'Tracking Settings Project')

    def test_update_project_product_url_rejects_invalid_url_without_500(self):
        response = self.client.post(
            self._project_route('update_project_product_url'),
            {'product_url': '['},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Enter a valid product URL.')
        self.project.refresh_from_db()
        self.assertEqual(self.project.product_url, 'https://app.example.com')
        self.assertEqual(self.project.allowed_domains, ['example.com'])

    def test_update_project_product_url_stores_root_domain(self):
        response = self.client.post(
            self._project_route('update_project_product_url'),
            {'product_url': 'https://l11.com2.com/install'},
        )

        self.assertRedirects(response, self._project_route('project_settings'))
        self.project.refresh_from_db()
        self.assertEqual(self.project.product_url, 'com2.com')
        self.assertEqual(self.project.allowed_domains, ['com2.com'])

    def test_update_project_product_url_uses_public_suffix_list(self):
        response = self.client.post(
            self._project_route('update_project_product_url'),
            {'product_url': 'https://app.acme.com.ua/install'},
        )

        self.assertRedirects(response, self._project_route('project_settings'))
        self.project.refresh_from_db()
        self.assertEqual(self.project.product_url, 'acme.com.ua')
        self.assertEqual(self.project.allowed_domains, ['acme.com.ua'])

    def test_update_project_product_url_rejects_public_suffix_only(self):
        response = self.client.post(
            self._project_route('update_project_product_url'),
            {'product_url': 'com.ua'},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Enter a valid product URL.')
        self.project.refresh_from_db()
        self.assertEqual(self.project.product_url, 'https://app.example.com')
        self.assertEqual(self.project.allowed_domains, ['example.com'])

    def test_project_product_areas_renders_rules_examples_and_volume(self):
        rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^app\.example\.com/customers/\d+$',
            product_area='Customers',
            page_name='Customer details',
            priority=140,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )
        analytics_session = AnalyticsSession.objects.create(
            project=self.project,
            visitor_guid=uuid4(),
            start_time=timezone.now(),
            last_activity=timezone.now(),
        )
        now = timezone.now()
        AnalyticsEvent.objects.create(
            session=analytics_session,
            timestamp=now - timedelta(minutes=2),
            url='https://app.example.com/customers/100',
            url_normalized='app.example.com/customers/100',
            product_area='Customers',
            page_name='Customer details',
            page_rule=rule,
        )
        AnalyticsEvent.objects.create(
            session=analytics_session,
            timestamp=now - timedelta(minutes=1),
            url='https://app.example.com/customers/101',
            url_normalized='app.example.com/customers/101',
            product_area='Customers',
            page_name='Customer details',
            page_rule=rule,
        )

        response = self.client.get(
            reverse('projects:project_product_areas', kwargs={'project_id': self.project.id}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Product areas')
        self.assertContains(response, 'Customers')
        self.assertContains(response, 'Customer details')
        self.assertContains(response, r'^app\.example\.com/customers/\d+$')
        self.assertContains(response, 'app.example.com/customers/100')
        self.assertContains(response, 'app.example.com/customers/101')
        self.assertEqual(response.context['product_area_rows'][0]['product_area'], 'Customers')
        self.assertEqual(response.context['product_area_rows'][0]['volume_7d'], 2)

    def test_project_product_areas_uses_prepared_pages_metrics_when_available(self):
        rule = ProjectPageRule.objects.create(
            project=self.project,
            pattern=r'^app\.example\.com/settings(?:/[^/]+)?$',
            product_area='Administration',
            page_name='Settings',
            priority=140,
            created_by=ProjectPageNamingRunMode.DAILY_STABLE,
        )
        today = timezone.now().date()
        RawPageDailyMetric.objects.create(
            project=self.project,
            date=today,
            url_normalized='app.example.com/settings',
            page_rule_id=rule.id,
            product_area_name='Administration',
            visits_count=7,
        )
        RawPageDailyMetric.objects.create(
            project=self.project,
            date=today - timedelta(days=1),
            url_normalized='app.example.com/settings/profile',
            page_rule_id=rule.id,
            product_area_name='Administration',
            visits_count=3,
        )

        response = self.client.get(
            reverse('projects:project_product_areas', kwargs={'project_id': self.project.id}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'app.example.com/settings')
        self.assertContains(response, 'app.example.com/settings/profile')
        self.assertEqual(response.context['product_area_rows'][0]['volume_7d'], 10)

    def test_project_product_areas_paginate_rules(self):
        for index in range(11):
            ProjectPageRule.objects.create(
                project=self.project,
                pattern=rf'^app\.example\.com/page-{index}$',
                page_name=f'Page {index}',
                priority=100 + index,
                created_by=ProjectPageNamingRunMode.DAILY_STABLE,
            )

        response = self.client.get(
            reverse('projects:project_product_areas', kwargs={'project_id': self.project.id}),
            {'page': 2},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['page_obj'].number, 2)
        self.assertEqual(len(response.context['product_area_rows']), 1)
        self.assertContains(response, 'Page 0')

    def test_project_product_areas_pagination_matches_mock_states(self):
        for index in range(21):
            ProjectPageRule.objects.create(
                project=self.project,
                pattern=rf'^app\.example\.com/page-{index}$',
                page_name=f'Page {index}',
                priority=100 + index,
                created_by=ProjectPageNamingRunMode.DAILY_STABLE,
            )

        first_page = self.client.get(
            reverse('projects:project_product_areas', kwargs={'project_id': self.project.id}),
        )
        self.assertContains(first_page, 'Page 1/3')
        self.assertContains(first_page, 'Continue to next page')
        self.assertContains(first_page, 'sm:justify-between', html=False)
        self.assertContains(first_page, 'sm:justify-end', html=False)
        self.assertNotContains(first_page, 'Go to first page')
        self.assertNotContains(first_page, 'aria-label="Go to previous page"', html=False)
        self.assertNotContains(first_page, 'Already here')
        self.assertNotContains(first_page, 'No more pages')

        middle_page = self.client.get(
            reverse('projects:project_product_areas', kwargs={'project_id': self.project.id}),
            {'page': 2},
        )
        self.assertContains(middle_page, 'Page 2/3')
        self.assertContains(middle_page, 'Continue to next page')
        self.assertContains(middle_page, 'sm:justify-between', html=False)
        self.assertNotContains(middle_page, 'Go to first page')
        self.assertContains(middle_page, 'aria-label="Go to previous page"', html=False)
        self.assertNotContains(middle_page, 'Already here')
        self.assertNotContains(middle_page, 'No more pages')

        last_page = self.client.get(
            reverse('projects:project_product_areas', kwargs={'project_id': self.project.id}),
            {'page': 3},
        )
        self.assertContains(last_page, 'Page 3/3')
        self.assertContains(last_page, 'sm:justify-between', html=False)
        self.assertContains(last_page, 'Go to first page')
        self.assertContains(last_page, 'aria-label="Go to previous page"', html=False)
        self.assertNotContains(last_page, 'Continue to next page')
        self.assertNotContains(last_page, 'Already here')
        self.assertNotContains(last_page, 'No more pages')

    def test_project_product_areas_hides_pagination_for_single_page(self):
        for index in range(10):
            ProjectPageRule.objects.create(
                project=self.project,
                pattern=rf'^app\.example\.com/single-page-{index}$',
                page_name=f'Single page {index}',
                priority=100 + index,
                created_by=ProjectPageNamingRunMode.DAILY_STABLE,
            )

        response = self.client.get(
            reverse('projects:project_product_areas', kwargs={'project_id': self.project.id}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Page 1/1')
        self.assertNotContains(response, 'Go to first page')
        self.assertNotContains(response, 'Continue to next page')
        self.assertNotContains(response, 'aria-label="Go to previous page"', html=False)

    def test_project_product_areas_hides_modify_structure_without_observed_pages(self):
        response = self.client.get(
            reverse('projects:project_product_areas', kwargs={'project_id': self.project.id}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['has_observed_pages'])
        self.assertNotContains(response, 'aria-controls="modify-page-structure"', html=False)
        self.assertNotContains(response, 'id="modify-page-structure"', html=False)
        self.assertContains(
            response,
            'Once we observe some pages, you will be able to guide how they should be organized here.',
        )

    def test_project_product_areas_shows_modify_structure_when_pages_exist_without_rules(self):
        analytics_session = AnalyticsSession.objects.create(
            project=self.project,
            visitor_guid=uuid4(),
            start_time=timezone.now(),
            last_activity=timezone.now(),
        )
        AnalyticsEvent.objects.create(
            session=analytics_session,
            url='https://app.example.com/dashboard',
            url_normalized='app.example.com/dashboard',
            page_name='Undefined',
        )

        response = self.client.get(
            reverse('projects:project_product_areas', kwargs={'project_id': self.project.id}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['has_observed_pages'])
        self.assertContains(response, 'aria-controls="modify-page-structure"', html=False)
        self.assertContains(response, 'id="modify-page-structure"', html=False)

    def test_project_pages_overview_renders(self):
        response = self.client.get(
            reverse('projects:project_pages', kwargs={'project_id': self.project.id}),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Pages')
        self.assertNotContains(response, 'Understand which pages/features are used')
        self.assertContains(response, 'No data were found in the last 30 complete days.')

    def test_update_page_structure_guidance_saves_value(self):
        response = self.client.post(
            reverse('projects:update_page_structure_guidance', kwargs={'project_id': self.project.id}),
            {
                'page_structure_guidance': 'Keep dashboard URLs grouped together.',
                'page': '2',
            },
        )

        self.project.refresh_from_db()
        self.assertEqual(self.project.page_structure_guidance, 'Keep dashboard URLs grouped together.')
        self.assertRedirects(
            response,
            f"{self._project_route('project_product_areas')}?page=2",
            fetch_redirect_response=False,
        )

    def test_update_page_structure_guidance_rejects_values_above_limit(self):
        response = self.client.post(
            reverse('projects:update_page_structure_guidance', kwargs={'project_id': self.project.id}),
            {'page_structure_guidance': 'x' * 501},
            follow=True,
        )

        self.project.refresh_from_db()
        self.assertEqual(self.project.page_structure_guidance, '')
        self.assertContains(response, 'Keep page structure guidance within 500 characters.')
