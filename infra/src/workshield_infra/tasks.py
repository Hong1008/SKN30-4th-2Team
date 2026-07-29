"""root justfile만 호출하는 WorkShield local infrastructure task runner."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from workshield_infra.config import (
    DeploymentConfig,
    load_secret_file,
    update_secret_file,
)
from workshield_infra.providers.aws import AwsProvider
from workshield_infra.providers.runpod import RunPodProvider
from workshield_infra.state import LocalState, operation_lock

INFRA_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = INFRA_ROOT.parent
CONFIG_DIR = INFRA_ROOT / "config"
REQUIRED_SECRETS = {
    "RUNPOD_MANAGEMENT_API_KEY",
    "ORIGIN_HEADER",
    "LAW_OC",
    "DUCKDNS_TOKEN",
}
RUNTIME_GENERATED_SECRETS = (
    "VLLM_API_KEY",
    "RUNPOD_EMBED_API_KEY",
)


def _paths(environment: str) -> tuple[Path, Path, Path, Path]:
    config = CONFIG_DIR / f"{environment}.json"
    secrets_file = CONFIG_DIR / f"{environment}.secrets.env"
    state_dir = INFRA_ROOT / ".state"
    return (
        config,
        secrets_file,
        state_dir / f"{environment}.json",
        state_dir / f"{environment}.lock",
    )


def _load(
    environment: str,
    *,
    require_secrets: bool,
) -> tuple[DeploymentConfig, dict[str, str], LocalState, Path, Path]:
    config_path, secrets_path, state_path, lock_path = _paths(environment)
    config = DeploymentConfig.from_file(config_path)
    if config.environment != environment:
        raise RuntimeError("요청 environment와 config의 environment가 다릅니다.")
    values = load_secret_file(secrets_path, required=require_secrets)
    if require_secrets:
        missing = sorted(key for key in REQUIRED_SECRETS if not values.get(key))
        if missing:
            raise RuntimeError(f"필수 secret 값이 비어 있습니다: {', '.join(missing)}")
        if os.name != "nt" and secrets_path.stat().st_mode & 0o077:
            raise RuntimeError(f"secret 파일 권한은 0600이어야 합니다: {secrets_path}")
    scope = f"{config.aws_account_id}-{config.aws_region}-{environment}"
    state_path = INFRA_ROOT / ".state" / f"{scope}.json"
    lock_path = INFRA_ROOT / ".state" / f"{scope}.lock"
    return config, values, LocalState.load(state_path, environment), state_path, lock_path


def _providers(
    config: DeploymentConfig,
    values: dict[str, str],
    *,
    profile: str,
    dry_run: bool = False,
) -> tuple[AwsProvider, RunPodProvider]:
    return (
        AwsProvider(config, profile=profile, infra_root=INFRA_ROOT, dry_run=dry_run),
        RunPodProvider(
            config,
            repository_root=REPOSITORY_ROOT,
            secrets_values=values,
            dry_run=dry_run,
        ),
    )


def _require_runtime_keys(values: dict[str, str], *, operation: str) -> None:
    missing = [key for key in RUNTIME_GENERATED_SECRETS if not values.get(key)]
    if missing:
        raise RuntimeError(
            f"{operation}에 필요한 runtime secret 값이 비어 있습니다: "
            f"{', '.join(missing)}. 최초 생성은 infra-ensure를 사용하세요."
        )


def _ensure_runtime_keys(
    values: dict[str, str],
    secrets_path: Path,
) -> tuple[dict[str, str], set[str]]:
    """누락된 Pod 호출 키를 생성해 로컬 원본에 먼저 원자적으로 바인딩한다."""

    generated = {
        key: secrets.token_urlsafe(48)
        for key in RUNTIME_GENERATED_SECRETS
        if not values.get(key)
    }
    if not generated:
        return values, set()
    update_secret_file(secrets_path, generated)
    return {**values, **generated}, set(generated)


def _clear_runtime_keys(secrets_path: Path) -> None:
    """전체 환경 폐기 후 자동 생성 runtime key 값만 비운다."""

    update_secret_file(
        secrets_path,
        {key: "" for key in RUNTIME_GENERATED_SECRETS},
    )


def _assert_identity(aws: AwsProvider, config: DeploymentConfig) -> None:
    actual = aws.identity()
    if actual != config.aws_account_id:
        raise RuntimeError(
            f"AWS account 불일치: config={config.aws_account_id}, caller={actual}"
        )


def _binding(
    config: DeploymentConfig,
    llm: dict[str, Any],
    embed: dict[str, Any],
) -> dict[str, str]:
    return {
        "vllm_pod_id": str(llm["pod_id"]),
        "vllm_base_url": str(llm["base_url"]),
        "vllm_model": str(llm.get("model_id") or config.runpod_llm_model),
        "vllm_template_id": config.runpod_llm_template_id,
        "embed_pod_id": str(embed["pod_id"]),
        "embed_base_url": str(embed["base_url"]),
        "embed_template_id": config.runpod_embed_template_id,
        "nginx_image": config.nginx_image,
        "origin_domain": config.origin_domain,
    }


def check(environment: str) -> None:
    missing_tools = [
        tool
        for tool in ("git", "docker", "uv", "node", "npm", "aws", "just", "runpodctl")
        if shutil.which(tool) is None
    ]
    if missing_tools:
        raise RuntimeError(f"필수 도구를 찾지 못했습니다: {', '.join(missing_tools)}")
    node_version = subprocess.run(
        ["node", "--version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    node_numbers = tuple(int(item) for item in node_version.lstrip("v").split(".")[:2])
    if node_numbers < (24, 18):
        raise RuntimeError("Node.js 24.18 이상이 필요합니다.")
    subprocess.run(
        ["docker", "compose", "version"],
        check=True,
        capture_output=True,
        text=True,
    )
    config_path, secrets_path, _, _ = _paths(environment)
    if not config_path.exists():
        raise RuntimeError(
            f"{config_path}이 없습니다. prod.example.json을 복사해 작성하세요."
        )
    if not (REPOSITORY_ROOT / "mcp" / "deploy" / "deploy_embed_pod.py").exists():
        raise RuntimeError("MCP submodule이 초기화되지 않았습니다.")
    for private_path in (config_path, secrets_path):
        ignored = subprocess.run(
            ["git", "check-ignore", "--quiet", str(private_path)],
            cwd=REPOSITORY_ROOT,
        )
        if ignored.returncode != 0:
            raise RuntimeError(f"운영 설정이 .gitignore 대상이 아닙니다: {private_path}")
    config, values, _, _, _ = _load(environment, require_secrets=True)
    if any(
        (
            config.aws_account_id == "111122223333",
            "example" in config.github_organization,
            "example" in config.github_repository,
            "example" in config.ghcr_owner,
            "replace-with" in config.runpod_llm_template_id,
            "replace-with" in config.runpod_embed_template_id,
            config.nginx_image.endswith("0" * 64),
        )
    ):
        raise RuntimeError("prod.json에 example placeholder가 남아 있습니다.")
    if not config.runpod_embed_image.endswith(":latest"):
        raise RuntimeError("Embed RunPod image는 latest여야 합니다.")
    print(
        json.dumps(
            {
                "status": "ok",
                "environment": environment,
                "account": config.aws_account_id,
                "region": config.aws_region,
                "node": node_version,
                "python": sys.version.split()[0],
                "secret_keys_present": sorted(REQUIRED_SECRETS & values.keys()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def bootstrap(profile: str, environment: str) -> None:
    config, values, _, _, lock_path = _load(environment, require_secrets=False)
    aws, _ = _providers(config, values, profile=profile)
    _assert_identity(aws, config)
    with operation_lock(lock_path):
        aws.assert_owned_stack("WorkShieldAccess")
        aws.ensure_github_access()
        aws.bootstrap()
        aws.cdk("deploy", ["WorkShieldAccess"])


def status(profile: str, environment: str) -> dict[str, Any]:
    config, values, state, _, _ = _load(environment, require_secrets=True)
    aws, runpod = _providers(config, values, profile=profile)
    _assert_identity(aws, config)
    llm = runpod.status_vllm()
    embed = runpod.status_embed()
    llm_latest = runpod.latest_digest(config.runpod_llm_image)
    embed_latest = runpod.latest_digest(config.runpod_embed_image)
    llm_recorded = state.resources.get("llm", {}).get("image_digest", "unknown")
    embed_recorded = state.resources.get("embed", {}).get("image_digest", "unknown")
    llm["image"] = {
        "reference": config.runpod_llm_image,
        "pod_created_digest": llm_recorded,
        "current_latest_digest": llm_latest,
        "drift": (
            llm_recorded != llm_latest
            if "unknown" not in {llm_recorded, llm_latest}
            else "unknown"
        ),
    }
    embed["image"] = {
        "reference": config.runpod_embed_image,
        "pod_created_digest": embed_recorded,
        "current_latest_digest": embed_latest,
        "drift": (
            embed_recorded != embed_latest
            if "unknown" not in {embed_recorded, embed_latest}
            else "unknown"
        ),
    }
    service_status = aws.stack_status("WorkShieldService")
    cloudfront_domain = (
        aws.stack_output("WorkShieldService", "CloudFrontDomainName")
        if service_status != "NOT_FOUND"
        else ""
    )
    body = {
        "account": config.aws_account_id,
        "region": config.aws_region,
        "environment": environment,
        "stacks": {
            name: service_status if name == "WorkShieldService" else aws.stack_status(name)
            for name in ("WorkShieldAccess", "WorkShieldFoundation", "WorkShieldService")
        },
        "runtime": {
            "ssm_instance": aws.managed_instance_status(),
            "viewer_health": (
                aws.viewer_health(cloudfront_domain)
                if cloudfront_domain
                else "NOT_FOUND"
            ),
        },
        "runpod": {
            "llm": llm,
            "embed": embed,
        },
        "release": {
            "tag": aws.parameter(f"/workshield/{environment}/release/active-tag"),
            "api_image": aws.parameter(
                f"/workshield/{environment}/release/active-api-image"
            ),
            "mcp_image": aws.parameter(
                f"/workshield/{environment}/release/active-mcp-image"
            ),
        },
    }
    print(json.dumps(body, ensure_ascii=False, indent=2))
    return body


def plan(profile: str, environment: str, *, destroy: bool = False) -> None:
    body = status(profile, environment)
    config, values, _, _, _ = _load(environment, require_secrets=True)
    aws, _ = _providers(config, values, profile=profile)
    for stack_name in ("WorkShieldFoundation", "WorkShieldService"):
        aws.assert_owned_stack(stack_name)
    if not destroy:
        aws.cdk("diff", ["WorkShieldFoundation", "WorkShieldService"])
    action = "destroy" if destroy else "ensure"
    print(
        json.dumps(
            {
                "plan": action,
                "target": {
                    "account": body["account"],
                    "region": body["region"],
                    "environment": body["environment"],
                },
                "phases": (
                    ["runpod", "WorkShieldService", "WorkShieldFoundation", "retained-secrets"]
                    if destroy
                    else [
                        "WorkShieldFoundation",
                        "runtime-secrets",
                        "DuckDNS",
                        "RunPod",
                        "runtime-binding",
                        "WorkShieldService",
                        "origin-TLS",
                        "runtime-assets",
                    ]
                ),
                "changes_applied": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def ensure(profile: str, environment: str) -> None:
    config, values, state, state_path, lock_path = _load(
        environment,
        require_secrets=True,
    )
    aws, _ = _providers(config, values, profile=profile)
    _assert_identity(aws, config)
    _, secrets_path, _, _ = _paths(environment)
    with operation_lock(lock_path):
        values, _ = _ensure_runtime_keys(values, secrets_path)
        aws, runpod = _providers(config, values, profile=profile)
        state.begin()
        state.save(state_path)
        created: list[tuple[str, str]] = []
        created_stacks: list[str] = []
        previous_binding = "{}"
        binding_changed = False
        try:
            foundation_before = aws.stack_status("WorkShieldFoundation")
            aws.assert_owned_stack("WorkShieldFoundation")
            aws.cdk("deploy", ["WorkShieldFoundation"])
            if foundation_before == "NOT_FOUND":
                state.record_created("aws", "stack", "WorkShieldFoundation")
                created_stacks.append("WorkShieldFoundation")
            previous_binding = aws.parameter(
                f"/workshield/{environment}/runtime/binding"
            )
            eip = aws.stack_output("WorkShieldFoundation", "OriginElasticIp")
            aws.sync_duckdns(eip, values["DUCKDNS_TOKEN"])

            llm = runpod.ensure_vllm()
            if llm.get("created"):
                created.append(("llm", str(llm["pod_id"])))
                state.record_created("runpod", "llm", str(llm["pod_id"]))
            embed = runpod.ensure_embed()
            if embed.get("created"):
                created.append(("embed", str(embed["pod_id"])))
                state.record_created("runpod", "embed", str(embed["pod_id"]))
            aws.sync_secrets(values)
            aws.put_runtime_binding(_binding(config, llm, embed))
            binding_changed = True

            service_before = aws.stack_status("WorkShieldService")
            aws.assert_owned_stack("WorkShieldService")
            aws.cdk("deploy", ["WorkShieldService"])
            if service_before == "NOT_FOUND":
                state.record_created("aws", "stack", "WorkShieldService")
                created_stacks.append("WorkShieldService")
            aws.provision_origin_tls()
            aws.install_runtime_assets()
            state.resources = {
                "llm": {
                    "id": str(llm["pod_id"]),
                    "image_digest": str(
                        llm.get("image_digest")
                        if llm.get("created")
                        else state.resources.get("llm", {}).get(
                            "image_digest",
                            "unknown",
                        )
                    ),
                },
                "embed": {
                    "id": str(embed["pod_id"]),
                    "image_digest": str(
                        embed.get("image_digest")
                        if embed.get("created")
                        else state.resources.get("embed", {}).get(
                            "image_digest",
                            "unknown",
                        )
                    ),
                },
                "foundation": {"id": "WorkShieldFoundation"},
                "service": {"id": "WorkShieldService"},
            }
            state.complete()
            state.save(state_path)
        except Exception:
            if binding_changed and previous_binding != "NOT_FOUND":
                try:
                    aws.put_runtime_binding_value(previous_binding)
                except Exception as compensation_error:
                    print(
                        f"warning: runtime binding compensation failed: "
                        f"{compensation_error}",
                        file=sys.stderr,
                    )
            for kind, resource_id in reversed(created):
                try:
                    if kind == "llm":
                        runpod.delete_vllm(resource_id, ignore_not_found=True)
                    else:
                        runpod.delete_embed(resource_id, ignore_not_found=True)
                except Exception as compensation_error:
                    print(
                        f"warning: compensation failed for {kind}/{resource_id}: "
                        f"{compensation_error}",
                        file=sys.stderr,
                    )
            for stack_name in reversed(created_stacks):
                try:
                    aws.cdk("destroy", [stack_name])
                except Exception as compensation_error:
                    print(
                        f"warning: compensation failed for AWS stack "
                        f"{stack_name}: {compensation_error}",
                        file=sys.stderr,
                    )
            if "WorkShieldFoundation" in created_stacks:
                try:
                    aws.schedule_secret_deletion()
                except Exception as compensation_error:
                    print(
                        f"warning: secret compensation failed: {compensation_error}",
                        file=sys.stderr,
                    )
            state.save(state_path)
            raise


def destroy(profile: str, environment: str, confirm: str) -> None:
    config, values, state, state_path, lock_path = _load(
        environment,
        require_secrets=True,
    )
    expected = f"DESTROY {config.app_name}"
    if confirm != expected:
        raise RuntimeError(f"확인 문자열이 필요합니다: {expected}")
    aws, runpod = _providers(config, values, profile=profile)
    _assert_identity(aws, config)
    _, secrets_path, _, _ = _paths(environment)
    with operation_lock(lock_path):
        aws.assert_owned_stack("WorkShieldService")
        aws.assert_owned_stack("WorkShieldFoundation")
        embed_id = state.resources.get("embed", {}).get("id")
        llm_id = state.resources.get("llm", {}).get("id")
        runpod.delete_embed(embed_id, ignore_not_found=True)
        runpod.delete_vllm(llm_id, ignore_not_found=True)
        # 직전 교체의 cleanup 실패로 소유권이 확인된 이전 Pod가 하나 남았을
        # 수 있으므로 active ID 제거 후 결정적 이름으로 한 번 더 재발견한다.
        runpod.delete_embed(ignore_not_found=True)
        runpod.delete_vllm(ignore_not_found=True)
        aws.cdk("destroy", ["WorkShieldService", "WorkShieldFoundation"])
        aws.schedule_secret_deletion()
        _clear_runtime_keys(secrets_path)
        state.resources = {}
        state.complete()
        state.save(state_path)


def purge(profile: str, environment: str, confirm: str) -> None:
    config, values, _, _, lock_path = _load(environment, require_secrets=False)
    expected = f"PURGE {config.app_name}-bootstrap"
    if confirm != expected:
        raise RuntimeError(f"확인 문자열이 필요합니다: {expected}")
    aws, _ = _providers(config, values, profile=profile)
    _assert_identity(aws, config)
    with operation_lock(lock_path):
        aws.assert_owned_stack("WorkShieldAccess")
        aws.purge_bootstrap()


def secrets_sync(profile: str, environment: str) -> None:
    config, values, _, _, lock_path = _load(environment, require_secrets=True)
    _require_runtime_keys(values, operation="secret 동기화")
    aws, _ = _providers(config, values, profile=profile)
    _assert_identity(aws, config)
    with operation_lock(lock_path):
        aws.sync_secrets(values)


def runpod_replace(target: str, profile: str, environment: str) -> None:
    config, values, state, state_path, lock_path = _load(
        environment,
        require_secrets=True,
    )
    _require_runtime_keys(values, operation="RunPod 교체")
    aws, runpod = _providers(config, values, profile=profile)
    _assert_identity(aws, config)
    with operation_lock(lock_path):
        state.begin()
        state.save(state_path)
        old_llm = runpod.status_vllm()
        old_embed = runpod.status_embed()
        llm = old_llm
        embed = old_embed
        candidates: list[tuple[str, str]] = []
        committed = False
        try:
            if target in {"llm", "all"}:
                llm = runpod.ensure_vllm(replace=True)
                candidates.append(("llm", str(llm["pod_id"])))
                state.record_created("runpod", "llm", str(llm["pod_id"]))
            if target in {"embed", "all"}:
                embed = runpod.ensure_embed(replace=True)
                candidates.append(("embed", str(embed["pod_id"])))
                state.record_created("runpod", "embed", str(embed["pod_id"]))
            state.save(state_path)
            aws.put_runtime_binding(_binding(config, llm, embed))
            aws.reapply_active_release()
            committed = True
            for kind, candidate_id in candidates:
                previous = llm.get("previous_pod_id") if kind == "llm" else embed.get("previous_pod_id")
                if previous and previous != candidate_id:
                    if kind == "llm":
                        runpod.delete_vllm(str(previous), ignore_not_found=True)
                    else:
                        runpod.delete_embed(str(previous), ignore_not_found=True)
            state.resources["llm"] = {
                "id": str(llm["pod_id"]),
                "image_digest": str(llm.get("image_digest", "unknown")),
            }
            state.resources["embed"] = {
                "id": str(embed["pod_id"]),
                "image_digest": str(embed.get("image_digest", "unknown")),
            }
            state.complete()
            state.save(state_path)
        except Exception as error:
            if committed:
                state.resources["llm"] = {
                    "id": str(llm["pod_id"]),
                    "image_digest": str(llm.get("image_digest", "unknown")),
                }
                state.resources["embed"] = {
                    "id": str(embed["pod_id"]),
                    "image_digest": str(embed.get("image_digest", "unknown")),
                }
                state.complete()
                state.save(state_path)
                raise RuntimeError(
                    "새 RunPod binding은 활성화됐지만 기존 Pod 정리가 실패했습니다. "
                    "infra-status로 잔존 Pod를 확인하세요."
                ) from error
            if old_llm.get("pod_id") and old_embed.get("pod_id"):
                try:
                    aws.put_runtime_binding(_binding(config, old_llm, old_embed))
                    aws.reapply_active_release()
                except Exception:
                    pass
            compensated = True
            for kind, candidate_id in reversed(candidates):
                try:
                    if kind == "llm":
                        runpod.delete_vllm(candidate_id, ignore_not_found=True)
                    else:
                        runpod.delete_embed(candidate_id, ignore_not_found=True)
                except Exception:
                    compensated = False
            if compensated:
                state.complete()
                state.save(state_path)
            raise


def github_configure(profile: str, environment: str, github_environment: str) -> None:
    config, values, _, _, _ = _load(environment, require_secrets=False)
    if github_environment != config.github_environment:
        raise RuntimeError(
            "GitHub Environment가 OIDC trust config와 일치하지 않습니다."
        )
    aws, _ = _providers(config, values, profile=profile)
    _assert_identity(aws, config)
    variables = {
        "AWS_REGION": config.aws_region,
        "AWS_DEPLOY_ROLE_ARN": aws.stack_output(
            "WorkShieldAccess", "GitHubDeployRoleArn"
        ),
        "SSM_DOCUMENT_NAME": aws.stack_output(
            "WorkShieldService", "DeployDocumentName"
        ),
        "WEB_BUCKET": aws.stack_output("WorkShieldService", "WebBucketName"),
        "CLOUDFRONT_DISTRIBUTION_ID": aws.stack_output(
            "WorkShieldService", "CloudFrontDistributionId"
        ),
        "GHCR_OWNER": config.ghcr_owner,
    }
    repository = f"{config.github_organization}/{config.github_repository}"
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GitHub Environment 설정에는 로컬 GH_TOKEN이 필요합니다.")
    base_url = (
        "https://api.github.com/repos/"
        f"{urllib.parse.quote(repository, safe='/')}/environments/"
        f"{urllib.parse.quote(github_environment, safe='')}"
    )

    def request(method: str, url: str, body: dict[str, str] | None = None) -> int:
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        api_request = urllib.request.Request(
            url,
            data=payload,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(api_request, timeout=30) as response:
                return response.status
        except urllib.error.HTTPError as error:
            if method == "GET" and error.code == 404:
                return 404
            raise RuntimeError(f"GitHub API 요청 실패: HTTP {error.code}") from error

    request("PUT", base_url)
    for name, value in variables.items():
        variable_url = f"{base_url}/variables/{urllib.parse.quote(name, safe='')}"
        operation = "PATCH" if request("GET", variable_url) == 200 else "POST"
        target = variable_url if operation == "PATCH" else f"{base_url}/variables"
        request(operation, target, {"name": name, "value": value})


def rotate_secret(name: str, profile: str, environment: str) -> None:
    """Pod 호출 키를 pending→candidate→current→consumer health 순서로 회전한다."""
    supported = {
        "vllm": "VLLM_API_KEY",
        "embed": "RUNPOD_EMBED_API_KEY",
    }
    if name not in supported:
        raise RuntimeError(
            "자동 회전은 vllm과 embed 호출 키만 지원합니다. "
            "외부 발급 secret은 값을 갱신한 뒤 infra-secrets-sync를 사용하세요."
        )
    config, old_values, state, state_path, lock_path = _load(
        environment,
        require_secrets=True,
    )
    _, secrets_path, _, _ = _paths(environment)
    _require_runtime_keys(old_values, operation="secret 회전")
    key = supported[name]
    new_value = secrets.token_urlsafe(48)
    new_values = {**old_values, key: new_value}
    aws, runpod = _providers(config, new_values, profile=profile)
    _assert_identity(aws, config)
    with operation_lock(lock_path):
        old_runpod = RunPodProvider(
            config,
            repository_root=REPOSITORY_ROOT,
            secrets_values=old_values,
        )
        old_llm = old_runpod.status_vllm()
        old_embed = old_runpod.status_embed()
        pending, previous = aws.stage_secret(name, key, new_value)
        promoted = False
        binding_changed = False
        committed = False
        candidate: dict[str, Any] | None = None
        try:
            candidate = (
                runpod.ensure_vllm(replace=True)
                if name == "vllm"
                else runpod.ensure_embed(replace=True)
            )
            llm = candidate if name == "vllm" else old_llm
            embed = candidate if name == "embed" else old_embed
            aws.promote_secret(
                name,
                pending_version=pending,
                current_version=previous,
            )
            promoted = True
            aws.put_runtime_binding(_binding(config, llm, embed))
            binding_changed = True
            aws.reapply_active_release()
            aws.discard_pending_secret(name, pending)
            update_secret_file(secrets_path, {key: new_value})
            state.resources["llm" if name == "vllm" else "embed"] = {
                "id": str(candidate["pod_id"]),
                "image_digest": str(candidate.get("image_digest", "unknown")),
            }
            state.complete()
            state.save(state_path)
            committed = True
            old_id = (
                old_llm.get("pod_id") if name == "vllm" else old_embed.get("pod_id")
            )
            if old_id:
                if name == "vllm":
                    runpod.delete_vllm(str(old_id), ignore_not_found=True)
                else:
                    runpod.delete_embed(str(old_id), ignore_not_found=True)
        except Exception as error:
            if committed:
                raise RuntimeError(
                    "새 secret과 candidate는 활성화됐지만 기존 Pod 정리가 "
                    "실패했습니다. infra-status로 잔존 Pod를 확인하세요."
                ) from error
            if promoted:
                try:
                    aws.restore_secret(
                        name,
                        previous_version=previous,
                        failed_version=pending,
                    )
                except Exception:
                    pass
            else:
                try:
                    aws.discard_pending_secret(name, pending)
                except Exception:
                    pass
            if binding_changed and old_llm.get("pod_id") and old_embed.get("pod_id"):
                try:
                    aws.put_runtime_binding(_binding(config, old_llm, old_embed))
                    aws.reapply_active_release()
                except Exception:
                    pass
            if candidate and candidate.get("pod_id"):
                try:
                    if name == "vllm":
                        runpod.delete_vllm(
                            str(candidate["pod_id"]),
                            ignore_not_found=True,
                        )
                    else:
                        runpod.delete_embed(
                            str(candidate["pod_id"]),
                            ignore_not_found=True,
                        )
                except Exception:
                    pass
            raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("check",):
        child = subparsers.add_parser(name)
        child.add_argument("--environment", default="prod")
    for name in (
        "bootstrap",
        "plan",
        "ensure",
        "status",
        "destroy-plan",
        "secrets-sync",
    ):
        child = subparsers.add_parser(name)
        child.add_argument("--profile", required=True)
        child.add_argument("--environment", default="prod")
    child = subparsers.add_parser("destroy")
    child.add_argument("--profile", required=True)
    child.add_argument("--environment", default="prod")
    child.add_argument("--confirm", required=True)
    child = subparsers.add_parser("purge")
    child.add_argument("--profile", required=True)
    child.add_argument("--environment", default="prod")
    child.add_argument("--confirm", required=True)
    child = subparsers.add_parser("runpod-replace")
    child.add_argument("target", choices=("llm", "embed", "all"))
    child.add_argument("--profile", required=True)
    child.add_argument("--environment", default="prod")
    child = subparsers.add_parser("github-configure")
    child.add_argument("--profile", required=True)
    child.add_argument("--environment", default="prod")
    child.add_argument("--github-environment", default="production")
    child = subparsers.add_parser("secrets-rotate")
    child.add_argument("name")
    child.add_argument("--profile", required=True)
    child.add_argument("--environment", default="prod")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "check":
            check(args.environment)
        elif args.command == "bootstrap":
            bootstrap(args.profile, args.environment)
        elif args.command == "plan":
            plan(args.profile, args.environment)
        elif args.command == "ensure":
            ensure(args.profile, args.environment)
        elif args.command == "status":
            status(args.profile, args.environment)
        elif args.command == "destroy-plan":
            plan(args.profile, args.environment, destroy=True)
        elif args.command == "destroy":
            destroy(args.profile, args.environment, args.confirm)
        elif args.command == "purge":
            purge(args.profile, args.environment, args.confirm)
        elif args.command == "secrets-sync":
            secrets_sync(args.profile, args.environment)
        elif args.command == "secrets-rotate":
            rotate_secret(args.name, args.profile, args.environment)
        elif args.command == "runpod-replace":
            runpod_replace(args.target, args.profile, args.environment)
        elif args.command == "github-configure":
            github_configure(
                args.profile,
                args.environment,
                args.github_environment,
            )
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
