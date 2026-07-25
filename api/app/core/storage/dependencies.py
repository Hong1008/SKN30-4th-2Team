"""FastAPI에서 공유 FileStorage를 주입한다."""

from typing import Annotated, cast

from fastapi import Depends, Request

from app.core.storage.protocol import FileStorage


async def get_file_storage(request: Request) -> FileStorage:
    """lifespan에서 준비한 FileStorage를 반환한다."""
    storage = getattr(request.app.state, "file_storage", None)
    if storage is None:
        raise RuntimeError("FileStorage가 준비되지 않았습니다.")
    return cast(FileStorage, storage)


FileStorageDep = Annotated[FileStorage, Depends(get_file_storage)]
