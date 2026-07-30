"""AWS CLI와 CDK를 호출하는 local-only adapter."""

from __future__ import annotations

import base64
import json
import subprocess
import tempfile
import time
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable

from workshield_infra.config import DeploymentConfig


class AwsProvider:
    def __init__(
        self,
        config: DeploymentConfig,
        *,
        profile: str,
        infra_root: Path,
        dry_run: bool = False,
    ) -> None:
        self.config = config
        self.profile = profile
        self.infra_root = infra_root
        self.dry_run = dry_run

    def _aws(self, arguments: list[str], *, capture: bool = True) -> str:
        command = [
            "aws",
            "--profile",
            self.profile,
            "--region",
            self.config.aws_region,
            "--no-cli-pager",
            *arguments,
        ]
        if self.dry_run:
            print("PLAN aws", " ".join(arguments))
            return ""
        result = subprocess.run(
            command,
            check=True,
            capture_output=capture,
            text=True,
        )
        return result.stdout.strip() if capture else ""

    def identity(self) -> str:
        return self._aws(["sts", "get-caller-identity", "--query", "Account", "--output", "text"])

    def cdk(self, action: str, stacks: Iterable[str]) -> None:
        stack_list = list(stacks)
        command = [
            "npm",
            "exec",
            "cdk",
            "--",
            action,
            *stack_list,
            "--context",
            "config=config/prod.json",
        ]
        if action == "deploy":
            command.extend(["--require-approval", "never"])
        if action == "destroy":
            command.append("--force")
        if self.profile:
            command.extend(["--profile", self.profile])
        if self.dry_run:
            print("PLAN", " ".join(command))
            return
        subprocess.run(command, cwd=self.infra_root, check=True)

    def bootstrap(self) -> None:
        command = [
            "npm",
            "exec",
            "cdk",
            "--",
            "bootstrap",
            f"aws://{self.config.aws_account_id}/{self.config.aws_region}",
            "--profile",
            self.profile,
        ]
        if self.dry_run:
            print("PLAN", " ".join(command))
            return
        subprocess.run(command, cwd=self.infra_root, check=True)

    def ensure_github_access(self) -> None:
        """기존 broad deploy role을 application-only trust/권한 경계로 수렴한다."""

        provider_arn = (
            f"arn:aws:iam::{self.config.aws_account_id}:"
            "oidc-provider/token.actions.githubusercontent.com"
        )
        provider_created = False
        try:
            self._aws(
                [
                    "iam",
                    "get-open-id-connect-provider",
                    "--open-id-connect-provider-arn",
                    provider_arn,
                ]
            )
        except subprocess.CalledProcessError:
            self._aws(
                [
                    "iam",
                    "create-open-id-connect-provider",
                    "--url",
                    "https://token.actions.githubusercontent.com",
                    "--client-id-list",
                    "sts.amazonaws.com",
                ]
            )
            provider_created = True
        if provider_created:
            self._aws(
                [
                    "iam",
                    "tag-open-id-connect-provider",
                    "--open-id-connect-provider-arn",
                    provider_arn,
                    "--tags",
                    "Key=Project,Value=WorkShield",
                    f"Key=Environment,Value={self.config.environment}",
                    "Key=ManagedBy,Value=workshield-infra",
                ]
            )

        role_name = f"{self.config.app_name}-github-deploy"
        subject = (
            f"repo:{self.config.github_organization}@{self.config.github_owner_id}/"
            f"{self.config.github_repository}@{self.config.github_repository_id}:"
            f"environment:{self.config.github_environment}"
        )
        trust = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Federated": provider_arn},
                    "Action": "sts:AssumeRoleWithWebIdentity",
                    "Condition": {
                        "StringEquals": {
                            "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
                        },
                        "StringLike": {
                            "token.actions.githubusercontent.com:sub": subject,
                        }
                    },
                }
            ],
        }
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as handle:
            json.dump(trust, handle)
            trust_file = Path(handle.name)
        try:
            try:
                raw = self._aws(
                    ["iam", "get-role", "--role-name", role_name, "--output", "json"]
                )
            except subprocess.CalledProcessError:
                self._aws(
                    [
                        "iam",
                        "create-role",
                        "--role-name",
                        role_name,
                        "--assume-role-policy-document",
                        f"file://{trust_file}",
                        "--description",
                        "Application-only deployment role; infrastructure is local-only.",
                        "--tags",
                        "Key=Project,Value=WorkShield",
                        f"Key=Environment,Value={self.config.environment}",
                        "Key=ManagedBy,Value=workshield-infra",
                    ]
                )
            else:
                role = json.loads(raw)["Role"]
                tags = {item["Key"]: item["Value"] for item in role.get("Tags", [])}
                managed_by = tags.get("ManagedBy")
                if managed_by and managed_by != "workshield-infra":
                    raise RuntimeError("기존 GitHub deploy role의 소유권이 다릅니다.")
                existing_trust = json.dumps(role.get("AssumeRolePolicyDocument", {}))
                if subject not in existing_trust:
                    raise RuntimeError(
                        "기존 GitHub deploy role trust가 이 repository를 가리키지 않습니다."
                    )
                self._aws(
                    [
                        "iam",
                        "update-assume-role-policy",
                        "--role-name",
                        role_name,
                        "--policy-document",
                        f"file://{trust_file}",
                    ]
                )
            for policy_name in json.loads(
                self._aws(
                    [
                        "iam",
                        "list-role-policies",
                        "--role-name",
                        role_name,
                        "--query",
                        "PolicyNames",
                        "--output",
                        "json",
                    ]
                )
            ):
                if policy_name == "WorkShieldDeployOrchestration":
                    self._aws(
                        [
                            "iam",
                            "delete-role-policy",
                            "--role-name",
                            role_name,
                            "--policy-name",
                            policy_name,
                        ]
                    )
                    continue
                policy_body = self._aws(
                    [
                        "iam",
                        "get-role-policy",
                        "--role-name",
                        role_name,
                        "--policy-name",
                        policy_name,
                        "--query",
                        "PolicyDocument",
                        "--output",
                        "json",
                    ]
                ).lower()
                if any(
                    forbidden in policy_body
                    for forbidden in (
                        "cloudformation:",
                        '"ec2:*"',
                        '"iam:*"',
                        "secretsmanager:getsecretvalue",
                    )
                ):
                    raise RuntimeError(
                        f"GitHub deploy role의 예상 밖 broad policy를 발견했습니다: {policy_name}"
                    )
            for policy_arn in json.loads(
                self._aws(
                    [
                        "iam",
                        "list-attached-role-policies",
                        "--role-name",
                        role_name,
                        "--query",
                        "AttachedPolicies[].PolicyArn",
                        "--output",
                        "json",
                    ]
                )
            ):
                self._aws(
                    [
                        "iam",
                        "detach-role-policy",
                        "--role-name",
                        role_name,
                        "--policy-arn",
                        policy_arn,
                    ]
                )
            self._aws(
                [
                    "iam",
                    "tag-role",
                    "--role-name",
                    role_name,
                    "--tags",
                    "Key=Project,Value=WorkShield",
                    f"Key=Environment,Value={self.config.environment}",
                    "Key=ManagedBy,Value=workshield-infra",
                ]
            )
        finally:
            trust_file.unlink(missing_ok=True)

    def stack_status(self, stack_name: str) -> str:
        try:
            return self._aws(
                [
                    "cloudformation",
                    "describe-stacks",
                    "--stack-name",
                    stack_name,
                    "--query",
                    "Stacks[0].StackStatus",
                    "--output",
                    "text",
                ]
            )
        except subprocess.CalledProcessError:
            return "NOT_FOUND"

    def stack_output(self, stack_name: str, output_key: str) -> str:
        return self._aws(
            [
                "cloudformation",
                "describe-stacks",
                "--stack-name",
                stack_name,
                "--query",
                f"Stacks[0].Outputs[?OutputKey=='{output_key}'].OutputValue|[0]",
                "--output",
                "text",
            ]
        )

    def assert_owned_stack(self, stack_name: str) -> None:
        if self.stack_status(stack_name) == "NOT_FOUND":
            return
        raw = self._aws(
            [
                "cloudformation",
                "describe-stacks",
                "--stack-name",
                stack_name,
                "--query",
                "Stacks[0].Tags",
                "--output",
                "json",
            ]
        )
        tags = {item["Key"]: item["Value"] for item in json.loads(raw)}
        expected = {
            "Project": "WorkShield",
            "Environment": self.config.environment,
            "ManagedBy": "workshield-infra",
        }
        if any(tags.get(key) != value for key, value in expected.items()):
            raise RuntimeError(
                f"{stack_name} stack의 소유권 tag를 확인할 수 없습니다."
            )

    def sync_secrets(self, values: dict[str, str]) -> None:
        mapping = {
            "vllm": ("VLLM_API_KEY", values["VLLM_API_KEY"]),
            "embed": ("RUNPOD_EMBED_API_KEY", values["RUNPOD_EMBED_API_KEY"]),
            "origin-header": ("ORIGIN_HEADER", values["ORIGIN_HEADER"]),
            "law": ("LAW_OC", values["LAW_OC"]),
            "duckdns": ("DUCKDNS_TOKEN", values["DUCKDNS_TOKEN"]),
        }
        for secret_name, (key, value) in mapping.items():
            secret_id = f"/workshield/{self.config.environment}/{secret_name}"
            if self.dry_run:
                print(f"PLAN sync secret {secret_id} ({key})")
                continue
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as handle:
                json.dump({key: value}, handle)
                secret_file = Path(handle.name)
            try:
                try:
                    self._aws(["secretsmanager", "describe-secret", "--secret-id", secret_id])
                    try:
                        self._aws(
                            [
                                "secretsmanager",
                                "restore-secret",
                                "--secret-id",
                                secret_id,
                            ]
                        )
                    except subprocess.CalledProcessError:
                        pass
                    operation = "put-secret-value"
                except subprocess.CalledProcessError:
                    operation = "create-secret"
                arguments = ["secretsmanager", operation]
                arguments.extend(["--secret-id" if operation == "put-secret-value" else "--name", secret_id])
                arguments.extend(["--secret-string", f"file://{secret_file}"])
                self._aws(arguments)
            finally:
                secret_file.unlink(missing_ok=True)

    def put_runtime_binding(self, binding: dict[str, str]) -> None:
        self.put_runtime_binding_value(
            json.dumps(binding, separators=(",", ":"), sort_keys=True)
        )

    def put_runtime_binding_value(self, value: str) -> None:
        self._aws(
            [
                "ssm",
                "put-parameter",
                "--name",
                f"/workshield/{self.config.environment}/runtime/binding",
                "--type",
                "String",
                "--overwrite",
                "--value",
                value,
            ]
        )

    def sync_duckdns(self, ip_address: str, token: str) -> None:
        """Foundation EIP를 DuckDNS에 반영하되 token을 command line에 남기지 않는다."""

        subdomain, _, suffix = self.config.origin_domain.partition(".")
        if suffix != "duckdns.org" or not subdomain:
            raise RuntimeError("origin_domain은 <subdomain>.duckdns.org 형식이어야 합니다.")
        if self.dry_run:
            print(f"PLAN update DuckDNS {self.config.origin_domain} -> {ip_address}")
            return
        query = urllib.parse.urlencode(
            {"domains": subdomain, "token": token, "ip": ip_address, "verbose": "true"}
        )
        try:
            with urllib.request.urlopen(
                f"https://www.duckdns.org/update?{query}",
                timeout=30,
            ) as response:
                body = response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError) as error:
            raise RuntimeError("DuckDNS A record 갱신 요청이 실패했습니다.") from error
        if not body.startswith("OK"):
            raise RuntimeError("DuckDNS가 A record 갱신을 거부했습니다.")

    def install_runtime_assets(self) -> None:
        """로컬 운영자만 EC2 runtime 파일을 바꿀 수 있도록 SSM으로 설치한다."""

        assets = {
            "/opt/workshield/deploy-release.sh": self.infra_root / "assets" / "deploy-release.sh",
            "/opt/workshield/runtime/compose.prod.yaml": self.infra_root / "assets" / "compose.yaml",
            "/opt/workshield/runtime/nginx/nginx.conf.template": self.infra_root / "assets" / "nginx.conf.template",
        }
        commands = [
            "set -euo pipefail",
            "install -d -m 0755 /opt/workshield/runtime/nginx /opt/workshield/releases",
        ]
        for destination, source in assets.items():
            encoded = base64.b64encode(source.read_bytes()).decode("ascii")
            mode = "0700" if destination.endswith(".sh") else "0644"
            commands.extend(
                [
                    f"printf '%s' '{encoded}' | base64 -d > '{destination}.tmp'",
                    f"chmod {mode} '{destination}.tmp'",
                    f"mv '{destination}.tmp' '{destination}'",
                ]
            )
        self._run_shell_commands(commands, "Install WorkShield runtime assets")

    def provision_origin_tls(self) -> None:
        """DuckDNS DNS-01 hook과 자동 갱신 timer를 managed instance에 설치한다."""

        subdomain, _, suffix = self.config.origin_domain.partition(".")
        if suffix != "duckdns.org" or not subdomain:
            raise RuntimeError("origin_domain은 <subdomain>.duckdns.org 형식이어야 합니다.")
        secret_id = f"/workshield/{self.config.environment}/duckdns"
        auth_hook = f"""#!/usr/bin/env bash
set -euo pipefail
token="$(aws secretsmanager get-secret-value --region {self.config.aws_region} --secret-id {secret_id} --query SecretString --output text | python3 -c 'import json,sys; print(json.load(sys.stdin)["DUCKDNS_TOKEN"])')"
response="$(curl --fail --silent --show-error --get https://www.duckdns.org/update --data-urlencode domains={subdomain} --data-urlencode "token=${{token}}" --data-urlencode "txt=${{CERTBOT_VALIDATION}}" --data-urlencode verbose=true)"
[[ "$response" == OK* ]]
sleep 75
"""
        cleanup_hook = f"""#!/usr/bin/env bash
set -euo pipefail
token="$(aws secretsmanager get-secret-value --region {self.config.aws_region} --secret-id {secret_id} --query SecretString --output text | python3 -c 'import json,sys; print(json.load(sys.stdin)["DUCKDNS_TOKEN"])')"
curl --fail --silent --show-error --get https://www.duckdns.org/update --data-urlencode domains={subdomain} --data-urlencode "token=${{token}}" --data-urlencode clear=true >/dev/null
"""
        deploy_hook = f"""#!/usr/bin/env bash
set -euo pipefail
install -d -m 0700 /opt/workshield/certificates
install -m 0600 /etc/letsencrypt/live/{self.config.origin_domain}/fullchain.pem /opt/workshield/certificates/fullchain.pem
install -m 0600 /etc/letsencrypt/live/{self.config.origin_domain}/privkey.pem /opt/workshield/certificates/privkey.pem
container="$(docker ps --filter label=com.docker.compose.project=workshield-prod --filter label=com.docker.compose.service=nginx --format '{{{{.ID}}}}' | head -n 1)"
[[ -z "$container" ]] || docker kill --signal HUP "$container"
"""
        service = """[Unit]
Description=Renew WorkShield origin TLS certificate
[Service]
Type=oneshot
ExecStart=/usr/bin/certbot renew --quiet --deploy-hook /usr/local/sbin/workshield-install-origin-certificate
"""
        timer = """[Unit]
Description=Daily WorkShield origin TLS renewal check
[Timer]
OnCalendar=*-*-* 03:17:00
Persistent=true
RandomizedDelaySec=30m
[Install]
WantedBy=timers.target
"""
        commands = [
            "set -euo pipefail",
            "dnf install -y certbot",
            "install -d -m 0700 /opt/workshield/certificates",
            *self._encoded_file_commands("/usr/local/sbin/workshield-duckdns-auth", auth_hook, "0700"),
            *self._encoded_file_commands("/usr/local/sbin/workshield-duckdns-cleanup", cleanup_hook, "0700"),
            *self._encoded_file_commands(
                "/usr/local/sbin/workshield-install-origin-certificate",
                deploy_hook,
                "0700",
            ),
            (
                "certbot certonly --manual --preferred-challenges dns "
                "--manual-auth-hook /usr/local/sbin/workshield-duckdns-auth "
                "--manual-cleanup-hook /usr/local/sbin/workshield-duckdns-cleanup "
                "--deploy-hook /usr/local/sbin/workshield-install-origin-certificate "
                "--manual-public-ip-logging-ok --non-interactive --agree-tos "
                f"--keep-until-expiring -m '{self.config.acme_email}' "
                f"-d '{self.config.origin_domain}'"
            ),
            "/usr/local/sbin/workshield-install-origin-certificate",
            *self._encoded_file_commands(
                "/etc/systemd/system/workshield-certbot-renew.service",
                service,
                "0644",
            ),
            *self._encoded_file_commands(
                "/etc/systemd/system/workshield-certbot-renew.timer",
                timer,
                "0644",
            ),
            "systemctl daemon-reload",
            "systemctl enable --now workshield-certbot-renew.timer",
        ]
        self._run_shell_commands(commands, "Provision WorkShield origin TLS")

    @staticmethod
    def _encoded_file_commands(destination: str, content: str, mode: str) -> list[str]:
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        return [
            f"printf '%s' '{encoded}' | base64 -d > '{destination}.tmp'",
            f"chmod {mode} '{destination}.tmp'",
            f"mv '{destination}.tmp' '{destination}'",
        ]

    def _run_shell_commands(self, commands: list[str], comment: str) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            json.dump({"commands": commands}, handle)
            parameters_file = Path(handle.name)
        if self.dry_run:
            parameters_file.unlink(missing_ok=True)
            print(f"PLAN {comment} through SSM")
            return
        try:
            command_id = self._aws(
                [
                    "ssm",
                    "send-command",
                    "--document-name",
                    "AWS-RunShellScript",
                    "--targets",
                    "Key=tag:Project,Values=WorkShield",
                    f"Key=tag:Environment,Values={self.config.environment}",
                    "--parameters",
                    f"file://{parameters_file}",
                    "--comment",
                    comment,
                    "--query",
                    "Command.CommandId",
                    "--output",
                    "text",
                ]
            )
        finally:
            parameters_file.unlink(missing_ok=True)
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            status = self._aws(
                [
                    "ssm",
                    "list-commands",
                    "--command-id",
                    command_id,
                    "--query",
                    "Commands[0].Status",
                    "--output",
                    "text",
                ]
            )
            if status == "Success":
                return
            if status in {"Failed", "Cancelled", "TimedOut", "Cancelling"}:
                raise RuntimeError(f"SSM command가 실패했습니다: {command_id} ({status})")
            time.sleep(5)
        raise TimeoutError(f"SSM command timeout: {command_id}")

    def parameter(self, name: str) -> str:
        try:
            return self._aws(
                ["ssm", "get-parameter", "--name", name, "--query", "Parameter.Value", "--output", "text"]
            )
        except subprocess.CalledProcessError:
            return "NOT_FOUND"

    def managed_instance_status(self) -> dict[str, str]:
        try:
            raw = self._aws(
                [
                    "ssm",
                    "describe-instance-information",
                    "--filters",
                    "Key=tag:Project,Values=WorkShield",
                    f"Key=tag:Environment,Values={self.config.environment}",
                    "--query",
                    "InstanceInformationList[0].{instance_id:InstanceId,ping_status:PingStatus}",
                    "--output",
                    "json",
                ]
            )
            body = json.loads(raw)
            return body if body else {"ping_status": "NOT_FOUND"}
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            return {"ping_status": "UNKNOWN"}

    @staticmethod
    def viewer_health(domain_name: str) -> str:
        try:
            with urllib.request.urlopen(
                f"https://{domain_name}/health/ready",
                timeout=20,
            ) as response:
                return "HEALTHY" if response.status == 200 else f"HTTP_{response.status}"
        except urllib.error.HTTPError as error:
            return f"HTTP_{error.code}"
        except (urllib.error.URLError, TimeoutError):
            return "UNREACHABLE"

    def stage_secret(self, name: str, key: str, value: str) -> tuple[str, str]:
        """새 version을 AWSPENDING으로 쓰고 (pending, current) ID를 반환한다."""

        secret_id = f"/workshield/{self.config.environment}/{name}"
        current = self._aws(
            [
                "secretsmanager",
                "list-secret-version-ids",
                "--secret-id",
                secret_id,
                "--query",
                "Versions[?contains(VersionStages, 'AWSCURRENT')].VersionId|[0]",
                "--output",
                "text",
            ]
        )
        previous_pending = self._aws(
            [
                "secretsmanager",
                "list-secret-version-ids",
                "--secret-id",
                secret_id,
                "--query",
                "Versions[?contains(VersionStages, 'AWSPENDING')].VersionId|[0]",
                "--output",
                "text",
            ]
        )
        if previous_pending not in {"", "None"}:
            self._aws(
                [
                    "secretsmanager",
                    "update-secret-version-stage",
                    "--secret-id",
                    secret_id,
                    "--version-stage",
                    "AWSPENDING",
                    "--remove-from-version-id",
                    previous_pending,
                ]
            )
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as handle:
            json.dump({key: value}, handle)
            secret_file = Path(handle.name)
        try:
            pending = self._aws(
                [
                    "secretsmanager",
                    "put-secret-value",
                    "--secret-id",
                    secret_id,
                    "--secret-string",
                    f"file://{secret_file}",
                    "--version-stages",
                    "AWSPENDING",
                    "--query",
                    "VersionId",
                    "--output",
                    "text",
                ]
            )
        finally:
            secret_file.unlink(missing_ok=True)
        return pending, current

    def promote_secret(
        self,
        name: str,
        *,
        pending_version: str,
        current_version: str,
    ) -> None:
        self._aws(
            [
                "secretsmanager",
                "update-secret-version-stage",
                "--secret-id",
                f"/workshield/{self.config.environment}/{name}",
                "--version-stage",
                "AWSCURRENT",
                "--move-to-version-id",
                pending_version,
                "--remove-from-version-id",
                current_version,
            ]
        )

    def discard_pending_secret(self, name: str, version: str) -> None:
        self._aws(
            [
                "secretsmanager",
                "update-secret-version-stage",
                "--secret-id",
                f"/workshield/{self.config.environment}/{name}",
                "--version-stage",
                "AWSPENDING",
                "--remove-from-version-id",
                version,
            ]
        )

    def restore_secret(
        self,
        name: str,
        *,
        previous_version: str,
        failed_version: str,
    ) -> None:
        self._aws(
            [
                "secretsmanager",
                "update-secret-version-stage",
                "--secret-id",
                f"/workshield/{self.config.environment}/{name}",
                "--version-stage",
                "AWSCURRENT",
                "--move-to-version-id",
                previous_version,
                "--remove-from-version-id",
                failed_version,
            ]
        )

    def reapply_active_release(self) -> None:
        prefix = f"/workshield/{self.config.environment}/release"
        release_tag = self.parameter(f"{prefix}/active-tag")
        api_image = self.parameter(f"{prefix}/active-api-image")
        mcp_image = self.parameter(f"{prefix}/active-mcp-image")
        if "__UNSET__" in {release_tag, api_image, mcp_image}:
            raise RuntimeError("활성 container release가 없어 secret 회전을 검증할 수 없습니다.")
        document = self.stack_output("WorkShieldService", "DeployDocumentName")
        parameters = json.dumps(
            {
                "ReleaseTag": [release_tag],
                "ApiImage": [api_image],
                "McpImage": [mcp_image],
            },
            separators=(",", ":"),
        )
        command_id = self._aws(
            [
                "ssm",
                "send-command",
                "--document-name",
                document,
                "--targets",
                "Key=tag:Project,Values=WorkShield",
                f"Key=tag:Environment,Values={self.config.environment}",
                "--parameters",
                parameters,
                "--comment",
                "Reapply WorkShield release after secret rotation",
                "--query",
                "Command.CommandId",
                "--output",
                "text",
            ]
        )
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            status = self._aws(
                [
                    "ssm",
                    "list-commands",
                    "--command-id",
                    command_id,
                    "--query",
                    "Commands[0].Status",
                    "--output",
                    "text",
                ]
            )
            if status == "Success":
                return
            if status in {"Failed", "Cancelled", "TimedOut", "Cancelling"}:
                raise RuntimeError(f"container secret 회전 검증이 실패했습니다: {status}")
            time.sleep(5)
        raise TimeoutError("container secret 회전 검증 timeout")

    def purge_bootstrap(self) -> None:
        """project stack이 모두 사라진 뒤 CDK bootstrap stack을 제거한다."""

        if any(
            self.stack_status(name) != "NOT_FOUND"
            for name in ("WorkShieldService", "WorkShieldFoundation")
        ):
            raise RuntimeError("Service와 Foundation stack이 남아 있어 bootstrap purge를 중단합니다.")
        self.cdk("destroy", ["WorkShieldAccess"])
        legacy_stack = f"{self.config.app_name}-github-oidc"
        if self.stack_status(legacy_stack) != "NOT_FOUND":
            self._aws(
                [
                    "cloudformation",
                    "delete-stack",
                    "--stack-name",
                    legacy_stack,
                ]
            )
            self._aws(
                [
                    "cloudformation",
                    "wait",
                    "stack-delete-complete",
                    "--stack-name",
                    legacy_stack,
                ]
            )
        role_name = f"{self.config.app_name}-github-deploy"
        try:
            for policy_name in json.loads(
                self._aws(
                    [
                        "iam",
                        "list-role-policies",
                        "--role-name",
                        role_name,
                        "--query",
                        "PolicyNames",
                        "--output",
                        "json",
                    ]
                )
            ):
                self._aws(
                    [
                        "iam",
                        "delete-role-policy",
                        "--role-name",
                        role_name,
                        "--policy-name",
                        policy_name,
                    ]
                )
            for policy_arn in json.loads(
                self._aws(
                    [
                        "iam",
                        "list-attached-role-policies",
                        "--role-name",
                        role_name,
                        "--query",
                        "AttachedPolicies[].PolicyArn",
                        "--output",
                        "json",
                    ]
                )
            ):
                self._aws(
                    [
                        "iam",
                        "detach-role-policy",
                        "--role-name",
                        role_name,
                        "--policy-arn",
                        policy_arn,
                    ]
                )
            self._aws(["iam", "delete-role", "--role-name", role_name])
        except subprocess.CalledProcessError:
            pass
        provider_arn = (
            f"arn:aws:iam::{self.config.aws_account_id}:"
            "oidc-provider/token.actions.githubusercontent.com"
        )
        try:
            raw_tags = self._aws(
                [
                    "iam",
                    "list-open-id-connect-provider-tags",
                    "--open-id-connect-provider-arn",
                    provider_arn,
                    "--query",
                    "Tags",
                    "--output",
                    "json",
                ]
            )
            tags = {item["Key"]: item["Value"] for item in json.loads(raw_tags)}
            if tags.get("ManagedBy") == "workshield-infra":
                self._aws(
                    [
                        "iam",
                        "delete-open-id-connect-provider",
                        "--open-id-connect-provider-arn",
                        provider_arn,
                    ]
                )
        except subprocess.CalledProcessError:
            pass
        command = [
            "aws",
            "--profile",
            self.profile,
            "--region",
            self.config.aws_region,
            "--no-cli-pager",
            "cloudformation",
            "delete-stack",
            "--stack-name",
            "CDKToolkit",
        ]
        if self.dry_run:
            print("PLAN", " ".join(command))
            return
        subprocess.run(command, check=True)

    def schedule_secret_deletion(self) -> None:
        for name in ("vllm", "embed", "origin-header", "law", "duckdns"):
            secret_id = f"/workshield/{self.config.environment}/{name}"
            try:
                self._aws(
                    [
                        "secretsmanager",
                        "delete-secret",
                        "--secret-id",
                        secret_id,
                        "--recovery-window-in-days",
                        "7",
                    ]
                )
            except subprocess.CalledProcessError:
                continue
