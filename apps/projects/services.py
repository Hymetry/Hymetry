from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .access import user_can_create_project, user_can_create_workspace
from .domain_utils import normalize_allowed_domains, normalize_workspace_website_url
from .models import (
    LifecycleStatus,
    Project,
    ProjectStatus,
    Workspace,
    WorkspaceMemberRole,
    WorkspaceMemberStatus,
    WorkspaceMembership,
    workspace_slug_exists,
)


ARCHIVE_RETENTION_DAYS = 30


def normalize_timezone(value):
    timezone_value = (value or 'UTC').strip() or 'UTC'
    if timezone_value == 'Europe/Kiev':
        timezone_value = 'Europe/Kyiv'
    try:
        ZoneInfo(timezone_value)
        return timezone_value
    except Exception:
        return 'UTC'


@transaction.atomic
def create_workspace_for_user(user, name, website_url=''):
    if not user_can_create_workspace(user):
        raise PermissionDenied('Only an instance administrator or workspace owner can create a workspace.')
    workspace = Workspace.objects.create(
        name=(name or '').strip(),
        website_url=normalize_workspace_website_url(website_url),
        created_by=user,
    )
    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=user,
        role=WorkspaceMemberRole.OWNER,
        status=WorkspaceMemberStatus.ACTIVE,
    )
    return workspace


def create_project_in_workspace(user, workspace, name, product_url='', timezone_value='UTC'):
    if not user_can_create_project(user, workspace):
        raise PermissionDenied('Only a workspace owner can create a project.')
    allowed_domains = normalize_allowed_domains([product_url])
    normalized_product_url = allowed_domains[0] if allowed_domains else ''
    project = Project.objects.create(
        workspace=workspace,
        name=(name or '').strip(),
        created_by=user,
        product_url=normalized_product_url,
        allowed_domains=allowed_domains,
        timezone=normalize_timezone(timezone_value),
    )
    project.generate_api_key()
    return project


@transaction.atomic
def create_first_workspace_project(user, workspace_name, project_name, product_url, timezone_value='UTC'):
    if WorkspaceMembership.objects.select_for_update().filter(
        user=user,
        status=WorkspaceMemberStatus.ACTIVE,
        removed_at__isnull=True,
    ).exists():
        raise PermissionDenied('Initial onboarding is already complete.')
    workspace = create_workspace_for_user(user, workspace_name, website_url=product_url)
    project = create_project_in_workspace(
        user,
        workspace,
        project_name,
        product_url=product_url,
        timezone_value=timezone_value,
    )
    return workspace, project


def rename_workspace(workspace, name):
    workspace_name = (name or '').strip()
    workspace.name = workspace_name
    workspace.save(update_fields=['name', 'updated_at'])
    return workspace


def change_workspace_slug(workspace, slug):
    workspace_slug = (slug or '').strip().lower()
    old_slug = workspace.slug
    if workspace_slug == old_slug:
        return workspace
    if workspace_slug_exists(workspace_slug, exclude_workspace_id=workspace.pk):
        raise ValueError('Workspace URL slug is already in use.')
    workspace.slug = workspace_slug
    if old_slug:
        workspace.previous_slug = old_slug
    workspace.save(update_fields=['slug', 'previous_slug', 'updated_at'])
    return workspace


def archive_project(project, archived_at=None):
    archived_at = archived_at or timezone.now()
    project.lifecycle_status = LifecycleStatus.ARCHIVED
    project.archived_at = archived_at
    project.delete_after = archived_at + timezone.timedelta(days=ARCHIVE_RETENTION_DAYS)
    project.save(update_fields=['lifecycle_status', 'archived_at', 'delete_after'])
    return project


def restore_project(project):
    project.lifecycle_status = LifecycleStatus.ACTIVE
    project.archived_at = None
    project.delete_after = None
    project.save(update_fields=['lifecycle_status', 'archived_at', 'delete_after'])
    return project


def workspace_has_active_projects(workspace):
    return Project.active.filter(workspace=workspace).exists()


def archive_workspace(workspace, archived_at=None):
    archived_at = archived_at or timezone.now()
    workspace.archived_at = archived_at
    workspace.delete_after = archived_at + timezone.timedelta(days=ARCHIVE_RETENTION_DAYS)
    workspace.save(update_fields=['archived_at', 'delete_after', 'updated_at'])
    return workspace


def restore_workspace(workspace):
    workspace.archived_at = None
    workspace.delete_after = None
    workspace.save(update_fields=['archived_at', 'delete_after', 'updated_at'])
    return workspace


