"""Suggestions 구조화 출력 계약을 검증한다."""

import pytest
from pydantic import ValidationError

from app.domains.suggestions.schemas import (
    SuggestionGeneratedOutput,
    SuggestionInsufficientGroundingOutput,
    SuggestionSourceKey,
    SuggestionStructuredOutput,
)


def test_generated_output_requires_nonempty_source_keys() -> None:
    """GENERATED는 적어도 하나의 닫힌 집합 source key를 선택해야 한다."""
    with pytest.raises(ValidationError):
        SuggestionStructuredOutput.model_validate({
            "outcome": "GENERATED",
            "suggestion": "협의 문구",
        })

    with pytest.raises(ValidationError):
        SuggestionStructuredOutput.model_validate({
            "outcome": "GENERATED",
            "suggestion": "협의 문구",
            "used_source_keys": [],
        })

    with pytest.raises(ValidationError):
        SuggestionStructuredOutput.model_validate({
            "outcome": "GENERATED",
            "suggestion": "협의 문구",
            "used_source_keys": ["SRC_UNKNOWN"],
        })


def test_generated_json_schema_marks_source_keys_required() -> None:
    """모든 provider에 전달되는 JSON Schema에도 source key 조건을 포함한다."""
    schema = SuggestionStructuredOutput.model_json_schema()
    generated = schema["$defs"]["SuggestionGeneratedOutput"]

    assert set(generated["required"]) >= {
        "outcome",
        "suggestion",
        "used_source_keys",
    }
    assert generated["properties"]["used_source_keys"]["minItems"] == 1


def test_generated_output_keeps_source_keys() -> None:
    """GENERATED의 논리 근거 선택은 식별자 없이 보존한다."""
    output = SuggestionStructuredOutput.model_validate({
        "outcome": "GENERATED",
        "suggestion": "협의 문구",
        "used_source_keys": ["SRC_USER", "SRC_STANDARD"],
    })

    assert isinstance(output.root, SuggestionGeneratedOutput)
    assert output.root.used_source_keys == [
        SuggestionSourceKey.USER,
        SuggestionSourceKey.STANDARD,
    ]


def test_insufficient_grounding_output_allows_no_provenance() -> None:
    """근거 부족 결과는 생성용 출처 배열을 요구하지 않는다."""
    output = SuggestionStructuredOutput.model_validate({
        "outcome": "INSUFFICIENT_GROUNDING",
    })

    assert isinstance(output.root, SuggestionInsufficientGroundingOutput)
