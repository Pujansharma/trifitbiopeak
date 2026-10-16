from django.utils import timezone

from accounts.customers.models import CustomerProfile
from diagnostics_orders.models import DiagnosticOrder
from programs.services.utils.constants import ModuleCategoryType

BLOOD_MODULE_LABEL = "Blood Diagnostics"
DEFAULT_FILE_TYPE_LABEL = "Blood Report"
PROVIDER_SOURCE_LABEL = "Provider"
PROVIDER_SOURCE_CODE = "provider"


def build_diagnostics_attachments_for_profile(
    customer_profile: CustomerProfile | None,
    *,
    category_type: str | None = None,
):
    if customer_profile is None:
        return []
    if (
        category_type
        and category_type != ModuleCategoryType.CLINICAL_LAB_DIAGNOSTICS
    ):
        return []

    orders = (
        DiagnosticOrder.objects.filter(customers__customer_profile=customer_profile)
        .exclude(reports=[])
        .distinct()
        .order_by("-created_at")
    )
    attachments = []
    for order in orders:
        attachments.extend(build_attachments_for_order(order))
    return attachments


def build_attachments_for_order(order: DiagnosticOrder):
    reports = order.reports or []
    if not isinstance(reports, list) or not reports:
        return []

    attachment_date = None
    if order.slot_datetime is not None:
        attachment_date = timezone.localtime(order.slot_datetime).date().isoformat()

    created_at = None
    if order.created_at is not None:
        created_at = timezone.localtime(order.created_at).isoformat()
    updated_at = None
    if order.updated_at is not None:
        updated_at = timezone.localtime(order.updated_at).isoformat()

    attachments = []
    for report in reports:
        attachment = build_attachment_from_report(
            order=order,
            report=report,
            attachment_date=attachment_date,
            created_at=created_at,
            updated_at=updated_at,
        )
        if attachment is not None:
            attachments.append(attachment)
    return attachments


def build_attachment_from_report(
    *,
    order: DiagnosticOrder,
    report,
    attachment_date: str | None,
    created_at: str | None,
    updated_at: str | None,
):
    if not isinstance(report, dict):
        return None
    report_id = report.get("id")
    file_url = (report.get("tokenize_public_file_url") or "").strip()
    if report_id is None or not file_url:
        return None

    file_name = (report.get("file_name") or "").strip() or f"report-{report_id}.pdf"
    file_type = (report.get("file_type") or "").strip() or DEFAULT_FILE_TYPE_LABEL
    attachment_id = f"diag-report-{order.pk}-{report_id}"
    metadata_id = f"diag-meta-{order.pk}-{report_id}"
    category_label = ModuleCategoryType.CLINICAL_LAB_DIAGNOSTICS.label

    return {
        "id": attachment_id,
        "has_pii": False,
        "file": file_url,
        "name": file_name,
        "file_type": file_type,
        "redacted_file": None,
        "attachment_date": attachment_date,
        "created_at": created_at,
        "updated_at": updated_at,
        "metadata": {
            "id": metadata_id,
            "module_type": BLOOD_MODULE_LABEL,
            "category_type": category_label,
            "questionnaire_date": attachment_date,
            "assessment_date": attachment_date,
            "source": PROVIDER_SOURCE_LABEL,
            "source_code": PROVIDER_SOURCE_CODE,
            "practitioner_name": None,
            "consultation_type": None,
            "language": None,
            "notes": None,
            "attachment": None,
            "files_count": 1,
            "created_at": created_at,
            "updated_at": updated_at,
        },
    }
