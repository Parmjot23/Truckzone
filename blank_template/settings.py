from pathlib import Path
import sys
import os
import importlib.util
from dotenv import load_dotenv
import dj_database_url
from urllib.parse import urlparse, parse_qsl

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Shared core apps live in company_core for reuse across projects.
CORE_DIR = BASE_DIR / "company_core"
if CORE_DIR.exists():
    sys.path.insert(0, str(CORE_DIR))

# Branding defaults (used as fallbacks when a profile/company name or logo is not set)
DEFAULT_BUSINESS_NAME = os.getenv("DEFAULT_BUSINESS_NAME", "Truck Zone").strip() or "Truck Zone"
DEFAULT_LOGO_STATIC_PATH = os.getenv("DEFAULT_LOGO_STATIC_PATH", "images/truck_zone_logo.png").strip() or "images/truck_zone_logo.png"
DEFAULT_BUSINESS_EMAIL = os.getenv("DEFAULT_BUSINESS_EMAIL", "support@truck-zone.ca").strip() or "support@truck-zone.ca"
DEFAULT_BUSINESS_PHONE = os.getenv("DEFAULT_BUSINESS_PHONE", "+1 (514) 802-999").strip() or "+1 (514) 802-999"
DEFAULT_BUSINESS_ADDRESS = (
    os.getenv("DEFAULT_BUSINESS_ADDRESS", "Truck Zone, 46th Avenue\nMontreal, QC\nCanada").strip()
    or "Truck Zone, 46th Avenue\nMontreal, QC\nCanada"
)
DEFAULT_BUSINESS_HOURS = os.getenv("DEFAULT_BUSINESS_HOURS", "Mon-Sun: 8:00 AM - 9:00 PM").strip() or "Mon-Sun: 8:00 AM - 9:00 PM"

# Load environment variables from .env (default) or .env.example (fallback)
_env_file = os.getenv("ENV_FILE")
if _env_file:
    # Load an explicit env file first (e.g. for CI or alternate configs).
    # Then load .env.example as a "defaults" layer (does not override).
    load_dotenv(_env_file)
    load_dotenv(BASE_DIR / '.env.example', override=False)
else:
    # Prefer local overrides from .env, but always allow .env.example to
    # provide defaults for missing keys (like DATABASE_URL) when developing.
    load_dotenv(BASE_DIR / '.env')
    load_dotenv(BASE_DIR / '.env.example', override=False)



# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-local-development-key')

DEBUG = os.getenv('DEBUG', 'True').lower() in ['1', 'true', 'yes']

# Primary business identity used to scope multi-user business accounts
PRIMARY_BUSINESS_USERNAME = os.getenv('PRIMARY_BUSINESS_USERNAME', 'Transtec')
# Keep existing storefront configuration aligned with the primary business user
CUSTOMER_PORTAL_BUSINESS_USERNAME = os.getenv(
    'CUSTOMER_PORTAL_BUSINESS_USERNAME',
    PRIMARY_BUSINESS_USERNAME,
)

_DEFAULT_ALLOWED_HOSTS = [
    'localhost',
    '127.0.0.1',
    '.koyeb.app',
    'www.2gtowing.ca',
    '2gtowing.ca',
]

_allowed_hosts_env = os.getenv('ALLOWED_HOSTS')
_configured_hosts = (
    [h.strip() for h in _allowed_hosts_env.split(',') if h.strip()]
    if _allowed_hosts_env
    else []
)

ALLOWED_HOSTS = []
for _host in _DEFAULT_ALLOWED_HOSTS + _configured_hosts:
    if _host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_host)

# CSRF trusted origins (comma-separated) e.g. https://your-app-123.koyeb.app,https://yourdomain.com
_csrf_env = os.getenv('CSRF_TRUSTED_ORIGINS', '')
if _csrf_env:
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf_env.split(',') if o.strip()]
else:
    CSRF_TRUSTED_ORIGINS = [
        'http://localhost:8000',
        'http://127.0.0.1:8000',
        'https://www.2gtowing.ca',
    ]

handler404 = 'accounts.views.custom_404'

PROVINCE_TAX_RATES = {
    'AB': 0.05,
    'BC': 0.12,
    'MB': 0.13,
    'NB': 0.15,
    'NL': 0.15,
    'NT': 0.05,
    'NS': 0.15,
    'NU': 0.05,
    'ON': 0.13,
    'PE': 0.15,
    'QC': 0.14975,
    'SK': 0.11,
    'YT': 0.05,
}

# Public booking configuration
BOOKING_BUSINESS_START = os.getenv('BOOKING_BUSINESS_START', '09:00')
BOOKING_BUSINESS_END = os.getenv('BOOKING_BUSINESS_END', '17:00')
try:
    _slot_interval = int(os.getenv('BOOKING_SLOT_INTERVAL_MINUTES', '60'))
    BOOKING_SLOT_INTERVAL_MINUTES = _slot_interval if _slot_interval > 0 else 60
