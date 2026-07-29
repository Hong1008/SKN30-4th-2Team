from pathlib import Path
from types import SimpleNamespace

import pytest

from workshield_infra import tasks
from workshield_infra.config import load_secret_file
from workshield_infra.state import LocalState


def _secret_file(path: Path) -> Path:
    path.write_text(
        "# local source\n"
        "RUNPOD_MANAGEMENT_API_KEY=management\n"
        "VLLM_API_KEY=\n"
        "RUNPOD_EMBED_API_KEY=\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def test_missing_runtime_keys_are_generated_and_atomically_bound(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = _secret_file(tmp_path / "prod.secrets.env")
    generated_values = iter(("generated-vllm", "generated-embed"))
    monkeypatch.setattr(
        tasks.secrets,
        "token_urlsafe",
        lambda _length: next(generated_values),
    )

    values, generated = tasks._ensure_runtime_keys(
        load_secret_file(path),
        path,
    )

    assert generated == {"VLLM_API_KEY", "RUNPOD_EMBED_API_KEY"}
    assert values["VLLM_API_KEY"] == "generated-vllm"
    assert values["RUNPOD_EMBED_API_KEY"] == "generated-embed"
    assert load_secret_file(path) == values
    assert path.stat().st_mode & 0o777 == 0o600


def test_existing_runtime_key_is_reused_without_rotation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = _secret_file(tmp_path / "prod.secrets.env")
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "VLLM_API_KEY=",
            "VLLM_API_KEY=existing-vllm",
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        tasks.secrets,
        "token_urlsafe",
        lambda _length: "generated-embed",
    )

    values, generated = tasks._ensure_runtime_keys(
        load_secret_file(path),
        path,
    )

    assert generated == {"RUNPOD_EMBED_API_KEY"}
    assert values["VLLM_API_KEY"] == "existing-vllm"
    assert values["RUNPOD_EMBED_API_KEY"] == "generated-embed"


class _DestroyAws:
    def __init__(self) -> None:
        self.secret_deletion_scheduled = False

    def identity(self) -> str:
        return "111122223333"

    def assert_owned_stack(self, _name: str) -> None:
        return None

    def cdk(self, _action: str, _stacks: list[str]) -> None:
        return None

    def schedule_secret_deletion(self) -> None:
        self.secret_deletion_scheduled = True


class _DestroyRunPod:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def delete_embed(
        self,
        _pod_id: str | None = None,
        *,
        ignore_not_found: bool,
    ) -> None:
        if self.fail:
            raise RuntimeError("delete failed")

    def delete_vllm(
        self,
        _pod_id: str | None = None,
        *,
        ignore_not_found: bool,
    ) -> None:
        return None


def _prepare_destroy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    fail: bool,
) -> tuple[Path, _DestroyAws]:
    secrets_path = _secret_file(tmp_path / "prod.secrets.env")
    secrets_path.write_text(
        secrets_path.read_text(encoding="utf-8")
        .replace("VLLM_API_KEY=", "VLLM_API_KEY=vllm")
        .replace("RUNPOD_EMBED_API_KEY=", "RUNPOD_EMBED_API_KEY=embed"),
        encoding="utf-8",
    )
    state_path = tmp_path / "state.json"
    lock_path = tmp_path / "state.lock"
    config = SimpleNamespace(
        app_name="workshield-prod",
        aws_account_id="111122223333",
    )
    state = LocalState(
        environment="prod",
        resources={
            "llm": {"id": "llm-pod"},
            "embed": {"id": "embed-pod"},
        },
    )
    aws = _DestroyAws()
    runpod = _DestroyRunPod(fail=fail)
    monkeypatch.setattr(
        tasks,
        "_load",
        lambda _environment, require_secrets: (
            config,
            load_secret_file(secrets_path),
            state,
            state_path,
            lock_path,
        ),
    )
    monkeypatch.setattr(
        tasks,
        "_paths",
        lambda _environment: (
            tmp_path / "prod.json",
            secrets_path,
            state_path,
            lock_path,
        ),
    )
    monkeypatch.setattr(
        tasks,
        "_providers",
        lambda *_args, **_kwargs: (aws, runpod),
    )
    return secrets_path, aws


def test_destroy_clears_runtime_keys_only_after_teardown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secrets_path, aws = _prepare_destroy(monkeypatch, tmp_path, fail=False)

    tasks.destroy("profile", "prod", "DESTROY workshield-prod")

    values = load_secret_file(secrets_path)
    assert aws.secret_deletion_scheduled
    assert values["VLLM_API_KEY"] == ""
    assert values["RUNPOD_EMBED_API_KEY"] == ""
    assert values["RUNPOD_MANAGEMENT_API_KEY"] == "management"


def test_destroy_failure_preserves_runtime_keys(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secrets_path, aws = _prepare_destroy(monkeypatch, tmp_path, fail=True)

    with pytest.raises(RuntimeError, match="delete failed"):
        tasks.destroy("profile", "prod", "DESTROY workshield-prod")

    values = load_secret_file(secrets_path)
    assert not aws.secret_deletion_scheduled
    assert values["VLLM_API_KEY"] == "vllm"
    assert values["RUNPOD_EMBED_API_KEY"] == "embed"
