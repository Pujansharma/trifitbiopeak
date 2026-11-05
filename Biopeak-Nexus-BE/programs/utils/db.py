from datetime import date
from uuid import UUID

from django.db import transaction
from django.db.models import Count, F, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from accounts.centers.models import Center
from accounts.utils import get_user_model
from core.utils.log import logger
from programs.models import (
    Program,
    ProgramService,
    RedemptionHistory,
    TherapyProgram,
    TherapyProgramService,
)
from programs.services.utils.constants import ServiceCategory
from programs.utils.audit import create_program_audit_log
from programs.utils.constants import RedemptionType

User = get_user_model()


def increment_program_service_sessions_used(program_service_id: UUID) -> None:
    Program.objects.filter(program_services__pk=program_service_id).update(
        updated_at=timezone.localtime(),
    )
    updated = TherapyProgramService.objects.filter(
        program_service__pk=program_service_id,
        is_discarded=False,
    ).exclude(
        program_service__program__therapy_program__is_discarded=True,
    ).update(
        sessions_used=F("sessions_used") + 1
    )
    if not updated:
        return
    TherapyProgram.objects.filter(
        program__program_services__pk=program_service_id,
        program__program_services__therapy_service__is_discarded=False,
        is_discarded=False,
    ).update(sessions_used=F("sessions_used") + 1)


def update_program_services_count(program_id: UUID) -> None:
    subquery = (
        ProgramService.objects.filter(program=OuterRef("pk"))
        .exclude(therapy_service__is_discarded=True)
        .values("program")
        .annotate(count=Count("pk"))
        .values("count")
    )
    Program.objects.filter(pk=program_id).update(
        services_count=Coalesce(Subquery(subquery), Value(0))
    )


def update_program_redeemable_centers_count(program_id: UUID) -> None:
    subquery = (
        Center.objects.filter(redeemable_programs=OuterRef("pk"))
        .values("redeemable_programs")
        .annotate(count=Count("pk"))
        .values("count")
    )
    Program.objects.filter(pk=program_id).update(
        redeemable_centers_count=Coalesce(Subquery(subquery), Value(0))
    )


def update_program_sessions_count(program_id: UUID) -> None:
    """Refresh all session totals from non-discarded assignments."""
    totals = TherapyProgramService.objects.filter(
        program_service__program__pk=program_id,
        is_discarded=False,
    ).aggregate(
        sessions_count=Coalesce(Sum("sessions_count"), Value(0)),
        sessions_used=Coalesce(Sum("sessions_used"), Value(0)),
        sessions_cancelled=Coalesce(Sum("sessions_cancelled"), Value(0)),
    )
    TherapyProgram.objects.filter(program__pk=program_id).update(**totals)


def update_program_services_cancelled_count(program_id: UUID) -> None:
    subquery = (
        ProgramService.objects.filter(program=OuterRef("pk"), is_active=False)
        .exclude(therapy_service__is_discarded=True)
        .values("program")
        .annotate(count=Count("pk"))
        .values("count")
    )
    Program.objects.filter(pk=program_id).update(
        services_cancelled=Coalesce(Subquery(subquery), Value(0))
    )


def discard_therapy_program(therapy_program: TherapyProgram, discarded_by: User) -> None:
    """Discard a therapy program and its assignments without cancelling them."""
    program = therapy_program.program
    now = timezone.localtime()
    Program.objects.filter(pk=program.pk).update(updated_at=now)
    updated = TherapyProgram.objects.filter(
        pk=therapy_program.pk, is_discarded=False,
    ).update(is_discarded=True, discarded_by=discarded_by, updated_at=now)
    discarded_services = TherapyProgramService.objects.filter(
        program_service__program=program, is_discarded=False,
    ).update(is_discarded=True, discarded_by=discarded_by, updated_at=now)
    update_program_sessions_count(program.pk)
    update_program_services_count(program.pk)
    update_program_services_cancelled_count(program.pk)
    logger.info(
        f"discard_therapy_program: program={program.pk} "
        f"discarded={updated} discarded_services={discarded_services}."
    )


def discard_therapy_program_service(
        therapy_program_service: TherapyProgramService,
        discarded_by: User,
) -> None:
    """Discard one assignment and refresh its parent's totals."""
    program = therapy_program_service.program_service.program
    now = timezone.localtime()
    Program.objects.filter(pk=program.pk).update(updated_at=now)
    updated = TherapyProgramService.objects.filter(
        pk=therapy_program_service.pk, is_discarded=False,
    ).update(is_discarded=True, discarded_by=discarded_by, updated_at=now)
    update_program_sessions_count(program.pk)
    update_program_services_count(program.pk)
    update_program_services_cancelled_count(program.pk)
    logger.info(
        f"discard_therapy_program_service: program={program.pk} "
        f"program_service={therapy_program_service.pk} discarded={updated}."
    )


