"""서버 생성 storage key를 사용하는 로컬 임시 파일 저장소."""

import os
import re
import secrets
import shutil
import tempfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, ContextManager


_EXTENSION_PATTERN = re.compile(r"[a-z0-9]{1,10}")
_STORAGE_KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]{40,}\.[a-z0-9]{1,10}")


class LocalFileStorage:
    """저장 루트와 실제 경로 연산을 내부에 캡슐화한다."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        for incomplete_upload in self._root.glob(".upload-*"):
            if incomplete_upload.is_file():
                incomplete_upload.unlink(missing_ok=True)

    def _path_for(self, storage_key: str) -> Path:
        if (
            Path(storage_key).name != storage_key
            or _STORAGE_KEY_PATTERN.fullmatch(storage_key) is None
        ):
            raise ValueError("유효하지 않은 storage key입니다.")
        return self._root / storage_key

    def save(self, source: BinaryIO, *, extension: str) -> str:
        """입력을 임시 파일에 기록한 뒤 원자적으로 최종 위치에 저장한다."""
        normalized_extension = extension.lower().removeprefix(".")
        if _EXTENSION_PATTERN.fullmatch(normalized_extension) is None:
            raise ValueError("유효하지 않은 파일 확장자입니다.")

        storage_key = (
            f"{secrets.token_urlsafe(32)}.{normalized_extension}"
        )
        destination = self._path_for(storage_key)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self._root,
                prefix=".upload-",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                shutil.copyfileobj(source, temporary)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, destination)
            temporary_path = None
            return storage_key
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    @contextmanager
    def open(self, storage_key: str) -> Iterator[BinaryIO]:
        """storage key에 해당하는 파일을 읽기 전용으로 연다."""
        with self._path_for(storage_key).open("rb") as stored_file:
            yield stored_file

    def delete(self, storage_key: str) -> None:
        """파일이 이미 없어도 성공하는 멱등 삭제를 수행한다."""
        self._path_for(storage_key).unlink(missing_ok=True)

    def list_keys(self) -> Iterable[str]:
        """정리 작업이 비교할 수 있는 유효한 storage key를 반환한다."""
        return tuple(
            path.name
            for path in self._root.iterdir()
            if path.is_file()
            and _STORAGE_KEY_PATTERN.fullmatch(path.name) is not None
        )

    def local_path(self, storage_key: str) -> ContextManager[Path]:
        """stdio MCP에 필요한 경로를 저장소가 통제하는 컨텍스트로 제공한다."""

        @contextmanager
        def managed_path() -> Iterator[Path]:
            path = self._path_for(storage_key)
            if not path.is_file():
                raise FileNotFoundError(storage_key)
            yield path

        return managed_path()
