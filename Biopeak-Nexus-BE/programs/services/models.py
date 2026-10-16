from django.db import models
from django.db.models.functions import Lower

from core.utils.constants import AppointmentModes
from core.utils.models import BaseUUIDModel
from products.models import Product
from programs.services.utils.constants import (
    ServiceCategory,
    ServiceDocumentCategory,
    ServiceDocumentType,
    RequestResultType,
    ResultRequestStatus,
    ResultType,
    ServiceReportComponent,
)


class Service(BaseUUIDModel):
    name = models.CharField(max_length=200)
    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_services",
    )
    service_category = models.CharField(choices=ServiceCategory)
    image = models.FileField(upload_to="products/services/", null=True, blank=True)
    is_global = models.BooleanField(default=False)
    centers_count = models.PositiveBigIntegerField(default=0, editable=False)
    products_count = models.PositiveBigIntegerField(default=0, editable=False)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                name="uniq_service_name",
            )
        ]

    def __str__(self):
        return f"{self.pk}"


class ServiceCareTemplate(BaseUUIDModel):
    """
    Optional per-service Meta WhatsApp care templates (keyed by service id).
    Pre: after appointment confirmed WhatsApp settles. Post: on completed.
    """

    service = models.OneToOneField(
        Service,
        on_delete=models.CASCADE,
        related_name="care_template",
    )
    pre_template_name = models.CharField(max_length=128, blank=True, default="")
    post_template_name = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.pk}"


class CenterServiceAssignment(BaseUUIDModel):
    service = models.ForeignKey(
        Service, on_delete=models.CASCADE, related_name="center_assignments"
    )
    center = models.ForeignKey(
        "centers.Center", on_delete=models.CASCADE, related_name="service_assignments"
    )
    duration = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Appointment duration in minutes for this center",
    )
    buffer_before = models.PositiveSmallIntegerField(
        default=0, help_text="Buffer minutes before the appointment"
    )
    buffer_after = models.PositiveSmallIntegerField(
        default=0, help_text="Buffer minutes after the appointment"
    )
    modality = models.CharField(choices=AppointmentModes, default=AppointmentModes.BOTH)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["service", "center"], name="unique_service_center"
            )
        ]
        indexes = [
            models.Index(fields=["service", "center"], name="service_center_idx")
        ]

    def __str__(self):
        return f"{self.pk}"


class CenterServiceRoleRequirement(BaseUUIDModel):
    assignment = models.ForeignKey(
        CenterServiceAssignment,
        on_delete=models.CASCADE,
        related_name="role_requirements",
    )
    role = models.ForeignKey(
        "associates.AssociateRole",
        on_delete=models.PROTECT,
        related_name="service_role_requirements",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["assignment", "role"], name="uniq_assignment_role_requirement"
            )
        ]

    def __str__(self):
        return f"{self.pk}"


class CenterServiceRoomTypeRequirement(BaseUUIDModel):
    assignment = models.ForeignKey(
        CenterServiceAssignment,
        on_delete=models.CASCADE,
        related_name="room_type_requirements",
    )
    room_type = models.ForeignKey(
        "inventory.RoomType",
        on_delete=models.PROTECT,
        related_name="service_room_type_requirements",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["assignment", "room_type"],
                name="uniq_assignment_room_type_requirement",
            )
        ]

    def __str__(self):
        return f"{self.pk}"


class ServiceProductAssignment(BaseUUIDModel):
    service = models.ForeignKey(
        Service, on_delete=models.PROTECT, related_name="product_assignments"
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="service_assignments"
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["service", "product"], name="unique_service_product"
            )
        ]

    def __str__(self):
        return f"{self.pk}"


class ResultRequest(BaseUUIDModel):
    program_service = models.ForeignKey(
        "programs.ProgramService",
        on_delete=models.PROTECT,
        related_name="result_requests",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="result_requests",
    )
    data = models.JSONField(default=dict, blank=True)
    profile_data = models.JSONField(default=dict, blank=True)
    request_type = models.CharField(
        choices=RequestResultType,
        default=RequestResultType.FETCH,
        editable=False,
        db_index=True,
    )
    status = models.CharField(
        choices=ResultRequestStatus,
        default=ResultRequestStatus.QUEUED,
        editable=False,
        db_index=True,
    )
    attempts_count = models.PositiveIntegerField(default=0, editable=False)
    failure_detail = models.TextField(default="", blank=True, editable=False)
    started_at = models.DateTimeField(null=True, blank=True, editable=False)
    completed_at = models.DateTimeField(null=True, blank=True, editable=False)
    is_submitted = models.BooleanField(default=False, editable=False)
    consent_file = models.FileField(upload_to="booking-consents/", null=True, blank=True)
    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_result_requests",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.pk}"


class ResultRequestFile(BaseUUIDModel):
    result_request = models.ForeignKey(
        ResultRequest, on_delete=models.CASCADE, related_name="files",
    )
    field_name = models.CharField(max_length=50)
    file = models.FileField(upload_to="result-request-files/")
    filename = models.CharField(max_length=255, editable=False)
    content_type = models.CharField(max_length=127, editable=False)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["result_request", "field_name"],
                name="unique_result_request_file_field",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.result_request.pk}: {self.field_name}"


class ServiceResult(BaseUUIDModel):
    result_request = models.ForeignKey(
        ResultRequest,
        on_delete=models.PROTECT,
        related_name="results",
        null=True,
        blank=True,
        editable=False,
    )
    program_service = models.ForeignKey(
        "programs.ProgramService",
        on_delete=models.PROTECT,
        related_name="results",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="service_results",
        null=True,
        blank=True,
    )
    provider_name = models.CharField(
        max_length=200, null=True, blank=True, editable=False
    )
    product_name = models.CharField(
        max_length=100, null=True, blank=True, editable=False
    )

    result_mode = models.CharField(
        choices=ResultType, default=ResultType.UPLOAD, editable=False
    )

    document_type = models.CharField(
        choices=ServiceDocumentType, default=ServiceDocumentType.OTHER
    )
    documents_count = models.PositiveBigIntegerField(default=0, editable=False)
    sample_collection_date = models.DateField(null=True, blank=True)
    report_generation_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_service_results",
    )
    data = models.JSONField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["result_request", "document_type"],
                condition=models.Q(result_request__isnull=False),
                name="unique_result_request_document_type",
            )
        ]

    def __str__(self):
        return f"{self.pk}"


class ServiceDocument(BaseUUIDModel):
    result = models.ForeignKey(
        ServiceResult, on_delete=models.CASCADE, related_name="documents"
    )

    file = models.FileField(upload_to="services/documents/")
    filename = models.CharField(max_length=255, editable=False)
    content_type = models.CharField(max_length=127, editable=False)
    file_hash = models.TextField(editable=False)

    document_category = models.CharField(choices=ServiceDocumentCategory)
    report_component = models.CharField(
        max_length=32, choices=ServiceReportComponent, null=True, blank=True, default=None,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.pk}"
