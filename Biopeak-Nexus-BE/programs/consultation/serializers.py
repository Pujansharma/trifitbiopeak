from pathlib import Path

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from accounts.users.serializers import BaseUserSerializer
from core.utils.log import logger
from core.utils.serializers import BaseModelSerializer, BaseSerializer
from programs.models import ConsultationDocument, ProgramService
from programs.consultation.utils.db import update_consultation_counts
from programs.program_services.utils.helper import generate_file_hash
from programs.utils.constants import ConsultationDocumentType, ConsultationType


class ConsultationDocumentFilterSerializer(BaseSerializer):
    document_type = serializers.ChoiceField(choices=ConsultationDocumentType, required=False)
    consultation_type = serializers.ChoiceField(choices=ConsultationType, required=False)
    consultation_date = serializers.DateField(required=False)


def validate_consultation_program_service(program_service: ProgramService) -> None:
    program = program_service.program
    if not program.is_active or not program_service.is_active:
        raise serializers.ValidationError("Inactive or cancelled consultations are read only.")
    if program.expires_at is not None and program.expires_at < timezone.localdate():
        raise serializers.ValidationError("Expired consultation programs are read only.")


class ConsultationDocumentSerializer(BaseModelSerializer):
    document_type = serializers.ChoiceField(choices=ConsultationDocumentType, required=True)
    document_type_code = serializers.CharField(source="document_type", read_only=True)
    consultation_type = serializers.ChoiceField(
        choices=ConsultationType, default=ConsultationType.BASELINE,
    )
    consultation_type_code = serializers.CharField(source="consultation_type", read_only=True)
    consultation_date = serializers.DateField(default=timezone.localdate)
    created_by = BaseUserSerializer(read_only=True)

    class Meta:
        model = ConsultationDocument
        fields = [
            "id", "document_type", "document_type_code", "consultation_type",
            "consultation_type_code", "consultation_date", "file", "filename",
            "content_type", "files_count", "created_by", "is_active", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "filename", "content_type", "files_count", "created_by",
            "is_active", "created_at", "updated_at",
        ]

    def validate_consultation_date(self, value):
        if value > timezone.localdate():
            raise serializers.ValidationError("Consultation date cannot be in the future.")
        return value

    def create(self, validated_data: dict):
        program_service = validated_data.pop("program_service")
        validate_consultation_program_service(program_service)
        consultation_service = program_service.consultation_service
        validated_data["consultation_program_service"] = consultation_service
        uploaded_file = validated_data["file"]
        validated_data["filename"] = Path(uploaded_file.name).name
        validated_data["content_type"] = uploaded_file.content_type or "application/octet-stream"
        validated_data["file_hash"] = generate_file_hash(uploaded_file)
        with transaction.atomic():
            document = super().create(validated_data)
            update_consultation_counts(consultation_service)
        logger.info(
            f"ConsultationDocumentSerializer.create: created document={document.pk}, "
            f"consultation_service={consultation_service.pk}."
        )
        return document
