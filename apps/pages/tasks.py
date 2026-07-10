from celery import shared_task

from apps.pages.company_analytics import build_companies_overview_cache, build_company_detail_cache
from apps.pages.user_detail_analytics import build_user_detail_cache
from apps.pages.user_analytics import build_users_overview_cache
from apps.pages.services import (
    build_pages_overview_cache,
    hydrate_pages_scatter_tooltips_cache,
    rebuild_project_pages_analytics,
    refresh_recent_projects_pages_analytics,
)
@shared_task
def build_page_visits_for_project(project_id, start_date, end_date):
    return rebuild_project_pages_analytics(project_id, start_date, end_date, range_keys=())


@shared_task
def build_page_transitions_for_project(project_id, start_date, end_date):
    return rebuild_project_pages_analytics(project_id, start_date, end_date, range_keys=())


@shared_task
def aggregate_page_daily_metrics(project_id, start_date, end_date):
    from apps.pages.services import aggregate_page_daily_metrics as aggregate_service

    return aggregate_service(project_id, start_date, end_date)


@shared_task
def build_pages_overview_cache_task(project_id, range_key='last_30_days'):
    return build_pages_overview_cache(project_id, range_key=range_key)


@shared_task
def build_companies_overview_cache_task(project_id, range_key='last_30_days'):
    return build_companies_overview_cache(project_id, range_key=range_key)


@shared_task
def build_users_overview_cache_task(project_id, range_key='last_30_days'):
    return build_users_overview_cache(project_id, range_key=range_key)


@shared_task
def build_company_detail_cache_task(project_id, company_id, range_key='last_30_days'):
    return build_company_detail_cache(project_id, company_id, range_key=range_key)


@shared_task
def build_user_detail_cache_task(project_id, user_id, range_key='last_30_days'):
    return build_user_detail_cache(project_id, user_id, range_key=range_key)


@shared_task
def hydrate_pages_scatter_tooltips_cache_task(project_id, range_key='last_30_days'):
    return hydrate_pages_scatter_tooltips_cache(project_id, range_key=range_key)


@shared_task
def backfill_pages_analytics_task(project_id, start_date, end_date):
    return rebuild_project_pages_analytics(project_id, start_date, end_date)


@shared_task
def refresh_recent_pages_analytics_task(lookback_days=2, active_since_days=2, range_keys=None, exclude_project_ids=None):
    return refresh_recent_projects_pages_analytics(
        lookback_days=lookback_days,
        active_since_days=active_since_days,
        range_keys=range_keys,
        exclude_project_ids=exclude_project_ids,
    )
