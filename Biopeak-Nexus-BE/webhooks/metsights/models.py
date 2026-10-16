from django.db import models

from core.utils.models import BaseUUIDModel


class MetSightsExportHistory(BaseUUIDModel):
    email = models.EmailField()
    file = models.FileField(upload_to="metsights/reports_exports/")

    def __str__(self):
        return f"{self.email} - {self.created_at:%Y-%m-%d %H:%M}"
