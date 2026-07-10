from functools import wraps

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import (
    Project,
    Workspace,
    WorkspaceMemberRole,
    WorkspaceMemberStatus,
    WorkspaceMembership,
)


INVITABLE_ROLES_BY_ROLE = {
    WorkspaceMemberRole.OWNER: {
        WorkspaceMemberRole.OWNER,
        WorkspaceMemberRole.ADMIN,
        WorkspaceMemberRole.MEMBER,
        WorkspaceMemberRole.VIEWER,
    },
    WorkspaceMemberRole.ADMIN: {
        WorkspaceMemberRole.ADMIN,
        WorkspaceMemberRole.MEMBER,
        WorkspaceMemberRole.VIEWER,
    },
    WorkspaceMemberRole.MEMBER: set(),
    WorkspaceMemberRole.VIEWER: set(),
}

ASSIGNABLE_WORKSPACE_ROLES = {
    WorkspaceMemberRole.OWNER,
    WorkspaceMemberRole.ADMIN,
    WorkspaceMemberRole.MEMBER,
    WorkspaceMemberRole.VIEWER,
}

ADMIN_MANAGED_ROLES = {
    WorkspaceMemberRole.ADMIN,
    WorkspaceMemberRole.MEMBER,
    WorkspaceMemberRole.VIEWER,
}

PROJECT_CREATOR_ROLES = {
    WorkspaceMemberRole.OWNER,
}

SETTINGS_EDITOR_ROLES = {
    WorkspaceMemberRole.OWNER,
    WorkspaceMemberRole.ADMIN,
    WorkspaceMemberRole.MEMBER,
}

WORKSPACE_EDITOR_ROLES = {
    WorkspaceMemberRole.OWNER,
    WorkspaceMemberRole.ADMIN,
}

MEMBER_MANAGER_ROLES = {
    WorkspaceMemberRole.OWNER,
    WorkspaceMemberRole.ADMIN,
}


def effective_workspace_role(role):
    return role


def workspace_role_label(role):
    labels = dict(WorkspaceMemberRole.choices)
    effective_role = effective_workspace_role(role)
    return labels.get(effective_role, str(effective_role or ''))


def active_workspace_memberships():
    return WorkspaceMembership.objects.filter(
        status=WorkspaceMemberStatus.ACTIVE,
        removed_at__isnull=True,
        workspace__archived_at__isnull=True,
    )


def get_workspace_membership(user, workspace):
    if not getattr(user, 'is_authenticated', False):
        return None
    return active_workspace_memberships().filter(user=user, workspace=workspace).first()


def get_project_workspace_membership(user, project):
    if not getattr(user, 'is_authenticated', False):
        return None
    return active_workspace_memberships().filter(user=user, workspace=project.workspace).first()


def user_can_access_workspace(user, workspace):
    return bool(getattr(user, 'is_superuser', False) or get_workspace_membership(user, workspace))


def user_can_access_project(user, project):
    return bool(getattr(user, 'is_superuser', False) or get_project_workspace_membership(user, project))


def user_can_create_workspace(user):
    if not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    return active_workspace_memberships().filter(
        user=user,
        role=WorkspaceMemberRole.OWNER,
    ).exists()


def user_can_create_project(user, workspace):
    if getattr(user, 'is_superuser', False):
        return True
    membership = get_workspace_membership(user, workspace)
    return bool(membership and effective_workspace_role(membership.role) in PROJECT_CREATOR_ROLES)


def user_can_manage_workspace_openai_key(user, workspace):
    return user_can_create_project(user, workspace)


def user_can_edit_project_settings(user, project):
    if getattr(user, 'is_superuser', False):
        return True
    membership = get_project_workspace_membership(user, project)
    return bool(membership and effective_workspace_role(membership.role) in SETTINGS_EDITOR_ROLES)


def user_can_edit_workspace(user, workspace):
    if getattr(user, 'is_superuser', False):
        return True
    membership = get_workspace_membership(user, workspace)
    return bool(membership and effective_workspace_role(membership.role) in WORKSPACE_EDITOR_ROLES)


def user_can_manage_members(user, workspace):
    if getattr(user, 'is_superuser', False):
        return True
    membership = get_workspace_membership(user, workspace)
    return bool(membership and effective_workspace_role(membership.role) in MEMBER_MANAGER_ROLES)


