"""로컬 state cache, 실행 journal, 동시 실행 lock을 관리한다."""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


@dataclass(slots=True)
class LocalState:
    """소유권 원장이 아닌 재발견 보조 cache다."""

    environment: str
    resources: dict[str, dict[str, str]] = field(default_factory=dict)
    created_in_run: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path, environment: str) -> "LocalState":
        if not path.exists():
            return cls(environment=environment)
        body = json.loads(path.read_text(encoding="utf-8"))
        if body.get("environment") != environment:
            raise RuntimeError("state environment가 요청 환경과 일치하지 않습니다.")
        return cls(
            environment=environment,
            resources=body.get("resources", {}),
            created_in_run=body.get("created_in_run", []),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "environment": self.environment,
                    "resources": self.resources,
                    "created_in_run": self.created_in_run,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)

    def begin(self) -> None:
        self.created_in_run = []

    def record_created(self, provider: str, kind: str, resource_id: str) -> None:
        self.created_in_run.append(
            {"provider": provider, "kind": kind, "id": resource_id}
        )

    def complete(self) -> None:
        self.created_in_run = []


@contextmanager
def operation_lock(path: Path, *, stale_seconds: int = 6 * 60 * 60) -> Iterator[None]:
    """원자적 파일 생성으로 계정·환경 단위 동시 실행을 차단한다."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and time.time() - path.stat().st_mtime > stale_seconds:
        path.unlink()
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise RuntimeError(f"다른 인프라 작업이 실행 중입니다: {path}") from error
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode())
        os.close(descriptor)
        yield
    finally:
        path.unlink(missing_ok=True)
