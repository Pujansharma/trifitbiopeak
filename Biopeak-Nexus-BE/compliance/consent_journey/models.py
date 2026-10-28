from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from compliance.consent_journey.utils.constants import (
    ConsentDecisionType,
    ConsentName,
)
from core.utils.models import BaseUUIDModel

UNIQ_CCH_PROFILE_VER_REQUIRED_NAME = "uniq_cch_profile_ver_required_name"
REQUIRED_CONSENT_NAME_VALUES = (
    ConsentName.PERSONALISED_HEALTH_SERVICES,
    ConsentName.SERVICE_IMPROVEMENT_RESEARCH,
    ConsentName.AI_SYSTEM_IMPROVEMENT,
)
CONSENT_FORM_HASH_IMMUTABLE_MESSAGE = "consent_form_hash cannot be changed."


class ConsentForm(BaseUUIDModel):
    consent_form = models.FileField(upload_to="compliance/consent-forms/")
    version = models.CharField(max_length=50, unique=True, db_index=True)
    consent_form_hash = models.CharField(max_length=64, editable=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.pk}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous_hash = (
                ConsentForm.objects.filter(pk=self.pk)
                .values_list("consent_form_hash", flat=True)
                .first()
            )
            if previous_hash is not None and self.consent_form_hash != previous_hash:
                raise ValidationError(CONSENT_FORM_HASH_IMMUTABLE_MESSAGE)
        super().save(*args, **kwargs)


class CustomerConsentHistory(BaseUUIDModel):
    customer_profile = models.ForeignKey(
        "customers.CustomerProfile",
        on_delete=models.CASCADE,
        related_name="consent_histories",
    )
    consent_name = models.CharField(choices=ConsentName, max_length=64)
    value = models.BooleanField()
    consent_form_version = models.ForeignKey(
        ConsentForm,
        to_field="version",
        on_delete=models.PROTECT,
        related_name="histories",
    )
    decision_type = models.CharField(choices=ConsentDecisionType, max_length=32)

    class Meta:
        db_table = "customer_consent_history"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["customer_profile", "-created_at"],
                name="cch_profile_created_idx",
            ),
            models.Index(
                fields=[
                    "customer_profile",
                    "consent_form_version",
                    "consent_name",
                    "-created_at",
                ],
                name="cch_profile_ver_name_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["customer_profile", "consent_form_version", "consent_name"],
                condition=Q(consent_name__in=REQUIRED_CONSENT_NAME_VALUES),
                name=UNIQ_CCH_PROFILE_VER_REQUIRED_NAME,
            ),
        ]

    def __str__(self):
        return f"{self.pk}"
