from django.db import models

from core.utils.models import BaseUUIDModel


class ServiceAccount(BaseUUIDModel):
    name = models.CharField(max_length=50)
    hashed_token = models.CharField(max_length=64, unique=True, editable=False)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name
