import math
import re
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any

from wearables.utils.constants import HealthDomain

PRIVATE_FIELDS = {
    "metadata",
    "metadata_info",
    "user_id",
    "client_uuid",
    "document_id",
    "event_id",
    "document_version",
    "version",
    "id",
    "_id",
    "data_structure",
    "type",
    "source",
    "data_source",
    "source_of_data",
    "source_of_data_string",
    "sources_of_data_array",
    "sources_of_data",
    "device_source_data_array",
    "measurement_types",
    "email",
    "phone",
    "phone_number",
    "access_token",
    "refresh_token",
    "session_token",
}

TIMESTAMP_FIELDS = {
    "datetime",
    "date",
    "datetime_string",
    "date_time",
    "start_datetime_string",
    "start_date_time",
    "summary_date_string",
    "last_updated_datetime_string",
    "sleep_date_string",
    "sleep_start_datetime_string",
    "activity_start_datetime_string",
    "activity_end_datetime_string",
    "period_start_date_string",
}

SELECTED_TEXT_FIELDS = {
    "activity_type_name_string",
    "workout_type_string",
}


@dataclass(frozen=True)
class ExtractedMetric:
    field_path: str
    metric: str
    domain: str
    value: float | str | bool
    unit: str


def is_private_field(field_name: str) -> bool:
    normalized = str(field_name).lower()
    return normalized in PRIVATE_FIELDS or normalized.endswith(
        ("_id", "_uuid", "_token", "_secret", "_timestamp")
    )


def terminal_field(field_path: str) -> str:
    terminal = field_path.rsplit(".", maxsplit=1)[-1]
    return re.sub(r"\[\d+\]", "", terminal)


# The Phase 1 presentation catalogue is deliberately separate from raw storage.
# ROOK proprietary/unrecognized numeric fields may be retained as canonical
# observations for provenance, but never appear on member dashboards by default.
V1_DISPLAY_METRICS = {
    HealthDomain.SLEEP: frozenset({
        "sleep_duration_seconds", "sleep_efficiency_percentage",
        "deep_sleep_duration_seconds", "rem_sleep_duration_seconds",
        "light_sleep_duration_seconds", "sleep_start_time", "sleep_end_time",
        "sleep_score",
    }),
    HealthDomain.ACTIVITY: frozenset({
        "steps", "activity_calories_kcal", "activity_distance_meters",
        "floors_climbed", "active_minutes",
    }),
    HealthDomain.HEART: frozenset({
        "resting_heart_rate", "average_heart_rate", "maximum_heart_rate", "hrv_rmssd",
    }),
    HealthDomain.RECOVERY: frozenset({"stress_level", "recovery_score", "readiness_score"}),
    HealthDomain.BODY: frozenset({
        "weight_kg", "bmi", "body_fat_percentage", "muscle_mass_kg",
        "body_water_percentage",
    }),
    HealthDomain.WORKOUTS: frozenset({
        "workout_count", "workout_duration_seconds", "workout_type",
        "workout_calories_kcal", "workout_distance_meters",
    }),
}

PROPRIETARY_V1_METRICS = frozenset({"sleep_score", "recovery_score", "readiness_score"})
SLEEP_BOUNDARY_FIELDS = {
    "sleep_start_datetime_string": "sleep_start_time",
    "sleep_end_datetime_string": "sleep_end_time",
    "sleep_start_date_time": "sleep_start_time",
    "sleep_end_date_time": "sleep_end_time",
}