@transaction.atomic
def purge_archived_entities(now=None):
    now = now or timezone.now()
    project_queryset = Project.objects.filter(
        lifecycle_status=LifecycleStatus.ARCHIVED,
        delete_after__isnull=False,
        delete_after__lte=now,
    )
    project_count = project_queryset.count()
    project_queryset.delete()

    deleted_workspaces = 0
    workspace_queryset = Workspace.objects.filter(
        archived_at__isnull=False,
        delete_after__isnull=False,
        delete_after__lte=now,
    )
    for workspace in workspace_queryset.iterator():
        if Project.objects.filter(workspace=workspace).exists():
            continue
        workspace.delete()
        deleted_workspaces += 1

    return {
        'projects': project_count,
        'workspaces': deleted_workspaces,
    }


def record_project_production_event(project, first_event_time=None, last_event_time=None):
    first_event_time = first_event_time or timezone.now()
    last_event_time = last_event_time or first_event_time
    project_update_fields = ['last_event_at', 'status']
    project.last_event_at = last_event_time
    project.status = ProjectStatus.ACTIVE if project.allowed_domains else ProjectStatus.SETUP_REQUIRED
    if project.first_production_event_at is None:
        project.first_production_event_at = first_event_time
        project_update_fields.append('first_production_event_at')
    project.save(update_fields=project_update_fields)


@transaction.atomic
def add_local_workspace_member(*, actor, workspace, email, role, temporary_password=''):
    from .access import user_can_invite_role, user_can_manage_members

    normalized_email = str(email or '').strip().lower()
    if not normalized_email:
        raise ValidationError({'email': 'Enter an email address.'})
    if role not in dict(WorkspaceMemberRole.choices):
        raise ValidationError({'role': 'Choose a valid role.'})
    if not user_can_manage_members(actor, workspace) or not user_can_invite_role(actor, workspace, role):
        raise PermissionDenied('You cannot add this workspace role.')

    User = get_user_model()
    user = User.objects.filter(email__iexact=normalized_email).first()
    created = user is None
    if created:
        if not temporary_password:
            raise ValidationError({'temporary_password': 'A temporary password is required for a new user.'})
        candidate = User(username=normalized_email, email=normalized_email)
        validate_password(temporary_password, candidate)
        candidate.set_password(temporary_password)
        candidate.save()
        user = candidate

    membership, membership_created = WorkspaceMembership.objects.select_for_update().get_or_create(
        workspace=workspace,
        user=user,
        defaults={
            'role': role,
            'status': WorkspaceMemberStatus.ACTIVE,
            'removed_at': None,
        },
    )
    if not membership_created:
        if membership.is_active:
            raise ValidationError({'email': 'This user is already a workspace member.'})
        membership.role = role
        membership.status = WorkspaceMemberStatus.ACTIVE
        membership.removed_at = None
        membership.save(update_fields=['role', 'status', 'removed_at', 'updated_at'])
    return membership, created


@transaction.atomic
def remove_workspace_member_safely(membership):
    locked_workspace = Workspace.objects.select_for_update().get(pk=membership.workspace_id)
    locked_membership = WorkspaceMembership.objects.select_for_update().get(pk=membership.pk)
    if locked_membership.role == WorkspaceMemberRole.OWNER:
        owner_count = WorkspaceMembership.objects.select_for_update().filter(
            workspace=locked_workspace,
            role=WorkspaceMemberRole.OWNER,
            status=WorkspaceMemberStatus.ACTIVE,
            removed_at__isnull=True,
        ).count()
        if owner_count <= 1:
            raise PermissionDenied('Transfer ownership before removing the last owner.')
    locked_membership.status = WorkspaceMemberStatus.REMOVED
    locked_membership.removed_at = timezone.now()
    locked_membership.save(update_fields=['status', 'removed_at', 'updated_at'])
    return locked_membership


@transaction.atomic
def change_workspace_member_role_safely(membership, role):
    if role not in dict(WorkspaceMemberRole.choices):
        raise ValidationError({'role': 'Choose a valid role.'})
    Workspace.objects.select_for_update().get(pk=membership.workspace_id)
    locked_membership = WorkspaceMembership.objects.select_for_update().get(pk=membership.pk)
    if locked_membership.role == WorkspaceMemberRole.OWNER and role != WorkspaceMemberRole.OWNER:
        owner_count = WorkspaceMembership.objects.select_for_update().filter(
            workspace_id=membership.workspace_id,
            role=WorkspaceMemberRole.OWNER,
            status=WorkspaceMemberStatus.ACTIVE,
            removed_at__isnull=True,
        ).count()
        if owner_count <= 1:
            raise PermissionDenied('Transfer ownership before changing the last owner.')
    locked_membership.role = role
    locked_membership.save(update_fields=['role', 'updated_at'])
    return locked_membership
