from django.urls import path

from apps.users.views import initial_admin_setup, user_profile, validate_old_password

app_name = 'users'

urlpatterns = [
    path('setup/admin/', initial_admin_setup, name='initial_admin_setup'),
    path('profile/', user_profile, name='user_profile'),
    path('profile/validate-password/', validate_old_password, name='account_validate_old_password'),
]
