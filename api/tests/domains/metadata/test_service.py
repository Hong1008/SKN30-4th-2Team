"""MCP metadata 응답 정규화의 경계 조건을 검증한다."""

from app.domains.metadata.service import _categories, _items, _toxic_patterns


def test_missing_null_and_non_list_metadata_become_empty_lists() -> None:
    assert _items({}, "categories") == []
    assert _items({"categories": None}, "categories") == []
    assert _items({"categories": "invalid"}, "categories") == []


def test_categories_use_real_mcp_fields_and_ignore_invalid_items() -> None:
    result = _categories(
        [
            {
                "value": "LIABILITY",
                "description": "책임·손해배상",
                "anchors": [" 손해배상 ", None, 1, ""],
            },
            {"value": ""},
            {"description": "식별자 없음"},
            None,
            {"value": "LIABILITY", "description": "중복"},
        ]
    )

    assert [item.model_dump() for item in result] == [
        {
            "code": "LIABILITY",
            "label": "책임·손해배상",
            "description": "책임·손해배상",
            "anchors": ["손해배상"],
        }
    ]


def test_toxic_patterns_use_real_mcp_fields_and_ignore_invalid_items() -> None:
    result = _toxic_patterns(
        [
            {
                "pattern": "UNILATERAL_CHANGE",
                "title": "일방 변경",
                "category": "CHANGE",
                "example_count": 3,
            },
            {"pattern": "NEGATIVE_COUNT", "example_count": -1},
            {"pattern": "BOOLEAN_COUNT", "example_count": True},
            {"title": "식별자 없음", "example_count": 1},
            None,
        ]
    )

    assert [item.model_dump() for item in result] == [
        {
            "code": "UNILATERAL_CHANGE",
            "label": "일방 변경",
            "category": "CHANGE",
            "example_count": 3,
        }
    ]


def test_string_metadata_values_remain_compatible() -> None:
    assert _categories(["LIABILITY"])[0].model_dump() == {
        "code": "LIABILITY",
        "label": "LIABILITY",
        "description": None,
        "anchors": [],
    }
    assert _toxic_patterns(["UNILATERAL_CHANGE"])[0].model_dump() == {
        "code": "UNILATERAL_CHANGE",
        "label": "UNILATERAL_CHANGE",
        "category": None,
        "example_count": 0,
    }
