from io import StringIO
from unittest.mock import call, patch

from django.core.management import call_command
from django.test import SimpleTestCase

from apps.pages.services import DEFAULT_OVERVIEW_RANGE_KEYS


class RebuildPagesOverviewCacheCommandTests(SimpleTestCase):
    @patch('apps.pages.management.commands.rebuild_pages_overview_cache.build_pages_overview_cache')
    def test_all_ranges_rebuilds_default_ranges(self, mock_build_pages_overview_cache):
        mock_build_pages_overview_cache.side_effect = (
            lambda project_id, **kwargs: {
                'status': 'success',
                'project_id': project_id,
                'range_key': kwargs['range_key'],
            }
        )

        output = StringIO()

        call_command(
            'rebuild_pages_overview_cache',
            project_id=33333333,
            all_ranges=True,
            stdout=output,
        )

        self.assertEqual(
            mock_build_pages_overview_cache.call_args_list,
            [
                call(
                    33333333,
                    range_key=range_key,
                    start_date=None,
                    end_date=None,
                )
                for range_key in DEFAULT_OVERVIEW_RANGE_KEYS
            ],
        )
        self.assertIn('Pages overview caches rebuilt', output.getvalue())

    @patch('apps.pages.management.commands.rebuild_pages_overview_cache.build_pages_overview_cache')
    def test_single_range_still_rebuilds_one_range(self, mock_build_pages_overview_cache):
        mock_build_pages_overview_cache.return_value = {
            'status': 'success',
            'project_id': 33333333,
            'range_key': 'last_90_days',
        }
        output = StringIO()

        call_command(
            'rebuild_pages_overview_cache',
            project_id=33333333,
            range_key='last_90_days',
            stdout=output,
        )

        mock_build_pages_overview_cache.assert_called_once_with(
            33333333,
            range_key='last_90_days',
            start_date=None,
            end_date=None,
        )
