from __future__ import annotations

from typing import Any

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_iam as iam
from constructs import Construct

from infra.config import enabled_integrations, enabled_scheduled_jobs, load_integrations_config
from infra.constructs.integration_queue import IntegrationQueue
from infra.constructs.scheduled_job import ScheduledFargateJob
from infra.constructs.worker_launcher import (
    SqsEcsWorkerLauncher,
    task_definition_run_task_resources,
)


class BackgroundJobsStack(Stack):
    """
    Provisions integration queues/DLQs and scheduled Fargate jobs from
    infra/integrations.yaml. Queues use RemovalPolicy.DESTROY so failed
    creates and stack deletes do not leave named SQS orphans. Disabling an
    integration in YAML skips provisioning it on the next deploy; remove the
    resource from the stack (or destroy) to delete an existing queue.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_prefix: str,
        cluster_arn: str,
        worker_task_definition_arn: str,
        subnet_ids: list[str],
        security_group_ids: list[str],
        container_name: str,
        assign_public_ip: str = "DISABLED",
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        config = load_integrations_config()

        scheduler_role = iam.Role(
            self,
            "SchedulerEcsRole",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
            description="EventBridge Scheduler to ECS RunTask for background jobs",
        )
        scheduler_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ecs:RunTask"],
                resources=task_definition_run_task_resources(worker_task_definition_arn),
            )
        )
        scheduler_role.add_to_policy(
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

        for integration_name, integration in enabled_integrations(config).items():
            queue_construct = IntegrationQueue(
                self,
                f"{integration_name}Queue",
                integration_name=integration_name,
                queue_config=integration["queue"],
                dlq_config=integration["dlq"],
                env_prefix=env_prefix,
            )
            SqsEcsWorkerLauncher(
                self,
                f"{integration_name}Launcher",
                integration_name=integration_name,
                queue=queue_construct.queue,
                cluster_arn=cluster_arn,
                task_definition_arn=worker_task_definition_arn,
                subnet_ids=subnet_ids,
                security_group_ids=security_group_ids,
                container_name=container_name,
                worker_command=integration.get("command") or "process_whatsapp_outbox",
                launcher_config=integration.get("launcher") or {},
                env_prefix=env_prefix,
                assign_public_ip=assign_public_ip,
            )
            CfnOutput(
                self,
                f"{integration_name}QueueUrl",
                value=queue_construct.queue.queue_url,
            )
            CfnOutput(
                self,
                f"{integration_name}QueueArn",
                value=queue_construct.queue.queue_arn,
            )
            # Queue URL SSM params are written post-deploy by
            # infra.scripts.export_outbox_queue_env (PutParameter Overwrite).
            # Do not create AWS::SSM::Parameter here — fixed names collide when
            # a prior partial update already owns the parameter in this stack.

        for job_name, job in enabled_scheduled_jobs(config).items():
            ScheduledFargateJob(
                self,
                f"{job_name}Schedule",
                job_name=job_name,
                job_config=job,
                env_prefix=env_prefix,
                cluster_arn=cluster_arn,
                task_definition_arn=worker_task_definition_arn,
                subnet_ids=subnet_ids,
                security_group_ids=security_group_ids,
                scheduler_role=scheduler_role,
                container_name=container_name,
                assign_public_ip=assign_public_ip,
            )
