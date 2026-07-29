#!/usr/bin/env python3
"""RunPod vLLM Pod을 로컬 또는 AWS 상태 backend에 멱등 생성한다."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

TEMPLATE_ID = "6o2zycj91k"
PARAMETER_PREFIX = "/workshield/{environment}/runpod/llm"
COMMON_ARGS = "--host 0.0.0.0 --port 8000 --enforce-eager --gpu-memory-utilization 0.90 --max-model-len 8128"
MODEL_PRESETS = {
    "qwen3.5-9B-FP8-dynamic": f"RedHatAI/Qwen3.5-9B-FP8-dynamic --language-model-only --reasoning-parser qwen3 {COMMON_ARGS}",
    "gemma-4-12B-it-FP8-Dynamic": f"RedHatAI/gemma-4-12B-it-FP8-Dynamic --reasoning-parser gemma4 {COMMON_ARGS}",
    "EXAONE-3.5-7.8B-Instruct": f"LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct --dtype bfloat16 --trust-remote-code {COMMON_ARGS}",
}


def _aws(args: list[str]) -> str:
    return subprocess.run(["aws", *args], check=True, capture_output=True, text=True).stdout.strip()


def _parameter(name: str, environment: str) -> str:
    return f"{PARAMETER_PREFIX.format(environment=environment)}/{name}"


def _get_state(environment: str) -> dict[str, str]:
    names = [_parameter(key, environment) for key in ("pod-id", "base-url", "model-id", "template-id", "last-provision-run-id")]
    try:
        body = json.loads(_aws(["ssm", "get-parameters", "--names", *names, "--output", "json"]))
    except subprocess.CalledProcessError:
        return {}
    return {item["Name"].rsplit("/", 1)[-1]: item["Value"] for item in body.get("Parameters", [])}


def _put_state(values: dict[str, str], environment: str) -> None:
    for key, value in values.items():
        _aws(["ssm", "put-parameter", "--name", _parameter(key, environment), "--value", value, "--type", "String", "--overwrite"])


def _local_env_path() -> Path:
    return Path(__file__).resolve().parents[2] / "api" / ".env"


def _local_state() -> dict[str, str]:
    path = _local_env_path()
    if not path.exists():
        return {}
    values = {
        key.strip(): value.strip().strip("'\"")
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
        for key, _, value in (line.partition("="),)
    }
    base_url = values.get("VLLM_BASE_URL", "")
    pod_id = base_url.removeprefix("https://").split("-8000.proxy.runpod.net", 1)[0]
    if not pod_id or "-8000.proxy.runpod.net" not in base_url:
        return {}
    return {
        "pod-id": pod_id,
        "base-url": base_url,
        "model-id": values.get("LLM_MODEL", ""),
        "api-key": values.get("VLLM_API_KEY", ""),
    }


def _update_local_env(values: dict[str, str]) -> None:
    path = _local_env_path()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = [line for line in lines if line.partition("=")[0].strip() not in values]
    path.write_text("\n".join([*remaining, *(f"{k}='{v}'" for k, v in values.items())]) + "\n", encoding="utf-8")


def _runpod_json(command: list[str]) -> dict[str, Any]:
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def _pod_is_usable(runpodctl: str, pod_id: str) -> bool:
    try:
        body = _runpod_json([runpodctl, "pod", "get", pod_id, "-o", "json"])
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return False
    return str(body.get("desiredStatus") or body.get("status") or "").upper() == "RUNNING"


def _wait_ready(base_url: str, api_key: str, timeout: int) -> str:
    import urllib.error
    import urllib.request

    deadline = time.monotonic() + timeout
    delay = 2.0
    while time.monotonic() < deadline:
        request = urllib.request.Request(f"{base_url}/v1/models", headers={"Authorization": f"Bearer {api_key}"})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = json.loads(response.read())
            models = body.get("data", [])
            if models and models[0].get("id"):
                try:
                    urllib.request.urlopen(f"{base_url}/v1/models", timeout=10)
                except urllib.error.HTTPError as error:
                    if error.code in (401, 403):
                        return str(models[0]["id"])
                    raise RuntimeError(f"vLLM 무인증 요청이 {error.code}으로 거부되었습니다.") from error
                raise RuntimeError("vLLM 무인증 요청이 허용되었습니다.")
        except Exception:
            time.sleep(delay)
            delay = min(delay * 2, 15)
    raise TimeoutError("vLLM readiness timeout")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="qwen3.5-9B-FP8-dynamic", choices=MODEL_PRESETS)
    parser.add_argument("--gpu", default="NVIDIA A40")
    parser.add_argument("--output", choices=("text", "json"), default="text")
    parser.add_argument("--state-backend", choices=("local", "aws"), default="local")
    parser.add_argument("--environment", default="prod")
    parser.add_argument("--name", default="workshield-prod-llm")
    parser.add_argument("--custom-args", default="", help="프리셋 대신 사용할 vLLM Docker 실행 인자")
    parser.add_argument("--no-env-file", action="store_true")
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args()
    runpodctl = shutil.which("runpodctl")
    if not runpodctl:
        print("runpodctl을 찾을 수 없습니다.", file=sys.stderr)
        return 2
    state = _get_state(args.environment) if args.state_backend == "aws" else _local_state()
    api_key = os.getenv("VLLM_API_KEY") or state.get("api-key", "")
    if state.get("pod-id") and _pod_is_usable(runpodctl, state["pod-id"]):
        model_id = state.get("model-id", "")
        if args.wait:
            if not api_key:
                print("기존 vLLM Pod readiness 확인에 VLLM_API_KEY가 필요합니다.", file=sys.stderr)
                return 2
            try:
                model_id = _wait_ready(state.get("base-url", ""), api_key, args.timeout_seconds)
            except Exception:
                print("기존 vLLM Pod가 readiness 검증을 통과하지 못했습니다.", file=sys.stderr)
                return 1
        output = {"pod_id": state["pod-id"], "base_url": state.get("base-url", ""), "model_id": model_id, "created": False}
        print(json.dumps(output) if args.output == "json" else f"기존 Pod 재사용: {output['pod_id']}")
        return 0
    api_key = api_key or secrets.token_hex(32)
    docker_args = args.custom_args or MODEL_PRESETS[args.model]
    command = [runpodctl, "pod", "create", "--template-id", TEMPLATE_ID, "--gpu-id", args.gpu, "--name", args.name, "--env", json.dumps({"VLLM_API_KEY": api_key}), "--docker-args", docker_args, "-o", "json"]
    pod_id: str | None = None
    try:
        payload = _runpod_json(command)
        pod_id = str(payload["id"])
        base_url = f"https://{pod_id}-8000.proxy.runpod.net"
        model_id = args.model
        if args.wait:
            model_id = _wait_ready(base_url, api_key, args.timeout_seconds)
        state_values = {
            "pod-id": pod_id,
            "base-url": base_url,
            "model-id": model_id,
            "template-id": TEMPLATE_ID,
            "last-provision-run-id": os.getenv("GITHUB_RUN_ID", "manual"),
        }
        if args.state_backend == "aws":
            _put_state(state_values, args.environment)
        elif not args.no_env_file:
            _update_local_env({"VLLM_BASE_URL": base_url, "VLLM_API_KEY": api_key, "LLM_MODEL": model_id})
        output = {"pod_id": pod_id, "base_url": base_url, "model_id": model_id, "created": True}
        print(json.dumps(output) if args.output == "json" else f"Pod 생성 완료: {pod_id}")
        return 0
    except Exception:
        if pod_id:
            # 기존 상태는 건드리지 않고, 이번 실행에서 만든 Pod만 정리한다.
            subprocess.run([runpodctl, "pod", "delete", pod_id], capture_output=True, text=True)
        print("vLLM Pod 생성 실패", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
