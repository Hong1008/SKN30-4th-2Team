"""환경별 설정과 FastAPI 의존성 provider를 정의한다."""

import os
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, cast

from fastapi import Depends
from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


API_ROOT = Path(__file__).resolve().parent.parent
Environment = Literal["local", "prod"]


class LLMProvider(StrEnum):
    """지원하는 LLM 공급자 식별자."""

    OPENAI = "openai"
    GEMINI = "gemini"
    OLLAMA = "ollama"


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
        extra="ignore",
    )

    app_env: Environment = _selected_environment()
    llm_provider: LLMProvider
    llm_model: str | None = None

    openai_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    ollama_base_url: AnyHttpUrl = "http://localhost:11434"
    workshield_mcp_transport: MCPTransport = MCPTransport.STDIO
    workshield_mcp_url: AnyHttpUrl = "http://localhost:8000/mcp"
    workshield_mcp_project_dir: Path = API_ROOT.parent / "mcp"
    workshield_mcp_timeout: float = Field(default=30.0, gt=0)
    workshield_mcp_read_timeout: float = Field(default=300.0, gt=0)

    @model_validator(mode="after")
    def validate_production_provider(self) -> "Settings":
        """운영 환경에서 계약서가 외부 LLM으로 전송되는 구성을 막는다."""
        if self.app_env == "prod" and self.llm_provider is not LLMProvider.OLLAMA:
            raise ValueError(
                "운영 환경에서는 LLM_PROVIDER=ollama만 사용할 수 있습니다."
            )
        return self

    def selected_provider_key(self) -> SecretStr | None:
        """선택된 외부 provider의 키만 반환한다. Ollama는 키가 필요하지 않다."""
        if self.llm_provider is LLMProvider.OPENAI:
            return self.openai_api_key
        if self.llm_provider is LLMProvider.GEMINI:
            return self.gemini_api_key
        return None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """프로세스에서 공유할 설정 인스턴스를 지연 생성한다."""
    return Settings()


SettingsDep = Annotated[Settings, Depends(get_settings)]
"""FastAPI 라우터와 하위 의존성에서 재사용하는 설정 의존성."""
