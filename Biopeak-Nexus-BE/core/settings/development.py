from corsheaders.defaults import default_headers

from core.settings.base import *

DEBUG = True

ALLOWED_HOSTS = ["*"]

# Debug toolbar
DEBUG_TOOLBAR_CONFIG = {
    "SHOW_TOOLBAR_CALLBACK": lambda request: True,
    "IS_RUNNING_TESTS": False,
}

# Database
# https://docs.djangoproject.com/en/dev/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DEV_DB_NAME"),
        "USER": config("DEV_DB_USER"),
        "PASSWORD": config("DEV_DB_PASSWORD"),
        "HOST": config("DEV_DB_HOST"),
        "PORT": config("DEV_DB_PORT"),
        "OPTIONS": {
            "sslmode": "prefer",
        },
    }
}

# Storages
# https://docs.djangoproject.com/en/dev/ref/settings/#storages

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Email
# https://docs.djangoproject.com/en/dev/ref/settings/#email
DEFAULT_FROM_EMAIL = config("DEV_DEFAULT_FROM_EMAIL", "Local <mail@localhost>")

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "OPTIONS": {
            "host": config("DEV_EMAIL_HOST", ""),
            "use_tls": False,
            "port": config("DEV_EMAIL_PORT", ""),
            "username": config("DEV_EMAIL_HOST_USER", ""),
            "password": config("DEV_EMAIL_HOST_PASSWORD", ""),
        },
    },
}
# Django CORS Headers

CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_HEADERS = [*default_headers, "x-center-id", "idempotency-key", "x-customer-profile-id", "x-correlation-id"]

PASSWORD_BASE_URL = config("DEV_PASSWORD_BASE_URL", "")

# Firebase
ADMIN_CERT = config("ADMIN_CERT", None)
APP_CERT = config("APP_CERT", None)

# Metsights
METSIGHTS_API_KEY = config('DEV_METSIGHTS_API_KEY', None)

# ASK-AI
ASK_AI_API_KEY = config('DEV_ASK_AI_API_KEY', None)

# SMS
SMS_API_KEY = config("DEV_SMS_API_KEY", None)

# Orange Labs
ORANGE_LABS_API_BASE_URL = config("DEV_ORANGE_LABS_API_BASE_URL", None)
ORANGE_LABS_API_KEY = config("DEV_ORANGE_LABS_API_KEY", None)
ORANGE_LABS_WEBHOOK_SECRET = config("DEV_ORANGE_LABS_WEBHOOK_SECRET", None)

# Google Calendar
GOOGLE_CLIENT_ID = config("DEV_GOOGLE_CLIENT_ID", None)
GOOGLE_CLIENT_SECRET = config("DEV_GOOGLE_CLIENT_SECRET", None)
GOOGLE_REDIRECT_URI = config("DEV_GOOGLE_REDIRECT_URI", None)
GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY = config("DEV_GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY", None)
GOOGLE_CALENDAR_ID = config("DEV_GOOGLE_CALENDAR_ID", None)
ADMIN_FRONTEND_URL = config("DEV_ADMIN_FRONTEND_URL", None)
COMMUNICATION_OUTBOX_WAKE_QUEUE_URL = config(
    "DEV_COMMUNICATION_OUTBOX_WAKE_QUEUE_URL", default=""
)
AWS_REGION = config("AWS_REGION", default=None)
# WhatsApp Cloud API (communications)
WHATSAPP_ACCESS_TOKEN = config("WHATSAPP_ACCESS_TOKEN", None)
WHATSAPP_PHONE_NUMBER_ID = config("WHATSAPP_PHONE_NUMBER_ID", None)
WHATSAPP_APP_SECRET = config("DEV_WHATSAPP_APP_SECRET", None)
WHATSAPP_WEBHOOK_VERIFY_TOKEN = config("DEV_WHATSAPP_WEBHOOK_VERIFY_TOKEN", None)
WHATSAPP_API_VERSION = config("DEV_WHATSAPP_API_VERSION", "v23.0")
WHATSAPP_WABA_ID = config("DEV_WHATSAPP_WABA_ID", None)
WHATSAPP_APP_ID = config("DEV_WHATSAPP_APP_ID", None)
WHATSAPP_TEMPLATE_LANGUAGE = config("DEV_WHATSAPP_TEMPLATE_LANGUAGE", "en")

