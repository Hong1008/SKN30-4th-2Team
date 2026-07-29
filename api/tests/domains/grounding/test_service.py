"""MCP 법령 DTO를 API 공개 DTO로 변환하는 경계를 검증한다."""

from app.domains.grounding.service import _normalize_items


def test_normalizes_korean_mcp_grounding_fields() -> None:
    items = _normalize_items(
        {
            "grounding": [
                {
                    "법령명": "민법",
                    "조번호": "제665조",
                    "본문": "보수는 완성된 목적물의 인도와 동시에 지급하여야 한다.",
                    "출처": "국가법령정보센터",
                }
            ]
        }
    )

    assert [item.model_dump() for item in items] == [
        {
            "source_id": "law_1",
            "law_name": "민법",
            "article": "제665조",
            "text": "보수는 완성된 목적물의 인도와 동시에 지급하여야 한다.",
            "source": "국가법령정보센터",
            "source_url": None,
        }
    ]


def test_keeps_english_compatibility_fields() -> None:
    items = _normalize_items(
        {
            "items": [
                {
                    "source_id": "law_existing",
                    "law_name": "민법",
                    "article": "제390조",
                    "text": "손해배상 참고 원문",
                    "source": "국가법령정보센터",
                }
            ]
        }
    )

    assert items[0].source_id == "law_existing"
    assert items[0].law_name == "민법"
