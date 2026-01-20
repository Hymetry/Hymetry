from django.urls import path

from apps.tracker import views

app_name = 'tracker'

urlpatterns = [
    path('api/record-event/', views.record_event, name='record_event'),
]