def cancel_all_program_services(
        program_id: UUID,
        center_id: UUID,
        cancelled_by: User | None = None,
        cancellation_reason: str | None = None,
        cancelled_date: date = timezone.localdate(),
) -> None:
    now = timezone.now()
    center = Center.objects.filter(pk=center_id).first()
    if not center:
        return None
    with transaction.atomic():
        Program.objects.filter(pk=program_id).update(updated_at=timezone.localtime())
        if TherapyProgram.objects.filter(program__pk=program_id, is_discarded=True).exists():
            return None
        active_services = list(
            TherapyProgramService.objects.filter(
                program_service__program=program_id,
                program_service__is_active=True,
                is_discarded=False,
            ).select_related("program_service__program__cancelled_by")
        )
        if not active_services:
            return None
        program_service_identifiers = []
        histories = []
        for therapy_program_service in active_services:
            remaining = (
                therapy_program_service.sessions_count
                - therapy_program_service.sessions_used
            )
            program_service_identifiers.append(therapy_program_service.program_service.pk)
            if remaining > 0:
                histories.append(
                    RedemptionHistory(
                        therapy_program_service=therapy_program_service,
                        redeem_center=center,
                        redeemed_at=now,
                        quantity=remaining,
                        redeemed_by=cancelled_by,
                        redemption_type=RedemptionType.CANCEL,
                        redeemed_date=cancelled_date,
                    )
                )
        ProgramService.objects.filter(pk__in=program_service_identifiers).update(
            is_active=False,
            cancelled_by=cancelled_by,
            cancellation_reason=cancellation_reason,
            cancelled_at=now,
            cancelled_date=cancelled_date,
        )
        TherapyProgramService.objects.filter(
            program_service__pk__in=program_service_identifiers
        ).update(
            sessions_cancelled=F("sessions_count") - F("sessions_used"),
        )
        update_program_sessions_count(program_id)
        program = active_services[0].program_service.program
        cancellation_fields = {
            "cancelled_by": cancelled_by,
            "cancellation_reason": cancellation_reason,
            "cancelled_at": now,
            "cancelled_date": cancelled_date,
        }
        for field, value in cancellation_fields.items():
            create_program_audit_log(
                program, field, getattr(program, field), value, cancelled_by,
            )
        Program.objects.filter(pk=program_id).update(**cancellation_fields)
        update_program_services_cancelled_count(program_id)
        RedemptionHistory.objects.bulk_create(histories)
    return None


def cancel_program_service(
        program_service_id: UUID,
        program_id: UUID,
        center_id: UUID | None = None,
        cancelled_by: User | None = None,
        cancellation_reason: str | None = None,
        cancelled_date: date = timezone.localdate(),
) -> None:
    program_service = (
        ProgramService.objects.filter(
            pk=program_service_id,
            program__pk=program_id,
        )
        .select_related(
            "program",
            "program__cancelled_by",
            "service",
        )
        .first()
    )
    if not program_service:
        return None
    if TherapyProgramService.objects.filter(
        program_service=program_service, is_discarded=True,
    ).exists():
        return None

    has_other_services = (
        ProgramService.objects.filter(program=program_id)
        .exclude(pk=program_service_id)
        .exists()
    )
    is_therapy_service = (
        program_service.service.service_category == ServiceCategory.THERAPY
    )
    if is_therapy_service and not center_id:
        return None
    if is_therapy_service and not has_other_services:
        cancel_all_program_services(
            program_id, center_id, cancelled_by, cancellation_reason, cancelled_date
        )
        return None

    therapy_program_service = None
    center = None
    remaining = 0
    if is_therapy_service:
        therapy_program_service = (
            TherapyProgramService.objects.filter(
                program_service__pk=program_service_id
            )
            .select_related("program_service")
            .first()
        )
        center = Center.objects.filter(pk=center_id).first()
        if not therapy_program_service or not center:
            return None
        remaining = (
                therapy_program_service.sessions_count
                - therapy_program_service.sessions_used
        )

    now = timezone.now()

    with transaction.atomic():
        Program.objects.filter(pk=program_id).update(updated_at=timezone.localtime())
        if TherapyProgramService.objects.filter(
            program_service=program_service, is_discarded=True,
        ).exists():
            return None
        ProgramService.objects.filter(pk=program_service_id).update(
            is_active=False,
            cancelled_by=cancelled_by,
            cancelled_at=now,
            cancellation_reason=cancellation_reason,
            cancelled_date=cancelled_date,
        )
        update_program_services_cancelled_count(program_id)
        if not has_other_services:
            cancellation_fields = {
                "cancelled_by": cancelled_by,
                "cancellation_reason": cancellation_reason,
                "cancelled_at": now,
                "cancelled_date": cancelled_date,
            }
            for field, value in cancellation_fields.items():
                create_program_audit_log(
                    program_service.program, field,
                    getattr(program_service.program, field), value, cancelled_by,
                )
            Program.objects.filter(pk=program_id).update(**cancellation_fields)
        if is_therapy_service:
            sessions_cancelled_subquery = (
                TherapyProgramService.objects.filter(
                    program_service__program=OuterRef("program"), is_discarded=False,
                )
                .values("program_service__program")
                .annotate(total=Sum("sessions_cancelled"))
                .values("total")
            )
            TherapyProgramService.objects.filter(
                program_service__pk=program_service_id
            ).update(
                sessions_cancelled=F("sessions_count") - F("sessions_used")
            )
            TherapyProgram.objects.filter(program=program_id).update(
                sessions_cancelled=Coalesce(
                    Subquery(sessions_cancelled_subquery), Value(0)
                ),
            )
        if is_therapy_service:
            RedemptionHistory.objects.create(
                therapy_program_service=therapy_program_service,
                redeem_center=center,
                redeemed_at=now,
                quantity=remaining,
                redeemed_by=cancelled_by,
                redemption_type=RedemptionType.CANCEL,
                redeemed_date=cancelled_date,
            )
    return None
