from corsheaders.defaults import default_headers

from core.settings.base import *

DEBUG = False

ALLOWED_HOSTS = ["*"]

# Database
# https://docs.djangoproject.com/en/dev/ref/settings/#databases
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("STG_DB_NAME"),
        "USER": config("STG_DB_USER"),
        "PASSWORD": config("STG_DB_PASSWORD"),
        "HOST": config("STG_DB_HOST"),
        "PORT": config("STG_DB_PORT"),
        "OPTIONS": {
            "sslmode": "prefer",
        },
    }
}

# Storages
# https://docs.djangoproject.com/en/dev/ref/settings/#storages

STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# AWS Settings
# https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html

AWS_QUERYSTRING_AUTH = False
AWS_S3_ACCESS_KEY_ID = config("AWS_S3_ACCESS_KEY_ID")
AWS_S3_SECRET_ACCESS_KEY = config("AWS_S3_SECRET_ACCESS_KEY")
AWS_STORAGE_BUCKET_NAME = config("AWS_STORAGE_BUCKET_NAME")
AWS_S3_REGION_NAME = config("AWS_S3_REGION_NAME")
AWS_S3_CUSTOM_DOMAIN = config("AWS_S3_CUSTOM_DOMAIN")

# Email
# https://docs.djangoproject.com/en/dev/ref/settings/#email

