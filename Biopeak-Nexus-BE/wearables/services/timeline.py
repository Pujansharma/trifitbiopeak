"""Provider-independent, read-only composite timeline for an owned customer profile.

No writes, signals, changes to legacy models, or exposure of report documents.
Chronology is based on stored record creation instants; report/sample dates are
separate metadata because the original tables do not guarantee event times.
"""
from datetime import date, datetime, timedelta, time, timezone as dt_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings

from wearables.models import HealthObservation
from wearables.utils.constants import HealthCardState

# Classification uses the client's existing clinical result codes; do not
# assume other assessment report types represent blood diagnostics.
LAB_DOCUMENT_TYPES = frozenset({
    "blood", "omics_urine", "omics_cortisol",
    "steroid_hormone_profile", "steroid_hormone_nad_longevity",
    "steroid_hormone_nutri_toxic", "steroid_hormone_fatty_acid",
    "steroid_hormone_neurotransmitter_profile",
})


def _member_zone(timezone_name: str):
    try:
        return ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _local_day(timestamp, timezone_name: str):
    return timestamp.astimezone(_member_zone(timezone_name)).date()


def _clinical_date_bounds(start_date, end_date, timezone_name):
    """UTC half-open datetime bounds derived from the member's local days."""
    zone = _member_zone(timezone_name)
    lower = datetime.combine(start_date, time.min, tzinfo=zone).astimezone(dt_timezone.utc) if start_date else None
    upper = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=zone).astimezone(dt_timezone.utc) if end_date else None
    return lower, upper


def _wearable_entries(customer_profile, *, start_date, end_date, domain, maximum):
    from wearables.services.analytics import observation_value

    observations = HealthObservation.objects.filter(
        customer_profile=customer_profile, is_current=True
    )
    if start_date:
        observations = observations.filter(local_date__gte=start_date)
    if end_date:
        observations = observations.filter(local_date__lte=end_date)
    if domain:
        observations = observations.filter(domain=domain)
    observations = observations.order_by("-observed_at", "-created_at")[:maximum]
    return [
        {
            "id": str(obs.pk),
            "timestamp": obs.observed_at,
            "localDate": obs.local_date,
            "sourceType": "wearable",
            "domain": obs.domain,
            "metric": obs.metric,
            "value": observation_value(obs),
            "unit": obs.unit,
            "confidence": obs.confidence,
            "provenance": {
                "sources": obs.data_sources,
                "sourceKey": obs.source_key,
                "documentVersion": obs.document_version,
                "sourceChange": obs.provenance.get("sourceChange"),
                "clinicalReviewSuggested": obs.provenance.get("clinicalReviewSuggested", False),
            },
        }
        for obs in observations
    ]


