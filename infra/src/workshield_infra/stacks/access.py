"""로컬 bootstrap이 관리하는 GitHub deploy role을 CDK에 연결한다."""

from __future__ import annotations

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_iam as iam
from constructs import Construct

from workshield_infra.config import DeploymentConfig


class AccessStack(Stack):
    """검증된 GitHub role을 import하고 실제 권한은 ServiceStack에 위임한다."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: DeploymentConfig,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        role_arn = (
            f"arn:{self.partition}:iam::{self.account}:role/"
            f"{config.app_name}-github-deploy"
        )
        # OIDC provider는 account 단위 공유 자원일 수 있다. local bootstrap이
        # 신뢰 정책과 기존 broad policy를 먼저 수렴한 뒤 여기서는 import한다.
        self.github_deploy_role = iam.Role.from_role_arn(
            self,
            "GitHubDeployRole",
            role_arn,
            mutable=True,
        )
        CfnOutput(self, "GitHubDeployRoleArn", value=role_arn)
