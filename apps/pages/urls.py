from django.urls import path

from apps.pages import views

app_name = 'pages'

urlpatterns = [
    path('', views.project_pages, name='overview'),
    path('scatter-tooltips/', views.scatter_tooltips, name='scatter_tooltips'),
]

