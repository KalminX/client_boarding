import os
from pathlib import Path
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env if present
load_dotenv(BASE_DIR / '.env')

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-default-dev-secret-key-replace-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'True').lower() in ('true', '1', 'yes')

ALLOWED_HOSTS = [host.strip() for host in os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1,*').split(',') if host.strip()]


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Custom Onboarding System Apps
    'workflow_engine.apps.WorkflowEngineConfig',
    'clients.apps.ClientsConfig',
    'contracts.apps.ContractsConfig',
    'onboarding.apps.OnboardingConfig',
    'documents.apps.DocumentsConfig',
    'integrations.apps.IntegrationsConfig',
    'notifications.apps.NotificationsConfig',
    'audit.apps.AuditConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
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


# Database
# Default is SQLite. Database can be switched to PostgreSQL via DATABASE_URL if configured.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
        'TIMEOUT': 20, # Higher SQLite timeout for concurrency under load
    }
}


# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Private Document Storage (NOT served via public media url)
PRIVATE_STORAGE_ROOT = BASE_DIR / 'private_media'
MEDIA_ROOT = BASE_DIR / 'media'
MEDIA_URL = '/media/'

# Max Upload Size (10MB)
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024
ALLOWED_DOCUMENT_EXTENSIONS = ['.pdf', '.txt', '.csv', '.json', '.png', '.jpg', '.jpeg']

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Auth URLs
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'

# Email Backend
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Worker Queue Configuration
WORKER_POLL_INTERVAL = float(os.getenv('WORKER_POLL_INTERVAL', '1.5'))
WORKER_BATCH_SIZE = int(os.getenv('WORKER_BATCH_SIZE', '10'))
WORKER_LEASE_DURATION_SECONDS = int(os.getenv('WORKER_LEASE_DURATION_SECONDS', '60'))
WORKER_MAX_RETRIES = int(os.getenv('WORKER_MAX_RETRIES', '3'))
WORKER_BASE_BACKOFF_SECONDS = int(os.getenv('WORKER_BASE_BACKOFF_SECONDS', '5'))

# Integration Adapters Selection
EMAIL_ADAPTER = os.getenv('EMAIL_ADAPTER', 'mock')
STORAGE_ADAPTER = os.getenv('STORAGE_ADAPTER', 'mock')
CRM_ADAPTER = os.getenv('CRM_ADAPTER', 'mock')
TASK_ADAPTER = os.getenv('TASK_ADAPTER', 'mock')
AI_EXTRACTOR_ADAPTER = os.getenv('AI_EXTRACTOR_ADAPTER', 'mock')

# External API Keys & Secrets
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')
WEBHOOK_SHARED_SECRET = os.getenv('WEBHOOK_SHARED_SECRET', 'super-secret-webhook-signing-key-12345')
