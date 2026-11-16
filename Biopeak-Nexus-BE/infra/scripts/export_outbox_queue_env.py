#!/usr/bin/env python3
"""Sync outbox queue URLs to SSM and export ECS task-def env lines.

For each enabled integrations.yaml entry with `queue_url_ssm_suffix`:

1. Resolve the queue URL via SQS (name = `{env}-{queue.name}`)
2. `PutParameter` with Overwrite to `/biopeak/{env}/{suffix}`
3. Print `PRD_<SUFFIX>=<url>` (or STG_/DEV_) for deploy-aws inject

SSM is owned by this CI step, not by CloudFormation — avoids
AWS::SSM::Parameter AlreadyExists on partial stack updates.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from typing import Any

from infra.config import enabled_integrations


def run_aws(args: list[str]) -> str:
    completed = subprocess.run(
        ["aws", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"aws {' '.join(args)} failed: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    return completed.stdout.strip()


def queue_export_targets() -> list[dict[str, Any]]:
    targets = []
    seen_suffixes: set[str] = set()
    for integration in enabled_integrations().values():
        suffix = integration.get("queue_url_ssm_suffix")
        if not suffix or suffix in seen_suffixes:
            continue
        seen_suffixes.add(suffix)
        queue_config = integration["queue"]
        queue_base = queue_config.get("name") or f"{integration['name']}-jobs"
        targets.append(
            {
                "suffix": suffix,
                "queue_base": queue_base,
            }
        )
    return targets


def resolve_queue_url(*, env_prefix: str, queue_base: str, region: str) -> str:
    queue_name = f"{env_prefix}-{queue_base}"
    return run_aws(
        [
            "sqs",
            "get-queue-url",
            "--queue-name",
            queue_name,
            "--region",
            region,
            "--query",
            "QueueUrl",
            "--output",
            "text",
        ]
    )


def put_queue_url_parameter(
    *,
    parameter_name: str,
    queue_url: str,
    region: str,
) -> None:
    run_aws(
        [
            "ssm",
            "put-parameter",
            "--name",
            parameter_name,
            "--type",
            "String",
            "--value",
            queue_url,
            "--overwrite",
            "--region",
            region,
        ]
    )


def export_lines(
    *,
    env_prefix: str,
    settings_prefix: str,
    region: str,
) -> list[str]:
    lines = []
    for target in queue_export_targets():
        suffix = target["suffix"]
        queue_url = resolve_queue_url(
            env_prefix=env_prefix,
            queue_base=target["queue_base"],
            region=region,
        )
        parameter_name = f"/biopeak/{env_prefix}/{suffix}"
        put_queue_url_parameter(
            parameter_name=parameter_name,
            queue_url=queue_url,
            region=region,
        )
        env_key = f"{settings_prefix}_{suffix}"
        lines.append(f"{env_key}={queue_url}")
        print(f"Synced {parameter_name} → will inject {env_key}", file=sys.stderr)
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-prefix", required=True, help="SSM path segment, e.g. prd")
    parser.add_argument(
        "--settings-prefix",
        required=True,
        help="Django settings env prefix, e.g. PRD",
    )
    parser.add_argument("--region", required=True)
    args = parser.parse_args(argv)

    lines = export_lines(
        env_prefix=args.env_prefix,
        settings_prefix=args.settings_prefix,
        region=args.region,
    )
    if not lines:
        print(
            "No enabled integrations with queue_url_ssm_suffix in integrations.yaml",
            file=sys.stderr,
        )
        return 1
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
