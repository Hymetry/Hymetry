from functools import wraps

from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from .access import user_can_access_project, user_can_access_workspace
from .models import Project, Workspace


def _with_query_string(request, url):
    query_string = request.META.get('QUERY_STRING')
    return f'{url}?{query_string}' if query_string else url


def project_route(project, route_name, **kwargs):
    route_kwargs = {
        'workspace_slug': project.workspace.slug,
        'project_id': project.id,
        **kwargs,
    }
    return reverse(f'w:{route_name}', kwargs=route_kwargs)


def project_pk_route(project, route_name, **kwargs):
    route_kwargs = {
        'workspace_slug': project.workspace.slug,
        'pk': project.id,
        **kwargs,
    }
    return reverse(f'w:{route_name}', kwargs=route_kwargs)


def workspace_route(workspace, route_name, **kwargs):
    return reverse(f'w:{route_name}', kwargs={'workspace_slug': workspace.slug, **kwargs})


def _current_slug_redirect(request, workspace):
    resolver_match = request.resolver_match
    if not resolver_match or not resolver_match.namespace or not resolver_match.url_name:
        raise Http404('No matching workspace route.')
    kwargs = dict(resolver_match.kwargs)
    kwargs['workspace_slug'] = workspace.slug
    url = reverse(f'{resolver_match.namespace}:{resolver_match.url_name}', kwargs=kwargs)
    return redirect(_with_query_string(request, url))


def _resolve_workspace_for_slug(user, workspace_slug):
    try:
        workspace = Workspace.active.get(slug=workspace_slug)
    except Workspace.DoesNotExist:
        try:
            workspace = Workspace.active.get(previous_slug=workspace_slug)
        except Workspace.DoesNotExist as exc:
            raise Http404('No Workspace matches the given slug.') from exc

    if not user_can_access_workspace(user, workspace):
        raise PermissionDenied('You do not have access to this workspace.')
    return workspace


def _resolve_project_for_slug(user, workspace_slug, project_id):
    project = get_object_or_404(Project.active.select_related('workspace'), pk=project_id)
    if project.workspace.archived_at is not None:
        raise Http404('No Project matches the given workspace slug.')
    if not user_can_access_project(user, project):
        raise PermissionDenied('You do not have access to this project.')
    if workspace_slug not in {project.workspace.slug, project.workspace.previous_slug}:
        raise Http404('No Project matches the given workspace slug.')
    return project


def workspace_slug_view(view_func):
    @wraps(view_func)
    def wrapper(request, workspace_slug, *args, **kwargs):
        if not request.user.is_authenticated:
            return view_func(request, workspace_slug, *args, **kwargs)

        workspace = _resolve_workspace_for_slug(request.user, workspace_slug)
        if workspace.slug != workspace_slug:
            return _current_slug_redirect(request, workspace)
        return view_func(request, workspace.public_id, *args, **kwargs)

    return wrapper


def project_slug_view(view_func):
    @wraps(view_func)
    def wrapper(request, workspace_slug, project_id, *args, **kwargs):
        if not request.user.is_authenticated:
            return view_func(request, project_id, *args, **kwargs)

        project = _resolve_project_for_slug(request.user, workspace_slug, project_id)
        if project.workspace.slug != workspace_slug:
            return _current_slug_redirect(request, project.workspace)
        return view_func(request, project_id, *args, **kwargs)

    return wrapper


def project_pk_slug_view(view_func):
    @wraps(view_func)
    def wrapper(request, workspace_slug, pk, *args, **kwargs):
        if not request.user.is_authenticated:
            return view_func(request, pk, *args, **kwargs)

        project = _resolve_project_for_slug(request.user, workspace_slug, pk)
        if project.workspace.slug != workspace_slug:
            return _current_slug_redirect(request, project.workspace)
        return view_func(request, pk, *args, **kwargs)

    return wrapper
