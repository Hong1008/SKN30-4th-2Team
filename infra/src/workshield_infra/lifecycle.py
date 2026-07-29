"""공급자에 독립적인 상태 판정과 실행 계획을 정의한다."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ReconcileAction(StrEnum):
    CREATE = "create"
    REUSE = "reuse"
    UPDATE = "update"
    REPLACE = "replace"
    REFUSE = "refuse"


@dataclass(frozen=True, slots=True)
class Discovery:
    exists: bool
    owned: bool = False
    matches: bool = False
    mutable_drift: bool = False
    immutable_drift: bool = False
    ambiguous: bool = False


def decide(discovery: Discovery, *, replacement_approved: bool = False) -> ReconcileAction:
    """공통 멱등성 상태표를 결정론적으로 적용한다."""

    if discovery.ambiguous or (discovery.exists and not discovery.owned):
        return ReconcileAction.REFUSE
    if not discovery.exists:
        return ReconcileAction.CREATE
    if discovery.immutable_drift:
        return ReconcileAction.REPLACE if replacement_approved else ReconcileAction.REFUSE
    if discovery.mutable_drift:
        return ReconcileAction.UPDATE
    if discovery.matches:
        return ReconcileAction.REUSE
    return ReconcileAction.REFUSE
