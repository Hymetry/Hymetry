from datetime import date, timedelta

from django.test import SimpleTestCase

from apps.pages.analytics_memo import analytics_memo_scope, covering_range, forget, memoized


class AnalyticsMemoScopeTests(SimpleTestCase):
    def test_lookups_fall_through_without_a_scope(self):
        calls = []

        for _ in range(3):
            memoized('facts', 1, lambda: calls.append(1))

        self.assertEqual(len(calls), 3)

    def test_scope_computes_once_and_does_not_outlive_itself(self):
        calls = []

        with analytics_memo_scope():
            for _ in range(3):
                memoized('facts', 1, lambda: calls.append(1))
        self.assertEqual(len(calls), 1)

        with analytics_memo_scope():
            memoized('facts', 1, lambda: calls.append(1))
        self.assertEqual(len(calls), 2)


class CoveringRangeTests(SimpleTestCase):
    END = date(2026, 6, 30)

    def setUp(self):
        self.loaded = []

    def _load(self, start, end):
        self.loaded.append((start, end))
        return f'facts-{start.isoformat()}..{end.isoformat()}'

    def _ago(self, days):
        return self.END - timedelta(days=days)

    def test_a_containing_load_serves_a_contained_request(self):
        with analytics_memo_scope():
            wide = covering_range('at_risk_facts', 1, self._ago(100), self.END, self._load)
            inner = covering_range('at_risk_facts', 1, self._ago(50), self._ago(20), self._load)

        self.assertIs(wide, inner)
        self.assertEqual(self.loaded, [(self._ago(100), self.END)])

    def test_a_request_reaching_earlier_is_reloaded_over_the_union(self):
        with analytics_memo_scope():
            covering_range('at_risk_facts', 1, self._ago(10), self.END, self._load)
            covering_range('at_risk_facts', 1, self._ago(100), self._ago(50), self._load)

        # The second read is not contained, so it reloads, and the new span
        # covers both so nothing after it has to load again.
        self.assertEqual(
            self.loaded,
            [(self._ago(10), self.END), (self._ago(100), self.END)],
        )

    def test_a_request_reaching_later_is_not_served_by_an_earlier_load(self):
        with analytics_memo_scope():
            covering_range('at_risk_facts', 1, self._ago(100), self._ago(50), self._load)
            covering_range('at_risk_facts', 1, self._ago(80), self.END, self._load)

        self.assertEqual(len(self.loaded), 2)
        self.assertEqual(self.loaded[1], (self._ago(100), self.END))

    def test_a_planned_span_makes_the_first_load_serve_every_later_one(self):
        planned = (self._ago(700), self.END)

        with analytics_memo_scope(floors={'at_risk_facts': planned}):
            covering_range('at_risk_facts', 1, self._ago(10), self.END, self._load)
            covering_range('at_risk_facts', 1, self._ago(700), self._ago(180), self._load)
            covering_range('at_risk_facts', 1, self._ago(360), self._ago(90), self._load)

        self.assertEqual(self.loaded, [planned])

    def test_reads_are_kept_apart_by_project(self):
        with analytics_memo_scope():
            covering_range('at_risk_facts', 1, self._ago(10), self.END, self._load)
            covering_range('at_risk_facts', 2, self._ago(10), self.END, self._load)

        self.assertEqual(len(self.loaded), 2)

    def test_producer_receives_the_span_actually_loaded(self):
        planned = (self._ago(700), self.END)

        with analytics_memo_scope(floors={'at_risk_facts': planned}):
            value = covering_range('at_risk_facts', 1, self._ago(10), self.END, self._load)

        self.assertEqual(
            value,
            f'facts-{self._ago(700).isoformat()}..{self.END.isoformat()}',
        )


class ForgetTests(SimpleTestCase):
    def test_forget_drops_one_namespace_and_keeps_the_others(self):
        calls = {'kept': 0, 'dropped': 0}

        with analytics_memo_scope():
            memoized('kept', 1, lambda: calls.__setitem__('kept', calls['kept'] + 1))
            memoized('dropped', 1, lambda: calls.__setitem__('dropped', calls['dropped'] + 1))

            forget('dropped')

            memoized('kept', 1, lambda: calls.__setitem__('kept', calls['kept'] + 1))
            memoized('dropped', 1, lambda: calls.__setitem__('dropped', calls['dropped'] + 1))

        self.assertEqual(calls['kept'], 1)
        self.assertEqual(calls['dropped'], 2)

    def test_forget_outside_a_scope_is_a_no_op(self):
        forget('anything')
