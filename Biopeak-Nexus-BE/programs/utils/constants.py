from django.db import models


class ProgramType(models.TextChoices):
    THERAPY = "therapy", "Therapy Program"
    ASSESSMENT = "assessment", "Assessment Program"
    CONSULTATION = "consultation", "Consultation"
    COMPOSITE = "composite", "Composite"


class RedemptionType(models.TextChoices):
    REDEEM = "redeem", "Redeem"
    CANCEL = "cancel", "Cancel"
    SCHEDULED = "scheduled", "Scheduled"
    CANCELLED = "cancelled", "Cancelled"


class ProgramAuditField(models.TextChoices):
    CENTER = "center", "Owning center"
    NOTES = "notes", "Notes"
    EXPIRES_AT = "expires_at", "Expiry date"
    IS_COMPLIMENTARY = "is_complimentary", "Complimentary"
    IS_CREDIT = "is_credit", "Credit"
    PRICE = "price", "Price"
    CREDIT_RECEIVED = "credit_received", "Credit amount"
    CREATED_DATE = "created_date", "Creation date"
    REDEEMABLE_CENTERS = "redeemable_centers", "Redeemable centers"
    IS_ACTIVE = "is_active", "Active status"
    CANCELLATION_REASON = "cancellation_reason", "Cancellation reason"
    CANCELLED_BY = "cancelled_by", "Cancelled by"
    CANCELLED_AT = "cancelled_at", "Cancellation timestamp"
    CANCELLED_DATE = "cancelled_date", "Cancellation date"


class ServiceAssignment(models.TextChoices):
    STANDALONE = "standalone", "Standalone"
    ADD_ON = "add_on", "Add On"


class ConsultationType(models.TextChoices):
    BASELINE = "baseline", "Baseline"
    FOLLOWUPS = "followups", "Followups"


class ConsultationDocumentType(models.TextChoices):
    QUESTIONNAIRE = "questionnaire", "Questionnaire Responses"
    CONSULTATION_NOTES = "consultation_notes", "Consultation Notes"
    POST_CONSULTATION = "post_consultation", "Post Consultation Notes"
