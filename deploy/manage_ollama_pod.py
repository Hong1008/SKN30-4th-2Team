#!/usr/bin/env python3
"""A5000 Ollama Pod 이미지·Template·Pod 생명주기를 관리한다.

모든 설정은 api/.env에서 읽고, 생성된 Template/Pod ID는 출력만 한다.
비용을 멈추려면 stop이 아닌 delete 명령을 사용해야 한다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final


ROOT: Final = Path(__file__).resolve().parents[1]
ENV_FILE: Final = ROOT / "api" / ".env"
DOCKER_CONTEXT: Final = ROOT / "deploy" / "ollama-pod"
SERVERLESS_DOCKER_CONTEXT: Final = ROOT / "deploy" / "ollama-serverless"
DEFAULTS: Final = {
    "RUNPOD_OLLAMA_TEMPLATE_NAME": "workshield-ollama-qwen35-9b",
    "RUNPOD_OLLAMA_POD_NAME": "workshield-ollama-qwen35-9b",
    "RUNPOD_OLLAMA_GPU_ID": "NVIDIA RTX A5000",
    "RUNPOD_OLLAMA_CLOUD_TYPE": "COMMUNITY",
    "RUNPOD_OLLAMA_CONTAINER_DISK_GB": "30",
    "RUNPOD_OLLAMA_MODEL": "hf.co/unsloth/Qwen3.5-9B-GGUF:Q4_K_M",
    "RUNPOD_OLLAMA_AUTO_TERMINATE_MINUTES": "0",
    "RUNPOD_OLLAMA_SERVERLESS_TEMPLATE_NAME": "workshield-ollama-qwen35-9b-serverless",
    "RUNPOD_OLLAMA_SERVERLESS_ENDPOINT_NAME": "workshield-ollama-qwen35-9b",
    "RUNPOD_OLLAMA_SERVERLESS_GPU_ID": "NVIDIA RTX A5000",
    "RUNPOD_OLLAMA_SERVERLESS_WORKERS_MIN": "0",
    "RUNPOD_OLLAMA_SERVERLESS_WORKERS_MAX": "1",
    "RUNPOD_OLLAMA_SERVERLESS_IDLE_TIMEOUT_SECONDS": "5",
    "RUNPOD_OLLAMA_SERVERLESS_EXECUTION_TIMEOUT_SECONDS": "600",
}


def load_environment() -> None:
    """api/.env의 Pod 배포 설정을 현재 환경에 없는 경우에 적용한다."""
    if not ENV_FILE.exists():
        return
    for line_number, raw_line in enumerate(ENV_FILE.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        key, separator, raw_value = line.partition("=")
        key = key.strip()
        if not separator or not key.startswith("RUNPOD_"):
            continue
        try:
            values = shlex.split(raw_value.strip(), posix=True)
        except ValueError as error:
            raise ValueError(f"{ENV_FILE}:{line_number}의 RUNPOD 환경변수 형식이 올바르지 않습니다.") from error
        os.environ.setdefault(key, "" if not values else values[0])


def setting(name: str, *, required: bool = False) -> str:
    value = os.getenv(name, DEFAULTS.get(name, "")).strip()
    if required and not value:
        raise ValueError(f"{name}이 필요합니다. {ENV_FILE}에 설정하세요.")
    return value


def require_command(command: str) -> None:
    if shutil.which(command) is None:
        raise RuntimeError(f"{command}을 찾을 수 없습니다. 설치 후 PATH에 추가하세요.")


def run(command: list[str], *, confirm: bool = False) -> str:
    """명령을 안전하게 실행하고 stdout JSON을 그대로 반환한다."""
    print(shlex.join(command))
    if not confirm:
        return ""
    completed = subprocess.run(command, check=True, capture_output=True, text=True, env=os.environ.copy())
    if completed.stdout.strip():
        print(completed.stdout.strip())
    return completed.stdout


def resource_id(output: str, resource_name: str) -> str | None:
    """Runpod CLI JSON 응답에서 Template 또는 Pod ID를 찾는다."""
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    for field in ("id", f"{resource_name}Id", f"{resource_name}_id"):
        value = payload.get(field)
        if isinstance(value, str) and value:
            return value
    nested = payload.get(resource_name)
    if isinstance(nested, dict) and isinstance(nested.get("id"), str):
        return nested["id"]
    return None


def auto_terminate_argument() -> list[str]:
    minutes = int(setting("RUNPOD_OLLAMA_AUTO_TERMINATE_MINUTES"))
    if minutes <= 0:
        return []
    deadline = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=minutes)
    return ["--terminate-after", deadline.strftime("%Y-%m-%dT%H:%M:%SZ")]


def template_create_command() -> list[str]:
    template_env = json.dumps({"OLLAMA_MODEL": setting("RUNPOD_OLLAMA_MODEL")})
    return [
        "runpodctl", "template", "create",
        "--name", setting("RUNPOD_OLLAMA_TEMPLATE_NAME"),
        "--image", setting("RUNPOD_OLLAMA_IMAGE", required=True),
        "--ports", "11434/http",
        "--container-disk-in-gb", setting("RUNPOD_OLLAMA_CONTAINER_DISK_GB"),
        "--env", template_env,
        "--readme", "Local Ollama Qwen3.5 9B validation Pod. Public proxy has no application authentication; delete after use.",
    ]


def pod_create_command() -> list[str]:
    command = [
        "runpodctl", "pod", "create",
        "--template-id", setting("RUNPOD_OLLAMA_TEMPLATE_ID", required=True),
        "--name", setting("RUNPOD_OLLAMA_POD_NAME"),
        "--gpu-id", setting("RUNPOD_OLLAMA_GPU_ID"),
        "--cloud-type", setting("RUNPOD_OLLAMA_CLOUD_TYPE"),
        "--gpu-count", "1",
        "--ssh=false",
    ]
    registry_auth_id = setting("RUNPOD_OLLAMA_REGISTRY_AUTH_ID")
    if registry_auth_id:
        command.extend(["--registry-auth-id", registry_auth_id])
    command.extend(auto_terminate_argument())
    return command


def pod_id() -> str:
    return setting("RUNPOD_OLLAMA_POD_ID", required=True)


def serverless_template_create_command() -> list[str]:
    return [
        "runpodctl", "template", "create",
        "--name", setting("RUNPOD_OLLAMA_SERVERLESS_TEMPLATE_NAME"),
        "--image", setting("RUNPOD_OLLAMA_SERVERLESS_IMAGE", required=True),
        "--serverless",
        "--container-disk-in-gb", setting("RUNPOD_OLLAMA_CONTAINER_DISK_GB"),
        "--env", json.dumps({"OLLAMA_MODEL": setting("RUNPOD_OLLAMA_MODEL")}),
        "--readme", "RunPod Serverless Ollama Qwen3.5 9B worker. Authenticate calls with a restricted RunPod API key.",
    ]


def serverless_create_command(template_id: str | None = None) -> list[str]:
    return [
        "runpodctl", "serverless", "create",
        "--name", setting("RUNPOD_OLLAMA_SERVERLESS_ENDPOINT_NAME"),
        "--template-id", template_id or setting("RUNPOD_OLLAMA_SERVERLESS_TEMPLATE_ID", required=True),
        "--gpu-id", setting("RUNPOD_OLLAMA_SERVERLESS_GPU_ID"),
        "--gpu-count", "1",
        "--workers-min", setting("RUNPOD_OLLAMA_SERVERLESS_WORKERS_MIN"),
        "--workers-max", setting("RUNPOD_OLLAMA_SERVERLESS_WORKERS_MAX"),
        "--idle-timeout", setting("RUNPOD_OLLAMA_SERVERLESS_IDLE_TIMEOUT_SECONDS"),
        "--execution-timeout", setting("RUNPOD_OLLAMA_SERVERLESS_EXECUTION_TIMEOUT_SECONDS"),
    ]


def serverless_endpoint_id() -> str:
    return setting("RUNPOD_OLLAMA_ENDPOINT_ID", required=True)


def require_runpod_api_key() -> None:
    setting("RUNPOD_API_KEY", required=True)


def serverless_deploy(*, confirm: bool) -> None:
    """운영 시연용 이미지·Serverless Template·Endpoint를 한 번에 만든다."""
    image = setting("RUNPOD_OLLAMA_SERVERLESS_IMAGE", required=True)
    run(serverless_docker_build_command(image), confirm=confirm)
    run(["docker", "push", image], confirm=confirm)
    template_output = run(serverless_template_create_command(), confirm=confirm)
    template_id = resource_id(template_output, "template")
    if not template_id:
        if confirm:
            raise RuntimeError("Serverless Template ID를 응답에서 찾지 못했습니다.")
        return
    endpoint_output = run(serverless_create_command(template_id), confirm=True)
    endpoint_id = resource_id(endpoint_output, "endpoint")
    if endpoint_id:
        print(f"\n생성된 Serverless Endpoint ID: {endpoint_id}")
        print("api/.env의 RUNPOD_OLLAMA_ENDPOINT_ID에 직접 기록하세요.")


def serverless_docker_build_command(image: str) -> list[str]:
    return [
        "docker", "build", "--platform", "linux/amd64",
        "--build-arg", f"OLLAMA_MODEL={setting('RUNPOD_OLLAMA_MODEL')}",
        "--tag", image, str(SERVERLESS_DOCKER_CONTEXT),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "build", "push", "template-create", "pod-create", "pod-list", "pod-info", "pod-stop", "pod-delete",
            "serverless-build", "serverless-push", "serverless-template-create", "serverless-create",
            "serverless-list", "serverless-info", "serverless-delete", "serverless-deploy",
        ),
    )
    parser.add_argument("--confirm", action="store_true", help="유료·외부 상태 변경 명령을 실제 실행합니다.")
    args = parser.parse_args()
    load_environment()

    try:
        if args.action in {"build", "push", "serverless-build", "serverless-push"}:
            require_command("docker")
            is_serverless = args.action.startswith("serverless-")
            image = setting(
                "RUNPOD_OLLAMA_SERVERLESS_IMAGE" if is_serverless else "RUNPOD_OLLAMA_IMAGE",
                required=True,
            )
            command = (
                serverless_docker_build_command(image)
                if is_serverless and args.action.endswith("build")
                else ["docker", "build", "--platform", "linux/amd64", "--tag", image, str(DOCKER_CONTEXT)]
                if args.action.endswith("build") else ["docker", "push", image]
            )
            run(command, confirm=args.confirm)
            return 0

        require_command("runpodctl")
        if args.action.startswith("serverless-"):
            require_runpod_api_key()
            if args.action == "serverless-template-create":
                output = run(serverless_template_create_command(), confirm=args.confirm)
                template_id = resource_id(output, "template")
                if template_id:
                    print(f"\n생성된 Serverless Template ID: {template_id}")
                    print("api/.env의 RUNPOD_OLLAMA_SERVERLESS_TEMPLATE_ID에 직접 기록하세요.")
                return 0
            if args.action == "serverless-create":
                output = run(serverless_create_command(), confirm=args.confirm)
                endpoint_id = resource_id(output, "endpoint")
                if endpoint_id:
                    print(f"\n생성된 Serverless Endpoint ID: {endpoint_id}")
                    print("api/.env의 RUNPOD_OLLAMA_ENDPOINT_ID에 직접 기록하세요.")
                return 0
            if args.action == "serverless-list":
                run(["runpodctl", "serverless", "list"], confirm=True)
                return 0
            if args.action == "serverless-info":
                run(["runpodctl", "serverless", "get", serverless_endpoint_id()], confirm=True)
                return 0
            if args.action == "serverless-delete":
                run(["runpodctl", "serverless", "delete", serverless_endpoint_id()], confirm=args.confirm)
                return 0
            if args.action == "serverless-deploy":
                require_command("docker")
                serverless_deploy(confirm=args.confirm)
                return 0
        if args.action == "template-create":
            output = run(template_create_command(), confirm=args.confirm)
            template_id = resource_id(output, "template")
            if template_id:
                print(f"\n생성된 Template ID: {template_id}")
                print("api/.env의 RUNPOD_OLLAMA_TEMPLATE_ID에 직접 기록하세요.")
            return 0
        if args.action == "pod-create":
            output = run(pod_create_command(), confirm=args.confirm)
            created_pod_id = resource_id(output, "pod")
            if created_pod_id:
                print(f"\n생성된 Pod ID: {created_pod_id}")
                print("api/.env의 RUNPOD_OLLAMA_POD_ID에 직접 기록하세요.")
                print(f"Ollama URL: https://{created_pod_id}-11434.proxy.runpod.net")
            return 0
        if args.action == "pod-list":
            run(["runpodctl", "pod", "list", "--all"], confirm=True)
            return 0
        if args.action == "pod-info":
            run(["runpodctl", "pod", "get", pod_id()], confirm=True)
            return 0
        if args.action == "pod-stop":
            run(["runpodctl", "pod", "stop", pod_id()], confirm=args.confirm)
            return 0
        if args.action == "pod-delete":
            run(["runpodctl", "pod", "delete", pod_id()], confirm=args.confirm)
            return 0
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
