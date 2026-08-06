from types import SimpleNamespace
from unittest.mock import patch

from django.http import QueryDict
from django.test import SimpleTestCase

from apps.projects.views import (
    _company_selector_rows,
    _detail_fallback_url,
    _first_project_user_id,
    _is_detail_route_placeholder,
    _user_selector_rows,
)


class UserSelectorRowsTests(SimpleTestCase):
    def test_alphabetical_fallback_ignores_recent_activity_order(self):
        users = [
            {'id': 'zoe', 'name': 'Zoe', 'companyName': 'Acme', 'lastActiveSort': 1},
            {'id': 'amy', 'name': 'Amy', 'companyName': 'Zenith', 'lastActiveSort': 99},
        ]

        rows, total = _user_selector_rows(users, '', 20, alphabetical=True)

        self.assertEqual(total, 2)
        self.assertEqual([row['id'] for row in rows], ['amy', 'zoe'])

    def test_default_selector_order_remains_activity_based(self):
        users = [
            {'id': 'amy', 'name': 'Amy', 'lastActiveSort': 99},
            {'id': 'zoe', 'name': 'Zoe', 'lastActiveSort': 1},
        ]

        rows, _ = _user_selector_rows(users, '', 20)

        self.assertEqual([row['id'] for row in rows], ['zoe', 'amy'])

    @patch('apps.projects.views.user_analytics.is_current_users_payload_schema', return_value=True)
    @patch('apps.projects.views.user_analytics.get_cached_users_overview_payload')
    def test_fallback_user_comes_from_requested_project_and_range(self, get_cache, _schema):
        get_cache.return_value = {
            'schema_version': 1,
            'payload_json': {'users': [
                {'id': 'zoe', 'name': 'Zoe'},
                {'id': 'amy', 'name': 'Amy'},
            ]},
        }

        result = _first_project_user_id(SimpleNamespace(id=67007532), 'last_30_days')

        self.assertEqual(result, 'amy')
        get_cache.assert_called_once_with(67007532, range_key='last_30_days')

    def test_detail_fallback_preserves_range_and_encodes_identifier(self):
        request = SimpleNamespace(GET=QueryDict('range=last_30_days&user_id=missing'))

        result = _detail_fallback_url('/w/test/projects/7/users/detail/', 'amy@example.com', request)

        self.assertEqual(result, '/w/test/projects/7/users/amy%40example.com/?range=last_30_days')

    def test_company_fallback_can_be_sorted_alphabetically(self):
        companies = [
            {'id': 'z', 'name': 'Zeta', 'lastSeenDays': 1},
            {'id': 'a', 'name': 'Acme', 'lastSeenDays': 20},
        ]

        rows, total = _company_selector_rows(companies, '', 20, alphabetical=True)

        self.assertEqual(total, 2)
        self.assertEqual([row['id'] for row in rows], ['a', 'z'])

    def test_literal_company_id_is_not_treated_as_route_placeholder(self):
        self.assertFalse(_is_detail_route_placeholder('COMPANY_ID'))
        self.assertTrue(_is_detail_route_placeholder('detail'))
