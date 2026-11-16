from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

INTEGRATIONS_YAML_PATH = Path(__file__).resolve().parent / "integrations.yaml"


def load_integrations_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or INTEGRATIONS_YAML_PATH
    with config_path.open(encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError("integrations.yaml must be a mapping")
    if payload.get("version") != 1:
        raise ValueError("integrations.yaml version must be 1")
    return payload


def merge_section(defaults: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(defaults or {})
    if not override:
        return merged
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            nested = dict(merged[key])
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return merged


def enabled_integrations(config: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    payload = config or load_integrations_config()
    defaults = payload.get("defaults") or {}
    integrations = payload.get("integrations") or {}
    enabled = {}
    for name, entry in integrations.items():
        if not entry or not entry.get("enabled", True):
            continue
        enabled[name] = {
            "name": name,
            "handler": entry.get("handler"),
            "command": entry.get("command"),
            "batch_size": entry.get("batch_size", 10),
            "queue_url_ssm_suffix": entry.get("queue_url_ssm_suffix"),
            "queue": merge_section(defaults.get("queue") or {}, entry.get("queue")),
            "dlq": merge_section(defaults.get("dlq") or {}, entry.get("dlq")),
            "worker": merge_section(defaults.get("worker") or {}, entry.get("worker")),
            "launcher": merge_section(
                defaults.get("launcher") or {}, entry.get("launcher")
            ),
            "retry": merge_section(defaults.get("retry") or {}, entry.get("retry")),
        }
    return enabled


def enabled_scheduled_jobs(config: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    payload = config or load_integrations_config()
    defaults = payload.get("defaults") or {}
    jobs = payload.get("scheduled_jobs") or {}
    enabled = {}
    for name, entry in jobs.items():
        if not entry or not entry.get("enabled", True):
            continue
        enabled[name] = {
            "name": name,
            "schedule": entry["schedule"],
            "timezone": entry.get("timezone") or "UTC",
            "handler": entry.get("handler"),
            "command": entry.get("command"),
            "worker": merge_section(defaults.get("worker") or {}, entry.get("worker")),
        }
    return enabled
