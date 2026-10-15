from collections import defaultdict
from datetime import date, timedelta
from statistics import mean
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.cache import caches
from django.utils import timezone

from wearables.models import (
    HealthDailySummary,
    HealthDomainSnapshot,
    HealthObservation,
    WearableConnection,
)
from wearables.utils.constants import (
    ALGORITHM_VERSION,
    DOMAIN_DEFAULT_UNITS,
    DOMAIN_TITLES,
    HEADLINE_METRICS,
    HEALTH_DOMAIN_ORDER,
    LOWER_IS_BETTER_METRICS,
    MINIMUM_MEANINGFUL_CHANGE,
    ConfidenceLevel,
    ConnectionStatus,
    HealthCardState,
    HealthDomain,
    HistoricalImportStatus,
    PermissionStatus,
    PreferredUnits,
    TrendDirection,
)




def member_today(customer_profile) -> date:
    """Health data windows always follow the member's local calendar."""
    identity = getattr(customer_profile, "rook_identity", None)
    timezone_name = identity.timezone_name if identity else "UTC"
    try:
        return timezone.now().astimezone(ZoneInfo(timezone_name)).date()
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.now().date()


def health_cache_key(customer_profile) -> str:
    return f"health:dashboard:v2:{customer_profile.pk}"


def health_cache():
    return caches["health"]


def invalidate_health_dashboard(customer_profile) -> None:
    health_cache().delete(health_cache_key(customer_profile))

def domain_enabled(domain: str) -> bool:
    settings_map = {
        HealthDomain.RECOVERY: "RECOVERY_DOMAIN_ENABLED",
        HealthDomain.BODY: "BODY_DOMAIN_ENABLED",
    }
    setting_name = settings_map.get(domain)
    if setting_name is None:
        return True
    return getattr(settings, setting_name, True)


def summary_numeric_value(summary: HealthDailySummary) -> float | None:
    if summary.metric == "steps":
        return summary.maximum
    if summary.metric == "workout_count":
        return summary.total
    if summary.metric in {
        "average_heart_rate",
        "stress_level",
        "workout_duration_seconds",
    }:
        return summary.average
    return summary.latest


def one_summary_per_day(summaries: list[HealthDailySummary]) -> list[HealthDailySummary]:
    selected: dict[date, HealthDailySummary] = {}
    for summary in summaries:
        current = selected.get(summary.local_date)
        if current is None:
            selected[summary.local_date] = summary
            continue
        current_time = current.last_observed_at or current.updated_at
        candidate_time = summary.last_observed_at or summary.updated_at
        if candidate_time > current_time:
            selected[summary.local_date] = summary
    return [selected[local_date] for local_date in sorted(selected)]


def headline_series(
    *,
    customer_profile,
    domain: str,
    days: int = 90,
) -> tuple[str | None, list[HealthDailySummary]]:
    cutoff = member_today(customer_profile) - timedelta(days=days - 1)
    for metric in HEADLINE_METRICS[domain]:
        summaries = list(
            HealthDailySummary.objects.filter(
                customer_profile=customer_profile,
                domain=domain,
                metric=metric,
                local_date__gte=cutoff,
            ).order_by("local_date", "last_observed_at")
        )
        if summaries:
            return metric, one_summary_per_day(summaries)
    return None, []


def display_value(
    *,
    value: float,
    metric: str,
    preferred_units: str,
) -> tuple[float, str]:
    """Convert server-side for all V1 display metrics, never in the mobile app."""
    imperial = preferred_units == PreferredUnits.IMPERIAL
    if metric == "sleep_duration_seconds":
        return round(value / 3600.0, 2), "hours"
    if metric in {"weight_kg", "muscle_mass_kg"}:
        return (round(value * 2.2046226218, 2), "lb") if imperial else (round(value, 2), "kg")
    if metric.endswith("_meters"):
        return (round(value / 1609.344, 2), "mi") if imperial else (round(value / 1000.0, 2), "km")
    if metric.endswith("_seconds"):
        return round(value / 60.0, 2), "min"
    units = {
        "steps": "steps", "resting_heart_rate": "bpm",
        "average_heart_rate": "bpm", "maximum_heart_rate": "bpm",
        "hrv_rmssd": "ms", "recovery_score": "score",
        "readiness_score": "score", "stress_level": "score",
        "body_fat_percentage": "%", "body_water_percentage": "%",
        "bmi": "kg/m²", "workout_count": "sessions",
        "workout_calories_kcal": "kcal",
    }
    return round(value, 2), units.get(metric, "")