except (TypeError, ValueError):
    BOOKING_SLOT_INTERVAL_MINUTES = 60
BOOKING_BUSINESS_HOLIDAYS = [
    h.strip()
    for h in os.getenv('BOOKING_BUSINESS_HOLIDAYS', '').split(',')
    if h.strip()
]

def _env_truthy(value, default=False):
    """Return True when the provided environment value represents truthy."""

    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def _env_strip(value):
    return value.strip() if value else ''


GOOGLE_ANALYTICS_MEASUREMENT_ID = os.getenv('GOOGLE_ANALYTICS_MEASUREMENT_ID', 'G-M3B2S8MP4').strip()
GOOGLE_ANALYTICS_DEBUG = os.getenv('GOOGLE_ANALYTICS_DEBUG', '').lower() in {'1', 'true', 'yes', 'on'}
LOOKER_STUDIO_EMBED_URL = _env_strip(os.getenv('LOOKER_STUDIO_EMBED_URL', ''))

# Google Maps (used for towing distance + pricing calculator on the dashboard)
#
# Note: This key is rendered into HTML and used client-side by the Google Maps
# JavaScript API (Places Autocomplete + DirectionsService). In some deployments
# the environment variable may be set under a slightly different name; accept
# common aliases to avoid "key missing" regressions.
GOOGLE_MAPS_API_KEY = (
    _env_strip(os.getenv('GOOGLE_MAPS_API_KEY', ''))
    or _env_strip(os.getenv('GOOGLE_MAP_API_KEY', ''))
    or _env_strip(os.getenv('GOOGLE_API_KEY', ''))
    or _env_strip(os.getenv('GMAPS_API_KEY', ''))
)


_quickbooks_env = os.getenv('QUICKBOOKS_ENVIRONMENT', 'sandbox')
_quickbooks_env = _quickbooks_env.strip().lower() if _quickbooks_env else 'sandbox'
if _quickbooks_env not in {'sandbox', 'production'}:
    _quickbooks_env = 'sandbox'

QUICKBOOKS_DEFAULTS = {
    'client_id': _env_strip(os.getenv('QUICKBOOKS_CLIENT_ID', '')),
    'client_secret': _env_strip(os.getenv('QUICKBOOKS_CLIENT_SECRET', '')),
    'realm_id': _env_strip(os.getenv('QUICKBOOKS_REALM_ID', '')),
    'redirect_uri': _env_strip(os.getenv('QUICKBOOKS_REDIRECT_URI', '')),
    'refresh_token': _env_strip(os.getenv('QUICKBOOKS_REFRESH_TOKEN', '')),
    'environment': _quickbooks_env,
    'auto_sync_enabled': _env_truthy(os.getenv('QUICKBOOKS_AUTO_SYNC_ENABLED'), False),
}

# Cloudinary (media storage)
CLOUDINARY_CLOUD_NAME = _env_strip(os.getenv('CLOUDINARY_CLOUD_NAME', ''))
CLOUDINARY_API_KEY = _env_strip(os.getenv('CLOUDINARY_API_KEY', ''))
CLOUDINARY_API_SECRET = _env_strip(os.getenv('CLOUDINARY_API_SECRET', ''))

def _is_placeholder_cloudinary(value: str) -> bool:
    if not value:
        return True
    v = value.strip().lower()
    return v in {'your-cloud-name', 'your-api-key', 'your-api-secret'}

_cloudinary_values_present = all([
    CLOUDINARY_CLOUD_NAME and not _is_placeholder_cloudinary(CLOUDINARY_CLOUD_NAME),
    CLOUDINARY_API_KEY and not _is_placeholder_cloudinary(CLOUDINARY_API_KEY),
    CLOUDINARY_API_SECRET and not _is_placeholder_cloudinary(CLOUDINARY_API_SECRET),
])
_cloudinary_modules_available = all([
    importlib.util.find_spec('cloudinary_storage') is not None,
    importlib.util.find_spec('cloudinary') is not None,
])
USE_CLOUDINARY_STORAGE = _cloudinary_values_present and _cloudinary_modules_available

# Application definition

INSTALLED_APPS = [
    'django.contrib.staticfiles',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.humanize',
    'widget_tweaks',
    'accounts',  # Your custom app
    'django_cron',
    'crispy_forms',
    'crispy_bootstrap4',
    'corsheaders',
    'rest_framework',
    'rest_framework.authtoken',
    'api',
]

# Cloudinary needs to come before staticfiles when enabled
if USE_CLOUDINARY_STORAGE:
    INSTALLED_APPS = ['cloudinary_storage'] + INSTALLED_APPS + ['cloudinary']

