"""정규화된 검토 결과의 조항 식별자와 출처 레지스트리 검증."""

from app.reviews.context import find_user_clause, source_registry, user_clause_id


def test_user_clause_id_uses_only_backend_generated_canonical_field() -> None:
    normalized = {
        "user_clause_id": "uc_rev_1_1",
        "user_clause": "사용자 조항",
        "id": "untrusted-id",
        "clause_id": "untrusted-clause-id",
    }
    legacy = {
        "user_clause": {
            "id": "legacy-id",
            "text": "기존 fake가 사용하던 비공개 형태",
        }
    }

    assert user_clause_id(normalized) == "uc_rev_1_1"
    assert user_clause_id(legacy) is None


def test_find_and_registry_use_normalized_real_mcp_clause() -> None:
    result = {
        "clause_results": [
            {
                "user_clause_id": "uc_rev_1_1",
                "user_clause": "사용자 책임 조항",
                "deviation": "NONE",
                "match": {
                    "status": "CANDIDATE_SELECTED",
                    "standard": {
                        "clause_id": "std_1",
                        "category": "LIABILITY",
                    },
                },
                "toxic_patterns": [],
            }
        ],
        "missing_standard_clauses": [],
    }

    assert find_user_clause(result, "uc_rev_1_1") == result["clause_results"][0]
    assert find_user_clause(result, "std_1") is None
    assert source_registry(result) == {
        "USER_CLAUSE": {"uc_rev_1_1"},
        "STANDARD_CLAUSE": {"std_1"},
    }
