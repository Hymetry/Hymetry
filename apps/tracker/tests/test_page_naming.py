from datetime import timedelta
from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import re2
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.projects.models import Project
from apps.projects.tests.helpers import create_workspace_with_owner
from apps.tracker.models import AnalyticsEvent, AnalyticsSession, ProjectPageNamingPhase, TitlePrompt
from apps.tracker.page_naming import (
    _build_prompt,
    build_hybrid_urls,
    calculate_new_url_metrics,
    compile_page_rules,
    generate_page_naming_rules,
    get_source_adapter,
    normalize_page_url,
    normalize_page_url_key,
    resolve_page_rule_match,
    truncate_url_for_prompt,
)


class PageNamingUtilsTests(SimpleTestCase):
    def test_normalize_page_url_removes_query_fragment_and_trailing_slash(self):
        normalized = normalize_page_url('https://app.example.com/invoices/123/?tab=details#section')
        self.assertEqual(normalized, 'https://app.example.com/invoices/123')

    def test_normalize_page_url_key_removes_scheme_as_well(self):
        normalized = normalize_page_url_key('https://app.example.com/invoices/123/?tab=details#section')
        self.assertEqual(normalized, 'app.example.com/invoices/123')

    def test_truncate_url_for_prompt_adds_ellipsis(self):
        url = 'https://app.example.com/' + ('a' * 200)
        truncated = truncate_url_for_prompt(url)

        self.assertTrue(truncated.endswith('…'))
        self.assertEqual(truncated[:-1], url[:150])

    def test_fullmatch_rule_does_not_match_unrelated_subpath(self):
        rule = SimpleNamespace(
            id=1,
            pattern=r'^app\.example\.com/invoice/\d+$',
            product_area='Billing',
            page_name='Invoice details',
            priority=100,
        )
        compiled_rules = [(rule, re2.compile(rule.pattern))]

        exact_match = resolve_page_rule_match(
            'https://app.example.com/invoice/1234',
            compiled_rules=compiled_rules,
        )
        nested_match = resolve_page_rule_match(
            'https://app.example.com/help/invoice/1234/how-to-pay',
            compiled_rules=compiled_rules,
        )

        self.assertEqual(exact_match[1], 'Billing')
        self.assertEqual(exact_match[2], 'Invoice details')
        self.assertEqual(nested_match[1], '')
        self.assertEqual(nested_match[2], 'Undefined')

    def test_higher_priority_rule_matches_first(self):
        broad_rule = SimpleNamespace(
            id=1,
            pattern=r'^app\.example\.com/customers/.+$',
            product_area='Customers',
            page_name='Customers',
            priority=50,
        )
        specific_rule = SimpleNamespace(
            id=2,
            pattern=r'^app\.example\.com/customers/\d+$',
            product_area='Customers',
            page_name='Customer details',
            priority=150,
        )

        _, product_area, page_name = resolve_page_rule_match(
            'https://app.example.com/customers/123',
            compiled_rules=compile_page_rules([broad_rule, specific_rule]),
        )

        self.assertEqual(product_area, 'Customers')
        self.assertEqual(page_name, 'Customer details')


class PageNamingMetricsTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='page-naming-metrics-owner',
            email='page-naming-metrics-owner@example.com',
            password='testpass123',
        )
        self.workspace = create_workspace_with_owner(self.user, name='Page Naming Metrics Workspace')
        self.project = Project.objects.create(
            workspace=self.workspace,
            name='Page Naming Metrics',
            created_by=self.user,
            api_key='METRICS123',
            tracking_capture='analytics',
        )
        self.session = AnalyticsSession.objects.create(
            project=self.project,
            visitor_guid=uuid4(),
            start_time=timezone.now(),
            last_activity=timezone.now(),
        )

    def _create_event(self, timestamp, url_normalized):
        return AnalyticsEvent.objects.create(
            session=self.session,
            timestamp=timestamp,
            url=f'https://{url_normalized}',
            url_normalized=url_normalized,
            page_name='Undefined',
        )

    def test_page_naming_windows_exclude_future_analytics_events(self):
        now = timezone.now()
        self._create_event(now - timedelta(hours=2), 'example.com/known')
        self._create_event(now - timedelta(minutes=30), 'example.com/current')
        self._create_event(now + timedelta(hours=1), 'example.com/future')

        adapter = get_source_adapter(self.project)
        metrics = calculate_new_url_metrics(adapter, now=now)
        hybrid_urls = build_hybrid_urls(
            self.project,
            adapter,
            now=now,
            top_limit=10,
            random_limit=0,
        )

        self.assertEqual(metrics['events_1h'], 1)
        self.assertEqual(metrics['new_urls_1h'], 1)
        self.assertEqual(metrics['urls_last_hour'], {'example.com/current'})
        self.assertNotIn('example.com/future', metrics['urls_last_day'])
        self.assertNotIn('example.com/future', hybrid_urls)


