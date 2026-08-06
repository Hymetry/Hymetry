from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.http import HttpResponse
from django.urls import include, path

from apps.projects import views as project_views
from apps.tracker.views import (
    asset_proxy,
    get_consolidated_data,
    record_analytics,
    record_event,
    recording,
    recordings,
    replay_stream,
    visits_filter_options,
)
from apps.users.views import InitialSetupAwareLoginView


urlpatterns = [
    path('health', lambda request: HttpResponse(status=200), name='health'),
    path('', project_views.homepage, name='index'),
    path('project-list/', project_views.project_list, name='project_list'),
    path('admin/', admin.site.urls),
    path('asset-proxy', asset_proxy, name='asset_proxy'),
    path('hm/e/', record_event, name='record_event'),
    path('hm/ae/', record_analytics, name='record_analytics'),
    path('tracker/', include('apps.tracker.urls')),
    path('w/', include('apps.projects.workspace_slug_urls')),
    path('workspaces/', include('apps.projects.workspace_urls')),
    path('onboarding/first-project/', project_views.onboarding_first_project, name='onboarding_first_project'),
    path('projects/', include('apps.projects.urls')),
    path('account/', include('apps.users.urls')),
    path('projects/<int:project_id>/visits', recordings, name='recordings'),
    path('projects/<int:project_id>/visits/filter-options', visits_filter_options, name='visits_filter_options'),
    path('projects/<int:project_id>/visits/<uuid:session_id>/data', get_consolidated_data, name='get_consolidated_data'),
    path('projects/<int:project_id>/visits/<uuid:session_id>/stream', replay_stream, name='replay_stream'),
    path('projects/<int:project_id>/visits/<uuid:session_id>', recording, name='recording'),
    path('projects/<int:project_id>/', project_views.project_detail_redirect, name='project_detail'),
    path(
        'sign-in/',
        InitialSetupAwareLoginView.as_view(),
        name='sign_in',
    ),
    path('sign-out/', LogoutView.as_view(next_page='sign_in'), name='sign_out'),
]


if settings.DEBUG:
    for static_dir in settings.STATICFILES_DIRS:
        urlpatterns += static(settings.STATIC_URL, document_root=static_dir)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += staticfiles_urlpatterns()
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
