from collections.abc import Iterable
from uuid import UUID

from rest_framework import serializers

from accounts.centers.models import Center
from programs.services.models import Service
from programs.services.utils.constants import ServiceCategory


def validate_therapy_service_centers(
    center_selections: list[dict],
    allowed_centers: dict[UUID, Center],
    error_field: str,
) -> list[Center]:
    selected_identifiers = set()
    for selection in center_selections:
        selected_identifiers.add(selection.get("id"))
    if not selected_identifiers:
        raise serializers.ValidationError(
            {error_field: "Select at least one redemption center."}
        )
    if selected_identifiers - allowed_centers.keys():
        raise serializers.ValidationError(
            {error_field: "Centers must be active members of the program's redeemable centers."}
        )
    centers = []
    for center_identifier in selected_identifiers:
        centers.append(allowed_centers[center_identifier])
    return centers


def validate_composite_therapy_centers(
    service_centers: list[dict],
    template_services: list,
    allowed_centers: dict[UUID, Center],
) -> dict[UUID, list[Center]]:
    therapy_identifiers = set()
    for template_service in template_services:
        if template_service.service.service_category == ServiceCategory.THERAPY:
            therapy_identifiers.add(template_service.service.pk)
    centers_by_service = {}
    for selection in service_centers:
        service_identifier = selection["id"]
        if service_identifier not in therapy_identifiers:
            raise serializers.ValidationError(
                {"therapy_service_centers": "Select only active therapy services from this template."}
            )
        if service_identifier in centers_by_service:
            raise serializers.ValidationError(
                {"therapy_service_centers": "Duplicate therapy service selections are not allowed."}
            )
        centers_by_service[service_identifier] = validate_therapy_service_centers(
            selection["centers"], allowed_centers, "therapy_service_centers"
        )
    if therapy_identifiers - centers_by_service.keys():
        raise serializers.ValidationError(
            {"therapy_service_centers": "Select redemption centers for every active therapy service in the template."}
        )
    return centers_by_service


def validate_therapy_template_quantities(
    service_quantities: Iterable[tuple[Service, int | None]],
    error_field: str,
) -> None:
    invalid_identifiers = {
        str(service.pk)
        for service, quantity in service_quantities
        if service.service_category == ServiceCategory.THERAPY
        and (quantity is None or quantity < 1)
    }
    if invalid_identifiers:
        raise serializers.ValidationError(
            {
                error_field: (
                    "A positive quantity is required for therapy services: "
                    f"{', '.join(sorted(invalid_identifiers))}."
                )
            }
        )