def graph_values(
    *,
    summaries: list[HealthDailySummary],
    metric: str,
    preferred_units: str,
) -> list[dict]:
    points = []
    for summary in summaries:
        value = summary_numeric_value(summary)
        if value is None:
            continue
        converted, unit = display_value(
            value=value,
            metric=metric,
            preferred_units=preferred_units,
        )
        points.append(
            {
                "date": summary.local_date,
                "value": converted,
                "unit": unit,
            }
        )
    return points


def coverage_details(summaries: list[HealthDailySummary]) -> dict:
    if not summaries:
        return {
            "observationDays": 0,
            "expectedDays": 0,
            "missingDays": 0,
            "ratio": 0.0,
        }
    first_date = summaries[0].local_date
    last_date = summaries[-1].local_date
    expected_days = min((last_date - first_date).days + 1, 30)
    observation_days = len({summary.local_date for summary in summaries[-30:]})
    missing_days = max(expected_days - observation_days, 0)
    ratio = observation_days / expected_days if expected_days else 0.0
    return {
        "observationDays": observation_days,
        "expectedDays": expected_days,
        "missingDays": missing_days,
        "ratio": round(ratio, 3),
    }


def confidence_level(coverage: dict, summaries: list[HealthDailySummary]) -> str:
    observation_count = len(summaries)
    ratio = coverage["ratio"]
    if observation_count >= 21 and ratio >= 0.85:
        return ConfidenceLevel.HIGH
    if observation_count >= 7 and ratio >= 0.6:
        return ConfidenceLevel.MEDIUM
    if observation_count:
        return ConfidenceLevel.LOW
    return ConfidenceLevel.UNKNOWN


def history_window_availability(
    summaries: list[HealthDailySummary],
) -> dict[str, dict]:
    observation_days = len(summaries)
    return {
        "7d": {
            "available": observation_days >= 7,
            "requiredObservationDays": 7,
            "observationDays": min(observation_days, 7),
        },
        "30d": {
            "available": observation_days >= 21,
            "requiredObservationDays": 21,
            "observationDays": min(observation_days, 30),
        },
        "90d": {
            "available": observation_days >= 60,
            "requiredObservationDays": 60,
            "observationDays": min(observation_days, 90),
        },
    }


def trend_direction(
    *,
    metric: str,
    current_mean: float,
    baseline_mean: float,
    confidence: str,
) -> str:
    if confidence in (ConfidenceLevel.LOW, ConfidenceLevel.UNKNOWN):
        return TrendDirection.INSUFFICIENT_DATA
    difference = current_mean - baseline_mean
    threshold = MINIMUM_MEANINGFUL_CHANGE.get(metric, 0.0)
    # PRD §7.3.1: percentage-based defaults, configurable and provisional.
    relative_thresholds = getattr(settings, "HEALTH_RELATIVE_MMC", {
        "steps": 0.10, "weight_kg": 0.01,
        "stress_level": 0.10, "body_fat_percentage": 0.01,
    })
    if metric in relative_thresholds:
        baseline_threshold = abs(baseline_mean) * relative_thresholds[metric]
        threshold = baseline_threshold if metric != "body_fat_percentage" else 1.0
    if abs(difference) < threshold:
        return TrendDirection.STABLE
    # Weight/body-fat need an approved individual goal; direction must not be
    # interpreted as health improvement in its absence.
    if metric in {"weight_kg", "body_fat_percentage"}:
        return TrendDirection.UNKNOWN
    improving = difference > 0
    if metric in LOWER_IS_BETTER_METRICS:
        improving = difference < 0
    return TrendDirection.IMPROVING if improving else TrendDirection.DECLINING


