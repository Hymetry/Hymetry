import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from apps.pages import user_analytics
from apps.projects import views as project_views


class UsersOverviewPayloadTests(SimpleTestCase):
    @staticmethod
    def _user(index):
        return {
            'id': f'user-{index}',
            'userId': f'user-{index}',
            'name': f'User {index}',
            'email': f'user-{index}@example.com',
            'company': 'Acme Corp',
            'status': 'Healthy',
            'identified': True,
            'engagedSeconds': 120,
            'visitsCount': 7,
            'sessionsCount': 2,
            'pageGroups': [{
                'key': 'core',
                'name': 'Core product',
                'productArea': 'Core product',
                'productAreaId': 'core',
                'color': '#4269d0',
                'productAreaColor': '#4269d0',
                'product_area_color': '#4269d0',
                'engagedSeconds': 120,
                'visits': 7,
                'clicks': 3,
            }],
            'topFeatures': [{
                'feature': 'Dashboard',
                'productArea': 'Core product',
                'engagedSeconds': 120,
                'visits': 7,
                'clicks': 3,
            }],
        }

    def test_initial_payload_keeps_the_complete_compact_scatter(self):
        users = [self._user(index) for index in range(user_analytics.SCATTER_VISIBLE_LIMIT + 5)]
        sampled_users = list(reversed(users))[:user_analytics.SCATTER_VISIBLE_LIMIT]
        table_rows = users[:user_analytics.USERS_TABLE_PAGE_SIZE]
        table_payload = {
            'rows': table_rows,
            'pagination': {
                'page': 1,
                'pageSize': user_analytics.USERS_TABLE_PAGE_SIZE,
                'totalRows': len(users),
                'totalPages': 16,
                'sortKey': 'engagedSeconds',
                'sortDirection': 'desc',
            },
            'filterOptions': {
                'companies': ['Acme Corp'],
                'roles': [],
                'statuses': ['Healthy'],
            },
        }
        result = user_analytics.initial_users_overview_payload({
            'schema_version': user_analytics.USERS_PAYLOAD_SCHEMA_VERSION,
            'scatter': sampled_users,
            'scatterMeta': {'totalUsers': len(users)},
        }, table_payload=table_payload)

        self.assertEqual(result['users'], table_rows)
        self.assertEqual(len(result['scatter']), user_analytics.SCATTER_VISIBLE_LIMIT)
        self.assertEqual(result['users'][0]['id'], users[0]['id'])
        self.assertEqual(result['tableData']['users'], table_payload)
        self.assertEqual(result['usersDeferred']['initialScatter'], user_analytics.SCATTER_VISIBLE_LIMIT)
        self.assertEqual(result['usersDeferred']['sampledUsers'], user_analytics.SCATTER_VISIBLE_LIMIT)
        self.assertEqual(result['usersDeferred']['totalUsers'], len(users))
        self.assertFalse(result['usersDeferred']['isPartial'])
        self.assertNotIn('email', result['scatter'][0])
        self.assertNotIn('productAreaColor', result['scatter'][0]['pageGroups'][0])
        self.assertEqual(
            result['scatter'][0]['pageGroups'][0],
            {
                'name': 'Core product',
                'color': '#4269d0',
                'engagedSeconds': 120,
                'visits': 7,
                'clicks': 3,
            },
        )

    def test_deferred_payload_is_compact_chart_bootstrap_only(self):
        users = [self._user(index) for index in range(user_analytics.SCATTER_VISIBLE_LIMIT + 5)]
        sampled_users = list(reversed(users))[:user_analytics.SCATTER_VISIBLE_LIMIT]
        result = user_analytics.deferred_users_overview_payload({
            'schema_version': user_analytics.USERS_PAYLOAD_SCHEMA_VERSION,
            'period': {'days': 180},
            'users': users,
            'scatter': sampled_users,
            'scatterMeta': {'totalUsers': len(users)},
        })

        self.assertNotIn('users', result)
        self.assertEqual(len(result['scatter']), user_analytics.SCATTER_VISIBLE_LIMIT)
        self.assertNotIn('email', result['scatter'][0])
        self.assertFalse(result['usersDeferred']['isPartial'])
        self.assertEqual(result['usersDeferred']['sampledUsers'], user_analytics.SCATTER_VISIBLE_LIMIT)
        self.assertEqual(result['usersDeferred']['totalUsers'], len(users))

    def test_random_sample_keeps_all_users_at_or_below_the_limit(self):
        for count in (user_analytics.SCATTER_VISIBLE_LIMIT - 1, user_analytics.SCATTER_VISIBLE_LIMIT):
            with self.subTest(count=count):
                users = [self._user(index) for index in range(count)]

                self.assertEqual(user_analytics._random_scatter_sample(users, 300, 'sample'), users)

    def test_random_sample_is_stable_and_capped_above_the_limit(self):
        users = [self._user(index) for index in range(user_analytics.SCATTER_VISIBLE_LIMIT + 1)]

        first = user_analytics._random_scatter_sample(users, user_analytics.SCATTER_VISIBLE_LIMIT, 'sample')
        second = user_analytics._random_scatter_sample(users, user_analytics.SCATTER_VISIBLE_LIMIT, 'sample')

        self.assertEqual(len(first), user_analytics.SCATTER_VISIBLE_LIMIT)
        self.assertEqual(first, second)
        self.assertEqual(len({row['id'] for row in first}), user_analytics.SCATTER_VISIBLE_LIMIT)
        self.assertNotEqual(first, users[:user_analytics.SCATTER_VISIBLE_LIMIT])

    @patch('apps.pages.user_analytics.queries.fetch_one')
    def test_client_cache_fetch_excludes_the_full_users_array(self, fetch_one):
        self.assertIn("payload_json - 'users'", user_analytics.queries.FETCH_USERS_OVERVIEW_CLIENT_CACHE_SQL)
        fetch_one.return_value = {
            'payload_json_text': json.dumps({
                'schema_version': user_analytics.USERS_PAYLOAD_SCHEMA_VERSION,
                'scatter': [self._user(1)],
            }),
        }

        result = user_analytics.get_cached_users_overview_client_payload(42, range_key='last_180_days')

        self.assertEqual(result['payload_json']['scatter'][0]['id'], 'user-1')
        self.assertEqual(
            result['schema_version'],
            user_analytics.USERS_PAYLOAD_SCHEMA_VERSION,
        )
        fetch_one.assert_called_once_with(
            user_analytics.queries.FETCH_USERS_OVERVIEW_CLIENT_CACHE_SQL,
            [42, 'last_180_days', 'default'],
        )

    @patch('apps.pages.user_analytics.queries.fetch_one')
    def test_table_page_query_passes_filters_and_returns_small_contract(self, fetch_one):
        fetch_one.return_value = {
            'rows': '[{"id":"user-21"}]',
            'page': 2,
            'page_size': 100,
            'total_rows': 121,
            'total_pages': 2,
            'filter_options': '{"companies":["Acme Corp"],"roles":["Admin"],"statuses":["Healthy"]}',
            'schema_version': str(user_analytics.USERS_PAYLOAD_SCHEMA_VERSION),
        }

        result = user_analytics.get_cached_users_overview_table_page(
            42,
            range_key='last_180_days',
            page='2',
            page_size='500',
            sort_key='name',
            sort_direction='asc',
            company='Acme Corp',
            status='Healthy',
            query='ADA',
            role='Admin',
            identified_only=False,
            feature='Dashboard',
        )

        self.assertEqual(result['rows'], [{'id': 'user-21'}])
        self.assertEqual(result['pagination'], {
            'page': 2,
            'pageSize': 100,
            'totalRows': 121,
            'totalPages': 2,
            'sortKey': 'name',
            'sortDirection': 'asc',
        })
        self.assertEqual(result['filterOptions']['companies'], ['Acme Corp'])

        sql, params = fetch_one.call_args.args
        self.assertIn("LOWER(COALESCE(user_row ->> 'name', '')) ASC", sql)
        self.assertNotIn('user-21', sql)
        self.assertEqual(params[:3], [42, 'last_180_days', 'default'])
        self.assertEqual(params[3:12], [
            'Acme Corp',
            'Acme Corp',
            'Healthy',
            'Healthy',
            'Admin',
            'Admin',
            'ada',
            'ada',
            False,
        ])
        self.assertEqual(params[12:16], ['Dashboard'] * 4)
        self.assertEqual(params[-2:], [2, user_analytics.USERS_TABLE_MAX_PAGE_SIZE])

    @patch('apps.pages.user_analytics.queries.fetch_one')
    def test_table_page_query_rejects_unknown_sort_and_direction(self, fetch_one):
        fetch_one.return_value = {
            'rows': [],
            'page': 1,
            'page_size': user_analytics.USERS_TABLE_PAGE_SIZE,
            'total_rows': 0,
            'total_pages': 1,
            'filter_options': {},
        }

        result = user_analytics.get_cached_users_overview_table_page(
            42,
            sort_key="name; DROP TABLE users;--",
            sort_direction='sideways',
        )

        sql = fetch_one.call_args.args[0]
        self.assertNotIn('DROP TABLE', sql)
        self.assertEqual(result['pagination']['sortKey'], user_analytics.USERS_TABLE_DEFAULT_SORT_KEY)
        self.assertEqual(result['pagination']['sortDirection'], user_analytics.USERS_TABLE_DEFAULT_SORT_DIRECTION)


