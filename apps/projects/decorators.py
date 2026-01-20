from functools import wraps
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from .models import Project, ProjectMembership


def require_project_access(access_type='member'):
    """
    Decorator to check project access permissions.
    
    Args:
        access_type (str): Type of access required
            - 'member': User must be a project member
            - 'owner': User must be the project owner
            - 'member_or_owner': User must be either a member or the owner
    
    Usage:
        @require_project_access('member')
        def my_view(request, project_id):
            # project_id is available, get project with get_object_or_404 if needed
            pass
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, project_id, *args, **kwargs):
            project = get_object_or_404(Project, pk=project_id)
            
            if access_type == 'owner':
                if request.user != project.owner:
                    raise PermissionDenied(
                        f'Only the project owner can perform this action. '
                        f'This project is owned by {project.owner.get_full_name() or project.owner.username}.'
                    )
            elif access_type == 'member':
                is_member = ProjectMembership.objects.filter(
                    project=project, user=request.user
                ).exists()
                if not is_member:
                    raise PermissionDenied(
                        f'You do not have access to this project. '
                        f'Please contact the project owner ({project.owner.get_full_name() or project.owner.username}) '
                        f'to request access to "{project.name}".'
                    )
            elif access_type == 'member_or_owner':
                is_member = ProjectMembership.objects.filter(
                    project=project, user=request.user
                ).exists()
                if not is_member and request.user != project.owner:
                    raise PermissionDenied(
                        f'You do not have access to this project. '
                        f'Please contact the project owner ({project.owner.get_full_name() or project.owner.username}) '
                        f'to request access to "{project.name}".'
                    )
            
            return view_func(request, project_id, *args, **kwargs)
        return wrapper
    return decorator


def require_project_owner(view_func):
    """
    Decorator to check if user is the project owner.
    
    Usage:
        @require_project_owner
        def my_view(request, project_id):
            pass
    """
    return require_project_access('owner')(view_func)


def require_project_member(view_func):
    """
    Decorator to check if user is a project member.
    
    Usage:
        @require_project_member
        def my_view(request, project_id):
            pass
    """
    return require_project_access('member')(view_func)


def require_project_member_or_owner(view_func):
    """
    Decorator to check if user is either a project member or the owner.
    
    Usage:
        @require_project_member_or_owner
        def my_view(request, project_id):
            pass
    """
    return require_project_access('member_or_owner')(view_func) 