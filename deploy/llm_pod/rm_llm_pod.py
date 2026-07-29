#!/usr/bin/env python3
"""명시 Pod ID 또는 AWS 상태로 vLLM Pod을 멱등 삭제한다."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

PREFIX = "/workshield/{environment}/runpod/llm"


def _aws(args: list[str]) -> str:
    return subprocess.run(["aws", *args], check=True, capture_output=True, text=True).stdout.strip()


def _state_id(environment: str) -> str | None:
    try:
        body = json.loads(_aws(["ssm", "get-parameter", "--name", f"{PREFIX.format(environment=environment)}/pod-id", "--output", "json"]))
        return body["Parameter"]["Value"]
    except (subprocess.CalledProcessError, KeyError, json.JSONDecodeError):
        return None


def _local_id() -> str | None:
    path = Path(__file__).resolve().parents[2] / "api" / ".env"
    if not path.exists():
        return None
    match = re.search(r"^VLLM_BASE_URL=['\"]?https?://([A-Za-z0-9]+)-8000\\.proxy\\.runpod\\.net", path.read_text(encoding="utf-8"), re.MULTILINE)
    return match.group(1) if match else None


def _clear_local_state() -> None:
    path = Path(__file__).resolve().parents[2] / "api" / ".env"
    if not path.exists():
        return
    keys = {"VLLM_BASE_URL", "VLLM_API_KEY", "LLM_MODEL"}
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text(
        "\n".join(line for line in lines if line.partition("=")[0].strip() not in keys) + "\n",
        encoding="utf-8",
    )


def _not_found(result: subprocess.CompletedProcess[str]) -> bool:
    return "not found" in f"{result.stdout}\n{result.stderr}".lower()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pod-id")
    parser.add_argument("--state-backend", choices=("local", "aws"), default="local")
    parser.add_argument("--environment", default="prod")
    parser.add_argument("--ignore-not-found", action="store_true")
    parser.add_argument("--wait", action="store_true")
    args = parser.parse_args()
    pod_id = args.pod_id or (_state_id(args.environment) if args.state_backend == "aws" else _local_id())
    if not pod_id:
        # 상태 파일이 없거나 이미 수동으로 삭제된 경우도 멱등 성공으로 취급한다.
        return 0
    runpodctl = shutil.which("runpodctl")
    if not runpodctl:
        print("runpodctl을 찾을 수 없습니다.", file=sys.stderr)
        return 2
    result = subprocess.run([runpodctl, "pod", "delete", pod_id], capture_output=True, text=True)
    if result.returncode and not (args.ignore_not_found and _not_found(result)):
        print(result.stderr or result.stdout, file=sys.stderr)
        return result.returncode
    if args.state_backend == "aws":
        for key in ("pod-id", "base-url", "model-id", "template-id", "last-provision-run-id"):
            subprocess.run(["aws", "ssm", "delete-parameter", "--name", f"{PREFIX.format(environment=args.environment)}/{key}"], capture_output=True)
        for key in ("base-url", "model"):
            subprocess.run(["aws", "ssm", "delete-parameter", "--name", f"/workshield/{args.environment}/vllm/{key}"], capture_output=True)
    else:
        _clear_local_state()
    print(json.dumps({"pod_id": pod_id, "deleted": result.returncode == 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
