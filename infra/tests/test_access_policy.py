from __future__ import annotations

import json

from aws_cdk import App, Environment
from aws_cdk.assertions import Template

from workshield_infra.config import DeploymentConfig
from workshield_infra.stacks.access import AccessStack
from workshield_infra.stacks.foundation import FoundationStack
from workshield_infra.stacks.service import ServiceStack


def _config() -> DeploymentConfig:
    return DeploymentConfig(
        app_name="workshield-prod",
        environment="prod",
        aws_account_id="111122223333",
        aws_region="ap-northeast-2",
        availability_zone="ap-northeast-2a",
        origin_domain="workshield.duckdns.org",
        acme_email="infra@example.com",
        cloudfront_origin_prefix_list_id="pl-1234",
        instance_type="t3.small",
        github_organization="example",
        github_owner_id="123456",
        github_repository_id="654321",
        github_repository="repository",
        github_environment="production",
        ghcr_owner="example",
        nginx_image=f"nginx@sha256:{'0' * 64}",
        runpod_llm_image="vllm/vllm-openai:latest",
        runpod_llm_template_id="llm-template",
        runpod_llm_gpu="NVIDIA A40",
        runpod_llm_model="model",
        runpod_embed_template_id="embed-template",
        runpod_embed_gpu="NVIDIA RTX 2000 Ada",
        runpod_embed_image="ghcr.io/example/mcp/embed-rerank:latest",
    )


def test_github_deploy_policy_contains_no_infrastructure_or_secret_read() -> None:
    app = App()
    config = _config()
    environment = Environment(
        account=config.aws_account_id,
        region=config.aws_region,
    )
    access = AccessStack(app, "Access", config=config, env=environment)
    foundation = FoundationStack(
        app,
        "Foundation",
        config=config,
        env=environment,
    )
    service = ServiceStack(
        app,
        "Service",
        config=config,
        access=access,
        foundation=foundation,
        env=environment,
    )
    body = json.dumps(Template.from_stack(service).to_json()).lower()

    for forbidden in (
        "cloudformation:",
        '"ec2:*"',
        '"iam:*"',
        "secretsmanager:getsecretvalue",
    ):
        assert forbidden not in body
    for allowed in (
        "ssm:sendcommand",
        "s3:putobject",
        "cloudfront:createinvalidation",
    ):
        assert allowed in body