class TitlePromptTests(TestCase):
    def setUp(self):
        super().setUp()
        key_patcher = patch(
            'apps.tracker.page_naming.get_openai_api_key_for_project',
            return_value='workspace-test-key',
        )
        key_patcher.start()
        self.addCleanup(key_patcher.stop)

    def test_only_one_title_prompt_config_is_allowed(self):
        TitlePrompt.objects.create(
            name='prompt-one',
            hourly_unstable_openai_model='gpt-5.4-mini',
            daily_stable_openai_model='gpt-5.4-mini',
        )

        with self.assertRaises(ValidationError):
            TitlePrompt.objects.create(
                name='prompt-two',
                hourly_unstable_openai_model='gpt-5.4-mini',
                daily_stable_openai_model='gpt-5.4-mini',
            )

    def test_page_naming_prompt_is_rendered_from_titleprompt_table(self):
        TitlePrompt.objects.create(
            name='title_prompt_config',
            hourly_unstable_prompt='Current:\n{{CURRENT_STRUCTURE_JSON_OR_EMPTY_ARRAY}}\nObserved:\n{{OBSERVED_PAGES}}',
            hourly_unstable_openai_model='gpt-5.4-mini',
            daily_stable_openai_model='gpt-5.4-mini',
        )
        project = SimpleNamespace(name='Alpha')

        prompt_text, prompt_name, prompt_version = _build_prompt(
            mode='hourly_unstable',
            project=project,
            urls=['https://example.com/customers/123?tab=usage'],
        )

        self.assertEqual(prompt_name, 'title_prompt_config:hourly_unstable_prompt')
        self.assertTrue(prompt_version.startswith('db-'))
        self.assertIn('[]', prompt_text)
        self.assertIn('"url": "example.com/customers/123"', prompt_text)
        self.assertIn('"page_title": ""', prompt_text)

    def test_stable_page_naming_prompt_uses_second_field(self):
        TitlePrompt.objects.create(
            name='title_prompt_config',
            daily_stable_prompt='Current:\n{{CURRENT_STRUCTURE_JSON}}\nObserved:\n{{OBSERVED_PAGES_JSON}}',
            hourly_unstable_openai_model='gpt-5.4-mini',
            daily_stable_openai_model='gpt-5.4-mini',
        )
        project = SimpleNamespace(name='Alpha')

        prompt_text, prompt_name, prompt_version = _build_prompt(
            mode='daily_stable',
            project=project,
            urls=['https://example.com/customers/123?tab=usage'],
            existing_rules=[
                {
                    'pattern': r'^example\.com/customers/\d+$',
                    'page_group': 'Customer',
                    'page_group_short_name': 'Customer',
                    'page_name': 'Customer',
                    'priority': 140,
                }
            ],
        )

        self.assertEqual(prompt_name, 'title_prompt_config:daily_stable_prompt')
        self.assertTrue(prompt_version.startswith('db-'))
        self.assertIn('"pattern": "^example\\\\.com/customers/\\\\d+$"', prompt_text)
        self.assertIn('"page_group": "Customer"', prompt_text)
        self.assertIn('"page_group_short_name": "Customer"', prompt_text)
        self.assertIn('"page_name": "Customer"', prompt_text)
        self.assertIn('"priority": 140', prompt_text)
        self.assertIn('"url": "example.com/customers/123"', prompt_text)
        self.assertIn('"page_title": ""', prompt_text)

    def test_bootstrap_page_naming_prompt_uses_bootstrap_field(self):
        TitlePrompt.objects.create(
            name='title_prompt_config',
            bootstrap_page_naming_prompt='Bootstrap:\n{{OBSERVED_PAGES}}',
            bootstrap_page_naming_openai_model='gpt-5.4',
            hourly_unstable_prompt='Hourly:\n{{OBSERVED_PAGES}}',
            hourly_unstable_openai_model='gpt-5.4-mini',
            daily_stable_openai_model='gpt-5.4-mini',
        )
        project = SimpleNamespace(name='Alpha')

        prompt_text, prompt_name, _ = _build_prompt(
            mode='hourly_unstable',
            phase=ProjectPageNamingPhase.BOOTSTRAP,
            project=project,
            urls=['https://example.com/customers/123?tab=usage'],
        )

        self.assertEqual(prompt_name, 'title_prompt_config:bootstrap_page_naming_prompt')
        self.assertIn('Bootstrap:', prompt_text)
        self.assertNotIn('Hourly:', prompt_text)

    def test_prompt_renders_current_structure_and_observed_pages_placeholders(self):
        user = get_user_model().objects.create_user(
            username='page-naming-prompt-user',
            email='page-naming-prompt-user@example.com',
            password='testpass123',
        )
        workspace = create_workspace_with_owner(user, name='Page Naming Prompt Workspace')
        project = Project.objects.create(
            workspace=workspace,
            name='Alpha',
            created_by=user,
            api_key='PROMPTTEST123',
            tracking_capture='analytics',
        )
        analytics_session = AnalyticsSession.objects.create(
            project=project,
            visitor_guid=uuid4(),
            start_time=timezone.now(),
            last_activity=timezone.now(),
        )
        AnalyticsEvent.objects.create(
            session=analytics_session,
            timestamp=timezone.now(),
            url='https://example.com/customers/123?tab=usage',
            url_normalized='example.com/customers/123',
            page_name='Undefined',
            page_name_original='Customer 123 - Usage',
        )
        TitlePrompt.objects.create(
            name='title_prompt_config',
            hourly_unstable_prompt='Current:\n{{CURRENT_STRUCTURE_JSON_OR_EMPTY_ARRAY}}\nObserved:\n{{OBSERVED_PAGES}}',
            hourly_unstable_openai_model='gpt-5.4-mini',
            daily_stable_openai_model='gpt-5.4-mini',
        )

        prompt_text, _, _ = _build_prompt(
            mode='hourly_unstable',
            project=project,
            urls=['example.com/customers/123'],
            existing_rules=[
                {
                    'pattern': r'^example\.com/customers/\d+$',
                    'page_group': 'Customers',
                    'page_group_short_name': 'Customers',
                    'page_name': 'Customer details',
                    'priority': 140,
                    'id': 99,
                    'created_by': 'daily_stable',
                }
            ],
        )

        self.assertIn('"pattern": "^example\\\\.com/customers/\\\\d+$"', prompt_text)
        self.assertIn('"page_group": "Customers"', prompt_text)
        self.assertIn('"page_group_short_name": "Customers"', prompt_text)
        self.assertIn('"page_name": "Customer details"', prompt_text)
        self.assertIn('"priority": 140', prompt_text)
        self.assertNotIn('"id": 99', prompt_text)
        self.assertNotIn('"created_by"', prompt_text)
        self.assertIn('"url": "example.com/customers/123"', prompt_text)
        self.assertIn('"page_title": "Customer 123 - Usage"', prompt_text)

    def test_generate_page_naming_rules_preserves_page_group_short_name_from_ai_response(self):
        TitlePrompt.objects.create(
            name='title_prompt_config',
            hourly_unstable_prompt='Observed:\n{{OBSERVED_PAGES}}',
            hourly_unstable_openai_model='gpt-5.4-mini',
            daily_stable_openai_model='gpt-5.4-mini',
        )
        project = SimpleNamespace(name='Alpha')
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=(
                            '{"rules": ['
                            '{"pattern": "^example\\\\.com/settings/billing$", '
                            '"page_group": "Settings", '
                            '"page_group_short_name": "Settings", '
                            '"page_name": "Billing settings", '
                            '"priority": 220}'
                            ']}'
                        ),
                    )
                )
            ]
        )

        with patch('apps.tracker.page_naming.openai.OpenAI', return_value=fake_client):
            result = generate_page_naming_rules(
                project=project,
                mode='hourly_unstable',
                urls=['https://example.com/settings/billing'],
            )

        self.assertEqual(
            result['rules'],
            [
                {
                    'pattern': r'^example\.com/settings/billing$',
                    'page_group': 'Settings',
                    'page_group_short_name': 'Settings',
                    'area_role': 'unknown',
                    'is_adoption_recommendable': False,
                    'page_name': 'Billing settings',
                    'priority': 220,
                }
            ],
        )

    def test_generate_page_naming_rules_logs_llm_usage_on_success(self):
        TitlePrompt.objects.create(
            name='title_prompt_config',
            hourly_unstable_prompt='Observed:\n{{OBSERVED_PAGES}}',
            hourly_unstable_openai_model='gpt-5.4-mini',
            daily_stable_openai_model='gpt-5.4-mini',
        )
        project = SimpleNamespace(name='Alpha')
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=(
                            '{"rules": ['
                            '{"pattern": "^example\\\\.com/settings/billing$", '
                            '"page_group": "Settings", '
                            '"page_group_short_name": "Settings", '
                            '"page_name": "Billing settings", '
                            '"priority": 220}'
                            ']}'
                        ),
                    )
                )
            ]
        )

        with (
            patch('apps.tracker.page_naming.openai.OpenAI', return_value=fake_client),
            patch('apps.tracker.page_naming.time.perf_counter', side_effect=[1.0, 1.125]),
            self.assertLogs('llm_usage', level='INFO') as captured_logs,
        ):
            generate_page_naming_rules(
                project=project,
                mode='hourly_unstable',
                urls=['https://example.com/settings/billing'],
            )

        log_line = captured_logs.output[0]
        self.assertIn('result=ok', log_line)
        self.assertIn('duration_ms=125', log_line)
        self.assertIn("input20='Observed: [{", log_line)
        self.assertIn("output20='{\"rules\": [{", log_line)

    def test_generate_page_naming_rules_logs_llm_usage_on_error(self):
        TitlePrompt.objects.create(
            name='title_prompt_config',
            hourly_unstable_prompt='Observed:\n{{OBSERVED_PAGES}}',
            hourly_unstable_openai_model='gpt-5.4-mini',
            daily_stable_openai_model='gpt-5.4-mini',
        )
        project = SimpleNamespace(name='Alpha')
        fake_client = MagicMock()
        fake_client.chat.completions.create.side_effect = RuntimeError('upstream unavailable')

        with (
            patch('apps.tracker.page_naming.openai.OpenAI', return_value=fake_client),
            patch('apps.tracker.page_naming.time.perf_counter', side_effect=[1.0, 1.003]),
            self.assertLogs('llm_usage', level='ERROR') as captured_logs,
            self.assertRaises(RuntimeError),
        ):
            generate_page_naming_rules(
                project=project,
                mode='hourly_unstable',
                urls=['https://example.com/settings/billing'],
            )

        log_line = captured_logs.output[0]
        self.assertIn('result=error', log_line)
        self.assertIn('duration_ms=3', log_line)
        self.assertIn("input20='Observed: [{", log_line)
        self.assertIn("output20='upstream unavailable'", log_line)

    def test_prompt_renders_user_modification_request_placeholder(self):
        TitlePrompt.objects.create(
            name='title_prompt_config',
            hourly_unstable_prompt='Guidance:\n{{USER_MODIFICATION_REQUEST_OR_EMPTY}}\nObserved:\n{{OBSERVED_PAGES}}',
            hourly_unstable_openai_model='gpt-5.4-mini',
            daily_stable_openai_model='gpt-5.4-mini',
        )
        project = SimpleNamespace(
            name='Alpha',
            page_structure_guidance='Split dashboard pages from detail pages.',
        )

        prompt_text, _, _ = _build_prompt(
            mode='hourly_unstable',
            project=project,
            urls=['https://example.com/dashboard'],
        )

        self.assertIn('Split dashboard pages from detail pages.', prompt_text)
        self.assertIn('"url": "example.com/dashboard"', prompt_text)


    def test_page_naming_prompt_uses_unicode_ellipsis_for_long_urls(self):
        TitlePrompt.objects.create(
            name='title_prompt_config',
            hourly_unstable_prompt='Observed:\n{{OBSERVED_PAGES}}',
            hourly_unstable_openai_model='gpt-5.4-mini',
            daily_stable_openai_model='gpt-5.4-mini',
        )
        project = SimpleNamespace(name='Alpha')
        long_url = 'https://example.com/' + ('nested-path-segment-' * 10)

        prompt_text, _, _ = _build_prompt(
            mode='hourly_unstable',
            project=project,
            urls=[long_url],
        )

        self.assertIn(f'"url": "example.com/{("nested-path-segment-" * 10)[:138]}…"', prompt_text)
        self.assertNotIn('..."', prompt_text)

    def test_hourly_unstable_prompt_uses_its_own_openai_model(self):
        TitlePrompt.objects.create(
            name='title_prompt_config',
            hourly_unstable_prompt='Current:\n{{CURRENT_STRUCTURE_JSON_OR_EMPTY_ARRAY}}\nObserved:\n{{OBSERVED_PAGES}}',
            hourly_unstable_openai_model='gpt-4.1-mini',
            daily_stable_openai_model='gpt-5.4-mini',
        )
        project = SimpleNamespace(name='Alpha')
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"rules": []}'))]
        )

        with patch('apps.tracker.page_naming.openai.OpenAI', return_value=fake_client):
            generate_page_naming_rules(
                project=project,
                mode='hourly_unstable',
                urls=['https://example.com/customers/123'],
            )

        _, kwargs = fake_client.chat.completions.create.call_args
        self.assertEqual(kwargs['model'], 'gpt-4.1-mini')

    def test_bootstrap_prompt_uses_its_own_openai_model(self):
        TitlePrompt.objects.create(
            name='title_prompt_config',
            bootstrap_page_naming_prompt='Bootstrap:\n{{OBSERVED_PAGES}}',
            bootstrap_page_naming_openai_model='gpt-5.4',
            hourly_unstable_prompt='Current:\n{{CURRENT_STRUCTURE_JSON_OR_EMPTY_ARRAY}}\nObserved:\n{{OBSERVED_PAGES}}',
            hourly_unstable_openai_model='gpt-4.1-mini',
            daily_stable_openai_model='gpt-5.4-mini',
        )
        project = SimpleNamespace(name='Alpha')
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"rules": []}'))]
        )

        with patch('apps.tracker.page_naming.openai.OpenAI', return_value=fake_client):
            generate_page_naming_rules(
                project=project,
                mode='hourly_unstable',
                phase=ProjectPageNamingPhase.BOOTSTRAP,
                urls=['https://example.com/customers/123'],
            )

        _, kwargs = fake_client.chat.completions.create.call_args
        self.assertEqual(kwargs['model'], 'gpt-5.4')

    def test_daily_stable_prompt_uses_its_own_openai_model(self):
        TitlePrompt.objects.create(
            name='title_prompt_config',
            hourly_unstable_openai_model='gpt-5.4-mini',
            daily_stable_prompt='Current:\n{{CURRENT_STRUCTURE_JSON}}\nObserved:\n{{OBSERVED_PAGES_JSON}}',
            daily_stable_openai_model='gpt-4.1',
        )
        project = SimpleNamespace(name='Alpha')
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"rules": []}'))]
        )

        with patch('apps.tracker.page_naming.openai.OpenAI', return_value=fake_client):
            generate_page_naming_rules(
                project=project,
                mode='daily_stable',
                urls=['https://example.com/customers/123'],
                existing_rules=[],
            )

        _, kwargs = fake_client.chat.completions.create.call_args
        self.assertEqual(kwargs['model'], 'gpt-4.1')

    def test_page_naming_raises_when_legacy_prompt_model_is_empty(self):
        prompt = TitlePrompt.objects.create(
            name='title_prompt_config',
            hourly_unstable_openai_model='gpt-5.4-mini',
            daily_stable_prompt='Current:\n{{CURRENT_STRUCTURE_JSON}}\nObserved:\n{{OBSERVED_PAGES_JSON}}',
            daily_stable_openai_model='gpt-4.1',
        )
        TitlePrompt.objects.filter(pk=prompt.pk).update(daily_stable_openai_model='')
        project = SimpleNamespace(name='Alpha')

        with self.assertRaises(RuntimeError) as exc:
            generate_page_naming_rules(
                project=project,
                mode='daily_stable',
                urls=['https://example.com/customers/123'],
                existing_rules=[],
            )

        self.assertEqual(
            str(exc.exception),
            'TitlePrompt.daily_stable_openai_model is empty',
        )
