"""Suggestions 구조화 출력 계약을 검증한다."""

import pytest
from pydantic import ValidationError

from app.domains.suggestions.schemas import (
    SuggestionGeneratedOutput,
    SuggestionInsufficientGroundingOutput,
    SuggestionStructuredOutput,
)


def test_generated_output_requires_nonempty_source_ids() -> None:
    """GENERATED는 두 출처 배열을 생략하거나 비워 둘 수 없다."""
    with pytest.raises(ValidationError):
        SuggestionStructuredOutput.model_validate({
            "outcome": "GENERATED",
            "text": "협의 문구",
        })

    with pytest.raises(ValidationError):
        SuggestionStructuredOutput.model_validate({
            "outcome": "GENERATED",
            "text": "협의 문구",
            "standard_clause_ids": [],
            "grounding_source_ids": [],
        })


def test_generated_json_schema_marks_source_ids_required() -> None:
    """모든 provider에 전달되는 JSON Schema에도 출처 필수 조건을 포함한다."""
    schema = SuggestionStructuredOutput.model_json_schema()
    generated = schema["$defs"]["SuggestionGeneratedOutput"]

    assert set(generated["required"]) >= {
        "outcome",
        "text",
        "standard_clause_ids",
        "grounding_source_ids",
    }
    assert generated["properties"]["standard_clause_ids"]["minItems"] == 1
    assert generated["properties"]["grounding_source_ids"]["minItems"] == 1


def test_generated_output_keeps_provenance_fields() -> None:
    """GENERATED의 출처 배열은 별도 필드로 보존한다."""
    output = SuggestionStructuredOutput.model_validate({
        "outcome": "GENERATED",
        "text": "협의 문구",
        "standard_clause_ids": ["std_1"],
        "grounding_source_ids": ["law_1"],
    })

    assert isinstance(output.root, SuggestionGeneratedOutput)
    assert output.root.standard_clause_ids == ["std_1"]
    assert output.root.grounding_source_ids == ["law_1"]


def test_insufficient_grounding_output_allows_no_provenance() -> None:
    """근거 부족 결과는 생성용 출처 배열을 요구하지 않는다."""
    output = SuggestionStructuredOutput.model_validate({
        "outcome": "INSUFFICIENT_GROUNDING",
    })

    assert isinstance(output.root, SuggestionInsufficientGroundingOutput)
