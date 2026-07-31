"""검토 결과에서 조항·표준조항·카테고리 컨텍스트를 안전하게 추출."""

import re
from copy import deepcopy
from typing import Any


ARTICLE_HEADING_PATTERN = re.compile(
    r"제\s*(\d+)\s*조(?:\s*[（(]\s*([^）)\n]+)\s*[）)])?"
)
# 사용자는 `제1조`뿐 아니라 `1조`, `조항 1`처럼 조문을 가리킨다.
# 두 캡처 그룹 중 채워진 번호를 referenced_article_numbers에서 사용한다.
ARTICLE_REFERENCE_PATTERN = re.compile(r"(?:제\s*)?(\d+)\s*조|조항\s*(\d+)")
STANDARD_CONTRACT_LABELS = {
    "SW_FREELANCE": "SW 프리랜서 용역 표준계약서",
    "SI_SUBCONTRACT": "SI 하도급 표준계약서",
    "SM_SUBCONTRACT": "SM 하도급 표준계약서",
}


def standard_contract_label(contract_type: object) -> str:
    """내부 계약 유형을 파일명과 무관한 안전한 사용자 표시명으로 변환한다."""
    return (
        STANDARD_CONTRACT_LABELS.get(contract_type, "표준계약서")
        if isinstance(contract_type, str)
        else "표준계약서"
    )


def clause_display_label(text: object, title: object = None) -> str | None:
    """조항 원문의 번호·제목 또는 검증된 제목으로 사용자 표시명을 만든다."""
    searchable = text if isinstance(text, str) else ""
    match = ARTICLE_HEADING_PATTERN.search(searchable)
    if match:
        article = f"제{match.group(1)}조"
        heading = match.group(2).strip() if match.group(2) else ""
        return f"{article} {heading}".strip()
    if isinstance(title, str) and title.strip():
        return title.strip()
    return None


def clause_article_number(item: dict[str, Any]) -> str | None:
    """사용자 조항에서 조문 번호를 추출한다."""
    text = item.get("user_clause")
    match = ARTICLE_HEADING_PATTERN.search(text) if isinstance(text, str) else None
    return match.group(1) if match else None


def referenced_article_numbers(message: str) -> set[str]:
    """질문에 명시된 조문 번호를 근거 선택에만 사용한다."""
    return {
        next(group for group in match.groups() if group is not None)
        for match in ARTICLE_REFERENCE_PATTERN.finditer(message)
    }


def clause_results(result: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not result or not isinstance(result.get("clause_results"), list):
        return []
    return [item for item in result["clause_results"] if isinstance(item, dict)]


def user_clause_id(item: dict[str, Any]) -> str | None:
    """백엔드 정규화 단계에서 생성한 canonical ID만 반환한다."""
    value = item.get("user_clause_id")
    return value if isinstance(value, str) and value else None


def match_data(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("match")
    return value if isinstance(value, dict) else {}


def standard_clause(item: dict[str, Any]) -> dict[str, Any] | None:
    match = match_data(item)
    value = match.get("standard")
    if not isinstance(value, dict):
        value = item.get("standard")
    return value if isinstance(value, dict) else None


def standard_clause_id(item: dict[str, Any]) -> str | None:
    standard = standard_clause(item)
    if not standard:
        return None
    value = standard.get("clause_id") or standard.get("id")
    return str(value) if value is not None else None


def clause_category(item: dict[str, Any]) -> str | None:
    direct = item.get("category")
    if isinstance(direct, str):
        return direct
    standard = standard_clause(item)
    if standard and isinstance(standard.get("category"), str):
        return standard["category"]
    return None


def find_user_clause(
    result: dict[str, Any] | None,
    clause_id: str,
) -> dict[str, Any] | None:
    return next(
        (item for item in clause_results(result) if user_clause_id(item) == clause_id),
        None,
    )


def source_registry(result: dict[str, Any] | None) -> dict[str, set[str]]:
    registry = {"USER_CLAUSE": set(), "STANDARD_CLAUSE": set()}
    for item in clause_results(result):
        user_id = user_clause_id(item)
        standard_id = standard_clause_id(item)
        if user_id:
            registry["USER_CLAUSE"].add(user_id)
        if standard_id:
            registry["STANDARD_CLAUSE"].add(standard_id)
    return registry


def llm_review_result(result: dict[str, Any]) -> dict[str, Any]:
    """LLM 설명에 필요 없는 내부 후보 점수를 제거한 복사본을 반환한다."""
    sanitized = deepcopy(result)
    for item in clause_results(sanitized):
        match = item.get("match")
        if isinstance(match, dict):
            match.pop("score", None)
    return sanitized
