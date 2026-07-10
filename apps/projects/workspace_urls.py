from django.urls import path

from apps.projects import views

app_name = 'workspaces'

urlpatterns = [
    path('create/', views.workspace_create, name='workspace_create'),
    path('<int:workspace_id>/settings/details/', views.workspace_details, name='workspace_details'),
    path('<int:workspace_id>/settings/details/update/', views.update_workspace_details, name='update_workspace_details'),
    path('<int:workspace_id>/settings/details/update-name/', views.update_workspace_name, name='update_workspace_name'),
    path('<int:workspace_id>/settings/details/update-slug/', views.update_workspace_slug, name='update_workspace_slug'),
    path('<int:workspace_id>/settings/details/update-website/', views.update_workspace_website, name='update_workspace_website'),
    path('<int:workspace_id>/settings/details/openai-key/', views.save_workspace_openai_key, name='save_workspace_openai_key'),
    path('<int:workspace_id>/settings/details/openai-key/validate/', views.validate_workspace_openai_key_view, name='validate_workspace_openai_key'),
    path('<int:workspace_id>/settings/details/openai-key/remove/', views.remove_workspace_openai_key, name='remove_workspace_openai_key'),
    path('<int:workspace_id>/settings/team/', views.workspace_team, name='workspace_team'),
    path('<int:workspace_id>/settings/team/add/', views.workspace_add_member, name='workspace_add_member'),
    path('<int:workspace_id>/settings/team/leave/', views.leave_workspace, name='leave_workspace'),
    path('<int:workspace_id>/settings/details/delete/', views.delete_workspace, name='delete_workspace'),
    path(
        '<int:workspace_id>/settings/team/members/<int:membership_id>/remove/',
        views.remove_workspace_member,
        name='remove_workspace_member',
    ),
    path(
        '<int:workspace_id>/settings/team/members/<int:membership_id>/role/',
        views.update_workspace_member_role,
        name='update_workspace_member_role',
    ),
]
