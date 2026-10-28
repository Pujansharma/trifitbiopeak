from django.db import models


class ConsentName(models.TextChoices):
    PERSONALISED_HEALTH_SERVICES = (
        "personalised_health_services",
        "Personalised health services",
    )
    SERVICE_IMPROVEMENT_RESEARCH = (
        "service_improvement_research",
        "Service improvement research",
    )
    AI_SYSTEM_IMPROVEMENT = (
        "ai_system_improvement",
        "AI system improvement",
    )
    MARKETING_COMMUNICATIONS = (
        "marketing_communications",
        "Marketing communications",
    )


class ConsentDecisionType(models.TextChoices):
    INITIAL_CONFIRMATION = "initial-confirmation", "Initial confirmation"
    RE_CONFIRMATION = "re-confirmation", "Re-confirmation"


REQUIRED_TRUE_CONSENT_NAMES = (
    ConsentName.PERSONALISED_HEALTH_SERVICES,
    ConsentName.SERVICE_IMPROVEMENT_RESEARCH,
    ConsentName.AI_SYSTEM_IMPROVEMENT,
)
