from functools import wraps

from django.core.exceptions import PermissionDenied

from .access import get_accessible_project_or_404, get_workspace_membership, require_project_member
from .models import WorkspaceMemberRole


def require_project_owner(view_func):
    @wraps(view_func)
    def wrapper(request, project_id, *args, **kwargs):
        project = get_accessible_project_or_404(request.user, project_id)
        membership = get_workspace_membership(request.user, project.workspace)
        if not membership or membership.role != WorkspaceMemberRole.OWNER:
            raise PermissionDenied('Only workspace owners can access this project action.')
        return view_func(request, project_id, *args, **kwargs)
    return wrapper


def require_project_member_or_owner(view_func):
    return require_project_member(view_func)


def require_project_access(access_type='member'):
    if access_type == 'owner':
        return require_project_owner
    return require_project_member