def trend_payload(
    *,
    summaries: list[HealthDailySummary],
    metric: str,
    confidence: str,
    preferred_units: str,
) -> dict:
    # Compare calendar windows, not "last N readings"; otherwise missing days
    # shift old measurements into a newer week and fabricate a trajectory.
    dated_summaries = [
        (summary.local_date, summary_numeric_value(summary))
        for summary in summaries
        if summary_numeric_value(summary) is not None
    ]
    if not dated_summaries:
        return {
            "direction": TrendDirection.INSUFFICIENT_DATA,
            "window": "7d vs prior 28d", "confidence": confidence,
            "baseline": {"available": False}, "change": {"available": False},
            "interpretationSuppressed": True,
        }
    latest_day = max(local_date for local_date, _ in dated_summaries)
    current_start = latest_day - timedelta(days=6)
    baseline_start = current_start - timedelta(days=28)
    current_values = [value for day, value in dated_summaries if day >= current_start]
    baseline_values = [
        value for day, value in dated_summaries
        if baseline_start <= day < current_start
    ]
    minimum_observations = getattr(settings, "HEALTH_TREND_MINIMUM_OBSERVATIONS", 7)
    if len(current_values) < minimum_observations or len(baseline_values) < getattr(settings, "HEALTH_MIN_BASELINE_DAYS", 7):
        return {
            "direction": TrendDirection.INSUFFICIENT_DATA,
            "window": "7d vs prior 28d", "confidence": confidence,
            "baseline": {"available": False}, "change": {"available": False},
            "interpretationSuppressed": True,
        }
    current_mean = mean(current_values)
    baseline_mean = mean(baseline_values)
    direction = trend_direction(
        metric=metric,
        current_mean=current_mean,
        baseline_mean=baseline_mean,
        confidence=confidence,
    )
    display_baseline, display_unit = display_value(
        value=baseline_mean,
        metric=metric,
        preferred_units=preferred_units,
    )
    display_change, _ = display_value(
        value=current_mean - baseline_mean,
        metric=metric,
        preferred_units=preferred_units,
    )
    return {
        "direction": direction,
        "window": "7d vs prior 28d",
        "confidence": confidence,
        "baseline": {
            "available": True,
            "value": display_baseline,
            "unit": display_unit,
            "observationDays": len(baseline_values),
        },
        "change": {
            "available": True,
            "value": display_change,
            "unit": display_unit,
        },
        "interpretationSuppressed": direction in {TrendDirection.INSUFFICIENT_DATA, TrendDirection.UNKNOWN},
    }


def freshness_payload(summaries: list[HealthDailySummary], *, today: date | None = None) -> dict:
    if not summaries:
        return {"label": "No measurements", "lastMeasurementAt": None}
    last_summary = summaries[-1]
    last_time = last_summary.last_observed_at
    age_days = ((today or timezone.now().date()) - last_summary.local_date).days
    if age_days <= 0:
        label = "Today"
    elif age_days == 1:
        label = "Yesterday"
    elif age_days <= 7:
        label = "Last 7 days"
    else:
        label = "Stale"
    return {"label": label, "lastMeasurementAt": last_time}


def connection_priority_state(connections: list[WearableConnection]) -> str | None:
    if not connections:
        return None
    if all(
        connection.status == ConnectionStatus.DISCONNECTED
        for connection in connections
    ):
        return HealthCardState.DISCONNECTED
    if any(
        connection.status == ConnectionStatus.AUTHORIZATION_EXPIRED
        for connection in connections
    ):
        return HealthCardState.AUTHORIZATION_EXPIRED
    if any(
        connection.status == ConnectionStatus.PROVIDER_ERROR
        for connection in connections
    ):
        return HealthCardState.PROVIDER_ERROR
    if any(
        connection.import_status == HistoricalImportStatus.FAILED
        for connection in connections
    ):
        return HealthCardState.HISTORICAL_IMPORT_FAILED
    if any(
        connection.import_status == HistoricalImportStatus.PARTIAL
        for connection in connections
    ):
        return HealthCardState.HISTORICAL_IMPORT_PARTIAL
    if any(
        connection.permission_status == PermissionStatus.DENIED
        for connection in connections
    ):
        return HealthCardState.PERMISSION_REQUIRED
    if any(
        connection.import_status == HistoricalImportStatus.RUNNING
        for connection in connections
    ):
        return HealthCardState.HISTORICAL_IMPORT_RUNNING
    active_connections = [
        connection
        for connection in connections
        if connection.status in {
            ConnectionStatus.ACTIVE,
            ConnectionStatus.IDLE,
            ConnectionStatus.PARTIAL,
        }
    ]
    delay_hours = getattr(settings, "ROOK_SYNC_DELAY_HOURS", 48)
    delayed_before = timezone.now() - timedelta(hours=delay_hours)
    if active_connections and all(
        (connection.last_successful_sync < delayed_before)
        if connection.last_successful_sync is not None
        else (connection.connected_at is not None and connection.connected_at < delayed_before)
        for connection in active_connections
    ):
        return HealthCardState.SYNC_DELAYED
    return None


