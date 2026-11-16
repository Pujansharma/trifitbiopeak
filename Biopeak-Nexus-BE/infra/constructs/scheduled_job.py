from __future__ import annotations

from typing import Any

from aws_cdk import aws_iam as iam
from aws_cdk import aws_scheduler as scheduler
from constructs import Construct


class ScheduledFargateJob(Construct):
    """
    EventBridge Scheduler → ECS RunTask for a YAML scheduled_jobs entry.

    Pass existing cluster ARN, task definition ARN, subnets, and security
    groups via stack props so this construct does not recreate networking.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        job_name: str,
        job_config: dict[str, Any],
        env_prefix: str,
        cluster_arn: str,
        task_definition_arn: str,
        subnet_ids: list[str],
        security_group_ids: list[str],
        scheduler_role: iam.IRole,
        container_name: str,
        assign_public_ip: str = "DISABLED",
    ) -> None:
        super().__init__(scope, construct_id)
        command = job_config.get("command") or job_name
        schedule_expression = job_config["schedule"]
        timezone_name = job_config.get("timezone") or "UTC"
        public_ip = assign_public_ip if assign_public_ip in {"ENABLED", "DISABLED"} else "DISABLED"

        self.schedule = scheduler.CfnSchedule(
            self,
            "Schedule",
            name=f"{env_prefix}-{job_name}",
            flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(
                mode="OFF"
            ),
            schedule_expression=schedule_expression,
            schedule_expression_timezone=timezone_name,
            state="ENABLED",
            target=scheduler.CfnSchedule.TargetProperty(
                arn=cluster_arn,
                role_arn=scheduler_role.role_arn,
                ecs_parameters=scheduler.CfnSchedule.EcsParametersProperty(
                    task_definition_arn=task_definition_arn,
                    launch_type="FARGATE",
                    network_configuration=scheduler.CfnSchedule.NetworkConfigurationProperty(
                        awsvpc_configuration=scheduler.CfnSchedule.AwsVpcConfigurationProperty(
                            subnets=subnet_ids,
                            security_groups=security_group_ids,
                            assign_public_ip=public_ip,
                        )
                    ),
                    task_count=1,
                ),
                input=(
                    '{"containerOverrides":[{"name":"'
                    + container_name
                    + '","command":["python","manage.py","'
                    + command
                    + '"]}]}'
                ),
            ),
        )
