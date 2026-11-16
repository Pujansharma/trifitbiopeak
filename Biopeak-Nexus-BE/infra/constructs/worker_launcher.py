from __future__ import annotations

from pathlib import Path
from typing import Any

from aws_cdk import Duration
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_lambda_event_sources as lambda_event_sources
from aws_cdk import aws_sqs as sqs
from constructs import Construct

LAMBDA_CODE_PATH = Path(__file__).resolve().parent.parent / "lambdas" / "sqs_ecs_launcher"


def task_definition_family(task_definition: str) -> str:
    """Return ECS task-definition family from a family, family:rev, or ARN."""
    value = task_definition.strip()
    if value.startswith("arn:") and ":task-definition/" in value:
        after = value.split(":task-definition/", 1)[1]
        return after.split(":", 1)[0]
    if ":" in value:
        return value.split(":", 1)[0]
    return value


def task_definition_run_task_resources(task_definition: str) -> list[str]:
    """
    Allow ecs:RunTask on an entire family.

    Image deploys register new revisions; launcher uses family name so it
    always picks latest ACTIVE without requiring a CDK update.
    """
    value = task_definition.strip()
    family = task_definition_family(value)
    if value.startswith("arn:") and ":task-definition/" in value:
        prefix = value.split(":task-definition/", 1)[0]
        return [f"{prefix}:task-definition/{family}:*"]
    return [f"arn:aws:ecs:*:*:task-definition/{family}:*"]


class SqsEcsWorkerLauncher(Construct):
    """
    SQS event-source Lambda that calls ecs.RunTask for one batch message.

    Successful Lambda invocation lets the event source delete the SQS message.
    Application durability is WhatsAppOutbox QUEUED/SENDING + cron re-dispatch.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        integration_name: str,
        queue: sqs.IQueue,
        cluster_arn: str,
        task_definition_arn: str,
        subnet_ids: list[str],
        security_group_ids: list[str],
        container_name: str,
        worker_command: str,
        launcher_config: dict[str, Any],
        env_prefix: str,
        assign_public_ip: str = "DISABLED",
    ) -> None:
        super().__init__(scope, construct_id)

        memory_mb = int(launcher_config.get("memory_mb") or 256)
        timeout_seconds = int(launcher_config.get("timeout_seconds") or 60)
        reserved_concurrency = launcher_config.get("reserved_concurrency")
        public_ip = assign_public_ip if assign_public_ip in {"ENABLED", "DISABLED"} else "DISABLED"

        self.function = lambda_.Function(
            self,
            "Function",
            function_name=f"{env_prefix}-{integration_name}-sqs-ecs-launcher",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.handler",
            code=lambda_.Code.from_asset(str(LAMBDA_CODE_PATH)),
            memory_size=memory_mb,
            timeout=Duration.seconds(timeout_seconds),
            reserved_concurrent_executions=(
                int(reserved_concurrency) if reserved_concurrency is not None else None
            ),
            environment={
                "CLUSTER_ARN": cluster_arn,
                # Family only → ecs.RunTask uses latest ACTIVE revision.
                "TASK_DEFINITION_ARN": task_definition_family(task_definition_arn),
                "SUBNET_IDS": ",".join(subnet_ids),
                "SECURITY_GROUP_IDS": ",".join(security_group_ids),
                "CONTAINER_NAME": container_name,
                "WORKER_COMMAND": worker_command,
                "QUEUE_URL": queue.queue_url,
                "ASSIGN_PUBLIC_IP": public_ip,
            },
        )

        self.function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ecs:RunTask"],
                resources=task_definition_run_task_resources(task_definition_arn),
            )
        )
        self.function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["iam:PassRole"],
                resources=["*"],
                conditions={
                    "StringLike": {
                        "iam:PassedToService": "ecs-tasks.amazonaws.com",
                    }
                },
            )
        )
        queue.grant_consume_messages(self.function)

        self.function.add_event_source(
            lambda_event_sources.SqsEventSource(
                queue,
                batch_size=1,
                report_batch_item_failures=True,
            )
        )
