"""LocalFileStorage의 경로 격리와 멱등 동작을 검증한다."""

from io import BytesIO
from pathlib import Path

import pytest

from app.core.storage.local import LocalFileStorage


def test_storage_uses_server_key_and_can_open_file(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path / "uploads")

    key = storage.save(BytesIO(b"contract"), extension=".pdf")

    assert "contract" not in key
    assert key.endswith(".pdf")
    assert list(storage.list_keys()) == [key]
    with storage.open(key) as stored:
        assert stored.read() == b"contract"


def test_delete_is_idempotent(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path / "uploads")
    key = storage.save(BytesIO(b"contract"), extension="pdf")

    storage.delete(key)
    storage.delete(key)

    assert list(storage.list_keys()) == []


def test_startup_removes_incomplete_upload(tmp_path: Path) -> None:
    root = tmp_path / "uploads"
    root.mkdir()
    incomplete = root / ".upload-interrupted"
    incomplete.write_bytes(b"partial")

    LocalFileStorage(root)

    assert incomplete.exists() is False


@pytest.mark.parametrize("key", ["../secret.pdf", "nested/file.pdf", "bad key.pdf"])
def test_storage_rejects_path_traversal(tmp_path: Path, key: str) -> None:
    storage = LocalFileStorage(tmp_path / "uploads")

    with pytest.raises(ValueError):
        storage.delete(key)