CRISPY_TEMPLATE_PACK = "bootstrap4"

CRON_CLASSES = [
    'accounts.cron.ProcessRecurringExpensesCronJob',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'accounts.middleware.MissingMediaCloudinaryRedirectMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'accounts.middleware.CustomerPortalIsolationMiddleware',
    'accounts.middleware.BusinessImpersonationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'accounts.middleware.TrialPeriodMiddleware',
    'blank_template.allow_iframe.AllowIframeFromPortfolioMiddleware',
]

CORS_ORIGIN_ALLOW_ALL = True
CORS_ALLOW_CREDENTIALS = True


ROOT_URLCONF = 'blank_template.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.csrf',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'accounts.context_processors.branding_defaults',
                'accounts.context_processors.ui_scale_settings',
                'accounts.context_processors.analytics_settings',
                'accounts.context_processors.maps_settings',
                'accounts.context_processors.customer_portal_context',
                'accounts.context_processors.storefront_location_context',
                'accounts.context_processors.storefront_nav_context',
                'accounts.context_processors.cart_summary',
            ],
        },
    },
]

WSGI_APPLICATION = 'blank_template.wsgi.application'

# Database
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Keep SQLite when explicitly requested (used by the current Koyeb setup).
_force_sqlite = os.getenv('FORCE_SQLITE', '').strip().lower() in {'1', 'true', 'yes', 'on'}

# Enable DATABASE_URL parsing when provided; fallback stays SQLite
_raw_db_url = os.getenv('DATABASE_URL', '')
_clean_db_url = _raw_db_url.strip().strip('"').strip("'")
if (not _force_sqlite) and _clean_db_url:
    try:
        DATABASES['default'] = dj_database_url.parse(
            _clean_db_url,
            conn_max_age=600,
            ssl_require=os.getenv('DB_SSL_REQUIRE', 'true').lower() in ['1', 'true', 'yes']
        )
    except Exception:
        # Fallback manual parse for Postgres URLs if dj_database_url fails
        try:
            _u = urlparse(_clean_db_url)
            if _u.scheme in ('postgres', 'postgresql', 'pgsql'):
                _opts = dict(parse_qsl(_u.query or ''))
                if os.getenv('DB_SSL_REQUIRE', 'true').lower() in ['1', 'true', 'yes'] and 'sslmode' not in _opts:
                    _opts['sslmode'] = 'require'
                DATABASES['default'] = {
                    'ENGINE': 'django.db.backends.postgresql',
                    'NAME': (_u.path or '').lstrip('/'),
                    'USER': _u.username,
                    'PASSWORD': _u.password,
                    'HOST': _u.hostname,
                    'PORT': _u.port or 5432,
                    'OPTIONS': _opts,
                }
        except Exception:
            # Keep SQLite default if still invalid
            pass

# Neon and other serverless Postgres providers can aggressively clean up
# server-side cursors between fetches which leads to errors such as
# "cursor ... does not exist" when Django iterates over lazy querysets
# (e.g., ModelChoiceField choices). Disabling server-side cursors keeps
# Django on the safer client-side cursor path while still working for
# traditional Postgres deployments.
if DATABASES['default']['ENGINE'] in {
    'django.db.backends.postgresql',
    'django.db.backends.postgresql_psycopg2',
}:
    DATABASES['default']['DISABLE_SERVER_SIDE_CURSORS'] = True


# Password validation
# https://docs.djangoproject.com/en/5.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {
            'min_length': 8,
        }
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


AUTHENTICATION_BACKENDS = [
    'accounts.backends.EmailOrUsernameBackend',
    'django.contrib.auth.backends.ModelBackend',
]

CRON_CLASSES = [
    "accounts.cron.ProcessRecurringExpensesCronJob",
    # ... other cron jobs ...
]
# Internationalization
# https://docs.djangoproject.com/en/5.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.0/howto/static-files/

try:
    DATA_UPLOAD_MAX_NUMBER_FIELDS = int(os.getenv('DATA_UPLOAD_MAX_NUMBER_FIELDS', '10000'))
except (TypeError, ValueError):
    DATA_UPLOAD_MAX_NUMBER_FIELDS = 10000

STATIC_URL = '/static/'
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# Whitenoise static files in production
if not DEBUG:
    # Use the simplest WhiteNoise storage in production.
    #
    # Some deploy environments can fail during collectstatic post-processing
    # (manifest rewriting or compression) due to duplicate admin assets and/or
    # missing optional static references. Using StaticFilesStorage avoids those
    # failures and keeps deploys reliable.
    STATICFILES_STORAGE = 'whitenoise.storage.StaticFilesStorage'
    # Allow the site to keep serving pages even if collectstatic has not been
    # executed yet (e.g., during the first deploy). Without this, WhiteNoise
    # raises a 500 error whenever a referenced static asset is missing from the
    # manifest, which is what happens right after setting DEBUG=False on the
    # live service. By relaxing the manifest strictness we can still render the
    # site while ensuring collectstatic remains the long-term fix.
    WHITENOISE_MANIFEST_STRICT = False
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # Default to False to avoid proxy/health-check redirect issues on platforms
    # like Koyeb; enable explicitly via env when desired.
    SECURE_SSL_REDIRECT = _env_truthy(os.getenv('SECURE_SSL_REDIRECT'), False)

