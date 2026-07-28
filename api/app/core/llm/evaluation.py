"""MCP 골든셋을 참조하는 경량 LLM 평가 fixture를 해석한다."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from pydantic import BaseModel, Field

from app.domains.suggestions.schemas import SuggestionSourceKey


class LLMEvaluationOverlay(BaseModel):
    """MCP case에 추가하는 LLM 전용 입력과 기대조건."""

    fixture_id: str
    mcp_case_id: str
    purpose: str
    provided_inputs: dict[str, object] = Field(default_factory=dict)
    required_terms: list[str] = Field(default_factory=list)
    required_source_keys: list[SuggestionSourceKey] = Field(default_factory=list)


class LLMEvaluationSuite(BaseModel):
    """평가 fixture 파일의 공통 참조와 overlay 목록."""

    schema_version: int
    mcp_fixture_path: str
    standard_db_path: str
    fixtures: list[LLMEvaluationOverlay]


class ResolvedLLMEvaluationFixture(BaseModel):
    """MCP case와 표준조항을 결합한 실행 입력."""

    overlay: LLMEvaluationOverlay
    user_clause: str
    deviation: str
    standard: dict[str, str]


def load_evaluation_suite(path: Path) -> LLMEvaluationSuite:
    """JSON overlay suite를 검증해 로드한다."""
    return LLMEvaluationSuite.model_validate_json(path.read_text(encoding="utf-8"))


def resolve_evaluation_fixtures(
    suite: LLMEvaluationSuite,
    *,
    repository_root: Path,
) -> list[ResolvedLLMEvaluationFixture]:
    """MCP fixture와 표준조항 DB를 case ID로 결합한다."""
    mcp_cases = json.loads(
        (repository_root / suite.mcp_fixture_path).read_text(encoding="utf-8")
    )
    cases_by_id = {case["case_id"]: case for case in mcp_cases}
    database_path = repository_root / suite.standard_db_path
    resolved: list[ResolvedLLMEvaluationFixture] = []
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        for overlay in suite.fixtures:
            case = cases_by_id.get(overlay.mcp_case_id)
            if case is None:
                raise ValueError(f"MCP fixture가 없습니다: {overlay.mcp_case_id}")
            clause_id = case.get("gold_clause_id")
            if not clause_id:
                raise ValueError(
                    f"LLM 생성 fixture에는 gold_clause_id가 필요합니다: {overlay.mcp_case_id}"
                )
            row = connection.execute(
                """
                SELECT clause_id, contract_type, category, title, text, source, version
                FROM standard_clauses
                WHERE clause_id = ?
                """,
                (clause_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"표준조항이 없습니다: {clause_id}")
            resolved.append(
                ResolvedLLMEvaluationFixture(
                    overlay=overlay,
                    user_clause=case["user_clause"],
                    deviation=case["gold_deviation"],
                    standard=dict(row),
                )
            )
    return resolved
