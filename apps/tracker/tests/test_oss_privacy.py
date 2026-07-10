from django.test import SimpleTestCase

from apps.tracker.analytics_tracker import AnalyticsTracker
from apps.tracker.session_tracker import SessionTracker


class OSSURLPrivacyTests(SimpleTestCase):
    def test_recording_url_strips_query_and_fragment(self):
        tracker = object.__new__(SessionTracker)
        self.assertEqual(
            tracker.clean_url('https://app.example.test/settings?token=secret#billing'),
            'https://app.example.test/settings',
        )

    def test_analytics_raw_url_also_strips_query_and_fragment(self):
        tracker = object.__new__(AnalyticsTracker)
        self.assertEqual(
            tracker._extract_page({'url': 'https://app.example.test/users?email=user@example.test#profile'}),
            'https://app.example.test/users',
        )
