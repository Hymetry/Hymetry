from allauth.account.views import LogoutView
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import path, include, re_path

from apps.projects.views import project_list
from apps.tracker.views import recordings, recording, get_consolidated_data, asset_proxy
from apps.users.views import (
    AutoLoginConfirmEmailView, CustomSignupView, custom_email_verification_sent,
    sign_in, welcome, password_reset_request, password_reset_email_sent,
    password_reset_set_new, password_reset_success
)
from config.views import github_push_event_handler

urlpatterns = [
    path('', project_list, name='index'),  # Homepage
    path('admin/', admin.site.urls),
    path('asset-proxy', asset_proxy, name='asset_proxy'),
    # Custom email confirmation must come BEFORE allauth.urls
    re_path(
        r"^accounts/confirm-email/(?P<key>[-:\w]+)/$",
        AutoLoginConfirmEmailView.as_view(),
        name="account_confirm_email"
    ),
    path('accounts/', include('allauth.urls')),
    path('tracker/', include('apps.tracker.urls')),
    path('projects/', include('apps.projects.urls')),
    path('account/', include('apps.users.urls')),
    # custom tracker urls
    path('projects/<int:project_id>/recordings/', recordings, name='recordings'),
    path('projects/<int:project_id>/', recordings, name='project_detail'),
    path('projects/<int:project_id>/recordings/<uuid:session_id>/', recording, name='recording'),
    path('projects/<int:project_id>/recordings/<uuid:session_id>/data/', get_consolidated_data,
         name='get_consolidated_data'),

    path('sign-up/', CustomSignupView.as_view(), name='sign_up'),
    path('sign-up/email-sent/', custom_email_verification_sent, name='sign_up_email_sent'),
    path('sign-in/', sign_in, name='sign_in'),
    path('sign-out/', LogoutView.as_view(), name='sign_out'),
    path('welcome/', welcome, name='welcome'),
    # Password reset URLs
    path('password/reset/request/', password_reset_request, name='password_reset_request'),
    path('password/reset/email-sent/', password_reset_email_sent, name='password_reset_email_sent'),
    path('password/reset/set-new/<str:uidb64>/<str:token>/', password_reset_set_new, name='password_reset_set_new'),
    path('password/reset/success/', password_reset_success, name='password_reset_success'),
    path('webhook-kpXoLsYbH6cZpEPyQ', github_push_event_handler, name='github_push_event_handler'),

]

# Serve static and media files in development
if settings.DEBUG:
    # Serve static files from STATICFILES_DIRS
    for static_dir in settings.STATICFILES_DIRS:
        urlpatterns += static(settings.STATIC_URL, document_root=static_dir)
    # Also serve files from STATIC_ROOT
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += staticfiles_urlpatterns()

    # Serve media files in development
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
