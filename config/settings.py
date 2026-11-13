import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOCAL = BASE_DIR / '.secrets' / 'settings.json'
private = json.loads(LOCAL.read_text()) if LOCAL.exists() else {}
def setting(name, default=''):
    return os.environ.get(name, private.get(name, default))

SECRET_KEY = setting('SECRET_KEY')
if not SECRET_KEY:
    raise RuntimeError('Skapa lokala inställningar med deploy/init_local.py först.')
DEBUG = str(setting('DEBUG', 'false')).lower() == 'true'
ALLOWED_HOSTS = str(setting('ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver')).split(',')
INSTALLED_APPS = ['django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
                  'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles', 'fleet']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware',
              'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware',
              'django.contrib.auth.middleware.AuthenticationMiddleware', 'django.contrib.messages.middleware.MessageMiddleware',
              'django.middleware.clickjacking.XFrameOptionsMiddleware', 'fleet.middleware.PrivateResponses']
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [BASE_DIR / 'templates'],
              'APP_DIRS': True, 'OPTIONS': {'context_processors': ['django.template.context_processors.request',
              'django.contrib.auth.context_processors.auth', 'django.contrib.messages.context_processors.messages',
              'fleet.context.navigation']}}]
WSGI_APPLICATION = 'config.wsgi.application'
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'private' / 'db.sqlite3',
                        'OPTIONS': {'timeout': 30, 'transaction_mode': 'IMMEDIATE'},
                        'TEST': {'NAME': setting('TEST_DATABASE', None)}}}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
LANGUAGE_CODE = 'sv-se'
TIME_ZONE = 'Europe/Stockholm'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/bokning/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_ROOT = BASE_DIR / 'private' / 'uploads'
LOGIN_URL = '/bokning/login/'
LOGIN_REDIRECT_URL = '/bokning/'
LOGOUT_REDIRECT_URL = LOGIN_URL
SESSION_COOKIE_NAME = 'bokning_session'
CSRF_COOKIE_NAME = 'bokning_csrf'
SESSION_COOKIE_PATH = '/bokning/'
CSRF_COOKIE_PATH = '/bokning/'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 60 * 60 * 12
SESSION_COOKIE_SECURE = str(setting('SECURE_COOKIES', 'true')).lower() == 'true'
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SECURE_SSL_REDIRECT = str(setting('SSL_REDIRECT', 'false')).lower() == 'true'
SECURE_HSTS_SECONDS = int(setting('HSTS_SECONDS', 0))
# This app may share its host with other projects. Subdomain-wide HSTS and
# permanent browser preload require a separate domain-wide decision.
SILENCED_SYSTEM_CHECKS = ['security.W005', 'security.W021']
if str(setting('TRUST_PROXY_HTTPS', 'false')).lower() == 'true':
    # Enable only behind a trusted proxy that overwrites X-Forwarded-Proto.
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_REFERRER_POLICY = 'same-origin'
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024
EMAIL_BACKEND = setting('EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = setting('EMAIL_HOST')
EMAIL_PORT = int(setting('EMAIL_PORT', 587))
EMAIL_HOST_USER = setting('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = setting('EMAIL_HOST_PASSWORD')
EMAIL_USE_TLS = True
EMAIL_TIMEOUT = 15
DEFAULT_FROM_EMAIL = setting('DEFAULT_FROM_EMAIL', 'Bokning <noreply@example.invalid>')
PUBLIC_ORIGIN = setting('PUBLIC_ORIGIN', 'http://127.0.0.1:8010').rstrip('/')
TOKEN_ENCRYPTION_KEY = setting('TOKEN_ENCRYPTION_KEY')
MICROSOFT_TENANT = setting('MICROSOFT_TENANT')
MICROSOFT_CLIENT_ID = setting('MICROSOFT_CLIENT_ID')
MICROSOFT_CLIENT_SECRET = setting('MICROSOFT_CLIENT_SECRET')
GOOGLE_CLIENT_ID = setting('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = setting('GOOGLE_CLIENT_SECRET')
SSO_ALLOWED_DOMAINS = [d.strip().lower() for d in str(setting('SSO_ALLOWED_DOMAINS')).split(',') if d.strip()]