def capabilities_support_domain(
    connections: list[WearableConnection],
    domain: str,
) -> bool | None:
    capability_lists = [
        {str(capability).lower() for capability in connection.capabilities}
        for connection in connections
        if connection.capabilities
    ]
    if not capability_lists:
        return None
    return any(domain in capabilities for capabilities in capability_lists)


def card_state(
    *,
    domain: str,
    summaries: list[HealthDailySummary],
    connections: list[WearableConnection],
    coverage: dict,
) -> str:
    if not domain_enabled(domain):
        return HealthCardState.UNSUPPORTED
    connection_state = connection_priority_state(connections)
    if connection_state in {
        HealthCardState.DISCONNECTED,
        HealthCardState.AUTHORIZATION_EXPIRED,
        HealthCardState.PROVIDER_ERROR,
        HealthCardState.PERMISSION_REQUIRED,
    }:
        return connection_state
    capability_support = capabilities_support_domain(connections, domain)
    if not summaries:
        if capability_support is False:
            return HealthCardState.UNSUPPORTED
        if connection_state is not None:
            return connection_state
        if connections:
            return HealthCardState.WAITING_FOR_DATA
        return HealthCardState.NO_DATA
    if connection_state in {
        HealthCardState.HISTORICAL_IMPORT_RUNNING,
        HealthCardState.HISTORICAL_IMPORT_PARTIAL,
        HealthCardState.HISTORICAL_IMPORT_FAILED,
        HealthCardState.SYNC_DELAYED,
    }:
        return connection_state
    gap_threshold = getattr(settings, "HEALTH_HISTORICAL_GAP_DAYS", 7)
    if coverage["missingDays"] >= gap_threshold:
        return HealthCardState.HISTORICAL_GAP
    minimum_observations = getattr(settings, "HEALTH_TREND_MINIMUM_OBSERVATIONS", 7)
    if len(summaries) >= minimum_observations:
        return HealthCardState.TREND_AVAILABLE
    return HealthCardState.CURRENT_VALUE_ONLY


def state_actions(state: str) -> list[dict]:
    actions = {
        HealthCardState.DISCONNECTED: [
            {"id": "reconnect", "label": "Reconnect"}
        ],
        HealthCardState.PERMISSION_REQUIRED: [
            {"id": "grant_permission", "label": "Grant Permission"}
        ],
        HealthCardState.PROVIDER_ERROR: [
            {"id": "retry_sync", "label": "Retry Sync"}
        ],
        HealthCardState.SYNC_DELAYED: [
            {"id": "retry_sync", "label": "Retry Sync"}
        ],
        HealthCardState.AUTHORIZATION_EXPIRED: [
            {"id": "reconnect", "label": "Reconnect"}
        ],
        HealthCardState.HISTORICAL_IMPORT_FAILED: [
            {"id": "retry_sync", "label": "Retry Import"}
        ],
        HealthCardState.UNSUPPORTED: [
            {"id": "learn_more", "label": "Learn More"}
        ],
    }
    return actions.get(state, [])


def state_messages(state: str) -> list[str]:
    messages = {
        HealthCardState.HISTORICAL_IMPORT_RUNNING: [
            "Historical health data is importing. Current values appear as they arrive."
        ],
        HealthCardState.HISTORICAL_IMPORT_PARTIAL: [
            "Some historical data could not be imported. Available measurements are shown."
        ],
        HealthCardState.HISTORICAL_IMPORT_FAILED: [
            "Historical import failed. Live data and retained history remain available."
        ],
        HealthCardState.WAITING_FOR_DATA: [
            "The provider is connected, but no measurement has arrived for this domain yet."
        ],
        HealthCardState.PERMISSION_REQUIRED: [
            "Additional device permission is required for this domain."
        ],
        HealthCardState.UNSUPPORTED: [
            "The connected source does not provide this domain."
        ],
        HealthCardState.DISCONNECTED: [
            "The source is disconnected. Historical measurements are retained."
        ],
        HealthCardState.PROVIDER_ERROR: [
            "The provider is temporarily unavailable. Last received data is retained."
        ],
        HealthCardState.AUTHORIZATION_EXPIRED: [
            "Provider authorization expired. Reconnect to resume synchronization."
        ],
        HealthCardState.SYNC_DELAYED: [
            "New measurements are delayed. Previously received data remains available."
        ],
        HealthCardState.HISTORICAL_GAP: [
            "A gap exists in the historical record. Missing days were not estimated."
        ],
    }
    return messages.get(state, [])


