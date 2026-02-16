from allauth.account.views import LogoutView, LoginView
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import path, include

from apps.projects.views import project_list
from apps.tracker.views import recordings, recording, get_consolidated_data, asset_proxy

from apps.projects.cls.homepage import homepage

urlpatterns = [
    path('', homepage, name='index'),  # Homepage
    path('project-list/', project_list, name='project_list'),  # Homepage
    path('admin/', admin.site.urls),
    path('asset-proxy', asset_proxy, name='asset_proxy'),

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

    path('sign-in/', LoginView.as_view(template_name='users/sign_in.html'),name='sign_in'),
    path('sign-out/', LogoutView.as_view(), name='sign_out'),

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
