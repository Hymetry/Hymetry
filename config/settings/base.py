import os
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-your-secret-key-here')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'True') == 'True'

#ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "*").split(",")

SITE_URL = os.getenv("SITE_URL", "http://localhost")
# 1. Try to get the name Heroku assigned
APP_NAME = os.environ.get('HEROKU_APP_NAME')

if APP_NAME:
    # If Metadata is enabled, we know the exact URL
    SITE_URL = f"https://{APP_NAME}.herokuapp.com"
    CSRF_TRUSTED_ORIGINS = [SITE_URL]
else:
    # 2. THE FAILSAFE: Use a wildcard for all Heroku apps
    # This allows the '1-click' install to work immediately
    # without the user entering anything.
    SITE_URL = os.environ.get('SITE_URL', '')
    CSRF_TRUSTED_ORIGINS = [
        "https://*.herokuapp.com",
        "https://*.onrender.com",
    ]

# Ensure ALLOWED_HOSTS matches
ALLOWED_HOSTS = [".herokuapp.com", ".onrender.com", "localhost", "127.0.0.1"]

if SITE_URL:
    CSRF_TRUSTED_ORIGINS.append(SITE_URL)

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
    'allauth',
    'allauth.account',
    'corsheaders',
    'axes',
    'apps.tracker',
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
    "allauth.account.middleware.AccountMiddleware",
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
                'django.template.context_processors.request',
                'config.context_processors.project_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DEV = os.getenv('DEV')

# CORS_TRUSTED_ORIGIN
SITE_URL = os.getenv("SITE_URL", "http://localhost").rstrip("/")
# Asset-proxy
APP_URL = os.getenv("APP_URL", SITE_URL)
# Tracking script / edge URL
EDGE_URL = os.getenv("EDGE_URL", f"{SITE_URL}/static/js")

import dj_database_url
DATABASES = {
    "default": dj_database_url.parse(
        os.getenv("DATABASE_URL"),
        conn_max_age=600
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
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
    'allauth.account.auth_backends.AuthenticationBackend',
]

SESSION_EXPIRATION_SECONDS = int(os.getenv('SESSION_EXPIRATION_SECONDS', '1800').split('#')[0].strip())
SESSION_MAX_CLOCK_SKEW_SECONDS = int(os.getenv('SESSION_MAX_CLOCK_SKEW_SECONDS', '300').split('#')[0].strip())

ACCOUNT_SIGNUP_FIELDS = ['email*', 'password1*']
ACCOUNT_EMAIL_SUBJECT_PREFIX = ""
ACCOUNT_LOGIN_METHODS = {'email'}
ACCOUNT_ADAPTER = "config.adapters.MyAccountAdapter"
ACCOUNT_EMAIL_VERIFICATION = 'none'

LOGIN_URL = '/sign-in/'
LOGIN_REDIRECT_URL = '/projects/'

ACCOUNT_LOGOUT_REDIRECT_URL = '/sign-in/'
ACCOUNT_CONFIRM_EMAIL_ON_GET = True
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True

# Additional allauth settings for better email confirmation flow
ACCOUNT_UNIQUE_EMAIL = True

# Logout settings - no confirmation dialog
ACCOUNT_LOGOUT_ON_GET = True
ACCOUNT_FORMS = {
    'reset_password_from_key': 'projects.forms.SinglePasswordResetForm',
}

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

ROWS_PER_PAGE = int(os.environ.get('ROWS_PER_PAGE', 100))

# Custom error handlers
HANDLER403 = 'config.views.permission_denied'
HANDLER404 = 'config.views.page_not_found'
HANDLER500 = 'config.views.server_error'


def OPENAI_API_KEY_PROVIDER(project_id):
    from apps.projects.models import ChatGptKey
    key_obj = ChatGptKey.objects.filter(project__id=project_id).first()
    if not key_obj:
        return ""
    return "" if not key_obj.key else key_obj.key
