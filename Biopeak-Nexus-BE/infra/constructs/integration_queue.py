from __future__ import annotations

from typing import Any

from aws_cdk import Duration, RemovalPolicy
from aws_cdk import aws_sqs as sqs
from constructs import Construct


class IntegrationQueue(Construct):
    """SQS main queue + DLQ for one integrations.yaml entry."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        integration_name: str,
        queue_config: dict[str, Any],
        dlq_config: dict[str, Any],
        env_prefix: str,
    ) -> None:
        super().__init__(scope, construct_id)
        queue_name = queue_config.get("name") or f"{integration_name}-jobs"
        prefixed_name = f"{env_prefix}-{queue_name}"
        retention_days = int(queue_config.get("message_retention_days") or 7)
        visibility_timeout = int(queue_config.get("visibility_timeout_seconds") or 900)

        dead_letter_queue = None
        if dlq_config.get("enabled", True):
            dlq_retention = int(dlq_config.get("retention_days") or 14)
            dead_letter_queue = sqs.Queue(
                self,
                "DeadLetterQueue",
                queue_name=f"{prefixed_name}-dlq",
                retention_period=Duration.days(dlq_retention),
                # DESTROY so failed CREATE rollbacks and stack deletes do not leave
                # named queues that block the next deploy (AlreadyExists).
                removal_policy=RemovalPolicy.DESTROY,
            )

        redrive = None
        if dead_letter_queue is not None:
            redrive = sqs.DeadLetterQueue(
                max_receive_count=int(dlq_config.get("max_receive_count") or 5),
                queue=dead_letter_queue,
            )

        self.queue = sqs.Queue(
            self,
            "Queue",
            queue_name=prefixed_name,
            visibility_timeout=Duration.seconds(visibility_timeout),
            retention_period=Duration.days(retention_days),
            dead_letter_queue=redrive,
            removal_policy=RemovalPolicy.DESTROY,
        )
        self.dead_letter_queue = dead_letter_queue
