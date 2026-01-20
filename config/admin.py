# your_project/admin.py
from django.contrib import admin
from django_celery_beat.models import PeriodicTask, IntervalSchedule, CrontabSchedule

admin.site.register(PeriodicTask)
admin.site.register(IntervalSchedule)
admin.site.register(CrontabSchedule)