def metric_name(field_path: str) -> str:
    field_name = terminal_field(field_path).lower()
    if field_name in SLEEP_BOUNDARY_FIELDS:
        return SLEEP_BOUNDARY_FIELDS[field_name]
    # Check stage-specific duration before generic sleep duration.
    for stage in ("deep", "rem", "light"):
        if stage in field_name and "sleep" in field_name and ("duration" in field_name or "time" in field_name):
            return f"{stage}_sleep_duration_seconds"
    rules = [
        (("sleep_efficiency", "efficiency_percentage", "efficiency_percent"), "sleep_efficiency_percentage"),
        (("sleep_score",), "sleep_score"),
        (("sleep_duration", "total_sleep_duration", "time_asleep"), "sleep_duration_seconds"),
        (("accumulated_steps", "steps_int", "total_steps", "steps"), "steps"),
        (("floors_climbed", "floors_ascended", "floors"), "floors_climbed"),
        (("active_minutes", "active_duration_minutes", "active_time_minutes"), "active_minutes"),
        (("activity_calories", "active_calories", "calories_expenditure", "calories_burned", "total_calories"), "activity_calories_kcal"),
        (("activity_distance", "total_distance", "distance_meters"), "activity_distance_meters"),
        (("hr_resting", "resting_heart_rate"), "resting_heart_rate"),
        (("hr_avg", "average_heart_rate", "avg_heart_rate"), "average_heart_rate"),
        (("hr_maximum", "maximum_heart_rate", "max_heart_rate"), "maximum_heart_rate"),
        (("hrv_avg_rmssd", "hrv_rmssd", "rmssd"), "hrv_rmssd"),
        (("recovery_score",), "recovery_score"),
        (("readiness_score",), "readiness_score"),
        (("stress_avg", "average_stress", "stress_level"), "stress_level"),
        (("weight_kg", "body_weight_kg"), "weight_kg"),
        (("bmi",), "bmi"),
        (("body_fat",), "body_fat_percentage"),
        (("muscle_mass", "muscle_composition"), "muscle_mass_kg"),
        (("water_composition", "body_water"), "body_water_percentage"),
        (("activity_duration", "workout_duration", "exercise_duration"), "workout_duration_seconds"),
        (("workout_calories",), "workout_calories_kcal"),
        (("workout_distance",), "workout_distance_meters"),
        (("activity_type_name", "workout_type"), "workout_type"),
    ]
    for patterns, canonical_name in rules:
        if any(pattern in field_name for pattern in patterns):
            return canonical_name
    normalized = re.sub(r"_(float|int|bool|string|object|array)$", "", field_name)
    return normalized[:128]


def health_domain_for(field_path: str, data_structure: str) -> str | None:
    """Use the metric leaf before the enclosing ROOK pillar to prevent
    sleep_health_summary.heart_rate.hr_resting being counted as Sleep.
    """
    metric = metric_name(field_path)
    leaf = terminal_field(field_path).lower()
    context = f"{data_structure}.{field_path}".lower()
    if metric in V1_DISPLAY_METRICS[HealthDomain.HEART] or any(
        token in leaf for token in ("heart_rate", "hrv", "hr_resting", "hr_avg", "hr_maximum", "rmssd", "sdnn")
    ):
        return HealthDomain.HEART
    if any(token in context for token in ("workout", "activity_event", "exercise_event")):
        return HealthDomain.WORKOUTS
    if metric in V1_DISPLAY_METRICS[HealthDomain.RECOVERY]:
        return HealthDomain.RECOVERY
    if metric in V1_DISPLAY_METRICS[HealthDomain.BODY] or any(
        token in leaf for token in ("weight", "body_fat", "muscle", "water_composition", "lean_mass")
    ):
        return HealthDomain.BODY
    if metric in V1_DISPLAY_METRICS[HealthDomain.SLEEP] or "sleep" in context or "time_in_bed" in context:
        return HealthDomain.SLEEP
    if metric in V1_DISPLAY_METRICS[HealthDomain.ACTIVITY] or any(
        token in context for token in ("physical", "steps", "floor", "calorie", "distance", "active_minutes")
    ):
        return HealthDomain.ACTIVITY
    return None


def is_v1_display_metric(domain: str, metric: str) -> bool:
    return metric in V1_DISPLAY_METRICS.get(domain, ())


