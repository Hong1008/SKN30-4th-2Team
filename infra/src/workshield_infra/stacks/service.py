"""EC2 runtime, S3/CloudFront edge, SSM document를 만드는 service stack."""

from __future__ import annotations

from pathlib import Path

from aws_cdk import CfnDeletionPolicy, CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_ssm as ssm
from constructs import Construct

from workshield_infra.config import DeploymentConfig
from workshield_infra.stacks.access import AccessStack
from workshield_infra.stacks.foundation import FoundationStack


class ServiceStack(Stack):
    """CloudFront viewer와 EC2 origin을 연결한다."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: DeploymentConfig,
        access: AccessStack,
        foundation: FoundationStack,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        # CloudFormation dynamic reference를 사용해 header 원문을 CDK command
        # argument·template output·workflow log에 노출하지 않는다.
        origin_header_dynamic_reference = (
            f"{{{{resolve:secretsmanager:/workshield/{config.environment}/"
            "origin-header:SecretString:ORIGIN_HEADER}}"
        )

        self.instance = ec2.Instance(
            self,
            "ApplicationInstance",
            vpc=foundation.vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            instance_type=ec2.InstanceType(config.instance_type),
            machine_image=ec2.MachineImage.resolve_ssm_parameter_at_launch(
                "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
            ),
            role=foundation.instance_role,
            security_group=foundation.security_group,
            require_imdsv2=True,
            detailed_monitoring=True,
        )
        self.instance.user_data.add_commands(*self._bootstrap_commands(foundation))
        ec2.CfnEIPAssociation(
            self,
            "OriginElasticIpAssociation",
            allocation_id=foundation.elastic_ip.attr_allocation_id,
            instance_id=self.instance.instance_id,
        )
        ec2.CfnVolumeAttachment(
            self,
            "UserDataVolumeAttachment",
            device="/dev/sdf",
            instance_id=self.instance.instance_id,
            volume_id=foundation.data_volume.ref,
        )
        ec2.CfnVolumeAttachment(
            self,
            "McpCorpusVolumeAttachment",
            device="/dev/sdg",
            instance_id=self.instance.instance_id,
            volume_id=foundation.corpus_volume.ref,
        )
        cloudwatch.Alarm(
            self,
            "HighCpuAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/EC2",
                metric_name="CPUUtilization",
                dimensions_map={"InstanceId": self.instance.instance_id},
                period=Duration.minutes(5),
            ),
            threshold=80,
            evaluation_periods=3,
            datapoints_to_alarm=3,
        )

        web_bucket = s3.Bucket(
            self,
            "WebBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            versioned=True,
            auto_delete_objects=True,
            removal_policy=RemovalPolicy.DESTROY,
        )
        oac = cloudfront.CfnOriginAccessControl(
            self,
            "WebOriginAccessControl",
            origin_access_control_config=cloudfront.CfnOriginAccessControl.OriginAccessControlConfigProperty(
                name=f"{config.app_name}-web-oac",
                origin_access_control_origin_type="s3",
                signing_behavior="always",
                signing_protocol="sigv4",
            ),
        )
        function_code = (
            Path(__file__).resolve().parents[3] / "assets" / "spa-rewrite.js"
        ).read_text(encoding="utf-8")
        spa_function = cloudfront.CfnFunction(
            self,
            "SpaRewriteFunction",
            name=f"{config.app_name}-spa-rewrite",
            auto_publish=True,
            function_code=function_code,
            function_config=cloudfront.CfnFunction.FunctionConfigProperty(comment="Rewrite SPA screen paths only", runtime="cloudfront-js-1.0"),
        )
        distribution = cloudfront.CfnDistribution(
            self,
            "Distribution",
            distribution_config=cloudfront.CfnDistribution.DistributionConfigProperty(
                enabled=True,
                default_root_object="index.html",
                http_version="http2and3",
                price_class="PriceClass_200",
                origins=[
                    cloudfront.CfnDistribution.OriginProperty(
                        id="web",
                        domain_name=web_bucket.bucket_regional_domain_name,
                        origin_access_control_id=oac.attr_id,
                        origin_path="/live",
                        s3_origin_config=cloudfront.CfnDistribution.S3OriginConfigProperty(origin_access_identity=""),
                    ),
                    cloudfront.CfnDistribution.OriginProperty(
                        id="api",
                        domain_name=config.origin_domain,
                        origin_custom_headers=[cloudfront.CfnDistribution.OriginCustomHeaderProperty(header_name="X-WorkShield-Origin", header_value=origin_header_dynamic_reference)],
                        custom_origin_config=cloudfront.CfnDistribution.CustomOriginConfigProperty(
                            http_port=80,
                            https_port=443,
                            origin_protocol_policy="https-only",
                            origin_read_timeout=120,
                            origin_ssl_protocols=["TLSv1.2"],
                        ),
                    ),
                ],
                default_cache_behavior=cloudfront.CfnDistribution.DefaultCacheBehaviorProperty(
                    target_origin_id="web",
                    viewer_protocol_policy="redirect-to-https",
                    allowed_methods=["GET", "HEAD", "OPTIONS"],
                    cached_methods=["GET", "HEAD"],
                    cache_policy_id=cloudfront.CachePolicy.CACHING_OPTIMIZED.cache_policy_id,
                    function_associations=[cloudfront.CfnDistribution.FunctionAssociationProperty(event_type="viewer-request", function_arn=spa_function.attr_function_arn)],
                    compress=True,
                ),
                cache_behaviors=[self._api_behavior("/api/*"), self._api_behavior("/health/*")],
                viewer_certificate=cloudfront.CfnDistribution.ViewerCertificateProperty(cloud_front_default_certificate=True, minimum_protocol_version="TLSv1.2_2021"),
            ),
        )
        distribution.cfn_options.deletion_policy = CfnDeletionPolicy.DELETE
        distribution.cfn_options.update_replace_policy = CfnDeletionPolicy.DELETE
        web_bucket.add_to_resource_policy(
            iam.PolicyStatement(
                principals=[iam.ServicePrincipal("cloudfront.amazonaws.com")],
                actions=["s3:GetObject"],
                resources=[web_bucket.arn_for_objects("*")],
                conditions={"StringEquals": {"AWS:SourceArn": f"arn:{self.partition}:cloudfront::{self.account}:distribution/{distribution.attr_id}"}},
            )
        )
        CfnOutput(self, "WebBucketName", value=web_bucket.bucket_name)
        CfnOutput(self, "CloudFrontDistributionId", value=distribution.attr_id)
        CfnOutput(
            self,
            "CloudFrontDomainName",
            value=distribution.attr_domain_name,
        )
        document = ssm.CfnDocument(
            self,
            "DeployContainersDocument",
            name=f"{config.app_name}-deploy",
            document_type="Command",
            document_format="YAML",
            update_method="NewVersion",
            content={
                "schemaVersion": "2.2",
                "description": "Deploy a verified WorkShield container release without passing secrets.",
                "parameters": {
                    "ReleaseTag": {
                        "type": "String",
                        "allowedPattern": "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
                    },
                    "ApiImage": {
                        "type": "String",
                        "allowedPattern": "^ghcr[.]io/.+@sha256:[0-9a-f]{64}$",
                    },
                    "McpImage": {
                        "type": "String",
                        "allowedPattern": "^ghcr[.]io/.+@sha256:[0-9a-f]{64}$",
                    },
                },
                "mainSteps": [
                    {
                        "action": "aws:runShellScript",
                        "name": "deploy",
                        "inputs": {
                            "runCommand": [
                                "/opt/workshield/deploy-release.sh "
                                "--release-tag '{{ ReleaseTag }}' "
                                "--api-image '{{ ApiImage }}' "
                                "--mcp-image '{{ McpImage }}'"
                            ]
                        },
                    }
                ],
            },
        )
        CfnOutput(self, "DeployDocumentName", value=document.name)

        deploy_policy = iam.Policy(
            self,
            "GitHubApplicationDeployPolicy",
            statements=[
                iam.PolicyStatement(
                    actions=["ssm:SendCommand"],
                    resources=[
                        f"arn:{self.partition}:ssm:{self.region}:{self.account}:document/{config.app_name}-deploy",
                        self.format_arn(
                            service="ec2",
                            resource="instance",
                            resource_name=self.instance.instance_id,
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    actions=[
                        "ssm:GetCommandInvocation",
                        "ssm:ListCommandInvocations",
                        "ssm:ListCommands",
                    ],
                    resources=["*"],
                ),
                iam.PolicyStatement(
                    actions=["s3:ListBucket"],
                    resources=[web_bucket.bucket_arn],
                ),
                iam.PolicyStatement(
                    actions=["s3:GetObject", "s3:PutObject"],
                    resources=[web_bucket.arn_for_objects("releases/*")],
                ),
                iam.PolicyStatement(
                    actions=["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
                    resources=[web_bucket.arn_for_objects("live/*")],
                ),
                iam.PolicyStatement(
                    actions=[
                        "cloudfront:CreateInvalidation",
                        "cloudfront:GetInvalidation",
                    ],
                    resources=[
                        f"arn:{self.partition}:cloudfront::{self.account}:distribution/{distribution.attr_id}"
                    ],
                ),
            ],
        )
        deploy_policy.attach_to_role(access.github_deploy_role)

    def _api_behavior(self, path_pattern: str) -> cloudfront.CfnDistribution.CacheBehaviorProperty:
        return cloudfront.CfnDistribution.CacheBehaviorProperty(
            path_pattern=path_pattern,
            target_origin_id="api",
            viewer_protocol_policy="redirect-to-https",
            allowed_methods=["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"],
            cached_methods=["GET", "HEAD"],
            cache_policy_id=cloudfront.CachePolicy.CACHING_DISABLED.cache_policy_id,
            origin_request_policy_id=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER.origin_request_policy_id,
            compress=False,
        )

    def _bootstrap_commands(self, foundation: FoundationStack) -> list[str]:
        data_id = foundation.data_volume.ref
        corpus_id = foundation.corpus_volume.ref
        return [
            # Amazon Linux 기본 awscli/curl 패키지와 충돌하지 않도록 Docker만 설치한다.
            "dnf install -y docker",
            "systemctl enable --now docker",
            "install -d -m 0755 /usr/local/lib/docker/cli-plugins",
            "curl --fail --location --silent --show-error https://github.com/docker/compose/releases/download/v5.1.2/docker-compose-linux-x86_64 --output /usr/local/lib/docker/cli-plugins/docker-compose",
            "chmod 0755 /usr/local/lib/docker/cli-plugins/docker-compose",
            "docker compose version",
            "usermod -aG docker ec2-user",
            "mkdir -p /opt/workshield/{data,mcp-corpus,certificates,secrets,releases}",
            "mkdir -p /opt/workshield/runtime/nginx",
            self._mount_command(data_id, "/opt/workshield/data"),
            self._mount_command(corpus_id, "/opt/workshield/mcp-corpus"),
        ]

    @staticmethod
    def _mount_command(volume_id: str, target: str) -> str:
        return f"""volume_id='{volume_id}'
device=/dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_${{volume_id//-/}}
for attempt in $(seq 1 60); do [ -b \"$device\" ] && break; sleep 2; done
test -b \"$device\"
blkid \"$device\" >/dev/null 2>&1 || mkfs.ext4 -F \"$device\"
mkdir -p '{target}'
grep -q \" {target} \" /etc/fstab || echo \"$device {target} ext4 defaults,nofail,noatime 0 2\" >> /etc/fstab
mount '{target}'"""