# Media files (Uploaded by users)
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
if USE_CLOUDINARY_STORAGE:
    CLOUDINARY_STORAGE = {
        'CLOUD_NAME': CLOUDINARY_CLOUD_NAME,
        'API_KEY': CLOUDINARY_API_KEY,
        'API_SECRET': CLOUDINARY_API_SECRET,
    }
    DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_REDIRECT_URL = 'accounts:home'
LOGIN_URL = 'accounts:login'

# Path to your Google Vision API key JSON file (for local development, this is optional)
# GOOGLE_APPLICATION_CREDENTIALS = os.path.join(BASE_DIR, 'vision-api-project-432902-3a3b7b7952d3.json')

# Set the environment variable (commented out for local development)
# os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = GOOGLE_APPLICATION_CREDENTIALS


EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_USE_TLS = True
EMAIL_PORT = 587
EMAIL_HOST_USER = 'Accounts@smart-invoices.com'
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', 'bdcy saat qavq fcus')
SUPPORT_EMAIL = 'Accounts@smart-invoices.com'
DEFAULT_FROM_EMAIL = 'Accounts@smart-invoices.com'

INVENTORY_PIN_HASH = "03ac674216f3e15c761ee1a5e255f067953623c8b388b4459e42d305dc0f132"

# OpenAI configuration (keep keys out of source control)
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '').strip()
OPENAI_BASE_URL = os.getenv('OPENAI_BASE_URL', '').strip()
OPENAI_ORG = os.getenv('OPENAI_ORG', 'org-KwQISbNJjBmdzbvYoMK8xZLS').strip()
OPENAI_PROJECT = os.getenv('OPENAI_PROJECT', 'proj_COnxZgb4QhTJSfmUobE5JzBS').strip()
OPENAI_PUBLIC_MODEL = os.getenv('OPENAI_PUBLIC_MODEL', 'gpt-4o-mini')
OPENAI_PUBLIC_FALLBACK_MODEL = os.getenv('OPENAI_PUBLIC_FALLBACK_MODEL', 'gpt-4o-mini')
OPENAI_CAUSE_CORRECTION_MODEL = os.getenv('OPENAI_CAUSE_CORRECTION_MODEL', 'gpt-5-nano').strip()
OPENAI_CAUSE_CORRECTION_FALLBACK_MODEL = os.getenv('OPENAI_CAUSE_CORRECTION_FALLBACK_MODEL', 'gpt-4o-mini').strip()
OPENAI_WHISPER_MODEL = os.getenv('OPENAI_WHISPER_MODEL', 'whisper-1').strip()

SITE_URL = os.getenv("SITE_URL", "https://www.truck-zone.ca").strip() or "https://www.truck-zone.ca"

STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')
STRIPE_PUBLISHABLE_KEY  = os.getenv('STRIPE_PUBLISHABLE_KEY')
STRIPE_PLANS = {
    'monthly': 'price_1PkqEFRuaH1ycRjhd2FfMhS3',  # Replace with your actual price ID
    'quarterly': 'price_1Plx0oRuaH1ycRjhJx68SDtY',
    'semi-annually': 'price_1PlxHPRuaH1ycRjh8TN3pRVM',
    'annually': 'price_1PkqFMRuaH1ycRjh53Ig91SX',
    '4months': 'price_1PpOYKRuaH1ycRjhddnsEVtk',# Replace with your actual price ID

}

STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')

TIME_ZONE = 'America/Toronto'  # Adjust to your actual time zone
USE_TZ = True


# os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/home/parmjot23/blank_template/capable-blend-435103-u2-63daa612d06d.json"

LOG_TO_FILE = os.getenv('LOG_TO_FILE', 'False').lower() in ['1', 'true', 'yes']
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
        **({
            'file': {
                'level': 'INFO',
                'class': 'logging.FileHandler',
                'filename': os.path.join(BASE_DIR, 'logs', 'process_recurring_expenses.log'),
            }
        } if LOG_TO_FILE else {})
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'your_app.management.commands.process_recurring_expenses': {
            'handlers': ['file'] if LOG_TO_FILE else ['console'],
            'level': 'INFO',
            'propagate': True,
        },
    },
}
X_FRAME_OPTIONS = "ALLOWALL"
