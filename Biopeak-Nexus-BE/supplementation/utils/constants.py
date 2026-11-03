from django.db import models


class SupplementForm(models.TextChoices):
    CAPSULE = "capsule", "Capsule"
    TABLET = "tablet", "Tablet"
    SOFTGEL = "softgel", "Softgel"
    POWDER = "powder", "Powder"
    LIQUID = "liquid", "Liquid"
    GUMMY = "gummy", "Gummy"
    LOZENGE = "lozenge", "Lozenge"
    OIL = "oil", "Oil"
    CREAM = "cream", "Cream"
    SPRAY = "spray", "Spray"
    OTHER = "other", "Other"


class RawMaterialSourceType(models.TextChoices):
    SYNTHETIC = "synthetic", "Synthetic"
    NATURAL = "natural", "Natural"
    WHOLE_FOOD = "whole food", "Whole food"
    FERMENTED = "fermented", "Fermented"
    BLENDED = "blended", "Blended"


class DietaryAttribute(models.TextChoices):
    VEGAN = "vegan", "Vegan"
    VEGETARIAN = "vegetarian", "Vegetarian"
    GLUTEN_FREE = "gluten_free", "Gluten free"
    DAIRY_FREE = "dairy_free", "Dairy free"
    SOY_FREE = "soy_free", "Soy free"
    NON_GMO = "non_gmo", "Non-GMO"
    ORGANIC = "organic", "Organic"
    KOSHER = "kosher", "Kosher"
    HALAL = "halal", "Halal"
    NUT_FREE = "nut_free", "Nut free"
    CORN_FREE = "corn_free", "Corn free"
    SUGAR_FREE = "sugar_free", "Sugar free"


class AllergenName(models.TextChoices):
    GLUTEN = "gluten", "Gluten"
    DAIRY = "dairy", "Dairy"
    SOY = "soy", "Soy"
    TREE_NUTS = "tree_nuts", "Tree nuts"
    PEANUTS = "peanuts", "Peanuts"
    SHELL_FISH = "shell_fish", "Shell fish"
    FISH = "fish", "Fish"
    SESAME = "sesame", "Sesame"
    CORN = "corn", "Corn"
    WHEAT = "wheat", "Wheat"


class AllergenPresenceType(models.TextChoices):
    CONTAINS = "contains", "Contains"
    IN_FACILITY = "in_facility", "In facility"


class ConstraintKind(models.TextChoices):
    ALLERGY = "allergy", "Allergy"
    DIETARY = "dietary", "Dietary"
    MEDICAL = "medical", "Medical"
    PREFERENCE = "preference", "Preference"


class ProtocolItemFrequency(models.TextChoices):
    DAILY = "daily", "Daily"
    TWICE_DAILY = "twice_daily", "Twice daily"
    THRICE_DAILY = "thrice_daily", "Thrice daily"
    EVERY_OTHER_DAY = "every_otherday", "Every other day"
    WEEKLY = "weekly", "Weekly"
    CUSTOM = "custom", "Custom"
    AS_NEEDED = "as_needed", "As needed"


class ProtocolItemTiming(models.TextChoices):
    BEFORE_BREAKFAST = "before_breakfast", "Before breakfast"
    WITH_BREAKFAST = "with_breakfast", "With breakfast"
    WITH_LUNCH = "with_lunch", "With lunch"
    WITH_DINNER = "with_dinner", "With dinner"
    AFTER_DINNER = "after_dinner", "After dinner"
    ANYTIME = "anytime", "Anytime"


class ProtocolVersionStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    UNDER_REVIEW = "under_review", "Under review"
    APPROVED = "approved", "Approved"
    SCHEDULED = "scheduled", "Scheduled"
    ACTIVE = "active", "Active"
    SUPERSEDED = "superseded", "Superseded"
    EXPIRED = "expired", "Expired"
    CANCELLED = "cancelled", "Cancelled"


class ProtocolEventAction(models.TextChoices):
    PROTOCOL_CREATED = "protocol_created", "Protocol created"
    PROTOCOL_RENAMED = "protocol_renamed", "Protocol renamed"
    VERSION_DRAFTED = "version_drafted", "Version drafted"
    SUBMITTED_FOR_REVIEW = "submitted_for_review", "Submitted for review"
    APPROVED = "approved", "Approved"
    PUBLISHED = "published", "Published"
    SCHEDULED = "scheduled", "Scheduled"
    SUPERSEDED = "superseded", "Superseded"
    CANCELLED = "cancelled", "Cancelled"
    EXTENDED = "extended", "Extended"
    SUPPLEMENT_ADDED = "supplement_added", "Supplement added"
    SUPPLEMENT_REMOVED = "supplement_removed", "Supplement removed"
    SUPPLEMENT_REPLACED = "supplement_replaced", "Supplement replaced"
    SUPPLEMENT_MODIFIED = "supplement_modified", "Supplement modified"
    RECOMMENDATION_ACCEPTED = "recommendation_accepted", "Recommendation accepted"
    RECOMMENDATION_REJECTED = "recommendation_rejected", "Recommendation rejected"
    RECOMMENDATION_MODIFIED = "recommendation_modified", "Recommendation modified"
    BATCH_COMPLETED = "batch_completed", "Batch completed"
    CONSTRAINT_ADDED = "constraint_added", "Constraint added"
    CONSTRAINT_UPDATED = "constraint_updated", "Constraint updated"
    CONSTRAINT_REMOVED = "constraint_removed", "Constraint removed"


class ProtocolChangeType(models.TextChoices):
    ADDED = "added", "Added"
    REMOVED = "removed", "Removed"
    REPLACED = "replaced", "Replaced"
    MODIFIED = "modified", "Modified"
    STARTED = "started", "Started"
    STOPPED = "stopped", "Stopped"


class ProtocolAiJobStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class AiRecommendationStatus(models.TextChoices):
    UNDER_REVIEW = "under_review", "Under review"
    APPLIED = "applied", "Applied"


class AiRecommendationItemOrigin(models.TextChoices):
    REQUESTED = "requested", "Requested"
    AI_ADDED = "ai_added", "AI added"


class AiRecommendationItemDecision(models.TextChoices):
    PENDING = "pending", "Pending"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"
    MODIFIED = "modified", "Modified"


OPEN_AI_RECOMMENDATION_DECISIONS = (
    AiRecommendationItemDecision.PENDING,
    AiRecommendationItemDecision.MODIFIED,
)
DECIDED_AI_RECOMMENDATION_DECISIONS = (
    AiRecommendationItemDecision.ACCEPTED,
    AiRecommendationItemDecision.REJECTED,
)


class AiRecommendationListStatus:
    PROCESSING = "processing"
    FAILED = "failed"
    PENDING = "pending"
    COMPLETED = "completed"
