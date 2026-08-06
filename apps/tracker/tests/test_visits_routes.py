import uuid

from django.test import SimpleTestCase
from django.urls import NoReverseMatch, reverse


class VisitsRouteTests(SimpleTestCase):
    def test_canonical_visit_list_urls_are_available_and_legacy_names_are_removed(self):
        self.assertEqual(
            reverse('recordings', kwargs={'project_id': 42}),
            '/projects/42/visits',
        )
        self.assertEqual(
            reverse('visits_filter_options', kwargs={'project_id': 42}),
            '/projects/42/visits/filter-options',
        )
        self.assertEqual(
            reverse(
                'w:recordings',
                kwargs={'workspace_slug': 'acme', 'project_id': 42},
            ),
            '/w/acme/projects/42/visits',
        )
        self.assertEqual(
            reverse(
                'w:visits_filter_options',
                kwargs={'workspace_slug': 'acme', 'project_id': 42},
            ),
            '/w/acme/projects/42/visits/filter-options',
        )
        with self.assertRaises(NoReverseMatch):
            reverse('legacy_recordings', kwargs={'project_id': 42})
        with self.assertRaises(NoReverseMatch):
            reverse(
                'w:legacy_recordings',
                kwargs={'workspace_slug': 'acme', 'project_id': 42},
            )

    def test_replay_and_data_urls_keep_the_recording_session_uuid(self):
        session_id = uuid.UUID('11111111-1111-4111-8111-111111111111')

        self.assertEqual(
            reverse('recording', kwargs={'project_id': 42, 'session_id': session_id}),
            f'/projects/42/visits/{session_id}',
        )
        self.assertEqual(
            reverse(
                'w:recording',
                kwargs={
                    'workspace_slug': 'acme',
                    'project_id': 42,
                    'session_id': session_id,
                },
            ),
            f'/w/acme/projects/42/visits/{session_id}',
        )
        self.assertEqual(
            reverse(
                'w:replay_stream',
                kwargs={
                    'workspace_slug': 'acme',
                    'project_id': 42,
                    'session_id': session_id,
                },
            ),
            f'/w/acme/projects/42/visits/{session_id}/stream',
        )
