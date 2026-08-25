from datetime import datetime, timedelta, timezone as datetime_timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone as django_timezone

from apps.pages import filtered_overview, services


def _state(*, active=True, filters_hash='hash-1', pairs=(('ca.7.op', 'in'), ('ca.7.value', '3'))):
    return SimpleNamespace(
        active=active,
        filters_hash=filters_hash,
        canonical_pairs=tuple(pairs),
        active_count=1,
    )


RANGE_KEY = 'last_180_days'

# Every window here resolves relative to the current project-local day -- once in
# these helpers and again inside the code under test. Left to the real clock the
# two resolutions can land on either side of midnight, which made a variant built
# for "today" look like one built for another day. Pinning the clock per test
# makes them agree by construction instead of by timing, so the assertions hold
# whatever hour the suite runs at.
FROZEN_NOW = datetime(2026, 6, 15, 12, 0, tzinfo=datetime_timezone.utc)

# Sentinel for "resolve the current window", distinct from the ``None`` that
# tells ``variant_is_usable`` to skip the period check entirely.
CURRENT_WINDOW = object()


def _window(range_key=RANGE_KEY):
    """The window a request for *range_key* means under the pinned clock."""

    return services.resolve_period('UTC', range_key=range_key)


def _stale_window(range_key=RANGE_KEY):
    """The window the same request meant one day earlier."""

    return tuple(day - timedelta(days=1) for day in _window(range_key))


def _project(*, facts=5, attribute_writes=0):
    # Fact rebuilds advance both counters; attribute writes advance only the
    # filtered one, so their difference counts the attribute writes.
    return SimpleNamespace(
        id=42,
        timezone='UTC',
        analytics_facts_revision=facts,
        filtered_analytics_revision=facts + attribute_writes,
    )


def _row(*, facts=5, attribute_writes=0, schema=12, is_stale=False,
         expires_in_seconds=3600, window=CURRENT_WINDOW):
    if window is CURRENT_WINDOW:
        window = _window()
    expires_at = None
    if expires_in_seconds is not None:
        expires_at = django_timezone.now() + timedelta(seconds=expires_in_seconds)
    return {
        'schema_version': schema,
        'is_stale': is_stale,
        'expires_at': expires_at,
        'start_date': window[0],
        'end_date': window[1],
        'payload_json': {'freshness': {
            'filtered_analytics_revision': facts + attribute_writes,
            'analytics_facts_revision': facts,
        }},
    }


def _schema_ok(schema_version):
    return schema_version == 12


class PinnedClock:
    """Resolve every window in a test against one fixed instant."""

    def setUp(self):
        super().setUp()
        clock = patch('django.utils.timezone.now', return_value=FROZEN_NOW)
        clock.start()
        self.addCleanup(clock.stop)


class VariantUsabilityTests(PinnedClock, SimpleTestCase):
    def _usable(self, row, project, *, filters_hash='hash-1', period=CURRENT_WINDOW):
        if period is CURRENT_WINDOW:
            period = _window()
        return filtered_overview.variant_is_usable(
            row,
            project=project,
            filters_hash=filters_hash,
            schema_is_current=_schema_ok,
            expected_period=period,
        )

    def test_default_variant_ignores_the_revisions(self):
        self.assertTrue(self._usable(
            _row(facts=999), _project(facts=5),
            filters_hash=filtered_overview.DEFAULT_FILTERS_HASH,
        ))

    def test_a_fact_rebuild_leaves_a_variant_servable(self):
        # The hourly refresh advances both counters. The cohort is unchanged, so
        # the row is still a correct answer -- just one rebuild out of date.
        self.assertTrue(self._usable(_row(facts=5), _project(facts=6)))

    def test_a_fact_rebuild_asks_for_a_background_refresh(self):
        row = _row(facts=5)
        self.assertFalse(filtered_overview.variant_needs_refresh(row, project=_project(facts=5)))
        self.assertTrue(filtered_overview.variant_needs_refresh(row, project=_project(facts=6)))

    def test_an_attribute_write_makes_a_variant_unusable(self):
        # Only the filtered counter moved, so the stored cohort is now wrong.
        self.assertFalse(self._usable(
            _row(facts=5, attribute_writes=0),
            _project(facts=5, attribute_writes=1),
        ))

    def test_a_variant_for_another_day_is_never_served(self):
        # The whole point of the window check: an untouched old variant
        # describes a period nobody asked for.
        self.assertFalse(self._usable(_row(window=_stale_window()), _project()))

    def test_an_old_schema_is_never_usable(self):
        self.assertFalse(self._usable(_row(schema=11), _project()))

    def test_a_stale_or_expired_row_stays_usable_but_needs_refresh(self):
        for row in (_row(is_stale=True), _row(expires_in_seconds=-1)):
            self.assertTrue(self._usable(row, _project()))
            self.assertTrue(filtered_overview.variant_needs_refresh(row))

        self.assertFalse(filtered_overview.variant_needs_refresh(_row()))

    def test_period_comparison_is_skipped_when_no_window_is_supplied(self):
        self.assertTrue(filtered_overview.variant_covers_period(_row(), None))


