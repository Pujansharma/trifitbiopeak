from django.db import models


class CommunicationEventType(models.TextChoices):
    APPOINTMENT_CONFIRMED = "appointment_confirmed", "Appointment Confirmed"
    APPOINTMENT_CANCELLED = "appointment_cancelled", "Appointment Cancelled"
    APPOINTMENT_RESCHEDULED = "appointment_rescheduled", "Appointment Rescheduled"
    APPOINTMENT_REMINDER = "appointment_reminder", "Appointment Reminder"
    APPOINTMENT_NO_SHOW = "appointment_no_show", "Appointment No Show"
    APPOINTMENT_PRE_CARE = "appointment_pre_care", "Appointment Pre Care"
    APPOINTMENT_POST_CARE = "appointment_post_care", "Appointment Post Care"
    ASSOCIATE_BLOCK_SYNC = "associate_block_sync", "Associate Block Sync"
    ASSOCIATE_LEAVE_SYNC = "associate_leave_sync", "Associate Leave Sync"


class WhatsAppOutboxStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    QUEUED = "queued", "Queued"
    SENDING = "sending", "Sending"
    ACCEPTED = "accepted", "Accepted"
    SENT = "sent", "Sent"
    DELIVERED = "delivered", "Delivered"
    READ = "read", "Read"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"


class GoogleCalendarOutboxStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    QUEUED = "queued", "Queued"
    SENDING = "sending", "Sending"
    ACCEPTED = "accepted", "Accepted"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"


OUTBOX_WORKER_JOB_IDS_MAX = 10

WHATSAPP_DISPATCH_BATCH_SIZE = OUTBOX_WORKER_JOB_IDS_MAX
MAX_WHATSAPP_OUTBOX_ATTEMPTS = 2
STALE_WHATSAPP_SENDING_MINUTES = 5
STALE_WHATSAPP_QUEUED_MINUTES = 10

GOOGLE_CALENDAR_DISPATCH_BATCH_SIZE = OUTBOX_WORKER_JOB_IDS_MAX
MAX_GOOGLE_CALENDAR_OUTBOX_ATTEMPTS = 2
STALE_GOOGLE_CALENDAR_SENDING_MINUTES = 5
STALE_GOOGLE_CALENDAR_QUEUED_MINUTES = 10


class ProtocolAiOutboxStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    QUEUED = "queued", "Queued"
    SENDING = "sending", "Sending"
    ACCEPTED = "accepted", "Accepted"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"


PROTOCOL_AI_DISPATCH_BATCH_SIZE = OUTBOX_WORKER_JOB_IDS_MAX
MAX_PROTOCOL_AI_OUTBOX_ATTEMPTS = 1
STALE_PROTOCOL_AI_OUTBOX_SENDING_MINUTES = 5
STALE_PROTOCOL_AI_OUTBOX_QUEUED_MINUTES = 10

# Lower runs first. Pre-care waits until confirmed ACCEPTED enqueue.
WHATSAPP_EVENT_PROCESS_PRIORITY = {
    CommunicationEventType.APPOINTMENT_CONFIRMED: 0,
    CommunicationEventType.APPOINTMENT_CANCELLED: 0,
    CommunicationEventType.APPOINTMENT_RESCHEDULED: 0,
    CommunicationEventType.APPOINTMENT_REMINDER: 0,
    CommunicationEventType.APPOINTMENT_NO_SHOW: 0,
    CommunicationEventType.APPOINTMENT_POST_CARE: 0,
    CommunicationEventType.APPOINTMENT_PRE_CARE: 1,
}

TERMINAL_WHATSAPP_OUTBOX_BLOCKING_STATUSES = (
    WhatsAppOutboxStatus.PENDING,
    WhatsAppOutboxStatus.QUEUED,
    WhatsAppOutboxStatus.SENDING,
    WhatsAppOutboxStatus.ACCEPTED,
    WhatsAppOutboxStatus.SENT,
    WhatsAppOutboxStatus.DELIVERED,
    WhatsAppOutboxStatus.READ,
    WhatsAppOutboxStatus.FAILED,
)


# Once-per-appointment WhatsApp/Google terminal events (partial unique).
TERMINAL_APPOINTMENT_EVENT_TYPES = (
    CommunicationEventType.APPOINTMENT_CONFIRMED,
    CommunicationEventType.APPOINTMENT_CANCELLED,
    CommunicationEventType.APPOINTMENT_REMINDER,
    CommunicationEventType.APPOINTMENT_NO_SHOW,
    CommunicationEventType.APPOINTMENT_PRE_CARE,
    CommunicationEventType.APPOINTMENT_POST_CARE,
)

CARE_WHATSAPP_EVENT_TYPES = frozenset(
    {
        CommunicationEventType.APPOINTMENT_PRE_CARE,
        CommunicationEventType.APPOINTMENT_POST_CARE,
    }
)

# Statuses that block a second terminal Google Calendar outbox row.
TERMINAL_GOOGLE_OUTBOX_BLOCKING_STATUSES = (
    GoogleCalendarOutboxStatus.PENDING,
    GoogleCalendarOutboxStatus.QUEUED,
    GoogleCalendarOutboxStatus.SENDING,
    GoogleCalendarOutboxStatus.ACCEPTED,
    GoogleCalendarOutboxStatus.FAILED,
)

# Meta-approved WhatsApp template names (not env-driven).
WHATSAPP_TEMPLATE_BY_EVENT = {
    CommunicationEventType.APPOINTMENT_CONFIRMED: "appointment_confirmed_template",
    CommunicationEventType.APPOINTMENT_CANCELLED: "appointment_cancelled_template",
    CommunicationEventType.APPOINTMENT_RESCHEDULED: "appointment_rescheduled_template",
    CommunicationEventType.APPOINTMENT_REMINDER: "therapy_session_reminder",
    CommunicationEventType.APPOINTMENT_NO_SHOW: "therapy_session_no_show",
}


class AppDownloadPlatform(models.TextChoices):
    ANDROID = "android", "Android"
    IOS = "ios", "iOS"
    OTHER = "other", "Other"


class AppDownloadEntry(models.TextChoices):
    """How the hit reached store redirect / chooser (QR URL unchanged)."""

    UA = "ua", "UA redirect"
    CHOOSER = "chooser", "Chooser page"
    PLATFORM_QUERY = "platform_query", "Chooser store badge"


PLAY_STORE_URL = (
    "https://play.google.com/store/apps/details?id=com.biopeak.healthapp"
)
APP_STORE_URL = "https://apps.apple.com/app/biopeak/id6759485756"

APP_DOWNLOAD_DESTINATION_BY_PLATFORM = {
    AppDownloadPlatform.ANDROID: PLAY_STORE_URL,
    AppDownloadPlatform.IOS: APP_STORE_URL,
}

APP_DOWNLOAD_USER_AGENT_MAX_LENGTH = 512
APP_DOWNLOAD_CHOOSER_TEMPLATE = "app_download/Biopeak_App_Download.html"

# Case-insensitive; `\bbot\b` avoids matching "both". Skip click insert only.
APP_DOWNLOAD_BOT_USER_AGENT_PATTERN = (
    r"("
    r"\bbot\b|spider|crawl|slurp|"
    r"facebookexternalhit|twitterbot|linkedinbot|discordbot|"
    r"googlebot|bingbot|yandex|baiduspider|duckduckbot|"
    r"semrush|ahrefs|mj12bot|dotbot|petalbot|bytespider|"
    r"slackbot|applebot|embedly|outbrain"
    r")"
)
