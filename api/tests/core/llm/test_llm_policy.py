"""LLM 기능 정책의 기본값과 불변 조건을 검증한다."""

from dataclasses import FrozenInstanceError

import pytest

from app.core.llm.policy import DEFAULT_LLM_POLICY, LLMPolicy


def test_default_llm_policy_matches_validated_generation_policy() -> None:
    assert DEFAULT_LLM_POLICY == LLMPolicy(
        timeout_seconds=60.0,
        temperature=0.0,
        top_p=1.0,
        seed=42,
        max_completion_tokens=512,
    )


def test_llm_policy_is_immutable() -> None:
    with pytest.raises(FrozenInstanceError):
        DEFAULT_LLM_POLICY.timeout_seconds = 10


@pytest.mark.parametrize(
    "overrides",
    [
        {"timeout_seconds": 0},
        {"temperature": -0.1},
        {"temperature": 2.1},
        {"top_p": 0},
        {"top_p": 1.1},
        {"max_completion_tokens": 0},
        {"max_completion_tokens": 1001},
    ],
)
def test_llm_policy_rejects_invalid_values(overrides: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        LLMPolicy(**overrides)
