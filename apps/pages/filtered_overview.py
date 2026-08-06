"""One materialization contract for every company-attribute overview variant.

A variant is ``(project, range_key, filters_hash)``. The unfiltered ``default``
variant and every filtered one are produced by the same surface builder and
stored in the same cache table; nothing derives a filtered payload by
post-processing the default one. Reads are therefore identical for both, which
is what lets Pages, Companies and Users keep serving their tables, selectors and
trimmed client payloads straight out of SQL no matter which filter is applied.

Web requests only ever read. A request that finds no usable row returns its
surface's pending state and asks a worker to build that exact variant, so
analytics work never runs in the web tier.
"""

import logging
import threading
import time
from collections import OrderedDict

from django.conf import settings
from django.http import QueryDict
from django.utils import timezone as django_timezone

from apps.pages import services
from apps.pages.services import DEFAULT_FILTERS_HASH
from apps.projects.company_attribute_filters import (
    CompanyAttributeFilterValidationError,
    parse_company_attribute_filters,
)
from apps.projects.models import Project


logger = logging.getLogger(__name__)

PAGES = 'pages'
COMPANIES = 'companies'
USERS = 'users'
SURFACES = (PAGES, COMPANIES, USERS)

DISPATCH_DEDUP_SECONDS = 60
DISPATCH_DEDUP_MAX_ENTRIES = 2048

_dispatch_lock = threading.Lock()
_dispatches = OrderedDict()


def metadata_row(sql, project_id, range_key, filters_hash):
    """
    Read a variant's freshness metadata without transferring its payload.

    Shaped like a payload row so ``variant_is_usable`` needs no second code
    path: callers that render from SQL can check usability as cheaply as a
    single indexed lookup.
    """

    from apps.pages import queries

    row = queries.fetch_one(sql, [project_id, range_key, filters_hash])
    if not row:
        return None
    row['payload_json'] = {
        'freshness': {
            'filtered_analytics_revision': row.get('filtered_analytics_revision'),
            'analytics_facts_revision': row.get('analytics_facts_revision'),
        },
    }
    return row


def _freshness_int(cache, key):
    payload = (cache or {}).get('payload_json')
    if not isinstance(payload, dict):
        return None
    freshness = payload.get('freshness')
    if not isinstance(freshness, dict):
        return None
    try:
        return int(freshness.get(key))
    except (TypeError, ValueError):
        return None


def payload_filtered_revision(cache):
    """The filtered analytics revision a cached payload was built against."""

    return _freshness_int(cache, 'filtered_analytics_revision')


def payload_facts_revision(cache):
    """The prepared-facts revision a cached payload was built against."""

    return _freshness_int(cache, 'analytics_facts_revision')


def _attribute_revision(filtered_revision, facts_revision):
    """
    A counter that advances only when company-attribute values change.

    Prepared-fact rebuilds advance both project revisions together; attribute
    writes advance only the filtered one. Their difference therefore isolates
    the attribute writes, which is the only class of change that makes a stored
    cohort wrong rather than merely out of date. No extra column is needed.
    """

    if filtered_revision is None or facts_revision is None:
        return None
    return int(filtered_revision) - int(facts_revision)


def expected_period(project, range_key):
    """The window this request means by *range_key*, in the project's local day."""

    return services.resolve_period(
        getattr(project, 'timezone', None) or 'UTC',
        range_key=range_key,
    )


def variant_covers_period(cache, expected_period):
    """
    Whether a cached payload describes the period the request is asking for.

    Every range resolves relative to the project's current local day, so a row
    built for an earlier day describes a different window. Serving it would
    misreport an old window as the current one, which is wrong data rather than
    stale data -- an untouched month-old variant would silently show a month-old
    period. Comparing the stored window is what bounds staleness to one day.
    """

    if expected_period is None:
        return True
    start_date, end_date = expected_period
    return cache.get('start_date') == start_date and cache.get('end_date') == end_date


def variant_is_usable(
    cache,
    *,
    project,
    filters_hash,
    schema_is_current,
    expected_period=None,
):
    """
    Whether a cache row may be served for this variant.

    Two conditions, and they fail for different reasons. The window must match,
    because a payload for another day is not an answer to this request. The
    attribute revision must match, because a payload built from a different
    cohort is not an answer either. A moved facts revision is neither -- it just
    means newer events exist, so the row stays servable and
    ``variant_needs_refresh`` asks for a rebuild behind it.
    """

    if not cache:
        return False
    if not schema_is_current(cache.get('schema_version')):
        return False
    if not variant_covers_period(cache, expected_period):
        return False
    if filters_hash == DEFAULT_FILTERS_HASH:
        return True
    expected = _attribute_revision(
        getattr(project, 'filtered_analytics_revision', None),
        getattr(project, 'analytics_facts_revision', None),
    )
    stored = _attribute_revision(
        payload_filtered_revision(cache),
        payload_facts_revision(cache),
    )
    return stored is not None and stored == expected


def variant_needs_refresh(cache, *, project=None):
    """Whether a usable row should still be rebuilt in the background."""

    if not cache:
        return True
    if cache.get('is_stale'):
        return True
    if project is not None:
        stored_facts = payload_facts_revision(cache)
        current_facts = getattr(project, 'analytics_facts_revision', None)
        if stored_facts is not None and current_facts is not None:
            if stored_facts != int(current_facts):
                return True
    expires_at = cache.get('expires_at')
    return expires_at is None or expires_at <= django_timezone.now()