# ROOK / Wearables Phase 1 — additive. All keys remain external to source control.
WEARABLES_ENABLED = config("DEV_WEARABLES_ENABLED", default=True, cast=bool)
WEARABLES_REQUIRE_PROFILE_FEATURE = config(
    "DEV_WEARABLES_REQUIRE_PROFILE_FEATURE", default=False, cast=bool
)
TIMELINE_ENABLED = config("DEV_TIMELINE_ENABLED", default=True, cast=bool)
RECOVERY_DOMAIN_ENABLED = config("DEV_RECOVERY_DOMAIN_ENABLED", default=True, cast=bool)
BODY_DOMAIN_ENABLED = config("DEV_BODY_DOMAIN_ENABLED", default=True, cast=bool)
ROOK_ENVIRONMENT = config("DEV_ROOK_ENVIRONMENT", default="sandbox")
ROOK_BASE_URL = config("DEV_ROOK_BASE_URL", default="https://api.rook-connect.review")
ROOK_CLIENT_UUID = config("DEV_ROOK_CLIENT_UUID", default="")
ROOK_SECRET_KEY = config("DEV_ROOK_SECRET_KEY", default="")
ROOK_WEBHOOK_HASH_KEY = config("DEV_ROOK_WEBHOOK_HASH_KEY", default="")
ROOK_SDK_CLIENT_UUID = config("DEV_ROOK_SDK_CLIENT_UUID", default="")
ROOK_SDK_SECRET = config("DEV_ROOK_SDK_SECRET", default="")
ROOK_HISTORICAL_DAYS = config("DEV_ROOK_HISTORICAL_DAYS", default=7, cast=int)
ROOK_PREEXISTING_ENABLED = config(
    "DEV_ROOK_PREEXISTING_ENABLED", default=True, cast=bool
)
# None means 'not configured'. An empty string/list means no provider approved.
# Specify exact API names (case-sensitive), e.g. Garmin,Fitbit,Oura.
ROOK_PROVISIONED_SOURCES = config("DEV_ROOK_PROVISIONED_SOURCES", default=None)
ROOK_SYNC_DELAY_HOURS = config("DEV_ROOK_SYNC_DELAY_HOURS", default=48, cast=int)
ROOK_CONNECT_TIMEOUT_SECONDS = config("DEV_ROOK_CONNECT_TIMEOUT_SECONDS", default=5, cast=int)
ROOK_READ_TIMEOUT_SECONDS = config("DEV_ROOK_READ_TIMEOUT_SECONDS", default=12, cast=int)
ROOK_ALLOW_UNSIGNED_WEBHOOKS = config("DEV_ROOK_ALLOW_UNSIGNED_WEBHOOKS", default=False, cast=bool)
ROOK_AUTHORIZATION_ALLOWED_HOSTS = config(
    "DEV_ROOK_AUTHORIZATION_ALLOWED_HOSTS", default="",
    cast=lambda v: [host.strip() for host in v.split(",") if host.strip()],
)
ROOK_CALLBACK_URL = config("DEV_ROOK_CALLBACK_URL", default="")
ROOK_OAUTH_TIMEOUT_MINUTES = config("DEV_ROOK_OAUTH_TIMEOUT_MINUTES", default=15, cast=int)
ROOK_MOBILE_REDIRECT_ALLOWED_HOSTS = config(
    "DEV_ROOK_MOBILE_REDIRECT_ALLOWED_HOSTS", default="",
    cast=lambda v: [host.strip() for host in v.split(",") if host.strip()],
)
HEALTH_TREND_MINIMUM_OBSERVATIONS = config("DEV_HEALTH_TREND_MINIMUM_OBSERVATIONS", default=7, cast=int)
HEALTH_HISTORICAL_GAP_DAYS = config("DEV_HEALTH_HISTORICAL_GAP_DAYS", default=7, cast=int)
TIMELINE_INCLUDE_LEGACY_RESULTS = config("DEV_TIMELINE_INCLUDE_LEGACY_RESULTS", default=True, cast=bool)
