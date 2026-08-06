import logging

from celery import shared_task
from django.http import QueryDict

from apps.pages.company_analytics import build_companies_overview_cache, build_company_detail_cache
from apps.pages.product_area_color_assignment import (
    assign_not_stable_project_product_area_colors,
    assign_stable_project_product_area_colors,
)
from apps.pages.user_detail_analytics import build_user_detail_cache
from apps.pages.user_analytics import build_users_overview_cache
from apps.pages.services import (
    build_pages_overview_cache,
    hydrate_pages_scatter_tooltips_cache,
    rebuild_project_pages_analytics,
    refresh_recent_projects_pages_analytics,
)
from apps.projects.company_attribute_filters import (
    CompanyAttributeFilterValidationError,
    parse_company_attribute_filters,
)
from apps.projects.models import Project, ProjectPageNamingState


logger = logging.getLogger(__name__)


PAGES_LOCK_RETRY_BASE_SECONDS = 30
PAGES_LOCK_RETRY_MAX_SECONDS = 300
PAGES_LOCK_MAX_RETRIES = 4


class PagesRebuildLockUnavailable(RuntimeError):
    pass


def _pages_lock_retry_countdown(retries):
    retry_number = max(0, int(retries or 0))
    return min(
        PAGES_LOCK_RETRY_BASE_SECONDS * (2 ** retry_number),
        PAGES_LOCK_RETRY_MAX_SECONDS,
    )


def _locked_project_ids(result):
    if isinstance(result, dict):
        if result.get('status') == 'skipped' and result.get('reason') == 'lock_not_acquired':
            return [result.get('project_id')]
        project_ids = []
        for nested_result in result.values():
            if isinstance(nested_result, (dict, list, tuple)):
                project_ids.extend(_locked_project_ids(nested_result))
        return project_ids
    if isinstance(result, (list, tuple)):
        project_ids = []
        for nested_result in result:
            project_ids.extend(_locked_project_ids(nested_result))
        return project_ids
    return []


def _retry_task_if_pages_lock_unavailable(task, result, *, best_effort=False):
    """
    Retry a task that lost the project rebuild lock, and decide how it ends.

    A scheduled or explicitly invoked task that never wins the lock has dropped
    a unit of work nothing else will redo, so it raises once the budget is spent
    and the failure is visible. A best-effort warm queued by a web request has
    not failed in the same sense: whoever holds the lock is rebuilding that
    project, and the next request queues the warm again. Raising there reports
    ordinary contention as an unhandled error, so it returns the skip instead
    and leaves the record in the task result and the worker log.
    """

    locked_project_ids = list(dict.fromkeys(_locked_project_ids(result)))
    if not locked_project_ids:
        return result

    retries = int(getattr(task.request, 'retries', 0) or 0)
    if best_effort and retries >= PAGES_LOCK_MAX_RETRIES:
        logger.warning(
            'Stopped waiting for the pages rebuild lock in %s for projects: %s (%s retries)',
            task.name,
            locked_project_ids,
            retries,
        )
        return result

    countdown = _pages_lock_retry_countdown(retries)
    error = PagesRebuildLockUnavailable(
        f'Pages rebuild lock unavailable for projects: {locked_project_ids}'
    )
    raise task.retry(
        exc=error,
        countdown=countdown,
        max_retries=PAGES_LOCK_MAX_RETRIES,
    )


@shared_task(bind=True, max_retries=PAGES_LOCK_MAX_RETRIES)
def build_page_visits_for_project(self, project_id, start_date, end_date):
    result = rebuild_project_pages_analytics(project_id, start_date, end_date, range_keys=())
    return _retry_task_if_pages_lock_unavailable(self, result)


@shared_task(bind=True, max_retries=PAGES_LOCK_MAX_RETRIES)
def build_page_transitions_for_project(self, project_id, start_date, end_date):
    result = rebuild_project_pages_analytics(project_id, start_date, end_date, range_keys=())
    return _retry_task_if_pages_lock_unavailable(self, result)


@shared_task(bind=True, max_retries=PAGES_LOCK_MAX_RETRIES)
def aggregate_page_daily_metrics(self, project_id, start_date, end_date):
    from apps.pages.services import aggregate_page_daily_metrics as aggregate_service

    result = aggregate_service(project_id, start_date, end_date)
    return _retry_task_if_pages_lock_unavailable(self, result)


@shared_task(bind=True, max_retries=PAGES_LOCK_MAX_RETRIES)
def build_pages_overview_cache_task(self, project_id, range_key='last_30_days'):
    result = build_pages_overview_cache(project_id, range_key=range_key)
    return _retry_task_if_pages_lock_unavailable(self, result, best_effort=True)





@shared_task(bind=True, max_retries=PAGES_LOCK_MAX_RETRIES)
def build_companies_overview_cache_task(self, project_id, range_key='last_30_days'):
    result = build_companies_overview_cache(project_id, range_key=range_key)
    return _retry_task_if_pages_lock_unavailable(self, result)