EMAIL_USE_TLS = True
EMAIL_HOST = config("STG_EMAIL_HOST")
EMAIL_HOST_USER = config("STG_EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = config("STG_EMAIL_HOST_PASSWORD")
EMAIL_PORT = config("STG_EMAIL_PORT")
DEFAULT_FROM_EMAIL = config("STG_DEFAULT_FROM_EMAIL")

# Logging
# https://docs.djangoproject.com/en/dev/ref/settings/#logging

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "django.server": {
            "()": "core.utils.log.BaseFormatter",
            "format": "[{server_time}] {message}",
            "style": "{",
        }
    },
    "handlers": {
        "console": {
            "level": "INFO",
            "filters": [],
            "class": "logging.StreamHandler",
            "formatter": "django.server",
        },
    },
    "loggers": {
        "django": {
            "handlers": [
                "console",
            ],
            "level": "INFO",
        },
        "django.request": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

# Django CORS Headers

CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_HEADERS = [*default_headers, "x-center-id", "idempotency-key", "x-customer-profile-id", "x-correlation-id"]

# Other

PASSWORD_BASE_URL = config("STG_PASSWORD_BASE_URL", "")

# Firebase
ADMIN_CERT = config("ADMIN_CERT", None)
APP_CERT = config("APP_CERT", None)

# Metsights
METSIGHTS_API_KEY = config('STG_METSIGHTS_API_KEY', None)

# ASK-AI
ASK_AI_API_KEY = config('STG_ASK_AI_API_KEY', None)

# SMS
SMS_API_KEY = config("STG_SMS_API_KEY", None)

# Orange Labs
ORANGE_LABS_API_BASE_URL = config("STG_ORANGE_LABS_API_BASE_URL", None)
ORANGE_LABS_API_KEY = config("STG_ORANGE_LABS_API_KEY", None)
ORANGE_LABS_WEBHOOK_SECRET = config("STG_ORANGE_LABS_WEBHOOK_SECRET", None)

# Google Calendar
GOOGLE_CLIENT_ID = config("STG_GOOGLE_CLIENT_ID", None)
GOOGLE_CLIENT_SECRET = config("STG_GOOGLE_CLIENT_SECRET", None)
GOOGLE_REDIRECT_URI = config("STG_GOOGLE_REDIRECT_URI", None)
GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY = config("STG_GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY", None)
GOOGLE_CALENDAR_ID = config("STG_GOOGLE_CALENDAR_ID", None)
ADMIN_FRONTEND_URL = config("STG_ADMIN_FRONTEND_URL", None)
COMMUNICATION_OUTBOX_WAKE_QUEUE_URL = config(
    "STG_COMMUNICATION_OUTBOX_WAKE_QUEUE_URL", default=""
)
AWS_REGION = config("AWS_REGION", default=None)
# WhatsApp Cloud API (communications)
WHATSAPP_ACCESS_TOKEN = config("STG_WHATSAPP_ACCESS_TOKEN", None)
WHATSAPP_PHONE_NUMBER_ID = config("STG_WHATSAPP_PHONE_NUMBER_ID", None)
WHATSAPP_APP_SECRET = config("STG_WHATSAPP_APP_SECRET", None)
WHATSAPP_WEBHOOK_VERIFY_TOKEN = config("STG_WHATSAPP_WEBHOOK_VERIFY_TOKEN", None)
WHATSAPP_API_VERSION = config("STG_WHATSAPP_API_VERSION", "v23.0")
WHATSAPP_WABA_ID = config("STG_WHATSAPP_WABA_ID", None)
WHATSAPP_APP_ID = config("STG_WHATSAPP_APP_ID", None)
WHATSAPP_TEMPLATE_LANGUAGE = config("STG_WHATSAPP_TEMPLATE_LANGUAGE", "en")

# ROOK / Wearables Phase 1 — additive. All keys remain external to source control.
WEARABLES_ENABLED = config("STG_WEARABLES_ENABLED", default=False, cast=bool)
WEARABLES_REQUIRE_PROFILE_FEATURE = config(
    "STG_WEARABLES_REQUIRE_PROFILE_FEATURE", default=True, cast=bool
)
TIMELINE_ENABLED = config("STG_TIMELINE_ENABLED", default=False, cast=bool)
RECOVERY_DOMAIN_ENABLED = config("STG_RECOVERY_DOMAIN_ENABLED", default=True, cast=bool)
BODY_DOMAIN_ENABLED = config("STG_BODY_DOMAIN_ENABLED", default=True, cast=bool)
ROOK_ENVIRONMENT = config("STG_ROOK_ENVIRONMENT", default="sandbox")
ROOK_BASE_URL = config("STG_ROOK_BASE_URL", default="https://api.rook-connect.review")
ROOK_CLIENT_UUID = config("STG_ROOK_CLIENT_UUID", default="")
ROOK_SECRET_KEY = config("STG_ROOK_SECRET_KEY", default="")
ROOK_WEBHOOK_HASH_KEY = config("STG_ROOK_WEBHOOK_HASH_KEY", default="")
ROOK_SDK_CLIENT_UUID = config("STG_ROOK_SDK_CLIENT_UUID", default="")
ROOK_SDK_SECRET = config("STG_ROOK_SDK_SECRET", default="")
ROOK_HISTORICAL_DAYS = config("STG_ROOK_HISTORICAL_DAYS", default=7, cast=int)
ROOK_PREEXISTING_ENABLED = config(
    "STG_ROOK_PREEXISTING_ENABLED", default=False, cast=bool
)
# None means 'not configured'. An empty string/list means no provider approved.
# Specify exact API names (case-sensitive), e.g. Garmin,Fitbit,Oura.
ROOK_PROVISIONED_SOURCES = config("STG_ROOK_PROVISIONED_SOURCES", default=None)
ROOK_SYNC_DELAY_HOURS = config("STG_ROOK_SYNC_DELAY_HOURS", default=48, cast=int)
ROOK_CONNECT_TIMEOUT_SECONDS = config("STG_ROOK_CONNECT_TIMEOUT_SECONDS", default=5, cast=int)
ROOK_READ_TIMEOUT_SECONDS = config("STG_ROOK_READ_TIMEOUT_SECONDS", default=12, cast=int)
ROOK_ALLOW_UNSIGNED_WEBHOOKS = config("STG_ROOK_ALLOW_UNSIGNED_WEBHOOKS", default=False, cast=bool)
ROOK_AUTHORIZATION_ALLOWED_HOSTS = config(
    "STG_ROOK_AUTHORIZATION_ALLOWED_HOSTS", default="",
    cast=lambda v: [host.strip() for host in v.split(",") if host.strip()],
)
ROOK_CALLBACK_URL = config("STG_ROOK_CALLBACK_URL", default="")
ROOK_OAUTH_TIMEOUT_MINUTES = config("STG_ROOK_OAUTH_TIMEOUT_MINUTES", default=15, cast=int)
ROOK_MOBILE_REDIRECT_ALLOWED_HOSTS = config(
    "STG_ROOK_MOBILE_REDIRECT_ALLOWED_HOSTS", default="",
    cast=lambda v: [host.strip() for host in v.split(",") if host.strip()],
)
HEALTH_TREND_MINIMUM_OBSERVATIONS = config("STG_HEALTH_TREND_MINIMUM_OBSERVATIONS", default=7, cast=int)
HEALTH_HISTORICAL_GAP_DAYS = config("STG_HEALTH_HISTORICAL_GAP_DAYS", default=7, cast=int)
TIMELINE_INCLUDE_LEGACY_RESULTS = config("STG_TIMELINE_INCLUDE_LEGACY_RESULTS", default=True, cast=bool)
