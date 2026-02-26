from .base import *

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
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    "allauth.account.middleware.AccountMiddleware",
]

# Security settings for production
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

ACCOUNT_EMAIL_VERIFICATION = 'none'


def OPENAI_API_KEY_PROVIDER(project_id):
    from apps.projects.models import ChatGptKey
    key_obj = ChatGptKey.objects.filter(project__id=project_id).first()
    if not key_obj:
        return ""
    return "" if not key_obj.key else key_obj.key