@shared_task(bind=True, max_retries=PAGES_LOCK_MAX_RETRIES)
def build_users_overview_cache_task(self, project_id, range_key='last_30_days'):
    result = build_users_overview_cache(project_id, range_key=range_key)
    return _retry_task_if_pages_lock_unavailable(self, result)


def _build_filtered_variant(task, surface, project_id, canonical_pairs, filters_hash, range_key):
    from apps.pages import filtered_overview

    result = filtered_overview.build_variant(
        surface,
        project_id,
        canonical_pairs,
        filters_hash,
        range_key,
    )
    return _retry_task_if_pages_lock_unavailable(task, result, best_effort=True)


@shared_task(bind=True, max_retries=PAGES_LOCK_MAX_RETRIES)
def build_filtered_pages_overview_cache_task(
    self,
    project_id,
    canonical_pairs,
    filters_hash,
    range_key='last_30_days',
):
    return _build_filtered_variant(
        self, 'pages', project_id, canonical_pairs, filters_hash, range_key,
    )


@shared_task(bind=True, max_retries=PAGES_LOCK_MAX_RETRIES)
def build_filtered_companies_overview_cache_task(
    self,
    project_id,
    canonical_pairs,
    filters_hash,
    range_key='last_30_days',
):
    return _build_filtered_variant(
        self, 'companies', project_id, canonical_pairs, filters_hash, range_key,
    )


@shared_task(bind=True, max_retries=PAGES_LOCK_MAX_RETRIES)
def build_filtered_users_overview_cache_task(
    self,
    project_id,
    canonical_pairs,
    filters_hash,
    range_key='last_30_days',
):
    return _build_filtered_variant(
        self, 'users', project_id, canonical_pairs, filters_hash, range_key,
    )


@shared_task(bind=True, max_retries=PAGES_LOCK_MAX_RETRIES)
def build_company_detail_cache_task(self, project_id, company_id, range_key='last_30_days'):
    result = build_company_detail_cache(project_id, company_id, range_key=range_key)
    return _retry_task_if_pages_lock_unavailable(self, result, best_effort=True)


@shared_task(bind=True, max_retries=PAGES_LOCK_MAX_RETRIES)
def build_user_detail_cache_task(self, project_id, user_id, range_key='last_30_days'):
    result = build_user_detail_cache(project_id, user_id, range_key=range_key)
    return _retry_task_if_pages_lock_unavailable(self, result, best_effort=True)


@shared_task(bind=True, max_retries=PAGES_LOCK_MAX_RETRIES)
def hydrate_pages_scatter_tooltips_cache_task(self, project_id, range_key='last_30_days'):
    result = hydrate_pages_scatter_tooltips_cache(project_id, range_key=range_key)
    return _retry_task_if_pages_lock_unavailable(self, result, best_effort=True)


@shared_task(bind=True, max_retries=PAGES_LOCK_MAX_RETRIES)
def backfill_pages_analytics_task(self, project_id, start_date, end_date):
    result = rebuild_project_pages_analytics(project_id, start_date, end_date)
    return _retry_task_if_pages_lock_unavailable(self, result)


@shared_task(bind=True, max_retries=PAGES_LOCK_MAX_RETRIES)
def refresh_recent_pages_analytics_task(
    self,
    lookback_days=2,
    active_since_days=2,
    range_keys=None,
    exclude_project_ids=None,
):
    if exclude_project_ids is None:
        exclude_project_ids = ()

    result = refresh_recent_projects_pages_analytics(
        lookback_days=lookback_days,
        active_since_days=active_since_days,
        range_keys=range_keys,
        exclude_project_ids=exclude_project_ids,
    )
    return _retry_task_if_pages_lock_unavailable(self, result)


@shared_task(bind=True, max_retries=PAGES_LOCK_MAX_RETRIES)
def run_hourly_not_stable_product_area_colors(self):
    project_ids = list(
        Project.active
        .filter(page_naming_state=ProjectPageNamingState.NOT_STABLE)
        .order_by('id')
        .values_list('id', flat=True)
    )
    results = [
        assign_not_stable_project_product_area_colors(project_id)
        for project_id in project_ids
    ]
    return _retry_task_if_pages_lock_unavailable(self, results)


@shared_task(bind=True, max_retries=PAGES_LOCK_MAX_RETRIES)
def run_daily_stable_product_area_colors(self):
    project_ids = list(
        Project.active
        .filter(page_naming_state=ProjectPageNamingState.STABLE)
        .order_by('id')
        .values_list('id', flat=True)
    )
    results = [
        assign_stable_project_product_area_colors(project_id)
        for project_id in project_ids
    ]
    return _retry_task_if_pages_lock_unavailable(self, results)
