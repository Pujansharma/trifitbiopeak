"""Dependency-free smoke tests of pure wearable logic (NOT Django integration tests).

Run: python scripts/check_phase1_behavior_offline.py
"""
import ast
import importlib
import sys
import types
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

# The actual wearable constants extend Django's TextChoices. For an offline
# smoke test only, provide their string values so pure metric tests can run.
constants = types.ModuleType("wearables.utils.constants")
constants.HealthDomain = SimpleNamespace(
    SLEEP="sleep", ACTIVITY="activity", HEART="heart", BODY="body",
    RECOVERY="recovery", WORKOUTS="workouts",
)
sys.modules["wearables.utils.constants"] = constants

from wearables.services.metrics import extract_metric_values  # noqa: E402


def load_analytics_pure_functions(names: set[str], env: dict) -> dict:
    source = ast.parse((PROJECT / "wearables/services/analytics.py").read_text())
    functions = [
        node for node in source.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    module = ast.Module(
        body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *functions],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(module), "analytics_pure", "exec"), env)
    return env


def main():
    suite = unittest.defaultTestLoader.loadTestsFromName("wearables.tests.test_metrics")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    assert result.wasSuccessful(), "Metric extraction tests failed"

    statuses = SimpleNamespace(
        ACTIVE="connected_active", IDLE="connected_idle", PARTIAL="connected_partial",
        DISCONNECTED="disconnected", AUTHORIZATION_EXPIRED="authorization_expired",
        PROVIDER_ERROR="provider_error",
    )
    states = SimpleNamespace(
        DISCONNECTED="disconnected", AUTHORIZATION_EXPIRED="authorization_expired",
        PROVIDER_ERROR="provider_error", HISTORICAL_IMPORT_FAILED="historical_import_failed",
        HISTORICAL_IMPORT_PARTIAL="historical_import_partial",
        PERMISSION_REQUIRED="permission_required", HISTORICAL_IMPORT_RUNNING="historical_import_running",
        SYNC_DELAYED="sync_delayed", UNSUPPORTED="unsupported", NO_DATA="no_data",
        WAITING_FOR_DATA="waiting_for_data", CURRENT_VALUE_ONLY="current_value_only",
        TREND_AVAILABLE="trend_available", HISTORICAL_GAP="historical_gap",
    )
    env = {
        "date": date,
        "timedelta": timedelta,
        "datetime": datetime,
        "UTC": UTC,
        "time": __import__("datetime").time,
        "timezone": SimpleNamespace(now=lambda: datetime.now(UTC)),
        "settings": SimpleNamespace(),
        "ConnectionStatus": statuses,
        "HealthCardState": states,
        "HealthDomain": constants.HealthDomain,
        "PermissionStatus": SimpleNamespace(DENIED="denied"),
        "HistoricalImportStatus": SimpleNamespace(FAILED="failed", PARTIAL="partial", RUNNING="running"),
        "TrendDirection": SimpleNamespace(INSUFFICIENT_DATA="insufficient_data", UNKNOWN="unknown"),
        "HEALTH_DOMAIN_ORDER": ["sleep", "activity", "heart", "recovery", "body", "workouts"],
    }
    load_analytics_pure_functions({
        "summary_numeric_value", "coverage_details", "history_window_availability",
        "connection_priority_state", "capabilities_support_domain", "card_state",
        "timeline_entry_order_key",
    }, env)
    today = datetime.now(UTC).date()
    recent = [SimpleNamespace(metric="steps", maximum=1000, local_date=today-timedelta(days=i)) for i in range(90)]
    availability = env["history_window_availability"](recent, today=today)
    assert all(availability[key]["available"] for key in ("7d", "30d", "90d"))
    stale = [SimpleNamespace(metric="steps", maximum=1000, local_date=today-timedelta(days=120+i)) for i in range(65)]
    assert all(not env["history_window_availability"](stale, today=today)[key]["available"] for key in ("7d", "30d", "90d"))
    assert env["coverage_details"](recent, today=today, days=7)["observationDays"] == 7

    good = SimpleNamespace(status=statuses.ACTIVE, permission_status="granted",
        import_status="completed", capabilities=["heart"], last_successful_sync=datetime.now(UTC))
    denied = SimpleNamespace(status=statuses.ACTIVE, permission_status="denied",
        import_status="completed", capabilities=["heart"], last_successful_sync=datetime.now(UTC))
    assert env["connection_priority_state"]([good, denied], domain="heart", has_data=True) is None
    assert env["connection_priority_state"]([denied], domain="heart", has_data=False) == states.PERMISSION_REQUIRED

    order = env["timeline_entry_order_key"]
    d = date(2026, 10, 8)
    actual = {"timestamp": datetime(2026, 10, 8, 12, tzinfo=UTC), "localDate": d, "id": "reading"}
    dated = {"timestamp": None, "localDate": d, "id": "report"}
    assert sorted([actual, dated], key=order, reverse=True)[0]["id"] == "reading"
    print("PASS: pure window availability, metric timestamps, provider-state isolation and timeline ordering")
    print("NOTE: Django/PostgreSQL migration, API, and live ROOK tests still required")


if __name__ == "__main__":
    main()
