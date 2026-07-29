"""네트워크·IAM·EBS·상태 namespace를 만드는 foundation stack."""

from __future__ import annotations

from aws_cdk import CfnDeletionPolicy, CfnOutput, CfnTag, Duration, RemovalPolicy, Stack
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_ssm as ssm
from constructs import Construct

from stacks.config import DeploymentConfig


class FoundationStack(Stack):
    """서비스 instance가 사용할 기본 AWS 자원을 제공한다."""

    def __init__(self, scope: Construct, construct_id: str, *, config: DeploymentConfig, **kwargs: object) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.config = config

        # L1 VPC 구성으로 account-specific AZ context lookup 없이 synth한다.
        vpc = ec2.CfnVPC(
            self,
            "Vpc",
            cidr_block="10.30.0.0/16",
            enable_dns_hostnames=True,
            enable_dns_support=True,
        )
        internet_gateway = ec2.CfnInternetGateway(self, "InternetGateway")
        gateway_attachment = ec2.CfnVPCGatewayAttachment(
            self,
            "InternetGatewayAttachment",
            internet_gateway_id=internet_gateway.ref,
            vpc_id=vpc.ref,
        )
        public_subnet = ec2.CfnSubnet(
            self,
            "PublicSubnet",
            vpc_id=vpc.ref,
            cidr_block="10.30.0.0/24",
            availability_zone=config.availability_zone,
            map_public_ip_on_launch=True,
        )
        route_table = ec2.CfnRouteTable(self, "PublicRouteTable", vpc_id=vpc.ref)
        default_route = ec2.CfnRoute(
            self,
            "PublicDefaultRoute",
            route_table_id=route_table.ref,
            destination_cidr_block="0.0.0.0/0",
            gateway_id=internet_gateway.ref,
        )
        default_route.add_dependency(gateway_attachment)
        ec2.CfnSubnetRouteTableAssociation(
            self,
            "PublicRouteAssociation",
            route_table_id=route_table.ref,
            subnet_id=public_subnet.ref,
        )
        self.vpc = ec2.Vpc.from_vpc_attributes(
            self,
            "VpcReference",
            vpc_id=vpc.ref,
            availability_zones=[config.availability_zone],
            public_subnet_ids=[public_subnet.ref],
            public_subnet_route_table_ids=[route_table.ref],
        )
        self.security_group = ec2.SecurityGroup(
            self,
            "OriginSecurityGroup",
            vpc=self.vpc,
            description="Allow CloudFront access to WorkShield origin HTTPS only",
            allow_all_outbound=True,
        )
        self.security_group.add_ingress_rule(
            ec2.Peer.prefix_list(config.cloudfront_origin_prefix_list_id),
            ec2.Port.tcp(443),
            "CloudFront origin-facing managed prefix list",
        )

        self.instance_role = iam.Role(
            self,
            "InstanceRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore"),
            ],
        )
        self.instance_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[f"arn:{self.partition}:secretsmanager:{self.region}:{self.account}:secret:/workshield/prod/*"],
            )
        )
        self.instance_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter", "ssm:GetParameters", "ssm:PutParameter"],
                resources=[f"arn:{self.partition}:ssm:{self.region}:{self.account}:parameter/workshield/prod/*"],
            )
        )

        self.data_volume = ec2.CfnVolume(
            self,
            "EphemeralUserDataVolume",
            availability_zone=config.availability_zone,
            encrypted=True,
            size=20,
            volume_type="gp3",
            tags=[CfnTag(key="Name", value=f"{config.app_name}-user-data")],
        )
        self.data_volume.cfn_options.deletion_policy = CfnDeletionPolicy.DELETE
        self.data_volume.cfn_options.update_replace_policy = CfnDeletionPolicy.DELETE

        self.corpus_volume = ec2.CfnVolume(
            self,
            "McpCorpusVolume",
            availability_zone=config.availability_zone,
            encrypted=True,
            size=30,
            volume_type="gp3",
            tags=[CfnTag(key="Name", value=f"{config.app_name}-mcp-corpus")],
        )
        self.corpus_volume.cfn_options.deletion_policy = CfnDeletionPolicy.DELETE
        self.corpus_volume.cfn_options.update_replace_policy = CfnDeletionPolicy.DELETE

        self.elastic_ip = ec2.CfnEIP(self, "OriginElasticIp", domain="vpc")
        self.elastic_ip.cfn_options.deletion_policy = CfnDeletionPolicy.DELETE

        # DuckDNS는 Route 53 hosted zone으로 위임할 수 없다. Foundation 배포 뒤
        # sync-duckdns-local.sh가 이 고정 Elastic IP를 DuckDNS A 레코드에 반영한다.
        CfnOutput(self, "OriginElasticIpOutput", key="OriginElasticIp", value=self.elastic_ip.attr_public_ip)

        self.log_group = logs.LogGroup(
            self,
            "ApplicationLogGroup",
            log_group_name=f"/workshield/prod/application",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )
        cloudwatch.CfnAlarm(
            self,
            "LogDeliveryErrorAlarm",
            comparison_operator="GreaterThanThreshold",
            evaluation_periods=1,
            metric_name="IncomingLogEvents",
            namespace="AWS/Logs",
            period=300,
            statistic="Sum",
            threshold=1_000_000,
            treat_missing_data="notBreaching",
        )

        # 실제 값은 6단계의 안전한 stdin script가 입력한다. stack 삭제 시에는
        # 즉시 폐기하지 않고 destroy script가 7일 복구 기간을 예약한다.
        for name in ("vllm", "embed", "origin-header", "law", "duckdns"):
            secret = secretsmanager.CfnSecret(self, f"{name.title().replace('-', '')}Secret", name=f"/workshield/prod/{name}")
            secret.cfn_options.deletion_policy = CfnDeletionPolicy.RETAIN
            secret.cfn_options.update_replace_policy = CfnDeletionPolicy.RETAIN
        for name, value in {
            "release/active-sha": "__UNSET__",
            "vllm/base-url": "__UNSET__",
            "vllm/model": "__UNSET__",
            "runpod/llm/pod-id": "__UNSET__",
            "runpod/llm/base-url": "__UNSET__",
            "runpod/llm/model-id": "__UNSET__",
            "runpod/llm/template-id": "__UNSET__",
            "runpod/embed/pod-id": "__UNSET__",
            "runpod/embed/base-url": "__UNSET__",
            "runpod/embed/template-id": "__UNSET__",
            "runpod/last-provision-run-id": "__UNSET__",
            "api/session-ttl-seconds": "1800",
            "api/max-upload-size-bytes": "10485760",
            "runtime/ghcr-owner": "__UNSET__",
            "runtime/nginx-image": "__UNSET__",
            "runtime/origin-domain": "__UNSET__",
        }.items():
            ssm.StringParameter(self, f"Parameter{name.title().replace('/', '').replace('-', '')}", parameter_name=f"/workshield/prod/{name}", string_value=value)
