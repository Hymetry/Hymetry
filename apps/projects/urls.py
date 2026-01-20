from django.urls import path

from apps.projects import views

app_name = 'projects'

urlpatterns = [
    path('', views.project_list, name='project_list'),
    path('<int:project_id>/intro/', views.project_intro, name='project_intro'),
    path('projects/create/', views.project_create, name='project_create'),
    path('<int:pk>/delete/', views.project_delete, name='project_delete'),
    path('<int:project_id>/invite/', views.invite_user, name='invite_user'),
    path('<int:project_id>/invite-multiple/', views.invite_multiple_users, name='invite_multiple_users'),
    path('<int:project_id>/validate-emails/', views.validate_emails, name='validate_emails'),
    path('<int:project_id>/settings/', views.project_settings, name='project_settings'),
    path('<int:project_id>/update-name/', views.update_project_name, name='update_project_name'),
    path('<int:project_id>/update-timezone/', views.update_project_timezone, name='update_project_timezone'),
    path('<int:project_id>/resend_invitation/<str:token>/', views.resend_invitation, name='resend_invitation'),
    path('<int:project_id>/cancel_invitation/<str:token>/', views.cancel_invitation, name='cancel_invitation'),
    path('<int:project_id>/remove_invitation/<str:token>/', views.remove_invitation, name='remove_invitation'),
    path('accept/<str:token>/', views.accept_invitation, name='accept_invitation'),
    path('invitations/<str:token>/accept/', views.invitation_accept, name='invitation_accept'),
    path('invitations/<str:token>/accept-action/', views.accept_invitation_action, name='accept_invitation_action'),
    path('invitations/<str:token>/create-account/', views.invitation_create_account, name='invitation_create_account'),
    path('<int:project_id>/remove_active_user/<int:membership_id>/', views.remove_active_user,
         name='remove_active_user'),
]
