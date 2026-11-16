"""Pure sync presentation rules. Job progress never creates health-card states."""
from datetime import date, datetime, timedelta

PILLAR_DOMAINS = {
    "physical": ("activity", "heart", "recovery", "workouts"),
    "sleep": ("sleep",),
    "body": ("body", "heart"),
}
DOMAIN_ORDER = ("sleep", "activity", "heart", "recovery", "body", "workouts")
WAIT_REASONS = frozenset({"provider_budget", "provider_429", "budget_contention", "pulls_paused",
                          "authorization_pending", "awaiting_provider_revocation"})


def sync_unit_progress(plan: dict):
    if not plan:
        return {"checkedUnits": 0, "totalUnits": 0}
    start = date.fromisoformat(plan["startDate"])
    end = date.fromisoformat(plan["endDate"])
    total = max(0, (end - start).days + 1) * 3
    return {"checkedUnits": min(total, int(plan.get("requestCount", 0))), "totalUnits": total}


def sync_operation_state(*, status: str, payload: dict, attempts: int,
                         maximum_attempts: int, scheduled_at: datetime, now: datetime):
    result = payload.get("result", {})
    if status == "completed":
        if result.get("skipped"):
            return "skipped"
        # Old jobs did not distinguish fetched documents from new measurements.
        if "newObservationCount" not in result:
            return "completed"
        return "completed" if result["newObservationCount"] else "completed_no_new_data"
    if status == "running":
        return "processing"
    if status == "failed":
        return "failed" if attempts >= maximum_attempts else "waiting"
    if scheduled_at > now and result.get("reason") in WAIT_REASONS:
        return "waiting"
    return "queued"


def domain_sync_progress(*, plan: dict, operation_state: str, observed_domains: set[str],
                         new_domains: set[str]):
    next_date = date.fromisoformat(plan["nextDate"]) if plan else None
    start = date.fromisoformat(plan["startDate"]) if plan else None
    end = date.fromisoformat(plan["endDate"]) if plan else None
    next_pillar = int(plan.get("nextPillar", 0))
    pillars = ("physical", "sleep", "body")
    results = []
    for domain in DOMAIN_ORDER:
        relevant = [index for index, pillar in enumerate(pillars) if domain in PILLAR_DOMAINS[pillar]]
        completed = bool(plan) and all(
            next_date > end or (next_date == end and next_pillar > index)
            for index in relevant
        )
        progressed = bool(plan) and (next_date > start or next_pillar > min(relevant))
        state = "pending"
        if operation_state == "skipped":
            state = "skipped"
        elif completed:
            state = "checked"
        elif operation_state == "failed":
            state = "partial" if progressed else "failed"
        elif operation_state == "waiting":
            state = "waiting"
        elif operation_state == "processing" or progressed:
            state = "processing"
        results.append({"domain": domain, "syncState": state,
                        "hasStoredMeasurements": domain in observed_domains,
                        "newMeasurementsProcessed": domain in new_domains})
    return results


def revocation_confirmation_policy(*, provider: str, requested_at: datetime, now: datetime,
                                   ordinary_minutes: int = 30, withings_hours: int = 48):
    maximum = timedelta(hours=withings_hours) if provider == "Withings" else timedelta(minutes=ordinary_minutes)
    elapsed = now - requested_at
    return {"expired": elapsed >= maximum,
            "retryAfterSeconds": 900 if provider == "Withings" and elapsed >= timedelta(minutes=5) else 60}


def failure_recovery_action(*, job_type: str, status_code: int = 0, configuration_error: bool = False):
    if configuration_error or status_code in {400, 401, 403, 404}:
        return "contact_support"
    if job_type == "authorise_rook_connection":
        return "reconnect"
    if job_type == "revoke_rook_connection":
        return "retry_disconnect"
    if job_type == "fetch_rook_data" and status_code != 422:
        return "retry_sync"
    return "contact_support"
