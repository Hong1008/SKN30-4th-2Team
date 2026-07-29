"""네트워크·IAM·EBS·상태 namespace를 만드는 foundation stack."""

from __future__ import annotations

from aws_cdk import CfnDeletionPolicy, CfnTag, Duration, RemovalPolicy, Stack
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_route53 as route53
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
            description="CloudFront만 WorkShield origin HTTPS에 접근 가능",
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
        self.instance_role.add_to_policy(
            iam.PolicyStatement(
                actions=["route53:ChangeResourceRecordSets"],
                resources=[f"arn:{self.partition}:route53:::hostedzone/{config.hosted_zone_id}"],
            )
        )
        self.instance_role.add_to_policy(
            iam.PolicyStatement(
                actions=["route53:GetChange", "route53:ListResourceRecordSets"],
                resources=["*"],
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

        zone = route53.HostedZone.from_hosted_zone_attributes(
            self,
            "OriginHostedZone",
            hosted_zone_id=config.hosted_zone_id,
            zone_name=config.hosted_zone_name,
        )
        route53.ARecord(
            self,
            "OriginRecord",
            zone=zone,
            record_name=config.origin_domain,
            target=route53.RecordTarget.from_ip_addresses(self.elastic_ip.attr_public_ip),
            ttl=Duration.minutes(5),
        )

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

        for name in ("vllm", "embed", "origin-header"):
            secret = secretsmanager.CfnSecret(self, f"{name.title().replace('-', '')}Secret", name=f"/workshield/prod/{name}")
            secret.cfn_options.deletion_policy = CfnDeletionPolicy.DELETE
        for name, value in {
            "release/active-sha": "__UNSET__",
            "vllm/base-url": "__UNSET__",
            "vllm/model": "__UNSET__",
            "runpod/llm/pod-id": "__UNSET__",
            "runpod/embed/pod-id": "__UNSET__",
            "runpod/embed/base-url": "__UNSET__",
            "api/session-ttl-seconds": "1800",
            "api/max-upload-size-bytes": "10485760",
        }.items():
            ssm.StringParameter(self, f"Parameter{name.title().replace('/', '').replace('-', '')}", parameter_name=f"/workshield/prod/{name}", string_value=value)
