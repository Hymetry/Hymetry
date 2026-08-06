import subprocess

from celery import shared_task

from apps.projects.models import Project, ProjectPageNamingState
from apps.tracker.models import ProjectNormalizationFactor, ProjectPageNamingRunMode, Session
from apps.tracker.page_naming import run_page_naming_for_project
from apps.tracker.session_visualizer import SessionVisualizer
from apps.tracker.visits_retention import prune_expired_recording_visits
from config.utils import get_django_settings_module


@shared_task
def calculate_bubble_cache():
    return SessionVisualizer.calculate_and_cache_bubbles_for_all_pages()

@shared_task
def calculate_project_normalization_factors():
    project_ids = Session.objects.values_list('visitor__project_id', flat=True).distinct()
    results = SessionVisualizer.calculate_normalization_factors_for_projects(
        Project.active.filter(id__in=project_ids).values_list('id', flat=True)
    )
    for project_id, factor in results.items():
        ProjectNormalizationFactor.objects.update_or_create(
            project_id=project_id,
            defaults={'factor': factor},
        )
    return results


def get_project_normalization_factor(project_id):
    factor = ProjectNormalizationFactor.objects.filter(project_id=project_id).first()
    return factor.factor if factor else 1000.0

@shared_task
def run_calculate_bubble_cache():
    result = subprocess.run(
        ['python', 'manage.py', 'calculate_bubble_cache', f'--settings={get_django_settings_module()}'],
        capture_output=True,
        text=True,
    )
    return result.stdout if result.returncode == 0 else f'Error {result.returncode}: {result.stderr}'


@shared_task
def prune_expired_recording_visits_task(retention_days=30, batch_size=100):
    return prune_expired_recording_visits(
        retention_days=retention_days,
        batch_size=batch_size,
    )


def _serialize_page_naming_run(run):
    if run is None:
        return {'status': 'skipped', 'reason': 'lock_not_acquired'}
    return {
        'project_id': run.project_id,
        'mode': run.mode,
        'phase': run.phase,
        'status': run.status,
        'skip_reason': run.skip_reason,
        'error_message': run.error_message,
        'input_urls_count': run.input_urls_count,
        'output_rules_count': run.output_rules_count,
        'new_urls_1h': run.new_urls_1h,
        'new_urls_24h': run.new_urls_24h,
        'unique_urls_total': run.unique_urls_total,
    }


@shared_task
def run_project_page_naming_task(project_id, mode):
    return _serialize_page_naming_run(run_page_naming_for_project(project_id, mode))


@shared_task
def run_project_page_title_backfill_task(project_id):
    return _serialize_page_naming_run(
        run_page_naming_for_project(project_id, ProjectPageNamingRunMode.HOURLY_TITLE_BACKFILL)
    )


@shared_task
def run_hourly_page_naming():
    return [
        _serialize_page_naming_run(
            run_page_naming_for_project(project_id, ProjectPageNamingRunMode.HOURLY_UNSTABLE)
        )
        for project_id in Project.active.filter(
            page_naming_state=ProjectPageNamingState.NOT_STABLE
        ).values_list('id', flat=True)
    ]


@shared_task
def run_daily_page_naming():
    return [
        _serialize_page_naming_run(
            run_page_naming_for_project(project_id, ProjectPageNamingRunMode.DAILY_STABLE)
        )
        for project_id in Project.active.filter(
            page_naming_state=ProjectPageNamingState.STABLE
        ).values_list('id', flat=True)
    ]


@shared_task
def run_hourly_page_title_backfill():
    return [
        _serialize_page_naming_run(
            run_page_naming_for_project(project_id, ProjectPageNamingRunMode.HOURLY_TITLE_BACKFILL)
        )
        for project_id in Project.active.values_list('id', flat=True)
    ]
