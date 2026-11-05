from uuid import UUID

from django.db.models import Exists, F, OuterRef, Q, QuerySet
from django.utils import timezone
from rest_framework import serializers

from programs.models import ProgramService, TherapyProgramService
from programs.services.utils.constants import ServiceCategory
from programs.utils.constants import ProgramType


def therapy_services_at_center(center_identifier: UUID) -> QuerySet:
    return TherapyProgramService.objects.filter(
        is_active=True,
        is_discarded=False,
        program_service__is_active=True,
        program_service__program__program_type=ProgramType.THERAPY,
        program_service__program__is_active=True,
        program_service__program__therapy_program__is_active=True,
        program_service__program__therapy_program__is_discarded=False,
        program_service__program__redeemable_centers__pk=center_identifier,
        redeemable_centers__pk=center_identifier,
        program_service__service__center_assignments__center__pk=center_identifier,
        program_service__service__center_assignments__is_active=True,
    )


def composite_therapy_services_for_redemption(
    center_identifier: UUID | None = None,
) -> QuerySet:
    filter_kwargs = {}
    if center_identifier is not None:
        filter_kwargs["program_service__service__center_assignments__center__pk"] = center_identifier
    redemption_center = F("program_service__service__center_assignments__center")
    selected_centers = TherapyProgramService.objects.filter(
        pk=OuterRef("pk"), redeemable_centers__isnull=False,
    )
    return TherapyProgramService.objects.filter(
        Q(program_service__program__expires_at__isnull=True)
        | Q(program_service__program__expires_at__gte=timezone.localdate()),
        Q(program_service__program__composite_program__therapy_redemption_is_global=True)
        | Q(program_service__program__redeemable_centers=redemption_center),
        Q(redeemable_centers=redemption_center)
        | Q(
            ~Exists(selected_centers),
            program_service__program__composite_program__therapy_redemption_is_global=True,
        ),
        is_active=True,
        program_service__is_active=True,
        program_service__program__program_type=ProgramType.COMPOSITE,
        program_service__program__is_active=True,
        program_service__program__composite_program__is_active=True,
        program_service__service__is_active=True,
        program_service__service__service_category=ServiceCategory.THERAPY,
        sessions_used__lt=F("sessions_count"),
        program_service__service__center_assignments__center__is_active=True,
        program_service__service__center_assignments__is_active=True,
        program_service__program__customer_profile__center_assignments__center=redemption_center,
        program_service__program__customer_profile__center_assignments__is_active=True,
        **filter_kwargs,
    )


def ensure_therapy_service_center(
    program_service: ProgramService,
    center_identifier: UUID,
    field_name: str = "center_id",
) -> None:
    eligibility_query = {
        ProgramType.THERAPY: therapy_services_at_center,
        ProgramType.COMPOSITE: composite_therapy_services_for_redemption,
    }.get(program_service.program.program_type)
    if eligibility_query is None:
        return
    if (
        not eligibility_query(center_identifier)
        .filter(program_service=program_service)
        .exists()
    ):
        raise serializers.ValidationError(
            {
                field_name: [
                    "This program service is not redeemable or available at this center."
                ]
            }
        )
