"""사용자 파일의 실제 경로를 숨기는 임시 파일 저장소."""

from app.core.storage.local import LocalFileStorage
from app.core.storage.protocol import FileStorage

__all__ = ["FileStorage", "LocalFileStorage"]
