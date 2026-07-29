from pathlib import Path

import pytest

from workshield_infra.state import LocalState, operation_lock


def test_state_journal_is_atomic_cache_not_ownership_source(tmp_path: Path) -> None:
    path = tmp_path / "prod.json"
    state = LocalState(environment="prod")
    state.begin()
    state.record_created("runpod", "llm", "pod-1")
    state.save(path)

    loaded = LocalState.load(path, "prod")

    assert loaded.created_in_run == [
        {"provider": "runpod", "kind": "llm", "id": "pod-1"}
    ]
    assert not path.with_suffix(".tmp").exists()


def test_operation_lock_refuses_concurrent_writer(tmp_path: Path) -> None:
    path = tmp_path / "account-region-prod.lock"

    with operation_lock(path), pytest.raises(RuntimeError, match="실행 중"):
        with operation_lock(path):
            pass

    assert not path.exists()
