"""LLM 응답 생성에 적용하는 고정 기능 정책."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LLMPolicy:
    """LLM timeout과 생성 품질의 배포 정책."""

    timeout_seconds: float = 60.0
    temperature: float = 0.0
    top_p: float = 1.0
    seed: int = 42
    max_completion_tokens: int = 512

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("LLM timeout은 양수여야 합니다.")
        if not 0 <= self.temperature <= 2:
            raise ValueError("LLM temperature는 0 이상 2 이하여야 합니다.")
        if not 0 < self.top_p <= 1:
            raise ValueError("LLM top_p는 0 초과 1 이하여야 합니다.")
        if not 0 < self.max_completion_tokens <= 1000:
            raise ValueError("LLM 최대 생성 토큰은 1 이상 1000 이하여야 합니다.")


DEFAULT_LLM_POLICY = LLMPolicy()
"""운영과 일반 요청에 적용하는 기본 LLM 기능 정책."""
