"""부모 저장소의 vLLM lifecycle과 MCP submodule adapter."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from workshield_infra.config import DeploymentConfig
from workshield_infra.llm_presets import resolve_model_preset

HTTP_USER_AGENT = "workshield-infra/1.0"
RUNPOD_REST_API = "https://rest.runpod.io/v1"


class RunPodCommandError(RuntimeError):
    def __init__(self, result: subprocess.CalledProcessError) -> None:
        super().__init__("RunPod CLI 명령이 실패했습니다.")
        self.stdout = result.stdout or ""
        self.stderr = result.stderr or ""


class RunPodNotFoundError(RuntimeError):
    """관리 대상 Pod가 이미 사라진 경우다."""


class RunPodProvider:
    def __init__(
        self,
        config: DeploymentConfig,
        *,
        repository_root: Path,
        secrets_values: dict[str, str],
        dry_run: bool = False,
    ) -> None:
        self.config = config
        self.repository_root = repository_root
        self.secrets = secrets_values
        self.dry_run = dry_run
        self.runpodctl = shutil.which("runpodctl") or "runpodctl"

    def _environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        management_key = self.secrets.get("RUNPOD_MANAGEMENT_API_KEY", "")
        if management_key:
            environment["RUNPOD_MANAGEMENT_API_KEY"] = management_key
            environment["RUNPOD_API_KEY"] = management_key
        return environment

    def _json(self, command: list[str]) -> Any:
        try:
            result = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                env=self._environment(),
            )
        except subprocess.CalledProcessError as error:
            raise RunPodCommandError(error) from error
        return json.loads(result.stdout)

    def _pods(self) -> list[dict[str, Any]]:
        body = self._rest_json("/pods")
        if not isinstance(body, list):
            raise RuntimeError("RunPod REST Pod 목록 응답이 배열이 아닙니다.")
        return [pod for pod in body if isinstance(pod, dict)]

    def _rest_json(self, path: str) -> Any:
        management_key = self.secrets.get("RUNPOD_MANAGEMENT_API_KEY")
        if not management_key:
            raise RuntimeError("RunPod REST 조회에는 관리 API key가 필요합니다.")
        request = urllib.request.Request(
            f"{RUNPOD_REST_API}{path}",
            headers={
                "Authorization": f"Bearer {management_key}",
                "Accept": "application/json",
                "User-Agent": HTTP_USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            if error.code == 404:
                raise RunPodNotFoundError(path) from error
            raise RuntimeError(
                f"RunPod REST 조회 실패: HTTP {error.code}, path={path}"
            ) from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise RuntimeError(f"RunPod REST 조회 실패: path={path}") from error

    def _pod(self, pod_id: str) -> dict[str, Any]:
        body = self._rest_json(f"/pods/{urllib.parse.quote(pod_id, safe='')}")
        if not isinstance(body, dict):
            raise RuntimeError("RunPod REST Pod 상세 응답이 객체가 아닙니다.")
        return body

    @staticmethod
    def latest_digest(image: str) -> str:
        """registry 조회가 가능한 경우 mutable tag의 현재 digest를 반환한다."""

        result = subprocess.run(
            ["docker", "buildx", "imagetools", "inspect", image],
            capture_output=True,
            text=True,
        )
        if result.returncode:
            return "unknown"
        for line in result.stdout.splitlines():
            label, _, value = line.strip().partition(":")
            if label == "Digest" and value.strip().startswith("sha256:"):
                return value.strip()
        return "unknown"

    def _vllm_candidates(self) -> list[dict[str, Any]]:
        name = f"{self.config.app_name}-llm"
        return [pod for pod in self._pods() if self._pod_name(pod) == name]

    @staticmethod
    def _gpu_name(pod: dict[str, Any]) -> str:
        machine = pod.get("machine") if isinstance(pod.get("machine"), dict) else {}
        return str(
            pod.get("gpuDisplayName")
            or pod.get("gpuTypeId")
            or pod.get("gpuType")
            or machine.get("gpuDisplayName")
            or machine.get("gpuTypeId")
            or ""
        )

    @staticmethod
    def _normalized_gpu(value: str) -> str:
        return (
            "".join(character.lower() for character in value if character.isalnum())
            .replace("nvidia", "")
            .replace("generation", "")
        )

    @staticmethod
    def _template_id(pod: dict[str, Any]) -> str:
        template = pod.get("template") if isinstance(pod.get("template"), dict) else {}
        return str(pod.get("templateId") or template.get("id") or "")

    @staticmethod
    def _pod_name(pod: dict[str, Any]) -> str:
        return str(pod.get("name") or pod.get("podName") or "")

    def _assert_vllm_owned(
        self,
        pod: dict[str, Any],
        *,
        pod_id: str | None = None,
    ) -> None:
        """REST가 제공하는 immutable 식별자를 모두 확인하고 불일치를 중단한다."""

        mismatches: list[str] = []
        actual_id = str(pod.get("id") or "")
        if pod_id is not None and actual_id != pod_id:
            mismatches.append(f"pod-id={actual_id or '<unknown>'}")
        actual_name = self._pod_name(pod)
        if actual_name != f"{self.config.app_name}-llm":
            mismatches.append(f"name={actual_name or '<unknown>'}")
        actual_template = self._template_id(pod)
        if actual_template != self.config.runpod_llm_template_id:
            mismatches.append(f"template-id={actual_template or '<unknown>'}")
        actual_image = str(pod.get("imageName") or pod.get("image") or "")
        if actual_image != self.config.runpod_llm_image:
            mismatches.append(f"image={actual_image or '<unknown>'}")
        ports = pod.get("ports")
        if isinstance(ports, list) and "8000/http" not in ports:
            mismatches.append("port=8000/http-missing")
        actual_gpu = self._gpu_name(pod)
        if actual_gpu and self._normalized_gpu(actual_gpu) != self._normalized_gpu(
            self.config.runpod_llm_gpu
        ):
            mismatches.append(f"gpu={actual_gpu}")
        if mismatches:
            raise RuntimeError(
                "vLLM Pod 소유권 또는 immutable 설정을 확인하지 못했습니다: "
                + ", ".join(mismatches)
            )

    def status_vllm(self) -> dict[str, str]:
        if self.dry_run:
            return {"status": "PLAN", "name": f"{self.config.app_name}-llm"}
        candidates = self._vllm_candidates()
        if len(candidates) > 1:
            raise RuntimeError("동일한 결정적 이름의 vLLM Pod가 둘 이상입니다.")
        if not candidates:
            return {"status": "NOT_FOUND"}
        pod = candidates[0]
        self._assert_vllm_owned(pod)
        return {
            "status": str(pod.get("desiredStatus") or pod.get("status") or "UNKNOWN"),
            "pod_id": str(pod["id"]),
            "base_url": f"https://{pod['id']}-8000.proxy.runpod.net",
            "model_id": self.config.runpod_llm_model,
            "template_id": self.config.runpod_llm_template_id,
        }

    def ensure_vllm(self, *, replace: bool = False) -> dict[str, str]:
        current = self.status_vllm()
        if current.get("status") == "RUNNING" and not replace:
            self._wait_vllm(current["base_url"])
            current["created"] = False
            current["image_digest"] = "unknown"
            return current
        if current.get("pod_id") and not replace:
            raise RuntimeError("기존 vLLM Pod가 원하는 RUNNING 상태가 아닙니다. 명시적 교체가 필요합니다.")
        if self.dry_run:
            print(f"PLAN ensure RunPod vLLM {self.config.app_name}-llm")
            return {
                "status": "PLAN",
                "pod_id": "planned",
                "base_url": "https://planned-8000.proxy.runpod.net",
                "model_id": self.config.runpod_llm_model,
                "template_id": self.config.runpod_llm_template_id,
                "created": True,
                "previous_pod_id": str(current.get("pod_id") or ""),
                "image_digest": self.latest_digest(self.config.runpod_llm_image),
            }
        api_key = self.secrets.get("VLLM_API_KEY")
        if not api_key:
            raise RuntimeError(
                "VLLM_API_KEY가 바인딩되지 않았습니다. 부모 infra-ensure로 생성하세요."
            )
        docker_args = resolve_model_preset(self.config.runpod_llm_model)
        pod_environment = {"VLLM_API_KEY": api_key}
        if self.secrets.get("HUGGING_FACE_TOKEN"):
            pod_environment["HUGGING_FACE_TOKEN"] = self.secrets[
                "HUGGING_FACE_TOKEN"
            ]
        payload = self._json(
            [
                self.runpodctl,
                "pod",
                "create",
                "--template-id",
                self.config.runpod_llm_template_id,
                "--gpu-id",
                self.config.runpod_llm_gpu,
                "--name",
                f"{self.config.app_name}-llm",
                "--env",
                json.dumps(pod_environment),
                "--docker-args",
                docker_args,
                "-o",
                "json",
            ]
        )
        candidate = {
            "status": "RUNNING",
            "pod_id": str(payload["id"]),
            "base_url": f"https://{payload['id']}-8000.proxy.runpod.net",
            "model_id": self.config.runpod_llm_model,
            "template_id": self.config.runpod_llm_template_id,
            "previous_pod_id": str(current.get("pod_id") or ""),
            "created": True,
            "image_digest": self.latest_digest(self.config.runpod_llm_image),
        }
        try:
            self._wait_vllm(candidate["base_url"])
        except Exception:
            subprocess.run(
                [self.runpodctl, "pod", "delete", candidate["pod_id"]],
                env=self._environment(),
                check=False,
                capture_output=True,
            )
            raise
        return candidate

    def _wait_vllm(self, base_url: str, timeout: int = 900) -> None:
        key = self.secrets["VLLM_API_KEY"]
        endpoint = f"{base_url}/v1/models"
        started_at = time.monotonic()
        deadline = started_at + timeout
        delay = 2.0
        last_status = "endpoint 연결 대기"
        while time.monotonic() < deadline:
            authenticated = urllib.request.Request(
                endpoint,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Accept": "application/json",
                    "User-Agent": HTTP_USER_AGENT,
                },
            )
            try:
                with urllib.request.urlopen(authenticated, timeout=10) as response:
                    body = json.loads(response.read())
                if not body.get("data"):
                    last_status = "인증 응답의 model 목록이 비어 있음"
                    raise ValueError(last_status)
                anonymous = urllib.request.Request(
                    endpoint,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": HTTP_USER_AGENT,
                    },
                )
                try:
                    with urllib.request.urlopen(anonymous, timeout=10):
                        pass
                except urllib.error.HTTPError as error:
                    if error.code in {401, 403}:
                        detail = error.read(256).decode(
                            "utf-8",
                            "replace",
                        ).strip()
                        if "error code: 1010" in detail:
                            raise RuntimeError(
                                "RunPod proxy가 무인증 health check를 "
                                "Cloudflare 1010으로 차단했습니다."
                            ) from error
                        return
                    last_status = f"무인증 요청 HTTP {error.code}"
                    raise
                raise RuntimeError("vLLM 무인증 요청이 허용되었습니다.")
            except urllib.error.HTTPError as error:
                detail = error.read(256).decode("utf-8", "replace").strip()
                if error.code in {401, 403} and "error code: 1010" in detail:
                    raise RuntimeError(
                        "RunPod proxy가 health check 요청을 Cloudflare 1010으로 "
                        "차단했습니다."
                    ) from error
                if error.code in {401, 403}:
                    raise RuntimeError(
                        f"vLLM 인증 요청이 HTTP {error.code}으로 거부되었습니다."
                    ) from error
                last_status = f"HTTP {error.code}"
            except (
                urllib.error.URLError,
                TimeoutError,
                json.JSONDecodeError,
                ValueError,
            ) as error:
                last_status = str(error) or type(error).__name__
            elapsed = int(time.monotonic() - started_at)
            print(
                f"vLLM readiness 대기 중: {elapsed}s, 최근 상태={last_status}",
                file=sys.stderr,
            )
            time.sleep(min(delay, max(0.0, deadline - time.monotonic())))
            delay = min(delay * 1.5, 15.0)
        raise TimeoutError(
            f"vLLM readiness timeout: {timeout}s, 최근 상태={last_status}"
        )

    def delete_vllm(self, pod_id: str | None = None, *, ignore_not_found: bool = False) -> None:
        if self.dry_run:
            print(f"PLAN delete RunPod vLLM {pod_id or f'{self.config.app_name}-llm'}")
            return
        if pod_id:
            target = pod_id
            try:
                pod = self._pod(target)
            except RunPodNotFoundError:
                if ignore_not_found:
                    return
                raise
            self._assert_vllm_owned(pod, pod_id=target)
        else:
            current = self.status_vllm()
            target = current.get("pod_id")
        if not target:
            if ignore_not_found:
                return
            raise RuntimeError("삭제할 vLLM Pod를 찾지 못했습니다.")
        result = subprocess.run(
            [self.runpodctl, "pod", "delete", target],
            env=self._environment(),
            capture_output=True,
            text=True,
        )
        if result.returncode and not (
            ignore_not_found and "not found" in f"{result.stdout}\n{result.stderr}".lower()
        ):
            raise RuntimeError(result.stderr or result.stdout)

    def _embed_command(self, *, status: bool = False, dry_run: bool = False) -> list[str]:
        command = [
            sys.executable,
            str(self.repository_root / "mcp" / "deploy" / "deploy_embed_pod.py"),
            "--environment",
            self.config.environment,
            "--name",
            f"{self.config.app_name}-embed",
            "--template-id",
            self.config.runpod_embed_template_id,
            "--gpu",
            self.config.runpod_embed_gpu,
            "--output",
            "json",
            "--no-env-file",
            "--wait",
        ]
        if status:
            command.append("--status")
        if dry_run:
            command.append("--dry-run")
        return command

    def _embed_environment(self) -> dict[str, str]:
        environment = self._environment()
        api_key = self.secrets.get("RUNPOD_EMBED_API_KEY")
        if api_key:
            environment["RUNPOD_EMBED_API_KEY"] = api_key
        return environment

    def ensure_embed(self, *, replace: bool = False) -> dict[str, str]:
        if not self.secrets.get("RUNPOD_EMBED_API_KEY"):
            raise RuntimeError(
                "RUNPOD_EMBED_API_KEY가 바인딩되지 않았습니다. "
                "부모 infra-ensure로 생성하세요."
            )
        current = self.status_embed() if replace else {}
        command = self._embed_command(dry_run=self.dry_run)
        if replace:
            command.append("--replace")
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            env=self._embed_environment(),
        )
        output = json.loads(result.stdout or '{"status":"PLAN"}')
        output["previous_pod_id"] = current.get("pod_id") or ""
        output["image_digest"] = (
            self.latest_digest(self.config.runpod_embed_image)
            if output.get("created")
            else "unknown"
        )
        return output

    def status_embed(self) -> dict[str, str]:
        if self.dry_run:
            return {"status": "PLAN"}
        result = subprocess.run(
            self._embed_command(status=True),
            check=True,
            capture_output=True,
            text=True,
            env=self._embed_environment(),
        )
        return json.loads(result.stdout)

    def delete_embed(
        self,
        pod_id: str | None = None,
        *,
        ignore_not_found: bool = False,
    ) -> None:
        command = [
            sys.executable,
            str(self.repository_root / "mcp" / "deploy" / "rm_embed_pod.py"),
            "--environment",
            self.config.environment,
            "--name",
            f"{self.config.app_name}-embed",
            "--template-id",
            self.config.runpod_embed_template_id,
            "--gpu",
            self.config.runpod_embed_gpu,
            "--output",
            "json",
            "--no-env-file",
        ]
        if pod_id:
            command.extend(["--pod-id", pod_id])
        if ignore_not_found:
            command.append("--ignore-not-found")
        if self.dry_run:
            command.append("--dry-run")
        subprocess.run(command, check=True, env=self._environment())
