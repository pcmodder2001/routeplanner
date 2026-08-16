"""
Django settings for Openreach Route Planner.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Prefer this project's .env over leftover shell/user DB_* from other apps
load_dotenv(BASE_DIR / '.env', override=True)

SECRET_KEY = os.environ.get(
    'SECRET_KEY',
    'django-insecure-a-n*83pliko=eb)(bz04b@y0%ayi*32nrhm8p2!&+#@jdsa05)',
)

DEBUG = os.environ.get('DEBUG', '1') == '1'

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get('ALLOWED_HOSTS', '*').split(',')
    if h.strip()
]
if not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ['*']

CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        'CSRF_TRUSTED_ORIGINS',
        'https://plan.sitematrix.co.uk',
    ).split(',')
    if o.strip()
]

# Trust HTTPS from reverse proxy (Traefik / nginx / Cloudflare, etc.)
if os.environ.get('USE_X_FORWARDED_PROTO', '1') == '1':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

INSTALLED_APPS = [
    "sitematrix_client",
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'planner',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    "sitematrix_client.middleware.SiteMatrixGateMiddleware",
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database: PostgreSQL when DB_* is set, otherwise SQLite
_db_engine = (os.environ.get('DB_ENGINE') or '').strip().lower()
_db_name = (os.environ.get('DB_NAME') or '').strip()
if _db_engine in ('postgresql', 'postgres', 'django.db.backends.postgresql') and _db_name:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': _db_name,
            'USER': os.environ.get('DB_USER', ''),
            'PASSWORD': os.environ.get('DB_PASSWORD', ''),
            'HOST': os.environ.get('DB_HOST', 'localhost'),
            'PORT': os.environ.get('DB_PORT', '5432'),
            'CONN_MAX_AGE': int(os.environ.get('DB_CONN_MAX_AGE', '60') or '60'),
            'OPTIONS': {
                'connect_timeout': int(os.environ.get('DB_CONNECT_TIMEOUT', '10') or '10'),
            },
        }
    }
else:
    SQLITE_PATH = os.environ.get('SQLITE_PATH')
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': SQLITE_PATH if SQLITE_PATH else str(BASE_DIR / 'db.sqlite3'),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-gb'
TIME_ZONE = 'Europe/London'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage',
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'

# Sessions: "Remember me" extends to 90 days; sliding expiry while active
SESSION_COOKIE_AGE = 60 * 60 * 24 * 90
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django.request': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
        'sitematrix_client': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# SiteMatrix (optional — leave API key empty to disable the gate)
SITEMATRIX_API_URL = os.environ.get(
    'SITEMATRIX_API_URL',
    'https://www.sitematrix.co.uk',
)
SITEMATRIX_API_KEY = os.environ.get('SITEMATRIX_API_KEY', '')
SITEMATRIX_FAIL_OPEN = os.environ.get('SITEMATRIX_FAIL_OPEN', '1') not in (
    '0',
    'false',
    'False',
    'no',
    'NO',
)
SITEMATRIX_SITE_NAME = os.environ.get('SITEMATRIX_SITE_NAME', '')
try:
    SITEMATRIX_TIMEOUT = int(os.environ.get('SITEMATRIX_TIMEOUT', '3') or '3')
except ValueError:
    SITEMATRIX_TIMEOUT = 3

# Optional traffic / road routing keys (Google preferred for live traffic)
GOOGLE_MAPS_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY', '')
OPENROUTESERVICE_API_KEY = os.environ.get('OPENROUTESERVICE_API_KEY', '')
