#!/usr/bin/env python3
from __future__ import annotations

import aws_cdk as cdk

from infra.stacks.background_jobs_stack import BackgroundJobsStack


def _as_id_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def main() -> None:
    app = cdk.App()
    env_prefix = app.node.try_get_context("envPrefix") or "dev"
    cluster_arn = app.node.try_get_context("clusterArn")
    worker_task_definition_arn = app.node.try_get_context("workerTaskDefinitionArn")
    subnet_ids = _as_id_list(app.node.try_get_context("subnetIds"))
    security_group_ids = _as_id_list(app.node.try_get_context("securityGroupIds"))
    container_name = app.node.try_get_context("containerName") or "backend"
    assign_public_ip = app.node.try_get_context("assignPublicIp") or "DISABLED"

    if not cluster_arn or not worker_task_definition_arn:
        raise SystemExit(
            "CDK context required: clusterArn, workerTaskDefinitionArn, "
            "subnetIds, securityGroupIds"
        )

    BackgroundJobsStack(
        app,
        f"BiopeakBackgroundJobs-{env_prefix}",
        env_prefix=env_prefix,
        cluster_arn=cluster_arn,
        worker_task_definition_arn=worker_task_definition_arn,
        subnet_ids=subnet_ids,
        security_group_ids=security_group_ids,
        container_name=container_name,
        assign_public_ip=assign_public_ip,
        env=cdk.Environment(
            account=app.node.try_get_context("account"),
            region=app.node.try_get_context("region"),
        ),
    )
    app.synth()


if __name__ == "__main__":
    main()
