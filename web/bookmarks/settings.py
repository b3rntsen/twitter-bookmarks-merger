"""
Django settings for bookmarks project.
"""

from pathlib import Path
from decouple import config
import os

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config('SECRET_KEY', default='django-insecure-change-me-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config('DEBUG', default=True, cast=bool)

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=lambda v: [s.strip() for s in v.split(',')])

# CSRF Trusted Origins (required for HTTPS and OAuth)
CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='', cast=lambda v: [s.strip() for s in v.split(',') if s.strip()])
if not CSRF_TRUSTED_ORIGINS:
    # Auto-populate from ALLOWED_HOSTS if not explicitly set
    CSRF_TRUSTED_ORIGINS = []
    for host in ALLOWED_HOSTS:
        if host not in ['localhost', '127.0.0.1', '0.0.0.0']:
            CSRF_TRUSTED_ORIGINS.extend([
                f'http://{host}',
                f'https://{host}',
            ])
    # Add localhost variants
    CSRF_TRUSTED_ORIGINS.extend([
        'http://localhost:8000',
        'http://127.0.0.1:8000',
    ])

# HTTPS/SSL Configuration
USE_HTTPS = config('USE_HTTPS', default=False, cast=bool)
if USE_HTTPS:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    # Trust nginx proxy
    USE_X_FORWARDED_HOST = True
    USE_X_FORWARDED_PORT = True


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    
    # Third party
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'rest_framework',
    'django_q',  # Background job processing
    
    # Local apps
    'accounts',
    'twitter',
    'bookmarks_app',
    'lists_app',
    'processing_app.apps.ProcessingAppConfig',  # Content processing and job management
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'allauth.account.middleware.AccountMiddleware',
]

ROOT_URLCONF = 'bookmarks.urls'

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
            ],
        },
    },
]

WSGI_APPLICATION = 'bookmarks.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases

# Database path - use /app/db if mounted, otherwise /app
DB_DIR = Path('/app/db') if Path('/app/db').exists() else BASE_DIR
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': DB_DIR / 'db.sqlite3',
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 8},
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
    {
        'NAME': 'web.accounts.validators.NotAllLowercaseValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.0/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
# https://docs.djangoproject.com/en/5.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Django Allauth settings
SITE_ID = 1

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_AUTHENTICATION_METHOD = 'email'
ACCOUNT_EMAIL_VERIFICATION = 'none'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'
ACCOUNT_LOGOUT_ON_GET = True

# Google OAuth
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'SCOPE': [
            'profile',
            'email',
        ],
        'AUTH_PARAMS': {
            'access_type': 'online',
        },
        'APP': {
            'client_id': config('GOOGLE_CLIENT_ID', default=''),
            'secret': config('GOOGLE_CLIENT_SECRET', default=''),
        }
    }
}

# Social account settings - allow connecting to existing accounts
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_REQUIRED = True
SOCIALACCOUNT_QUERY_EMAIL = True
SOCIALACCOUNT_ADAPTER = 'web.accounts.adapters.CustomSocialAccountAdapter'

# Ensure django-allauth uses HTTPS when USE_HTTPS is enabled
if USE_HTTPS:
    ACCOUNT_DEFAULT_HTTP_PROTOCOL = 'https'

# Django-Q Configuration
# Use Redis by default (install locally for development), with ORM fallback for tests
# Set Q_USE_ORM=true in environment to use ORM broker instead of Redis
USE_REDIS = not config('Q_USE_ORM', default=False, cast=bool)

# Try to connect to Redis, fall back to ORM if unavailable
REDIS_AVAILABLE = False
if USE_REDIS:
    try:
        import redis
        redis_client = redis.Redis(
            host=config('REDIS_HOST', default='localhost'),
            port=int(config('REDIS_PORT', default=6379)),
            db=int(config('REDIS_DB', default=0)),
            password=config('REDIS_PASSWORD', default=None),
            socket_connect_timeout=2
        )
        redis_client.ping()
        REDIS_AVAILABLE = True
    except (redis.ConnectionError, redis.TimeoutError, ImportError, Exception):
        # Redis not available, fall back to ORM
        REDIS_AVAILABLE = False
        import warnings
        warnings.warn(
            "Redis is not available. Falling back to ORM broker. "
            "Install Redis or set Q_USE_ORM=true to suppress this warning.",
            UserWarning
        )

Q_CLUSTER = {
    'name': 'content_processing',
    'workers': int(config('Q_WORKERS', default=2)),
    'recycle': int(config('Q_RECYCLE', default=500)),
    'timeout': int(config('Q_TIMEOUT', default=3600)),  # 1 hour timeout
    'retry': int(config('Q_RETRY', default=7200)),  # 2 hours (must be > timeout)
    'queue_limit': int(config('Q_QUEUE_LIMIT', default=50)),
    'bulk': int(config('Q_BULK', default=10)),
}

# Configure broker: Redis (default) or ORM (fallback)
if USE_REDIS and REDIS_AVAILABLE:
    # Use Redis broker (default for development and production)
    # Note: 'charset' and 'errors' parameters removed - not supported in redis-py 4.0+
    Q_CLUSTER['redis'] = {
        'host': config('REDIS_HOST', default='localhost'),
        'port': int(config('REDIS_PORT', default=6379)),
        'db': int(config('REDIS_DB', default=0)),
        'password': config('REDIS_PASSWORD', default=None),
        'socket_timeout': 30,
        # 'charset' and 'errors' removed - not supported in redis-py 4.0+
        # 'unix_socket_path': None  # Not needed for standard TCP connections
    }
else:
    # Use ORM broker (for tests or when Redis is unavailable)
    Q_CLUSTER['orm'] = config('Q_ORM_BROKER', default='default', cast=lambda v: v if v else 'default')

