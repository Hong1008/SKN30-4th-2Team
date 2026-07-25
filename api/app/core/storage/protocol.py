"""Application Service가 의존할 파일 저장소 계약."""

from collections.abc import Iterable
from pathlib import Path
from typing import BinaryIO, ContextManager, Protocol


class FileStorage(Protocol):
    """실제 파일 경로를 호출자에게 노출하지 않는 저장소."""

    def save(self, source: BinaryIO, *, extension: str) -> str: ...

    def open(self, storage_key: str) -> ContextManager[BinaryIO]: ...

    def delete(self, storage_key: str) -> None: ...

    def list_keys(self) -> Iterable[str]: ...

    def local_path(self, storage_key: str) -> ContextManager[Path]: ...