class ReadVariantTests(PinnedClock, SimpleTestCase):
    def setUp(self):
        super().setUp()
        filtered_overview._dispatches.clear()

    @patch('apps.pages.filtered_overview.queue_variant_rebuild', return_value=True)
    def test_a_cold_filtered_variant_is_pending_and_queued(self, queue):
        cache, queued = filtered_overview.read_variant(
            filtered_overview.USERS,
            _project(),
            RANGE_KEY,
            _state(),
            fetch=lambda *args, **kwargs: None,
            schema_is_current=_schema_ok,
        )

        self.assertIsNone(cache)
        self.assertTrue(queued)
        queue.assert_called_once()

    @patch('apps.pages.filtered_overview.queue_variant_rebuild', return_value=True)
    def test_a_variant_from_a_changed_cohort_is_pending_rather_than_served(self, queue):
        cache, _queued = filtered_overview.read_variant(
            filtered_overview.USERS,
            _project(facts=5, attribute_writes=1),
            RANGE_KEY,
            _state(),
            fetch=lambda *args, **kwargs: _row(facts=5),
            schema_is_current=_schema_ok,
        )

        self.assertIsNone(cache)
        queue.assert_called_once()

    @patch('apps.pages.filtered_overview.queue_variant_rebuild', return_value=True)
    def test_a_stale_filtered_variant_is_served_while_it_rebuilds(self, queue):
        cache, _queued = filtered_overview.read_variant(
            filtered_overview.USERS,
            _project(),
            RANGE_KEY,
            _state(),
            fetch=lambda *args, **kwargs: _row(is_stale=True),
            schema_is_current=_schema_ok,
        )

        self.assertIsNotNone(cache)
        queue.assert_called_once()

    @patch('apps.pages.filtered_overview.queue_variant_rebuild', return_value=True)
    def test_a_current_filtered_variant_queues_nothing(self, queue):
        cache, queued = filtered_overview.read_variant(
            filtered_overview.USERS,
            _project(),
            RANGE_KEY,
            _state(),
            fetch=lambda *args, **kwargs: _row(),
            schema_is_current=_schema_ok,
        )

        self.assertIsNotNone(cache)
        self.assertFalse(queued)
        queue.assert_not_called()

    @patch('apps.pages.filtered_overview.queue_variant_rebuild')
    def test_the_unfiltered_path_never_queues_a_filter_variant(self, queue):
        cache, queued = filtered_overview.read_variant(
            filtered_overview.USERS,
            _project(),
            RANGE_KEY,
            _state(active=False, filters_hash=filtered_overview.DEFAULT_FILTERS_HASH),
            fetch=lambda *args, **kwargs: _row(),
            schema_is_current=_schema_ok,
        )

        self.assertIsNotNone(cache)
        self.assertFalse(queued)
        queue.assert_not_called()

    def test_gating_an_unfiltered_request_reads_nothing(self):
        def explode(*args, **kwargs):
            raise AssertionError('the unfiltered path must not read variant metadata')

        ready, queued = filtered_overview.gate_filtered_variant(
            filtered_overview.USERS,
            _project(),
            RANGE_KEY,
            _state(active=False, filters_hash=filtered_overview.DEFAULT_FILTERS_HASH),
            fetch=explode,
            schema_is_current=_schema_ok,
        )

        self.assertTrue(ready)
        self.assertFalse(queued)


