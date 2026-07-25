"""LLM provider들이 공유하는 설정 타입과 오류를 정의한다."""

from enum import StrEnum


class ReasoningMode(StrEnum):
    """provider 독립적인 추론 모드."""

    OFF = "off"
    ON = "on"


class LLMConfigurationError(ValueError):
    """선택한 모델과 LLM 옵션의 조합이 유효하지 않을 때 발생한다."""
