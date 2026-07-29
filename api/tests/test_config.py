"""환경 설정과 FastAPI 의존성 주입 계약을 검증한다."""

import pytest
from pydantic import ValidationError

from app.config import (
    MCPTransport,
    Settings,
    get_settings,
)


def test_get_settings_is_cached() -> None:
    get_settings.cache_clear()

    assert get_settings() is get_settings()


def test_production_rejects_non_vllm_provider() -> None:
    with pytest.raises(ValidationError, match="LLM_PROVIDER=vllm"):
        Settings(app_env="prod", llm_provider="openai")


def test_production_accepts_vllm_provider() -> None:
    settings = Settings(
        app_env="prod",
        llm_provider="vllm",
        llm_model="served-qwen-model",
        vllm_base_url="https://vllm.example.com/v1",
        vllm_api_key="vllm-secret",
        app_debug=False,
        database_echo=False,
    )

    assert settings.llm_provider.value == "vllm"
    assert str(settings.vllm_base_url) == "https://vllm.example.com/v1"
    assert settings.selected_provider_key() is settings.vllm_api_key


def test_mcp_transport_defaults_to_stdio() -> None:
    settings = Settings(
        app_env="local",
        llm_provider="ollama",
        llm_model="configured-model",
        workshield_mcp_transport="stdio",
    )

    assert settings.workshield_mcp_transport is MCPTransport.STDIO


def test_mcp_timeout_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(
            app_env="local",
            llm_provider="ollama",
            llm_model="configured-model",
            workshield_mcp_timeout=0,
        )


def test_database_defaults_to_file_sqlite() -> None:
    settings = Settings(
        app_env="local",
        llm_provider="ollama",
        llm_model="configured-model",
    )

    assert settings.database_url.startswith("sqlite+pysqlite:///")
    assert settings.database_url.replace("\\", "/").endswith("/data/workshield.db")
    assert settings.database_echo is False
    assert settings.api_worker_count == 1
    assert settings.sqlite_busy_timeout_ms == 5000


def test_multiple_api_workers_are_rejected() -> None:
    with pytest.raises(ValidationError, match="API_WORKER_COUNT=1"):
        Settings(
            app_env="local",
            llm_provider="ollama",
            api_worker_count=2,
        )


def test_settings_excludes_feature_policy_fields() -> None:
    policy_fields = {
        "max_upload_size_bytes",
        "supported_file_extensions",
        "temp_upload_dir",
        "session_ttl_seconds",
        "expired_tombstone_ttl_seconds",
        "storage_cleanup_interval_seconds",
        "metadata_cache_ttl_seconds",
        "llm_timeout_seconds",
        "llm_temperature",
        "llm_top_p",
        "llm_seed",
        "llm_max_completion_tokens",
    }

    assert policy_fields.isdisjoint(Settings.model_fields)


def test_production_rejects_debug_mode() -> None:
    with pytest.raises(ValidationError, match="APP_DEBUG=false"):
        Settings(
            app_env="prod",
            llm_provider="vllm",
            app_debug=True,
            database_echo=False,
        )


def test_production_rejects_database_query_logging() -> None:
    with pytest.raises(ValidationError, match="DATABASE_ECHO=false"):
        Settings(
            app_env="prod",
            llm_provider="vllm",
            app_debug=False,
            database_echo=True,
        )