def _clinical_entries(customer_profile, *, start_date, end_date, maximum, timezone_name):
    """Existing service results + completed diagnostic orders for this profile.

    Every queryset is scoped through a concrete profile FK. Neither document
    storage paths nor health/lab result data are copied into the timeline.
    """
    from programs.services.models import ServiceResult
    from diagnostics_orders.models import DiagnosticOrderCustomer
    from diagnostics_orders.utils.constants import DiagnosticOrderStatus

    lower, upper = _clinical_date_bounds(start_date, end_date, timezone_name)
    results = ServiceResult.objects.filter(
        program_service__program__customer_profile=customer_profile,
    ).select_related("program_service__service").order_by("-created_at")
    if lower is not None:
        results = results.filter(created_at__gte=lower)
    if upper is not None:
        results = results.filter(created_at__lt=upper)
    events = []
    for result in results[:maximum]:
        is_lab = result.document_type in LAB_DOCUMENT_TYPES
        source_type = "lab" if is_lab else "assessment"
        title = result.product_name or result.get_document_type_display()
        events.append({
            "id": f"service-result:{result.pk}",
            "timestamp": result.created_at,
            "localDate": _local_day(result.created_at, timezone_name),
            "sourceType": source_type,
            "domain": None,
            "metric": "lab_result" if is_lab else "assessment_result",
            "title": str(title)[:200],
            "value": None,
            "unit": "",
            "confidence": None,
            "provenance": {"source": "biopeak_service_result", "id": str(result.pk)},
            "reportDate": result.report_generation_date,
            "sampleDate": result.sample_collection_date,
        })
    orders = DiagnosticOrderCustomer.objects.filter(
        customer_profile=customer_profile,
        order__status=DiagnosticOrderStatus.ORDER_COMPLETED,
    ).exclude(order__reports=[]).select_related("order").order_by("-order__created_at")
    if lower is not None:
        orders = orders.filter(order__created_at__gte=lower)
    if upper is not None:
        orders = orders.filter(order__created_at__lt=upper)
    for customer_order in orders[:maximum]:
        event_at = customer_order.order.created_at
        events.append({
            "id": f"diagnostic-report:{customer_order.pk}",
            "timestamp": event_at,
            "localDate": _local_day(event_at, timezone_name),
            "sourceType": "lab",
            "domain": None,
            "metric": "diagnostic_report",
            "title": "Diagnostic report available",
            "value": None,
            "unit": "",
            "confidence": None,
            "provenance": {"source": "biopeak_diagnostics_order", "id": str(customer_order.order_id)},
        })
    return events


def _timeline_gaps(*, customer_profile, start_date, end_date, domain) -> list[dict]:
    """Compute missing *recorded* days for the whole filtered time range.

    Gaps must not disappear when consecutive known days fall on two separate
    pagination pages. This query returns distinct dates only, not health values.
    """
    observations = HealthObservation.objects.filter(
        customer_profile=customer_profile, is_current=True,
    )
    if start_date:
        observations = observations.filter(local_date__gte=start_date)
    if end_date:
        observations = observations.filter(local_date__lte=end_date)
    if domain:
        observations = observations.filter(domain=domain)
    rows = observations.order_by("domain", "local_date").values_list(
        "domain", "local_date",
    ).distinct()
    gaps = []
    previous = {}
    for domain_name, local_date in rows.iterator():
        earlier = previous.get(domain_name)
        if earlier and (local_date - earlier).days > 1:
            gaps.append({
                "domain": domain_name,
                "state": HealthCardState.HISTORICAL_GAP,
                "startDate": earlier + timedelta(days=1),
                "endDate": local_date - timedelta(days=1),
                "missingDays": (local_date - earlier).days - 1,
            })
        previous[domain_name] = local_date
    return gaps


def timeline_payload(*, customer_profile, start_date: date | None, end_date: date | None,
                     domain: str | None, offset: int, limit: int) -> dict:
    maximum = offset + limit + 1
    items = _wearable_entries(
        customer_profile,
        start_date=start_date, end_date=end_date, domain=domain, maximum=maximum,
    )
    # Domain filtering applies only to the six wearable domains; legacy
    # reports have no medically validated cross-domain classification.
    include_clinical = bool(getattr(settings, "TIMELINE_INCLUDE_LEGACY_RESULTS", True))
    if domain is None and include_clinical:
        identity = getattr(customer_profile, "rook_identity", None)
        timezone_name = identity.timezone_name if identity is not None else "UTC"
        items.extend(_clinical_entries(
            customer_profile, start_date=start_date, end_date=end_date,
            maximum=maximum, timezone_name=timezone_name,
        ))
    items.sort(key=lambda item: (item["timestamp"], item["id"]), reverse=True)
    page = items[offset : offset + limit]
    return {
        "entries": page,
        "gaps": _timeline_gaps(
            customer_profile=customer_profile, start_date=start_date,
            end_date=end_date, domain=domain,
        ),
        "gapScope": "filtered_timeline",
        "nextOffset": offset + limit if len(items) > offset + limit else None,
        "sourceTypes": ["wearable", "lab", "assessment"] if include_clinical and domain is None else ["wearable"],
        "chronologyBasis": "recorded_at",  # event/reference dates may be separately present
    }
