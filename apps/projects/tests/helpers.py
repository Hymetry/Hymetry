from apps.projects.models import Workspace, WorkspaceMemberRole, WorkspaceMemberStatus, WorkspaceMembership


def create_workspace_with_owner(user, name='Test Workspace', website_url='example.com'):
    workspace = Workspace.objects.create(
        name=name,
        website_url=website_url,
        created_by=user,
    )
    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=user,
        role=WorkspaceMemberRole.OWNER,
        status=WorkspaceMemberStatus.ACTIVE,
    )
    return workspace
