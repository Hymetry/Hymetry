"""
Equivalence tests for the precomputed benchmark series.

`_benchmark_metric_series` builds one company's benchmark by re-scanning and
re-sorting every peer's series. The index-backed path computes the sorted peer
values once for the whole pool and removes the excluded company's contribution.
The original is kept as the oracle and both are compared point by point.
"""

import random

from django.test import SimpleTestCase

from apps.pages.company_detail_analytics import (
    _benchmark_metric_series,
    _benchmark_metric_series_from_index,
    _benchmark_series_index,
)

KEY = 'engaged'


def _pool(company_ids):
    return [{'id': company_id} for company_id in company_ids]


def _daily(series_by_company):
    return {
        company_id: {KEY: series}
        for company_id, series in series_by_company.items()
    }


def _oracle(pool, daily_by_company, exclude_company_id):
    """What the pre-change code produced for one company."""

    return _benchmark_metric_series(
        [peer for peer in pool if str(peer['id']) != str(exclude_company_id)],
        daily_by_company,
        KEY,
    )


def _optimised(pool, daily_by_company, exclude_company_id):
    index = _benchmark_series_index(pool, daily_by_company, KEY)
    return _benchmark_metric_series_from_index(index, exclude_company_id)


class BenchmarkSeriesEquivalenceTests(SimpleTestCase):
    def assert_matches_oracle(self, pool, daily_by_company, *, msg=''):
        for peer in pool:
            company_id = str(peer['id'])
            with self.subTest(excluded=company_id, msg=msg):
                self.assertEqual(
                    _optimised(pool, daily_by_company, company_id),
                    _oracle(pool, daily_by_company, company_id),
                )
        # A company outside the pool removes nothing.
        with self.subTest(excluded='not-in-pool', msg=msg):
            self.assertEqual(
                _optimised(pool, daily_by_company, 'absent-company'),
                _oracle(pool, daily_by_company, 'absent-company'),
            )

    def _series(self, values, *, dates=None, prefix='d'):
        return [
            {
                'date': (dates[index] if dates else f'{prefix}{index}'),
                'value': value,
            }
            for index, value in enumerate(values)
        ]

    def test_odd_and_even_pool_sizes(self):
        # Removing one company flips the parity at every point, which is where
        # the two-middle-values averaging has to be got right.
        for size in (2, 3, 4, 5, 6, 7):
            ids = [f'c{i}' for i in range(size)]
            daily = _daily({
                company_id: self._series([index + position for position in range(5)])
                for index, company_id in enumerate(ids)
            })
            self.assert_matches_oracle(_pool(ids), daily, msg=f'size={size}')

    def test_duplicate_values(self):
        ids = ['a', 'b', 'c', 'd', 'e']
        daily = _daily({company_id: self._series([7, 7, 7, 7]) for company_id in ids})
        self.assert_matches_oracle(_pool(ids), daily)

    def test_mixed_duplicates_and_distinct_values(self):
        daily = _daily({
            'a': self._series([1, 5, 5, 9]),
            'b': self._series([1, 5, 6, 9]),
            'c': self._series([2, 5, 6, 9]),
            'd': self._series([2, 5, 7, 10]),
        })
        self.assert_matches_oracle(_pool(['a', 'b', 'c', 'd']), daily)

    def test_missing_values_within_a_series(self):
        daily = _daily({
            'a': self._series([1, None, 3, None]),
            'b': self._series([None, None, 4, 8]),
            'c': self._series([2, 6, None, 9]),
        })
        self.assert_matches_oracle(_pool(['a', 'b', 'c']), daily)

    def test_a_point_where_only_the_excluded_company_has_a_value(self):
        daily = _daily({
            'a': self._series([5, 5]),
            'b': self._series([None, 7]),
            'c': self._series([None, 9]),
        })
        self.assert_matches_oracle(_pool(['a', 'b', 'c']), daily)

    def test_unequal_length_series(self):
        daily = _daily({
            'a': self._series([1, 2, 3, 4, 5]),
            'b': self._series([2, 3]),
            'c': self._series([3, 4, 5]),
        })
        self.assert_matches_oracle(_pool(['a', 'b', 'c']), daily)

    def test_excluding_the_unique_longest_series_shortens_the_result(self):
        daily = _daily({
            'long': self._series([1, 2, 3, 4, 5]),
            'short-a': self._series([2, 3]),
            'short-b': self._series([3, 4]),
        })
        pool = _pool(['long', 'short-a', 'short-b'])

        self.assertEqual(len(_optimised(pool, daily, 'long')), 2)
        self.assertEqual(len(_optimised(pool, daily, 'short-a')), 5)
        self.assert_matches_oracle(pool, daily)

    def test_tied_longest_series_keeps_the_length(self):
        daily = _daily({
            'long-a': self._series([1, 2, 3, 4]),
            'long-b': self._series([2, 3, 4, 5]),
            'short': self._series([9]),
        })
        pool = _pool(['long-a', 'long-b', 'short'])

        self.assertEqual(len(_optimised(pool, daily, 'long-a')), 4)
        self.assert_matches_oracle(pool, daily)

    def test_dates_come_from_the_first_series_that_carries_one(self):
        # The leader supplies the date, so removing it must fall through to the
        # next series rather than emitting a blank.
        daily = _daily({
            'a': self._series([1, 2], dates=['x0', 'x1']),
            'b': self._series([3, 4], dates=['y0', 'y1']),
        })
        pool = _pool(['a', 'b'])

        self.assertEqual(
            [point['date'] for point in _optimised(pool, daily, 'a')],
            ['y0', 'y1'],
        )
        self.assert_matches_oracle(pool, daily)

    def test_blank_dates_are_skipped_in_order(self):
        daily = _daily({
            'a': self._series([1, 2], dates=['', '']),
            'b': self._series([3, 4], dates=['', 'q1']),
            'c': self._series([5, 6], dates=['r0', 'r1']),
        })
        self.assert_matches_oracle(_pool(['a', 'b', 'c']), daily)

    def test_very_small_pools(self):
        single = _daily({'only': self._series([1, 2, 3])})
        self.assertEqual(_optimised(_pool(['only']), single, 'only'), [])
        self.assert_matches_oracle(_pool(['only']), single, msg='single')

        pair = _daily({'a': self._series([1, 2]), 'b': self._series([5, 6])})
        self.assert_matches_oracle(_pool(['a', 'b']), pair, msg='pair')

    def test_empty_pool_and_empty_series(self):
        self.assertEqual(_optimised([], {}, 'a'), [])
        self.assertEqual(_optimised(_pool(['a']), _daily({'a': []}), 'a'), [])
        self.assertEqual(_oracle(_pool(['a']), _daily({'a': []}), 'a'), [])

    def test_randomised_pools_match_the_oracle(self):
        rng = random.Random(20260802)

        for case in range(400):
            size = rng.randrange(1, 9)
            ids = [f'c{i}' for i in range(size)]
            series_by_company = {}
            for company_id in ids:
                length = rng.randrange(0, 7)
                values = [
                    None if rng.random() < 0.25 else rng.randrange(0, 6)
                    for _ in range(length)
                ]
                dates = [
                    '' if rng.random() < 0.2 else f'day-{position}'
                    for position in range(length)
                ]
                series_by_company[company_id] = [
                    {'date': dates[position], 'value': values[position]}
                    for position in range(length)
                ]

            pool = _pool(ids)
            daily = _daily(series_by_company)
            index = _benchmark_series_index(pool, daily, KEY)
            for company_id in [*ids, 'absent-company']:
                with self.subTest(case=case, excluded=company_id):
                    self.assertEqual(
                        _benchmark_metric_series_from_index(index, company_id),
                        _oracle(pool, daily, company_id),
                    )
