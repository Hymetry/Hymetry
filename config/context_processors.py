from django.conf import settings


def password_policy(request):
    return {
        'password_min_length': settings.PASSWORD_MIN_LENGTH,
        'password_max_length': settings.PASSWORD_MAX_LENGTH,
    }


def project_context(request):
    context = {}
    if not request.user.is_authenticated:
        return context

    from apps.projects.access import active_workspace_memberships
    from apps.projects.models import Project

    memberships = list(
        active_workspace_memberships()
        .filter(user=request.user)
        .select_related('workspace')
        .order_by('workspace__name', 'workspace__created_at')
    )
    workspace_ids = [membership.workspace_id for membership in memberships]
    projects = list(
        Project.active.filter(workspace_id__in=workspace_ids)
        .select_related('workspace')
        .order_by('workspace__name', 'name')
    )
    membership_by_workspace = {membership.workspace_id: membership for membership in memberships}
    projects_by_workspace = {}
    for project in projects:
        projects_by_workspace.setdefault(project.workspace_id, []).append(project)

    selected_project = None
    try:
        requested_project_id = int(request.GET.get('project', ''))
        selected_project = next((project for project in projects if project.id == requested_project_id), None)
    except (TypeError, ValueError):
        pass

    path_parts = request.path.strip('/').split('/')
    if selected_project is None:
        project_id = None
        if len(path_parts) >= 4 and path_parts[0] == 'w' and path_parts[2] == 'projects' and path_parts[3].isdigit():
            project_id = int(path_parts[3])
        elif len(path_parts) >= 2 and path_parts[0] == 'projects' and path_parts[1].isdigit():
            project_id = int(path_parts[1])
        if project_id is not None:
            selected_project = next((project for project in projects if project.id == project_id), None)

    selected_workspace = selected_project.workspace if selected_project else None
    if selected_workspace is None and len(path_parts) >= 2 and path_parts[0] == 'w':
        selected_workspace = next(
            (
                membership.workspace
                for membership in memberships
                if path_parts[1] in {membership.workspace.slug, membership.workspace.previous_slug}
            ),
            None,
        )

    selected_membership = (
        membership_by_workspace.get(selected_workspace.id)
        if selected_workspace
        else None
    )
    nav_workspaces = [
        {
            'workspace': membership.workspace,
            'membership': membership,
            'projects': projects_by_workspace.get(membership.workspace_id, []),
        }
        for membership in memberships
    ]
    user_projects = [
        {
            'project': project,
            'role': membership_by_workspace[project.workspace_id].role,
            'is_owner': membership_by_workspace[project.workspace_id].role == 'owner',
        }
        for project in projects
    ]

    context.update({
        'nav_workspaces': nav_workspaces,
        'workspace_memberships': memberships,
        'user_projects': user_projects,
        'selected_project': selected_project,
        'selected_workspace': selected_workspace,
        'selected_workspace_membership': selected_membership,
        'nav_context': 'project' if selected_project else ('workspace' if selected_workspace else 'global'),
    })
    return context
