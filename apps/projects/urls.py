from django.urls import path

from apps.projects import views


app_name = 'projects'

urlpatterns = [
    path('', views.project_list, name='project_list'),
    path('projects/create/', views.project_create, name='project_create'),
    path('<int:pk>/delete/', views.project_delete, name='project_delete'),
    path('<int:project_id>/settings/', views.project_settings, name='project_settings'),
    path('<int:project_id>/update-name/', views.update_project_name, name='update_project_name'),
    path('<int:project_id>/update-timezone/', views.update_project_timezone, name='update_project_timezone'),
    path('<int:project_id>/create_and_add_user_to_project/', views.create_and_add_user_to_project, name='create_and_add_user_to_project'),
    path('<int:project_id>/remove_active_user/<int:membership_id>/', views.remove_active_user,
         name='remove_active_user'),
    path('<int:project_id>/delete_left_user/<int:user_id>/', views.delete_left_user,
         name='delete_left_user'),
    path('<int:project_id>/save-chatgpt-key/', views.save_chatgpt_key, name='save_chatgpt_key'),
    path('<int:project_id>/check-chatgpt-key/', views.check_chatgpt_key, name='check_chatgpt_key'),
    path('<int:project_id>/remove-chatgpt-key/', views.remove_chatgpt_key, name='remove_chatgpt_key'),
]
