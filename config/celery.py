import os

from celery import Celery

from config.utils import get_django_settings_module

os.environ.setdefault('DJANGO_SETTINGS_MODULE', get_django_settings_module())

app = Celery('proj')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
app.conf.beat_scheduler = 'django_celery_beat.schedulers:DatabaseScheduler'
