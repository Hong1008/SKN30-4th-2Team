"""환경 설정과 FastAPI 의존성 주입 계약을 검증한다."""

import pytest
from pydantic import ValidationError

from app.config import (
    DEFAULT_SUPPORTED_FILE_EXTENSIONS,
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


def test_upload_and_session_settings_have_expected_defaults() -> None:
    settings = Settings(
        app_env="local",
        llm_provider="ollama",
        llm_model="configured-model",
    )

    assert settings.max_upload_size_bytes == 10 * 1024 * 1024
    assert settings.supported_file_extensions == DEFAULT_SUPPORTED_FILE_EXTENSIONS
    assert settings.temp_upload_dir.as_posix() == "data/99_uploads"
    assert settings.session_ttl_seconds == 30 * 60
    assert settings.storage_cleanup_interval_seconds == 60
    assert settings.llm_temperature == 0
    assert settings.llm_top_p == 1
    assert settings.llm_seed == 42
    assert settings.llm_max_completion_tokens == 512


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("llm_temperature", -0.1),
        ("llm_top_p", 0),
        ("llm_top_p", 1.1),
        ("llm_max_completion_tokens", 0),
        ("llm_max_completion_tokens", 1001),
    ],
)
def test_llm_generation_settings_reject_invalid_values(
    field_name: str,
    invalid_value: int | float,
) -> None:
    with pytest.raises(ValidationError):
        Settings(
            app_env="local",
            llm_provider="ollama",
            **{field_name: invalid_value},
        )


def test_supported_file_extensions_accepts_comma_separated_value() -> None:
    settings = Settings(
        app_env="local",
        llm_provider="ollama",
        supported_file_extensions="pdf, DOCX, .hwp",
    )

    assert settings.supported_file_extensions == ("pdf", "docx", "hwp")


def test_supported_file_extensions_rejects_formats_outside_product_scope() -> None:
    with pytest.raises(ValidationError, match="HWP, HWPX, PDF, DOCX"):
        Settings(
            app_env="local",
            llm_provider="ollama",
            supported_file_extensions="pdf,xlsx",
        )


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("max_upload_size_bytes", 0),
        ("session_ttl_seconds", 0),
        ("storage_cleanup_interval_seconds", 0),
        ("supported_file_extensions", ""),
    ],
)
def test_upload_and_session_settings_reject_invalid_values(
    field_name: str, invalid_value: int | str
) -> None:
    with pytest.raises(ValidationError):
        Settings(
            app_env="local",
            llm_provider="ollama",
            **{field_name: invalid_value},
        )


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
