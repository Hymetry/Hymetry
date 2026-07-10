import os
import secrets
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('SECRET_KEY', secrets.token_urlsafe(50))

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'True') == 'True'

HYMETRY_DOMAIN = os.getenv("HYMETRY_DOMAIN", "http://localhost")
# 1. Try to get the name Heroku assigned
APP_NAME = os.environ.get('HEROKU_APP_NAME')

if APP_NAME:
    # If Metadata is enabled, we know the exact URL
    HYMETRY_DOMAIN = f"https://{APP_NAME}.herokuapp.com"
    CSRF_TRUSTED_ORIGINS = [HYMETRY_DOMAIN]
else:
    # 2. THE FAILSAFE: Use a wildcard for all Heroku apps
    # This allows the '1-click' install to work immediately
    # without the user entering anything.
    HYMETRY_DOMAIN = os.environ.get('HYMETRY_DOMAIN', '')
    CSRF_TRUSTED_ORIGINS = [
        "https://*.herokuapp.com",
        "https://*.onrender.com",
    ]

# Ensure ALLOWED_HOSTS matches (supports self-hosted custom domains)
_allowed_hosts_env = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()]
ALLOWED_HOSTS = [".herokuapp.com", ".onrender.com", "localhost", "127.0.0.1", *_allowed_hosts_env]

if HYMETRY_DOMAIN:
    site_host = urlparse(HYMETRY_DOMAIN).hostname
    if site_host and site_host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(site_host)
    CSRF_TRUSTED_ORIGINS.append(HYMETRY_DOMAIN)

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_celery_beat',
    'apps.core',
    'apps.users',
    'corsheaders',
    'axes',
    'apps.tracker',
    'apps.pages',
    'apps.projects'
]

MIDDLEWARE = [
    'axes.middleware.AxesMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'config.runtime_url_middleware.RuntimeURLBootstrapMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# CORS settings
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = False  # Must be False when using CORS_ALLOW_ALL_ORIGINS
CORS_ALLOW_METHODS = [
    'GET',
    'POST',
    'OPTIONS',
]
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
]

# Add CORS headers to static files
CORS_ALLOW_STATIC_FILES = True

# Add security headers for static files
SECURE_CROSS_ORIGIN_OPENER_POLICY = None

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'config.context_processors.project_context',
                'config.context_processors.password_policy',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DEV = os.getenv('DEV')

# CORS_TRUSTED_ORIGIN
HYMETRY_DOMAIN = (HYMETRY_DOMAIN or "http://localhost").rstrip("/")
# Tracking script / edge URL
EDGE_URL = os.getenv("EDGE_URL", f"{HYMETRY_DOMAIN}/static/js")
HOSTED_DEMO_URL = os.getenv('HOSTED_DEMO_URL', 'https://app.hymetry.com/projects/demo/').strip()
OPENAI_KEY_ENCRYPTION_KEYS = os.getenv('OPENAI_KEY_ENCRYPTION_KEYS', '').strip()
ASSET_PROXY_MAX_BYTES = int(os.getenv('ASSET_PROXY_MAX_BYTES', str(5 * 1024 * 1024)))
ASSET_PROXY_TIMEOUT_SECONDS = float(os.getenv('ASSET_PROXY_TIMEOUT_SECONDS', '10'))
ASSET_PROXY_MAX_REDIRECTS = int(os.getenv('ASSET_PROXY_MAX_REDIRECTS', '3'))
ASSET_PROXY_ALLOW_PRIVATE_HOSTS = os.getenv('ASSET_PROXY_ALLOW_PRIVATE_HOSTS', 'False').lower() == 'true'

import dj_database_url
DATABASES = {
    "default": dj_database_url.parse(
        os.getenv("DATABASE_URL"),
        conn_max_age=600
    )
}

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': PASSWORD_MIN_LENGTH},
    },
    {
        'NAME': 'apps.users.password_validation.MaximumLengthValidator',
        'OPTIONS': {'max_length': PASSWORD_MAX_LENGTH},
    }
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [
    BASE_DIR / 'static'
]

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesBackend',
    'django.contrib.auth.backends.ModelBackend',
]

SESSION_EXPIRATION_SECONDS = int(os.getenv('SESSION_EXPIRATION_SECONDS', '1800').split('#')[0].strip())
SESSION_MAX_CLOCK_SKEW_SECONDS = int(os.getenv('SESSION_MAX_CLOCK_SKEW_SECONDS', '300').split('#')[0].strip())
ANALYTICS_SESSION_EXPIRATION_SECONDS = int(
    os.getenv('ANALYTICS_SESSION_EXPIRATION_SECONDS', '1800').split('#')[0].strip()
)

LOGIN_URL = '/sign-in/'
LOGIN_REDIRECT_URL = '/projects/'

EMAIL_BACKEND = 'django.core.mail.backends.dummy.EmailBackend'

# AXES - attempts locker (python manage.py axes_reset - to RESET)
AXES_FAILURE_LIMIT = 5  # кількість дозволених невдалих спроб
AXES_COOLOFF_TIME = 0.08  # хвилин блокування (0.08 * 60 = 4.8 хвилин)
AXES_RESET_ON_SUCCESS = True

# Celery settings
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://redis:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'redis://redis:6379/0')
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_SEND_SENT_EVENT = True
PAGES_QUEUE_REBUILDS_ON_REQUEST = os.getenv('PAGES_QUEUE_REBUILDS_ON_REQUEST', 'True').lower() == 'true'

ROWS_PER_PAGE = int(os.environ.get('ROWS_PER_PAGE', 100))

# Custom error handlers
HANDLER403 = 'config.views.permission_denied'
HANDLER404 = 'config.views.page_not_found'
HANDLER500 = 'config.views.server_error'


PAGE_NAMING_PROMPT_URL_LIMIT = 150
PAGE_NAMING_HYBRID_TOP_LIMIT = 100
PAGE_NAMING_HYBRID_RANDOM_LIMIT = 200
PAGE_NAMING_TITLE_BACKFILL_URL_LIMIT = 100
PAGE_NAMING_NEW_URLS_SHORT_WINDOW_SECONDS = 60 * 60
PAGE_NAMING_NEW_URLS_LONG_WINDOW_SECONDS = 24 * 60 * 60
PAGE_NAMING_COMPARISON_WINDOW_SECONDS = 4 * 24 * 60 * 60
PAGE_NAMING_UNSTABLE_REWRITE_WINDOW_SECONDS = 4 * 24 * 60 * 60
PAGE_NAMING_STABLE_INPUT_WINDOW_SECONDS = 7 * 24 * 60 * 60
PAGE_NAMING_STABLE_AFTER_SOFT_SECONDS = 2 * 24 * 60 * 60
PAGE_NAMING_STABLE_AFTER_HARD_SECONDS = 4 * 24 * 60 * 60
PAGE_NAMING_STABLE_MIN_UNIQUE_URLS = 10
PAGE_NAMING_STABLE_NEW_URLS_24H_THRESHOLD = 5.0
PAGE_NAMING_UNSTABLE_NEW_URLS_24H_THRESHOLD = 30.0