def metric_unit(field_path: str, metric: str) -> str:
    field_name = terminal_field(field_path).lower()
    if metric in {"sleep_duration_seconds", "deep_sleep_duration_seconds", "rem_sleep_duration_seconds", "light_sleep_duration_seconds"}:
        return "seconds"
    if metric in {"sleep_efficiency_percentage"}:
        return "%"
    if metric == "sleep_score":
        return "score"
    if metric == "floors_climbed":
        return "floors"
    if metric == "active_minutes":
        return "minutes"
    if metric in {"activity_calories_kcal", "workout_calories_kcal"}:
        return "kcal"
    if metric == "steps":
        return "steps"
    if metric in {"resting_heart_rate", "average_heart_rate", "maximum_heart_rate"}:
        return "bpm"
    if metric == "hrv_rmssd":
        return "ms"
    if metric in {"recovery_score", "readiness_score", "stress_level"}:
        return "score"
    if metric in {"weight_kg", "muscle_mass_kg"}:
        return "kg"
    if metric in {"body_fat_percentage", "body_water_percentage"}:
        return "%"
    if metric == "bmi":
        return "kg/m²"
    if metric == "workout_duration_seconds":
        return "seconds"
    if metric == "workout_calories_kcal":
        return "kcal"
    if metric == "workout_distance_meters":
        return "meters"
    if "percentage" in field_name or "_percent" in field_name:
        return "%"
    if "_seconds" in field_name:
        return "seconds"
    if "_minutes" in field_name:
        return "minutes"
    if "_hours" in field_name:
        return "hours"
    if "_kcal" in field_name:
        return "kcal"
    if "_meters" in field_name:
        return "meters"
    return ""


def canonical_numeric_value(field_path: str, metric: str, value: float) -> float:
    field_name = terminal_field(field_path).lower()
    if metric in {
        "sleep_duration_seconds", "deep_sleep_duration_seconds", "rem_sleep_duration_seconds",
        "light_sleep_duration_seconds", "workout_duration_seconds",
    }:
        if "_minutes" in field_name:
            return value * 60.0
        if "_hours" in field_name:
            return value * 3600.0
    return value


def extract_metric_values(
    node: Any,
    *,
    data_structure: str,
    path: str = "",
) -> Generator[ExtractedMetric]:
    if isinstance(node, dict):
        for key, value in node.items():
            child_path = f"{path}.{key}" if path else key
            if key in SLEEP_BOUNDARY_FIELDS and isinstance(value, str):
                # Keep UTC/local-session boundary as an explicit *text* metric;
                # never treat a timestamp as a numeric measure or discard it.
                yield ExtractedMetric(child_path, SLEEP_BOUNDARY_FIELDS[key], HealthDomain.SLEEP, value[:80], "ISO-8601")
                continue
            if is_private_field(key) or key in TIMESTAMP_FIELDS:
                continue
            yield from extract_metric_values(
                value,
                data_structure=data_structure,
                path=child_path,
            )
        return
    if isinstance(node, list):
        for index, value in enumerate(node):
            yield from extract_metric_values(
                value,
                data_structure=data_structure,
                path=f"{path}[{index}]",
            )
        return
    domain = health_domain_for(path, data_structure)
    if domain is None:
        return
    canonical_metric = metric_name(path)
    if domain == HealthDomain.WORKOUTS:
        if canonical_metric == "activity_calories_kcal":
            canonical_metric = "workout_calories_kcal"
        elif canonical_metric == "activity_distance_meters":
            canonical_metric = "workout_distance_meters"
    if isinstance(node, bool):
        yield ExtractedMetric(path, canonical_metric, domain, node, "")
        return
    if isinstance(node, (int, float)) and math.isfinite(node):
        numeric_value = canonical_numeric_value(path, canonical_metric, float(node))
        yield ExtractedMetric(
            path,
            canonical_metric,
            domain,
            numeric_value,
            metric_unit(path, canonical_metric),
        )
        return
    if isinstance(node, str) and terminal_field(path) in SELECTED_TEXT_FIELDS:
        yield ExtractedMetric(path, canonical_metric, domain, node[:512], "")


def structure_represents_workout(data_structure: str) -> bool:
    normalized = data_structure.lower()
    return any(
        token in normalized
        for token in ("activity_event", "workout", "exercise_event")
    )

