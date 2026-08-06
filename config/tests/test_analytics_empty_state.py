from pathlib import Path

from django.template.loader import render_to_string
from django.test import SimpleTestCase


BASE_DIR = Path(__file__).resolve().parents[2]


class AnalyticsEmptyStateTests(SimpleTestCase):
    def test_preparing_state_uses_expected_copy_and_network_loader(self):
        html = render_to_string(
            'partials/analytics_empty_state.html',
            {
                'analytics_is_preparing': True,
                'analytics_surface': 'companies',
                'analytics_variant_status_url': '/analytics/status/',
            },
        )

        self.assertIn('Please wait — preparing analytics', html)
        self.assertIn(
            'This usually takes a moment. Results will appear here automatically.',
            html,
        )
        self.assertIn('aria-live="polite"', html)
        self.assertIn('data-analytics-preparing', html)
        self.assertIn('data-network-loader', html)
        self.assertIn('data-analytics-surface="companies"', html)
        self.assertIn('data-analytics-status-url="/analytics/status/"', html)
        self.assertIn('aria-hidden="true"', html)
        self.assertIn('mt-[60px]', html)
        self.assertIn('js/shared/network-loader.js?v=20260729-1', html)
        self.assertIn('js/shared/analytics-variant-polling.js', html)
        self.assertNotIn('svg/no-sessions.svg', html)
        self.assertNotIn('svg/analytics-preparing.svg', html)

    def test_no_data_state_keeps_existing_illustration(self):
        html = render_to_string(
            'partials/analytics_empty_state.html',
            {
                'analytics_is_preparing': False,
                'analytics_empty_period_days': 30,
            },
        )

        self.assertIn('No data were found in the last 30 complete days.', html)
        self.assertIn('svg/no-sessions.svg', html)
        self.assertNotIn('data-network-loader', html)
        self.assertNotIn('js/shared/network-loader.js', html)

    def test_network_loader_supports_reduced_motion_and_detached_cleanup(self):
        script = (
            BASE_DIR / 'static' / 'js' / 'shared' / 'network-loader.js'
        ).read_text(encoding='utf-8')
        styles = (
            BASE_DIR / 'frontend' / 'tailwind' / 'input.css'
        ).read_text(encoding='utf-8')

        self.assertIn('prefers-reduced-motion: reduce', script)
        self.assertIn('"change",', script)
        self.assertIn('this.applyMotionPreference()', script)
        self.assertIn('this.monitorConnection(generation)', script)
        self.assertIn('if (!this.root.isConnected)', script)
        self.assertIn('activateWaitCursor(this.root.ownerDocument)', script)
        self.assertIn('deactivateWaitCursor(this.root.ownerDocument)', script)
        self.assertIn('cursor: wait !important', styles)
        self.assertIn('@keyframes network-loader-pulse', styles)
        self.assertIn('@media (prefers-reduced-motion: reduce)', styles)