def current_value_payload(
    *,
    summaries: list[HealthDailySummary],
    metric: str | None,
    preferred_units: str,
    domain: str,
    today: date | None = None,
) -> dict:
    if not summaries or metric is None:
        return {"available": False}
    if domain == HealthDomain.WORKOUTS:
        cutoff = (today or timezone.now().date()) - timedelta(days=6)
        workout_values = [
            value
            for summary in summaries
            if summary.local_date >= cutoff
            if (value := summary_numeric_value(summary)) is not None
        ]
        if not workout_values:
            return {"available": False}
        raw_value = sum(workout_values)
        recorded_at = summaries[-1].last_observed_at
    else:
        latest_summary = summaries[-1]
        raw_value = summary_numeric_value(latest_summary)
        recorded_at = latest_summary.last_observed_at
    if raw_value is None:
        return {"available": False}
    value, unit = display_value(
        value=raw_value,
        metric=metric,
        preferred_units=preferred_units,
    )
    return {
        "available": True,
        "metric": metric,
        "value": value,
        "unit": unit or DOMAIN_DEFAULT_UNITS[domain],
        "recordedAt": recorded_at,
    }


def build_domain_card(
    *,
    customer_profile,
    domain: str,
    connections: list[WearableConnection],
    preferred_units: str,
) -> dict:
    metric, summaries = headline_series(
        customer_profile=customer_profile,
        domain=domain,
    )
    coverage = coverage_details(summaries)
    confidence = confidence_level(coverage, summaries)
    # A device-methodology change can mimic a physiological trend. Show values,
    # but suppress interpretation until the new source stabilizes (PRD §8.3).
    if metric and HealthObservation.objects.filter(
        customer_profile=customer_profile, domain=domain, metric=metric,
        is_current=True, observed_at__gte=timezone.now() - timedelta(days=7),
        provenance__has_key="sourceChange",
    ).exists():
        confidence = ConfidenceLevel.LOW
    today = member_today(customer_profile)
    state = card_state(
        domain=domain,
        summaries=summaries,
        connections=connections,
        coverage=coverage,
    )
    graph = (
        graph_values(
            summaries=summaries,
            metric=metric,
            preferred_units=preferred_units,
        )
        if metric
        else []
    )
    trend = (
        trend_payload(
            summaries=summaries,
            metric=metric,
            confidence=confidence,
            preferred_units=preferred_units,
        )
        if metric
        else {
            "direction": TrendDirection.UNKNOWN,
            "window": "7d vs prior 28d",
            "confidence": ConfidenceLevel.UNKNOWN,
            "baseline": {"available": False},
            "change": {"available": False},
            "interpretationSuppressed": True,
        }
    )
    data_source_lists = HealthObservation.objects.filter(
        customer_profile=customer_profile,
        domain=domain,
        metric=metric or "",
        is_current=True,
        observed_at__gte=timezone.now() - timedelta(days=90),
    ).values_list("data_sources", flat=True)
    sources = sorted(
        {
            data_source
            for data_source_list in data_source_lists.iterator()
            for data_source in data_source_list
        }
    )
    return {
        "id": domain,
        "title": DOMAIN_TITLES[domain],
        "state": state,
        "currentValue": current_value_payload(
            summaries=summaries,
            metric=metric,
            preferred_units=preferred_units,
            domain=domain,
            today=today,
        ),
        "trend": trend,
        "graph": {
            "points": graph,
            "aggregationWindow": "daily",
            "unit": graph[-1]["unit"] if graph else DOMAIN_DEFAULT_UNITS[domain],
            "completeness": coverage,
            "confidence": confidence,
            "windowAvailability": history_window_availability(summaries),
        },
        "actions": state_actions(state),
        "messages": state_messages(state),
        "metadata": {
            "algorithmVersion": ALGORITHM_VERSION,
            "freshness": freshness_payload(summaries, today=today),
            "sources": sources,
            "generatedAt": timezone.now(),
        },
    }


