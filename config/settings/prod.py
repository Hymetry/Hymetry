from .base import *
import sentry_sdk

# Production settings
DEBUG = False
SESSION_COOKIE_AGE = 15768000  # 6 months in seconds

# WhiteNoise configuration for static files
STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'

# Add WhiteNoise middleware for production
MIDDLEWARE = [
    'axes.middleware.AxesMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # WhiteNoise for production
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'apps.projects.middleware.InvitationRedirectMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    "allauth.account.middleware.AccountMiddleware",
]

# Security settings for production
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# HTTPS settings (uncomment when you have SSL)
# SECURE_SSL_REDIRECT = True
# SECURE_HSTS_SECONDS = 31536000
# SECURE_HSTS_INCLUDE_SUBDOMAINS = True
# SECURE_HSTS_PRELOAD = True

if os.getenv("DJANGO_ENV") == "production":
    sentry_sdk.init(
        dsn="https://522a49b200e42995c6e6a0665ee9949b@o4509655757619200.ingest.us.sentry.io/4509655772823552",
        # Add data like request headers and IP for users,
        # see https://docs.sentry.io/platforms/python/data-management/data-collected/ for more info
        send_default_pii=True,
        traces_sample_rate=1.0,
    )

import os

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'github_webhook_file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': '/var/log/github_webhook.log',
        },
    },
    'loggers': {
        'github_webhook': {
            'handlers': ['github_webhook_file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}


GITHUB_SECRET = 'Ct2Lit4aby2dHcYKwKbesYKBmLXtnAnxjVYopseFbwx'