def _task_for_surface(surface):
    from apps.pages import tasks

    return {
        PAGES: tasks.build_filtered_pages_overview_cache_task,
        COMPANIES: tasks.build_filtered_companies_overview_cache_task,
        USERS: tasks.build_filtered_users_overview_cache_task,
    }[surface]


def _claim_dispatch(dispatch_key):
    """Reserve one dispatch slot, or report that a recent one covers it."""

    now = time.monotonic()
    with _dispatch_lock:
        while _dispatches:
            oldest_key, oldest_deadline = next(iter(_dispatches.items()))
            if oldest_deadline > now:
                break
            _dispatches.pop(oldest_key, None)
        if dispatch_key in _dispatches:
            return False
        _dispatches[dispatch_key] = now + DISPATCH_DEDUP_SECONDS
        while len(_dispatches) > DISPATCH_DEDUP_MAX_ENTRIES:
            _dispatches.popitem(last=False)
    return True


def _release_dispatch(dispatch_key):
    with _dispatch_lock:
        _dispatches.pop(dispatch_key, None)


def queue_variant_rebuild(surface, project_id, range_key, state):
    """
    Best-effort request for a worker to build one exact filter variant.

    Deduplicated per web process so a burst of table, selector and data requests
    for the same variant publishes one task. The project advisory lock remains
    the cross-process correctness boundary.
    """

    if surface not in SURFACES:
        raise ValueError(f'Unknown overview surface: {surface}')
    if not state.active:
        raise ValueError('Only filtered variants are queued through this path.')
    if not getattr(settings, 'PAGES_QUEUE_REBUILDS_ON_REQUEST', True):
        return False

    dispatch_key = (surface, int(project_id), str(range_key), str(state.filters_hash))
    if not _claim_dispatch(dispatch_key):
        return True

    try:
        _task_for_surface(surface).apply_async(
            kwargs={
                'project_id': int(project_id),
                'range_key': str(range_key),
                'canonical_pairs': [[str(key), str(value)] for key, value in state.canonical_pairs],
                'filters_hash': str(state.filters_hash),
            },
            retry=False,
            ignore_result=True,
        )
    except Exception:
        _release_dispatch(dispatch_key)
        logger.exception(
            'Could not queue a filtered overview rebuild.',
            extra={
                'surface': surface,
                'project_id': project_id,
                'range_key': range_key,
                'filters_hash': state.filters_hash,
            },
        )
        return False
    return True


def read_variant(
    surface,
    project,
    range_key,
    state,
    *,
    fetch,
    schema_is_current,
):
    """
    Read one variant without ever building it.

    Returns ``(cache, queued)``. A ``None`` cache means the caller should render
    its pending state; ``queued`` reports whether a build was published, which
    only tells the client whether polling is worth it.
    """

    cache = fetch(project.id, range_key=range_key, filters_hash=state.filters_hash)
    usable = variant_is_usable(
        cache,
        project=project,
        filters_hash=state.filters_hash,
        schema_is_current=schema_is_current,
        expected_period=expected_period(project, range_key) if state.active else None,
    )
    if not state.active:
        return (cache if usable else None), False
    if usable and not variant_needs_refresh(cache, project=project):
        return cache, False
    queued = queue_variant_rebuild(surface, project.id, range_key, state)
    return (cache if usable else None), queued


def gate_filtered_variant(
    surface,
    project,
    range_key,
    state,
    *,
    fetch,
    schema_is_current,
):
    """
    Decide whether an endpoint that renders from SQL may proceed.

    Returns ``(ready, queued)``. Without an active filter the answer is always
    yes and no lookup happens: the unfiltered cache row is the only thing those
    endpoints have ever read, and their own query already reports its absence.
    A filtered variant still has to clear the revision check first, so a cold or
    superseded one yields a pending response and a queued build.
    """

    if not state.active:
        return True, False
    cache, queued = read_variant(
        surface,
        project,
        range_key,
        state,
        fetch=fetch,
        schema_is_current=schema_is_current,
    )
    return cache is not None, queued


def build_variant(surface, project_id, canonical_pairs, filters_hash, range_key):
    """
    Worker-side entry point for one exact filter variant.

    The filter expression is re-parsed from its canonical pairs and re-hashed
    rather than trusted, so a task carrying a stale or hand-edited expression
    cannot publish a payload under the wrong key.
    """

    from apps.pages import company_analytics, user_analytics

    if surface not in SURFACES:
        raise ValueError(f'Unknown overview surface: {surface}')

    project = Project.active.filter(pk=project_id).first()
    if project is None:
        return {'status': 'skipped', 'reason': 'missing_project', 'project_id': project_id}

    query = QueryDict('', mutable=True)
    try:
        for pair in canonical_pairs or ():
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                raise ValueError
            key, value = pair
            query.appendlist(str(key), str(value))
        state = parse_company_attribute_filters(project, query, strict=True)
    except (CompanyAttributeFilterValidationError, TypeError, ValueError):
        return {'status': 'skipped', 'reason': 'invalid_filters', 'project_id': project_id}

    if not state.active or state.filters_hash != filters_hash:
        return {
            'status': 'skipped',
            'reason': 'filters_changed',
            'project_id': project_id,
            'filters_hash': filters_hash,
        }

    builder = {
        PAGES: services.build_pages_overview_cache,
        COMPANIES: company_analytics.build_companies_overview_cache,
        USERS: user_analytics.build_users_overview_cache,
    }[surface]
    return builder(
        project_id,
        range_key=range_key,
        company_attribute_filter_state=state,
    )