class DispatchDedupTests(SimpleTestCase):
    def setUp(self):
        filtered_overview._dispatches.clear()

    @patch('apps.pages.filtered_overview._task_for_surface')
    def test_repeat_requests_for_one_variant_publish_a_single_task(self, task_for_surface):
        task = task_for_surface.return_value

        for _ in range(3):
            self.assertTrue(
                filtered_overview.queue_variant_rebuild(
                    filtered_overview.USERS, 42, 'last_180_days', _state(),
                )
            )

        task.apply_async.assert_called_once()
        kwargs = task.apply_async.call_args.kwargs['kwargs']
        self.assertEqual(kwargs['filters_hash'], 'hash-1')
        self.assertEqual(kwargs['canonical_pairs'], [['ca.7.op', 'in'], ['ca.7.value', '3']])

    @patch('apps.pages.filtered_overview._task_for_surface')
    def test_distinct_variants_are_dispatched_separately(self, task_for_surface):
        task = task_for_surface.return_value

        filtered_overview.queue_variant_rebuild(
            filtered_overview.USERS, 42, 'last_180_days', _state(filters_hash='a'),
        )
        filtered_overview.queue_variant_rebuild(
            filtered_overview.USERS, 42, 'last_180_days', _state(filters_hash='b'),
        )
        filtered_overview.queue_variant_rebuild(
            filtered_overview.PAGES, 42, 'last_180_days', _state(filters_hash='a'),
        )

        self.assertEqual(task.apply_async.call_count, 3)

    @patch('apps.pages.filtered_overview._task_for_surface')
    def test_a_failed_publication_releases_its_dedup_slot(self, task_for_surface):
        task_for_surface.return_value.apply_async.side_effect = RuntimeError('broker down')

        with self.assertLogs('apps.pages.filtered_overview', level='ERROR'):
            self.assertFalse(
                filtered_overview.queue_variant_rebuild(
                    filtered_overview.USERS, 42, 'last_180_days', _state(),
                )
            )

        self.assertEqual(filtered_overview._dispatches, {})

    def test_queueing_rejects_an_inactive_state(self):
        with self.assertRaises(ValueError):
            filtered_overview.queue_variant_rebuild(
                filtered_overview.USERS,
                42,
                'last_180_days',
                _state(active=False),
            )


class BuildVariantTests(SimpleTestCase):
    @patch('apps.pages.filtered_overview.Project.active.filter')
    def test_a_missing_project_is_skipped(self, project_filter):
        project_filter.return_value = SimpleNamespace(first=lambda: None)

        result = filtered_overview.build_variant(
            filtered_overview.USERS, 42, [], 'hash-1', 'last_180_days',
        )

        self.assertEqual(result['status'], 'skipped')
        self.assertEqual(result['reason'], 'missing_project')

    def test_an_unknown_surface_is_rejected(self):
        with self.assertRaises(ValueError):
            filtered_overview.build_variant(
                'sessions', 42, [], 'hash-1', 'last_180_days',
            )

    @patch('apps.pages.filtered_overview.parse_company_attribute_filters')
    @patch('apps.pages.filtered_overview.Project.active.filter')
    def test_malformed_canonical_pairs_are_rejected(self, project_filter, parse_filters):
        project_filter.return_value = SimpleNamespace(first=lambda: _project())

        result = filtered_overview.build_variant(
            filtered_overview.USERS,
            42,
            [['only-one-element']],
            'hash-1',
            'last_180_days',
        )

        self.assertEqual(result['status'], 'skipped')
        self.assertEqual(result['reason'], 'invalid_filters')
        parse_filters.assert_not_called()
