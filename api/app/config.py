"""환경별 설정과 FastAPI 의존성 provider를 정의한다."""

import json
import os
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, cast

from fastapi import Depends
from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


API_ROOT = Path(__file__).resolve().parent.parent
Environment = Literal["local", "prod"]
class LLMProvider(StrEnum):
    """지원하는 LLM 공급자 식별자."""

    OPENAI = "openai"
    GEMINI = "gemini"
    OLLAMA = "ollama"
    RUNPOD_SERVERLESS = "runpod_serverless"
    VLLM = "vllm"


class MCPTransport(StrEnum):
    """WorkShield MCP 서버 연결 방식."""

    STREAMABLE_HTTP = "streamable_http"
    STDIO = "stdio"


def _selected_environment() -> Environment:
    """프로세스 환경으로 공개 기본 설정 파일을 고른다."""
    environment = os.getenv("APP_ENV", "local").lower()
    if environment not in {"local", "prod"}:
        raise ValueError("APP_ENV는 'local' 또는 'prod'여야 합니다.")
    return cast(Environment, environment)


def _environment_files() -> tuple[Path, Path]:
    """공개 환경 파일 뒤에 Git 비추적 비밀 파일을 적용한다."""
    environment = _selected_environment()
    return (API_ROOT / f".env.{environment}", API_ROOT / ".env")


class Settings(BaseSettings):
    """WorkShield API 실행에 필요한 설정값."""

    model_config = SettingsConfigDict(
        env_file=_environment_files(),
        env_file_encoding="utf-8",
        enable_decoding=False,
        extra="ignore",
    )

    app_env: Environment = _selected_environment()
    llm_provider: LLMProvider
    llm_model: str | None = None
    router_llm_provider: LLMProvider | None = None
    router_llm_model: str | None = None
    router_llm_timeout_seconds: float = Field(default=3.0, gt=0, le=20)
    database_url: str = (
        f"sqlite+pysqlite:///{API_ROOT / 'data' / 'workshield.db'}"
    )
    database_echo: bool = False
    api_worker_count: int = Field(default=1, ge=1)
    sqlite_busy_timeout_ms: int = Field(default=5000, ge=1)
    app_debug: bool = False
    api_docs_enabled: bool = True
    cors_origins: list[str] = ["http://localhost:5173"]

    openai_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    runpod_serverless_api_key: SecretStr | None = None
    runpod_ollama_endpoint_id: str | None = None
    ollama_base_url: AnyHttpUrl = "http://localhost:11434"
    vllm_base_url: AnyHttpUrl | None = None
    vllm_api_key: SecretStr | None = None
    workshield_mcp_transport: MCPTransport = MCPTransport.STDIO
    workshield_mcp_url: AnyHttpUrl = "http://localhost:8000/mcp"
    workshield_mcp_project_dir: Path = API_ROOT.parent / "mcp"
    workshield_mcp_timeout: float = Field(default=30.0, gt=0)
    workshield_mcp_read_timeout: float = Field(default=300.0, gt=0)
    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        """JSON 배열 환경변수를 CORS origin 목록으로 변환한다."""
        if not isinstance(value, str):
            return value
        parsed = json.loads(value)
        if not isinstance(parsed, list) or not all(
            isinstance(origin, str) for origin in parsed
        ):
            raise ValueError("CORS_ORIGINS는 문자열 JSON 배열이어야 합니다.")
        return parsed

    @model_validator(mode="after")
    def validate_production_provider(self) -> "Settings":
        """운영 환경의 외부 전송과 민감한 디버그 출력을 막는다."""
        if (self.router_llm_provider is None) != (self.router_llm_model is None):
            raise ValueError(
                "ROUTER_LLM_PROVIDER와 ROUTER_LLM_MODEL은 함께 설정해야 합니다."
            )
        if self.app_env == "prod" and self.llm_provider is not LLMProvider.VLLM:
            raise ValueError(
                "운영 환경에서는 LLM_PROVIDER=vllm만 사용할 수 있습니다."
            )
        if self.app_env == "prod" and self.app_debug:
            raise ValueError("운영 환경에서는 APP_DEBUG=false여야 합니다.")
        if self.app_env == "prod" and self.database_echo:
            raise ValueError("운영 환경에서는 DATABASE_ECHO=false여야 합니다.")
        if self.api_worker_count != 1:
            raise ValueError(
                "SQLite와 프로세스 내부 큐를 사용할 때 API_WORKER_COUNT=1이어야 합니다."
            )
        return self

    def selected_provider_key(self) -> SecretStr | None:
        """선택된 외부 provider의 키만 반환한다. Ollama는 키가 필요하지 않다."""
        if self.llm_provider is LLMProvider.OPENAI:
            return self.openai_api_key
        if self.llm_provider is LLMProvider.GEMINI:
            return self.gemini_api_key
        if self.llm_provider is LLMProvider.RUNPOD_SERVERLESS:
            return self.runpod_serverless_api_key
        if self.llm_provider is LLMProvider.VLLM:
            return self.vllm_api_key
        return None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """프로세스에서 공유할 설정 인스턴스를 지연 생성한다."""
    return Settings()


SettingsDep = Annotated[Settings, Depends(get_settings)]
"""FastAPI 라우터와 하위 의존성에서 재사용하는 설정 의존성."""
