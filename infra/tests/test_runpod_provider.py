import io
import json
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

from workshield_infra.config import DeploymentConfig
from workshield_infra.llm_presets import MODEL_PRESETS
from workshield_infra.providers.runpod import RunPodProvider


def _config() -> DeploymentConfig:
    return DeploymentConfig(
        app_name="workshield-prod",
        environment="prod",
        aws_account_id="111122223333",
        aws_region="ap-northeast-2",
        availability_zone="ap-northeast-2a",
        origin_domain="workshield.duckdns.org",
        acme_email="infra@example.com",
        cloudfront_origin_prefix_list_id="pl-1234",
        instance_type="t3.small",
        github_organization="example",
        github_owner_id="123456",
        github_repository_id="654321",
        github_repository="repository",
        github_environment="production",
        ghcr_owner="example",
        nginx_image=f"nginx@sha256:{'0' * 64}",
        runpod_llm_image="vllm/vllm-openai:latest",
        runpod_llm_template_id="llm-template",
        runpod_llm_gpu="NVIDIA A40",
        runpod_llm_model="RedHatAI/Qwen3.5-9B-FP8-dynamic",
        runpod_embed_template_id="embed-template",
        runpod_embed_gpu="NVIDIA RTX 2000 Ada",
        runpod_embed_image="ghcr.io/example/mcp/embed-rerank:latest",
    )


def _provider() -> RunPodProvider:
    return RunPodProvider(
        _config(),
        repository_root=Path("/repository"),
        secrets_values={
            "RUNPOD_MANAGEMENT_API_KEY": "management",
            "VLLM_API_KEY": "model-key",
            "RUNPOD_EMBED_API_KEY": "embed-key",
        },
    )


def test_status_refuses_same_name_with_unknown_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider()
    monkeypatch.setattr(
        provider,
        "_pods",
        lambda: [
            {
                "id": "pod-1",
                "name": "workshield-prod-llm",
                "templateId": "someone-elses-template",
                "gpuDisplayName": "NVIDIA A40",
            }
        ],
    )

    with pytest.raises(RuntimeError, match="소유권"):
        provider.status_vllm()


def test_replacement_candidate_does_not_delete_previous_before_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider()
    monkeypatch.setattr(
        provider,
        "_pods",
        lambda: [
            {
                "id": "old-pod",
                "name": "workshield-prod-llm",
                "templateId": "llm-template",
                "gpuDisplayName": "NVIDIA A40",
                "desiredStatus": "RUNNING",
                "imageName": "vllm/vllm-openai:latest",
                "ports": ["8000/http"],
            }
        ],
    )
    commands: list[list[str]] = []

    def create(command: list[str]) -> dict[str, str]:
        commands.append(command)
        return {"id": "candidate-pod"}

    monkeypatch.setattr(provider, "_json", create)
    monkeypatch.setattr(provider, "_wait_vllm", lambda _url: None)
    monkeypatch.setattr(provider, "latest_digest", lambda _image: "sha256:new")
    deleted: list[str] = []
    monkeypatch.setattr(
        provider,
        "delete_vllm",
        lambda pod_id, ignore_not_found=False: deleted.append(pod_id),
    )

    candidate = provider.ensure_vllm(replace=True)

    assert candidate["pod_id"] == "candidate-pod"
    assert candidate["previous_pod_id"] == "old-pod"
    assert deleted == []
    create_command = commands[0]
    docker_args_index = create_command.index("--docker-args") + 1
    assert (
        create_command[docker_args_index]
        == MODEL_PRESETS["qwen3.5-9B-FP8-dynamic"]
    )


def test_status_accepts_rest_identity_when_gpu_name_is_not_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider()
    monkeypatch.setattr(
        provider,
        "_pods",
        lambda: [
            {
                "id": "pod-1",
                "name": "workshield-prod-llm",
                "templateId": "llm-template",
                "imageName": "vllm/vllm-openai:latest",
                "ports": ["8000/http"],
                "desiredStatus": "RUNNING",
                "gpuCount": 1,
            }
        ],
    )

    status = provider.status_vllm()

    assert status["pod_id"] == "pod-1"
    assert status["status"] == "RUNNING"


class _Response:
    def __init__(self, body: dict[str, object]) -> None:
        self.body = json.dumps(body).encode()
        self.status = 200

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def test_vllm_health_uses_user_agent_and_requires_anonymous_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider()
    requests: list[object] = []

    def urlopen(request: object, timeout: int) -> _Response:
        requests.append(request)
        if request.get_header("Authorization"):  # type: ignore[attr-defined]
            return _Response({"data": [{"id": "model"}]})
        raise urllib.error.HTTPError(
            "https://pod/v1/models",
            401,
            "Unauthorized",
            {},
            io.BytesIO(b'{"error":"Unauthorized"}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    provider._wait_vllm("https://pod", timeout=1)

    assert len(requests) == 2
    assert all(
        request.get_header("User-agent") == "workshield-infra/1.0"  # type: ignore[attr-defined]
        for request in requests
    )


def test_vllm_health_reports_cloudflare_1010_without_retrying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider()
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            urllib.error.HTTPError(
                "https://pod/v1/models",
                403,
                "Forbidden",
                {},
                io.BytesIO(b"error code: 1010\n"),
            )
        ),
    )
    monkeypatch.setattr(
        "time.sleep",
        lambda _seconds: pytest.fail("Cloudflare 1010은 재시도하면 안 됩니다."),
    )

    with pytest.raises(RuntimeError, match="Cloudflare 1010"):
        provider._wait_vllm("https://pod", timeout=1)


def test_vllm_creation_requires_parent_bound_runtime_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider()
    provider.secrets["VLLM_API_KEY"] = ""
    monkeypatch.setattr(provider, "status_vllm", lambda: {"status": "NOT_FOUND"})

    with pytest.raises(RuntimeError, match="VLLM_API_KEY가 바인딩되지"):
        provider.ensure_vllm()


def test_embed_creation_requires_parent_bound_runtime_key() -> None:
    provider = _provider()
    provider.secrets["RUNPOD_EMBED_API_KEY"] = ""

    with pytest.raises(RuntimeError, match="RUNPOD_EMBED_API_KEY가 바인딩되지"):
        provider.ensure_embed()


def test_embed_status_uses_parent_bound_runtime_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider()
    captured_environment: dict[str, str] = {}

    def run(
        _command: list[str],
        **kwargs: object,
    ) -> SimpleNamespace:
        captured_environment.update(kwargs["env"])  # type: ignore[arg-type]
        return SimpleNamespace(stdout='{"status":"NOT_FOUND"}')

    monkeypatch.setattr("subprocess.run", run)

    assert provider.status_embed()["status"] == "NOT_FOUND"
    assert captured_environment["RUNPOD_EMBED_API_KEY"] == "embed-key"
