from django.urls import path

from apps.users.views import user_profile, validate_old_password

app_name = 'users'

# other links are in the config.urls due to links root path requirements
urlpatterns = [
    path('profile/', user_profile, name='user_profile'),
    path('profile/validate-password/', validate_old_password, name='account_validate_old_password'),
    # Email confirmation is handled by AutoLoginConfirmEmailView in config/urls.py
]
