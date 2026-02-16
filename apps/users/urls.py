from django.urls import path

from apps.users.views import create_admin_account, user_profile, validate_old_password

app_name = 'users'

urlpatterns = [
    path('create-admin-account/', create_admin_account, name='create_admin_account'),
    path('profile/', user_profile, name='user_profile'),
    path('profile/validate-password/', validate_old_password, name='account_validate_old_password'),
]
