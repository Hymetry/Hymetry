"""
Run-scoped memoization for repeated analytics fact reads.

A full cache rebuild walks several ranges through the same builders, and some
of the facts those builders read do not vary with the range at all. Others vary
only in how far back they reach, so the widest range's read already contains
every narrower one's.

The memo is opt-in: outside :func:`analytics_memo_scope` every lookup falls
through to its producer, so request-time builders keep their current behavior
and nothing is held past the call that asked for it.

Only derived facts that callers treat as read-only belong here. Anything a
caller mutates in place must stay uncached, because the second reader would
otherwise observe the first reader's edits.
"""

from contextlib import contextmanager
from contextvars import ContextVar

from apps.projects.company_attribute_filters import current_company_attribute_filter_state

_MISSING = object()

_memo: ContextVar[dict | None] = ContextVar('pages_analytics_memo', default=None)


@contextmanager
def analytics_memo_scope(floors=None):
    """
    Share repeated fact reads across the builders running inside the block.

    *floors* declares, as ``{namespace: (start, end)}``, the span the reads in
    this scope will collectively cover. A caller that knows its whole plan up
    front can use it to make the first read cover the rest, which otherwise
    cannot happen when the reads arrive narrowest first and each one only
    widens the last.

    Declare the union of what will actually be asked for. The span is loaded in
    full on the first read, so padding it reads rows nothing goes on to use.
    """

    token = _memo.set({'values': {}, 'floors': dict(floors or {})})
    try:
        yield
    finally:
        _memo.reset(token)


def _filter_scope_key():
    """
    Identify the company-attribute filter the enclosing scope applies.

    Cached helpers read through ``narrow_queryset_to_current_company_filters``,
    so a memo shared across two different filter states would serve one state's
    rows to the other. The resolved cohort is a function of the project and the
    filter state, and the project is already part of every caller's key, so the
    filters hash alone separates them.
    """

    state = current_company_attribute_filter_state()
    if state is None or not state.active:
        return None
    return state.filters_hash


def memoized(namespace, key, producer):
    """Return ``producer()``, reusing a value already computed in this scope."""

    store = _memo.get()
    if store is None:
        return producer()

    values = store['values']
    memo_key = (namespace, _filter_scope_key(), key)
    value = values.get(memo_key, _MISSING)
    if value is _MISSING:
        value = producer()
        values[memo_key] = value
    return value


def forget(namespace):
    """
    Drop everything held under *namespace*, keeping the rest of the scope.

    For values that only serve one stage of a longer run. Holding them for the
    whole scope costs memory proportional to the stages already finished, which
    is the wrong shape when each stage's entry is large.
    """

    store = _memo.get()
    if store is None:
        return

    values = store['values']
    for memo_key in [key for key in values if key[0] == namespace]:
        del values[memo_key]


def covering_range(namespace, project_id, requested_start, requested_end, producer):
    """
    Reuse a read whose span already contains ``requested_start..requested_end``.

    Reads are matched by containment rather than by an exact span, because the
    windows a rebuild asks for nest inside one another rather than lining up.
    One read covering their union then serves all of them.

    ``producer`` is called with the span actually loaded, which always contains
    the requested one and may extend past it on either side when a plan or an
    existing entry is wider. Callers must therefore tolerate surrounding data
    they did not ask for, and must bound their own work by the span they
    requested rather than by what they were handed.
    """

    store = _memo.get()
    if store is None:
        return producer(requested_start, requested_end)

    values = store['values']
    memo_key = (namespace, _filter_scope_key(), project_id)
    entry = values.get(memo_key)
    if entry is not None:
        loaded_start, loaded_end, value = entry
        if loaded_start <= requested_start and loaded_end >= requested_end:
            return value

    load_start, load_end = requested_start, requested_end
    planned = store['floors'].get(namespace)
    if planned is not None:
        planned_start, planned_end = planned
        load_start = min(load_start, planned_start)
        load_end = max(load_end, planned_end)
    if entry is not None:
        load_start = min(load_start, entry[0])
        load_end = max(load_end, entry[1])

    value = producer(load_start, load_end)
    values[memo_key] = (load_start, load_end, value)
    return value
