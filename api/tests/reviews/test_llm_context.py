"""LLM에 전달하는 검토 스냅샷의 비공개 필드 제거를 검증한다."""

from app.reviews.context import llm_review_result


def test_llm_review_result_removes_match_score_without_mutating_snapshot() -> None:
    snapshot = {
        "clause_results": [
            {
                "user_clause_id": "uc_rev_1",
                "match": {
                    "status": "CANDIDATE_SELECTED",
                    "score": 0.95,
                    "standard": {"clause_id": "std_1"},
                },
            }
        ]
    }

    sanitized = llm_review_result(snapshot)

    assert "score" not in sanitized["clause_results"][0]["match"]
    assert snapshot["clause_results"][0]["match"]["score"] == 0.95
