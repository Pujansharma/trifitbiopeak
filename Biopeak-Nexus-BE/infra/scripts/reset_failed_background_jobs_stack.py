#!/usr/bin/env python3
"""Clear failed BiopeakBackgroundJobs stacks and orphan named resources.

Run from CI before `cdk deploy` so retries are automatic after CREATE/ROLLBACK
failures. Safe on healthy stacks: leaves UPDATE_COMPLETE / CREATE_COMPLETE alone
for queues. Always clears expected outbox queue-URL SSM params — those are
written by `export_outbox_queue_env` (PutParameter Overwrite), not CloudFormation.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from typing import Sequence

from infra.config import enabled_integrations

FAILED_STACK_STATUSES = frozenset(
    {
        "ROLLBACK_COMPLETE",
        "CREATE_FAILED",
        "ROLLBACK_FAILED",
        "DELETE_FAILED",
        "UPDATE_ROLLBACK_COMPLETE",
        "UPDATE_FAILED",
    }
)

SQS_NAME_REUSE_WAIT_SECONDS = 70


def run_aws(args: Sequence[str], *, allow_fail: bool = False) -> str:
    completed = subprocess.run(
        ["aws", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        if allow_fail:
            return ""
        raise RuntimeError(
            f"aws {' '.join(args)} failed: {completed.stderr.strip() or completed.stdout.strip()}"
        )
    return completed.stdout.strip()


def stack_status(stack_name: str, region: str) -> str | None:
    output = run_aws(
        [
            "cloudformation",
            "describe-stacks",
            "--stack-name",
            stack_name,
            "--region",
            region,
            "--query",
            "Stacks[0].StackStatus",
            "--output",
            "text",
        ],
        allow_fail=True,
    )
    if not output or output == "None":
        return None
    return output


def delete_stack(stack_name: str, region: str) -> None:
    print(f"Deleting failed stack {stack_name}...")
    run_aws(
        [
            "cloudformation",
            "delete-stack",
            "--stack-name",
            stack_name,
            "--region",
            region,
        ]
    )
    run_aws(
        [
            "cloudformation",
            "wait",
            "stack-delete-complete",
            "--stack-name",
            stack_name,
            "--region",
            region,
        ]
    )
    print(f"Stack {stack_name} deleted.")


def expected_queue_names(env_prefix: str) -> list[str]:
    names: list[str] = []
    for integration in enabled_integrations().values():
        queue_config = integration["queue"]
        dlq_config = integration["dlq"]
        base = queue_config.get("name") or f"{integration['name']}-jobs"
        prefixed = f"{env_prefix}-{base}"
        names.append(prefixed)
        if dlq_config.get("enabled", True):
            names.append(f"{prefixed}-dlq")
    return names


def expected_ssm_parameter_names(env_prefix: str) -> list[str]:
    names: list[str] = []
    for integration in enabled_integrations().values():
        suffix = integration.get("queue_url_ssm_suffix")
        if not suffix:
            continue
        names.append(f"/biopeak/{env_prefix}/{suffix}")
    return names


def delete_queue_by_name(queue_name: str, region: str) -> bool:
    url = run_aws(
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
        ],
        allow_fail=True,
    )
    if not url or url == "None":
        return False
    print(f"Deleting orphan queue {queue_name} ({url})")
    run_aws(
        [
            "sqs",
            "delete-queue",
            "--queue-url",
            url,
            "--region",
            region,
        ]
    )
    return True


def delete_orphan_queues(env_prefix: str, region: str) -> int:
    deleted = 0
    for queue_name in expected_queue_names(env_prefix):
        if delete_queue_by_name(queue_name, region):
            deleted += 1
    return deleted


def delete_ssm_parameter(parameter_name: str, region: str) -> bool:
    exists = run_aws(
        [
            "ssm",
            "get-parameter",
            "--name",
            parameter_name,
            "--region",
            region,
            "--query",
            "Parameter.Name",
            "--output",
            "text",
        ],
        allow_fail=True,
    )
    if not exists or exists == "None":
        return False
    print(f"Deleting SSM parameter {parameter_name} (re-synced after cdk deploy)")
    run_aws(
        [
            "ssm",
            "delete-parameter",
            "--name",
            parameter_name,
            "--region",
            region,
        ]
    )
    return True


def delete_outbox_ssm_parameters(env_prefix: str, region: str) -> int:
    deleted = 0
    for parameter_name in expected_ssm_parameter_names(env_prefix):
        if delete_ssm_parameter(parameter_name, region):
            deleted += 1
    return deleted


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reset failed background-jobs CFN stack, orphan SQS queues, "
            "and outbox queue-URL SSM parameters."
        )
    )
    parser.add_argument("--env-prefix", required=True)
    parser.add_argument("--region", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stack_name = f"BiopeakBackgroundJobs-{args.env_prefix}"
    status = stack_status(stack_name, args.region)

    should_clear_queues = False
    if status is None:
        print(f"No stack {stack_name}; checking for orphan named queues.")
        should_clear_queues = True
    elif status in FAILED_STACK_STATUSES:
        print(f"Stack {stack_name} status={status}; resetting.")
        delete_stack(stack_name, args.region)
        should_clear_queues = True
    else:
        print(f"Stack {stack_name} status={status}; leaving stack and queues alone.")

    deleted_queues = 0
    if should_clear_queues:
        deleted_queues = delete_orphan_queues(args.env_prefix, args.region)

    # Always clear: SSM is CI-owned (export_outbox_queue_env PutParameter), and
    # deleting here also unblocks CFN when a prior AWS::SSM::Parameter create
    # partially attached the name to this stack.
    deleted_ssm = delete_outbox_ssm_parameters(args.env_prefix, args.region)

    if deleted_queues:
        print(
            f"Waiting {SQS_NAME_REUSE_WAIT_SECONDS}s for SQS name reuse after "
            f"deleting {deleted_queues} queue(s)..."
        )
        time.sleep(SQS_NAME_REUSE_WAIT_SECONDS)

    print(
        f"Preflight clear complete "
        f"(queues_deleted={deleted_queues}, ssm_deleted={deleted_ssm})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