def refresh_profile_snapshots(customer_profile, domains=None) -> list[dict]:
    connections = list(
        WearableConnection.objects.filter(customer_profile=customer_profile).order_by(
            "data_source"
        )
    )
    identity = getattr(customer_profile, "rook_identity", None)
    preferred_units = (
        identity.preferred_units if identity else PreferredUnits.METRIC
    )
    cards = []
    generated_at = timezone.now()
    included = set(domains or HEALTH_DOMAIN_ORDER)
    for domain in HEALTH_DOMAIN_ORDER:
        if domain not in included:
            continue
        card = build_domain_card(
            customer_profile=customer_profile,
            domain=domain,
            connections=connections,
            preferred_units=preferred_units,
        )
        cards.append(card)
        HealthDomainSnapshot.objects.update_or_create(
            customer_profile=customer_profile,
            domain=domain,
            defaults={
                "state": card["state"],
                "card": card,
                "algorithm_version": ALGORITHM_VERSION,
                "confidence": card["graph"]["confidence"],
                "generated_at": generated_at,
            },
        )
    invalidate_health_dashboard(customer_profile)
    return cards


def dashboard_payload(customer_profile) -> dict:
    key = health_cache_key(customer_profile)
    cached = health_cache().get(key)
    if cached is not None:
        return cached
    cards = refresh_profile_snapshots(customer_profile)
    result = {
        "cards": cards,
        "domainOrder": list(HEALTH_DOMAIN_ORDER),
        "algorithmVersion": ALGORITHM_VERSION,
        "generatedAt": timezone.now(),
    }
    health_cache().set(key, result, timeout=getattr(settings, "HEALTH_DASHBOARD_CACHE_SECONDS", 60))
    return result


def domain_metrics_payload(
    *,
    customer_profile,
    domain: str,
    days: int,
) -> list[dict]:
    cutoff = member_today(customer_profile) - timedelta(days=days - 1)
    summaries = HealthDailySummary.objects.filter(
        customer_profile=customer_profile,
        domain=domain,
        local_date__gte=cutoff,
    ).order_by("metric", "local_date", "last_observed_at")
    grouped: dict[str, list[HealthDailySummary]] = defaultdict(list)
    for summary in summaries.iterator():
        grouped[summary.metric].append(summary)
    identity = getattr(customer_profile, "rook_identity", None)
    preferred_units = identity.preferred_units if identity else PreferredUnits.METRIC
    return [
        {
            "metric": metric,
            "points": graph_values(
                summaries=one_summary_per_day(metric_summaries),
                metric=metric,
                preferred_units=preferred_units,
            ),
        }
        for metric, metric_summaries in sorted(grouped.items())
    ]


def domain_payload(*, customer_profile, domain: str, days: int) -> dict:
    connections = list(
        WearableConnection.objects.filter(customer_profile=customer_profile).order_by(
            "data_source"
        )
    )
    identity = getattr(customer_profile, "rook_identity", None)
    preferred_units = identity.preferred_units if identity else PreferredUnits.METRIC
    return {
        "domain": domain,
        "card": build_domain_card(
            customer_profile=customer_profile,
            domain=domain,
            connections=connections,
            preferred_units=preferred_units,
        ),
        "metrics": domain_metrics_payload(
            customer_profile=customer_profile,
            domain=domain,
            days=days,
        ),
        "historyWindowDays": days,
    }


def observation_value(observation: HealthObservation) -> dict:
    if observation.numeric_value is not None:
        return {"type": "number", "value": observation.numeric_value}
    if observation.text_value:
        return {"type": "text", "value": observation.text_value}
    if observation.boolean_value is not None:
        return {"type": "boolean", "value": observation.boolean_value}
    return {"type": "unavailable"}


# Composite wearable + existing Biopeak clinical timeline is implemented in an
# isolated read-only adapter to avoid changing legacy service models.
from wearables.services.timeline import timeline_payload