def user_can_remove_workspace_member(user, workspace, target_membership):
    if getattr(user, 'is_superuser', False):
        return target_membership.workspace_id == workspace.id and not is_last_owner(target_membership)
    actor_membership = get_workspace_membership(user, workspace)
    if not actor_membership:
        return False
    if target_membership.workspace_id != workspace.id:
        return False
    actor_role = effective_workspace_role(actor_membership.role)
    target_role = effective_workspace_role(target_membership.role)
    if target_membership.user_id == user.id:
        return not is_last_owner(target_membership)
    if actor_role == WorkspaceMemberRole.OWNER:
        return not is_last_owner(target_membership)
    if actor_role == WorkspaceMemberRole.ADMIN and target_role in ADMIN_MANAGED_ROLES:
        return True
    return False


def user_can_assign_workspace_role(user, workspace, target_membership, role):
    if getattr(user, 'is_superuser', False):
        return (
            target_membership.workspace_id == workspace.id
            and role in ASSIGNABLE_WORKSPACE_ROLES
            and not (
                effective_workspace_role(target_membership.role) == WorkspaceMemberRole.OWNER
                and role != WorkspaceMemberRole.OWNER
                and is_last_owner(target_membership)
            )
        )
    actor_membership = get_workspace_membership(user, workspace)
    if not actor_membership:
        return False
    if target_membership.workspace_id != workspace.id:
        return False
    if role not in ASSIGNABLE_WORKSPACE_ROLES:
        return False
    actor_role = effective_workspace_role(actor_membership.role)
    target_role = effective_workspace_role(target_membership.role)
    if (
        target_role == WorkspaceMemberRole.OWNER
        and role != WorkspaceMemberRole.OWNER
        and is_last_owner(target_membership)
    ):
        return False
    if actor_role == WorkspaceMemberRole.OWNER:
        return True
    if (
        actor_role == WorkspaceMemberRole.ADMIN
        and target_role in ADMIN_MANAGED_ROLES
        and role in ADMIN_MANAGED_ROLES
    ):
        return True
    return False


def user_can_invite_role(user, workspace, role):
    membership = get_workspace_membership(user, workspace)
    if not membership:
        return False
    return role in INVITABLE_ROLES_BY_ROLE.get(effective_workspace_role(membership.role), set())


def active_owner_count(workspace):
    return active_workspace_memberships().filter(
        workspace=workspace,
        role=WorkspaceMemberRole.OWNER,
    ).count()


def is_last_owner(membership):
    return (
        effective_workspace_role(membership.role) == WorkspaceMemberRole.OWNER
        and active_owner_count(membership.workspace) <= 1
    )


def remove_workspace_membership(membership):
    if is_last_owner(membership):
        raise PermissionDenied('Transfer ownership before leaving this workspace.')
    membership.status = WorkspaceMemberStatus.REMOVED
    membership.removed_at = timezone.now()
    membership.save(update_fields=['status', 'removed_at', 'updated_at'])


def get_accessible_project_or_404(user, project_id):
    project = get_object_or_404(Project.active.select_related('workspace'), pk=project_id)
    if project.workspace.archived_at is not None:
        raise Http404('No Project matches the given query.')
    if not user_can_access_project(user, project):
        raise PermissionDenied('You do not have access to this project.')
    return project


def get_accessible_workspace_or_404(user, workspace_id):
    value = str(workspace_id or '').strip()
    lookup = {'public_id': int(value)} if value.isdigit() else {'pk': value}
    try:
        workspace = Workspace.active.get(**lookup)
    except (Workspace.DoesNotExist, TypeError, ValueError, ValidationError):
        raise Http404('No Workspace matches the given query.')
    if not user_can_access_workspace(user, workspace):
        raise PermissionDenied('You do not have access to this workspace.')
    return workspace


def require_project_member(view_func):
    @wraps(view_func)
    def wrapper(request, project_id, *args, **kwargs):
        get_accessible_project_or_404(request.user, project_id)
        return view_func(request, project_id, *args, **kwargs)
    return wrapper


def require_project_settings_editor(view_func):
    @wraps(view_func)
    def wrapper(request, project_id, *args, **kwargs):
        project = get_accessible_project_or_404(request.user, project_id)
        if not user_can_edit_project_settings(request.user, project):
            raise PermissionDenied('You do not have access to project settings.')
        return view_func(request, project_id, *args, **kwargs)
    return wrapper


def require_workspace_member(view_func):
    @wraps(view_func)
    def wrapper(request, workspace_id, *args, **kwargs):
        get_accessible_workspace_or_404(request.user, workspace_id)
        return view_func(request, workspace_id, *args, **kwargs)
    return wrapper
