"""Additive connection metadata; existing card states and endpoint paths stay stable."""
from django.db.models import Max, Prefetch, prefetch_related_objects
from django.utils import timezone

from wearables.models import HealthDailySummary, RookOutbox, WearableConnection
from wearables.services.progress_policy import (
    domain_sync_progress,
    sync_operation_state,
    sync_unit_progress,
)
from wearables.services.job_claims import maximum_rook_outbox_attempts
from wearables.utils.constants import HealthJobType

SYNC_JOB_TYPES = (HealthJobType.FETCH_ROOK_DATA, HealthJobType.AUTHORISE_ROOK_CONNECTION, HealthJobType.REVOKE_ROOK_CONNECTION)
STATE_MESSAGES = {
    "queued": "Your sync is scheduled.",
    "processing": "Updating your health data.",
    "waiting": "Waiting to retry automatically.",
    "completed": "Sync completed.",
    "completed_no_new_data": "Checked successfully. No new measurements were available.",
    "failed": "Sync could not complete.",
    "skipped": "History import was skipped. Live synchronization remains available.",
}


def attach_connection_progress(connections: list, customer_profile):
    """One bounded latest-job prefetch and one aggregate for the whole device list."""
    prefetch_related_objects(connections, Prefetch(
        "rook_outboxes", queryset=RookOutbox.objects.filter(job_type__in=SYNC_JOB_TYPES)
        .order_by("-created_at", "-pk")[:1], to_attr="latest_sync_jobs",
    ))
    by_source = {connection.data_source: connection for connection in connections}
    for connection in connections:
        connection.measurement_domains = {}
    rows = HealthDailySummary.objects.filter(
        customer_profile=customer_profile, last_observed_at__isnull=False,
    ).values("domain", "data_sources").annotate(latest=Max("last_observed_at"))
    for row in rows.iterator():
        for source in row["data_sources"]:
            connection = by_source.get(source)
            if connection is not None:
                prior = connection.measurement_domains.get(row["domain"])
                connection.measurement_domains[row["domain"]] = max(filter(None, (prior, row["latest"])))


def connection_measurement_domains(connection: WearableConnection):
    if not hasattr(connection, "measurement_domains"):
        rows = HealthDailySummary.objects.filter(
            customer_profile=connection.customer_profile,
            data_sources__contains=[connection.data_source],
        ).values("domain").annotate(latest=Max("last_observed_at"))
        connection.measurement_domains = {row["domain"]: row["latest"] for row in rows}
    return connection.measurement_domains


def connection_latest_measurement(connection: WearableConnection):
    return max(connection_measurement_domains(connection).values(), default=None)


def connection_sync_progress(connection: WearableConnection):
    if hasattr(connection, "current_sync_progress"):
        return connection.current_sync_progress
    jobs = getattr(connection, "latest_sync_jobs", None)
    job = (jobs[0] if jobs else None) if jobs is not None else connection.rook_outboxes.filter(
        job_type__in=SYNC_JOB_TYPES,
    ).order_by("-created_at", "-pk").first()
    if job is None or job.payload.get("generation") != str(connection.authorization_generation):
        return None
    now = timezone.localtime()
    state = sync_operation_state(
        status=job.status, payload=job.payload, attempts=job.attempt_count,
        maximum_attempts=maximum_rook_outbox_attempts(job.job_type),
        scheduled_at=job.scheduled_at,
        now=now,
    )
    result = job.payload.get("result", {})
    plan = job.payload.get("sync", {})
    completed_at = job.completed_at
    action = None
    if state == "failed":
        action = "reconnect" if job.job_type == HealthJobType.AUTHORISE_ROOK_CONNECTION else "retry_sync"
        if job.job_type == HealthJobType.REVOKE_ROOK_CONNECTION:
            action = "retry_disconnect"
        if connection.authorization_status in {"expired", "revoked"} and job.job_type != HealthJobType.REVOKE_ROOK_CONNECTION:
            action = "reconnect"
        action = job.payload.get("failure", {}).get("recoveryAction", action)
    message = STATE_MESSAGES[state]
    if job.job_type == HealthJobType.AUTHORISE_ROOK_CONNECTION:
        message = "Connection verified." if state == "completed" else "Verifying your provider connection."
        if state == "failed":
            message = "We could not verify your connection."
    if job.job_type == HealthJobType.REVOKE_ROOK_CONNECTION:
        message = "Provider disconnection confirmed." if state == "completed" else "Disconnected locally. Provider confirmation is pending."
    connection.current_sync_progress = {
        "jobId": str(job.pk), "operation": job.job_type, "status": state,
        "message": message, "reason": result.get("reason"),
        "requestedAt": job.created_at, "completedAt": completed_at,
        "nextRetryAt": job.scheduled_at if state == "waiting" else None,
        "recoveryAction": action, "diagnostics": sync_unit_progress(plan),
        "domains": domain_sync_progress(
            plan=plan, operation_state=state,
            observed_domains=set(connection_measurement_domains(connection)),
            new_domains=set(job.payload.get("newMeasurementDomains", [])),
        ) if job.job_type == HealthJobType.FETCH_ROOK_DATA else [],
    }
    return connection.current_sync_progress
