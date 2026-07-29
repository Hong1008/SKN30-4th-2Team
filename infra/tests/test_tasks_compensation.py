from pathlib import Path
from types import SimpleNamespace

import pytest

from workshield_infra import tasks
from workshield_infra.state import LocalState


class FakeAws:
    def identity(self) -> str:
        return "111122223333"

    def stack_status(self, _name: str) -> str:
        return "UPDATE_COMPLETE"

    def assert_owned_stack(self, _name: str) -> None:
        return None

    def cdk(self, _action: str, _stacks: list[str]) -> None:
        return None

    def sync_secrets(self, _values: dict[str, str]) -> None:
        return None

    def parameter(self, _name: str) -> str:
        return "{}"

    def stack_output(self, _stack: str, _key: str) -> str:
        return "203.0.113.10"

    def sync_duckdns(self, _ip: str, _token: str) -> None:
        return None


class FakeRunPod:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def ensure_vllm(self) -> dict[str, object]:
        return {
            "created": True,
            "pod_id": "created-this-run",
            "base_url": "https://example",
            "model_id": "model",
        }

    def ensure_embed(self) -> dict[str, object]:
        raise RuntimeError("candidate failed")

    def delete_vllm(self, pod_id: str, *, ignore_not_found: bool) -> None:
        assert ignore_not_found
        self.deleted.append(pod_id)

    def delete_embed(self, _pod_id: str, *, ignore_not_found: bool) -> None:
        raise AssertionError("생성되지 않은 Embed Pod를 보상 삭제하면 안 됩니다.")


def test_ensure_compensates_only_resource_created_in_current_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = SimpleNamespace(
        aws_account_id="111122223333",
        aws_region="ap-northeast-2",
        environment="prod",
    )
    state_path = tmp_path / "state.json"
    lock_path = tmp_path / "state.lock"
    state = LocalState(environment="prod")
    runpod = FakeRunPod()
    monkeypatch.setattr(
        tasks,
        "_load",
        lambda _environment, require_secrets: (
            config,
            {
                "DUCKDNS_TOKEN": "secret",
                "VLLM_API_KEY": "vllm-key",
                "RUNPOD_EMBED_API_KEY": "embed-key",
            },
            state,
            state_path,
            lock_path,
        ),
    )
    monkeypatch.setattr(
        tasks,
        "_providers",
        lambda *_args, **_kwargs: (FakeAws(), runpod),
    )

    with pytest.raises(RuntimeError, match="candidate failed"):
        tasks.ensure("profile", "prod")

    assert runpod.deleted == ["created-this-run"]
    assert LocalState.load(state_path, "prod").created_in_run == [
        {"provider": "runpod", "kind": "llm", "id": "created-this-run"}
    ]