class UsersCalloutRowLimitTests(SimpleTestCase):
    """The attention and momentum sections are bounded triage lists.

    Most users in an active project trip at least one attention rule, so an
    unbounded list would put thousands of rows in the payload and hundreds of
    pages behind a section meant to be read top-down. The Users table is where
    the complete set lives.
    """

    def test_attention_rows_stop_at_the_limit_and_keep_the_riskiest(self):
        users = [
            {
                'id': f'u{index}',
                'userId': f'u{index}',
                'name': f'User {index:03d}',
                'status': 'Dropped',
                # Higher index means longer inactive, which scores higher.
                'lastActiveSort': 7 + index,
            }
            for index in range(120)
        ]

        rows = user_analytics._attention_rows(users, {})
        with patch.object(user_analytics, 'ATTENTION_ROWS_LIMIT', 10_000):
            everyone = user_analytics._attention_rows(users, {})

        self.assertEqual(len(rows), user_analytics.ATTENTION_ROWS_LIMIT)
        self.assertEqual(len(rows), 50)
        self.assertGreater(len(everyone), len(rows))
        scores = [row['riskScore'] for row in rows]
        self.assertEqual(scores, sorted(scores, reverse=True))
        # The cut is the head of the ranking, not a slice of the input order.
        self.assertEqual([row['name'] for row in rows], [row['name'] for row in everyone[:50]])

    def test_momentum_rows_stop_at_the_limit_and_keep_the_strongest(self):
        users = [
            {
                'id': f'u{index}',
                'userId': f'u{index}',
                'name': f'User {index:03d}',
                'status': 'Healthy',
                'engagedDeltaPct': 25 + index,
                'engagedSeconds': 600,
                'visitsCount': 10,
            }
            for index in range(120)
        ]

        rows = user_analytics._momentum_rows(users, {})
        with patch.object(user_analytics, 'MOMENTUM_ROWS_LIMIT', 10_000):
            everyone = user_analytics._momentum_rows(users, {})

        self.assertEqual(len(rows), user_analytics.MOMENTUM_ROWS_LIMIT)
        self.assertGreater(len(everyone), len(rows))
        scores = [row['momentumScore'] for row in rows]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual([row['name'] for row in rows], [row['name'] for row in everyone[:50]])


class UsersOverviewTableViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.project = SimpleNamespace(id=42)

    @patch('apps.projects.views.user_analytics.get_cached_users_overview_table_page')
    def test_table_response_forwards_supported_filters_and_pagination(self, get_table_page):
        get_table_page.return_value = {
            'rows': [{'id': 'user-21'}],
            'pagination': {
                'page': 2,
                'pageSize': 20,
                'totalRows': 21,
                'totalPages': 2,
                'sortKey': 'company',
                'sortDirection': 'asc',
            },
            'filterOptions': {
                'companies': ['Acme Corp'],
                'roles': ['Admin'],
                'statuses': ['Healthy'],
            },
        }
        request = self.factory.get('/users/table-data/', {
            'range': 'last_180_days',
            'page': '2',
            'page_size': '20',
            'sort': 'company',
            'direction': 'asc',
            'company': 'Acme Corp',
            'status': 'Healthy',
            'q': 'ada',
            'role': 'Admin',
            'identified': 'false',
            'feature': 'Dashboard',
        })

        response = project_views._users_overview_table_response(request, self.project)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['table'], 'users')
        self.assertEqual(payload['rows'], [{'id': 'user-21'}])
        get_table_page.assert_called_once_with(
            42,
            range_key='last_180_days',
            filters_hash='default',
            page='2',
            page_size='20',
            sort_key='company',
            sort_direction='asc',
            company='Acme Corp',
            status='Healthy',
            query='ada',
            role='Admin',
            identified_only=False,
            feature='Dashboard',
        )

    @patch('apps.projects.views.user_analytics.get_cached_users_overview_table_page', return_value=None)
    def test_table_response_is_pending_when_cache_is_missing(self, _get_table_page):
        response = project_views._users_overview_table_response(
            self.factory.get('/users/table-data/'),
            self.project,
        )
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 202)
        self.assertTrue(payload['pending'])
        self.assertEqual(payload['table'], 'users')
        self.assertEqual(payload['pagination']['pageSize'], user_analytics.USERS_TABLE_PAGE_SIZE)
