from collections.abc import Iterable
from uuid import UUID

from django.db.models import QuerySet

from accounts.centers.models import Center
from accounts.customers.models import CustomerProfile
from programs.composites.models import CompositeTemplateService
from programs.services.models import CenterServiceAssignment, Service
from programs.services.utils.constants import ServiceCategory


def get_selected_therapy_centers(
        center_selections: list[dict],
        allowed_centers: dict[UUID, Center],
) -> list[Center]:
    """Return selected centers, or an empty list if any are outside the scope."""
    selected_identifiers = set()
    for selection in center_selections:
        selected_identifiers.add(selection.get("id"))
    if selected_identifiers - allowed_centers.keys():
        return []
    centers = []
    for center_identifier in selected_identifiers:
        centers.append(allowed_centers[center_identifier])
    return centers


def get_therapy_template_service_identifiers(
        template_services: list[CompositeTemplateService],
) -> set[UUID]:
    therapy_identifiers = set()
    for template_service in template_services:
        if template_service.service.service_category == ServiceCategory.THERAPY:
            therapy_identifiers.add(template_service.service.pk)
    return therapy_identifiers


def get_invalid_therapy_service_identifiers(
        therapy_services: list[dict],
        therapy_identifiers: set[UUID],
) -> set[UUID]:
    invalid_identifiers = set()
    for selection in therapy_services:
        service_identifier = selection["id"]
        if service_identifier not in therapy_identifiers:
            invalid_identifiers.add(service_identifier)
    return invalid_identifiers


def get_duplicate_therapy_service_identifiers(
        therapy_services: list[dict],
) -> set[UUID]:
    selected_identifiers = set()
    duplicate_identifiers = set()
    for selection in therapy_services:
        service_identifier = selection["id"]
        if service_identifier in selected_identifiers:
            duplicate_identifiers.add(service_identifier)
        selected_identifiers.add(service_identifier)
    return duplicate_identifiers


def get_eligible_customer_centers(
        center_identifiers: set[UUID],
        customer_profile: CustomerProfile,
) -> QuerySet[Center]:
    return Center.objects.filter(
        pk__in=center_identifiers,
        is_active=True,
        customer_assignments__customer_profile=customer_profile,
        customer_assignments__is_active=True,
    )


def get_available_therapy_center_pairs(
        therapy_identifiers: set[UUID],
        center_identifiers: set[UUID],
) -> set[tuple[UUID, UUID]]:
    return set(
        CenterServiceAssignment.objects.filter(
            service__pk__in=therapy_identifiers,
            center__pk__in=center_identifiers,
            center__is_active=True,
            is_active=True,
        ).values_list("service__pk", "center__pk")
    )


def get_invalid_therapy_quantity_identifiers(
        service_quantities: Iterable[tuple[Service, int | None]],
) -> set[str]:
    invalid_identifiers = set()
    for service, quantity in service_quantities:
        if service.service_category == ServiceCategory.THERAPY:
            if quantity is None or quantity < 1:
                invalid_identifiers.add(str(service.pk))
    return invalid_identifiers
