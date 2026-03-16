from .base import *

# Production settings
DEBUG = False
SESSION_COOKIE_AGE = 15768000  # 6 months in seconds
DJANGO_SETTINGS_MODULE='config.settings.prod'
# WhiteNoise configuration for static files
STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"

# Add WhiteNoise middleware for production
MIDDLEWARE = [
    'axes.middleware.AxesMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # WhiteNoise for production
    'config.runtime_url_middleware.RuntimeURLBootstrapMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    "allauth.account.middleware.AccountMiddleware",
]

# Security settings for production
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL

if REDIS_URL.startswith("rediss://"):
    CELERY_BROKER_USE_SSL = {"ssl_cert_reqs": "none"}
    CELERY_REDIS_BACKEND_USE_SSL = {"ssl_cert_reqs": "none"}

import sys

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": sys.stdout,
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}
