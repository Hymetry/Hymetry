from django.db import transaction
from django.utils import timezone

from .models import (
    Project,
    WorkspaceOpenAICredential,
    WorkspaceOpenAIValidationStatus,
)
from .secret_store import decrypt_secret, encrypt_secret


class WorkspaceOpenAIKeyError(Exception):
    pass


@transaction.atomic
def set_workspace_openai_key(workspace, raw_key, *, updated_by):
    normalized_key = str(raw_key or '').strip()
    if not normalized_key:
        raise WorkspaceOpenAIKeyError('Enter an OpenAI API key.')

    credential, _ = WorkspaceOpenAICredential.objects.select_for_update().get_or_create(
        workspace=workspace,
        defaults={'encrypted_api_key': encrypt_secret(normalized_key)},
    )
    credential.encrypted_api_key = encrypt_secret(normalized_key)
    credential.key_last_four = normalized_key[-4:]
    credential.validation_status = WorkspaceOpenAIValidationStatus.UNCHECKED
    credential.validation_error_code = ''
    credential.validated_at = None
    credential.updated_by = updated_by
    credential.save()
    return credential


@transaction.atomic
def delete_workspace_openai_key(workspace):
    WorkspaceOpenAICredential.objects.select_for_update().filter(workspace=workspace).delete()


def get_workspace_openai_api_key(workspace):
    try:
        credential = workspace.openai_credential
    except WorkspaceOpenAICredential.DoesNotExist:
        return None
    if credential.validation_status == WorkspaceOpenAIValidationStatus.INVALID:
        return None
    return decrypt_secret(credential.encrypted_api_key)


def get_openai_api_key_for_project(project_or_id):
    if isinstance(project_or_id, Project):
        project = project_or_id
        if not hasattr(project, 'workspace'):
            project = Project.objects.select_related('workspace').get(pk=project.pk)
    else:
        project = Project.objects.select_related('workspace').get(pk=project_or_id)
    return get_workspace_openai_api_key(project.workspace)


@transaction.atomic
def validate_workspace_openai_key(workspace):
    credential = WorkspaceOpenAICredential.objects.select_for_update().get(workspace=workspace)
    api_key = decrypt_secret(credential.encrypted_api_key)

    status = WorkspaceOpenAIValidationStatus.UNAVAILABLE
    error_code = 'provider_unavailable'
    try:
        from openai import APIConnectionError, AuthenticationError, OpenAI, RateLimitError

        OpenAI(api_key=api_key).models.list()
        status = WorkspaceOpenAIValidationStatus.VALID
        error_code = ''
    except AuthenticationError:
        status = WorkspaceOpenAIValidationStatus.INVALID
        error_code = 'authentication_failed'
    except (APIConnectionError, RateLimitError):
        status = WorkspaceOpenAIValidationStatus.UNAVAILABLE
        error_code = 'provider_unavailable'
    except Exception:
        status = WorkspaceOpenAIValidationStatus.UNAVAILABLE
        error_code = 'validation_failed'

    credential.validation_status = status
    credential.validation_error_code = error_code
    credential.validated_at = timezone.now()
    credential.save(
        update_fields=['validation_status', 'validation_error_code', 'validated_at', 'updated_at']
    )
    return credential
