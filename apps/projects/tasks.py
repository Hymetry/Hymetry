from celery import shared_task

from .services import purge_archived_entities


@shared_task
def purge_archived_projects_and_workspaces():
    return purge_archived_entities()
