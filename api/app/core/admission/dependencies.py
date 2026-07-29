"""lifespan admission runtime 의존성."""

from typing import Annotated

from fastapi import Depends, Request

from app.core.admission.gate import BoundedFifoGate, ImmediateConcurrencyLimiter
from app.core.admission.policy import SUGGESTION_POLICY, UPLOAD_POLICY


def get_suggestion_gate(request: Request) -> BoundedFifoGate:
    gate = getattr(request.app.state, "suggestion_gate", None)
    if gate is None:
        gate = BoundedFifoGate(
            SUGGESTION_POLICY,
            error_code="SUGGESTION_QUEUE_FULL",
            error_message="현재 제안 생성 요청이 많습니다. 잠시 후 다시 시도해 주세요.",
        )
        request.app.state.suggestion_gate = gate
    if not isinstance(gate, BoundedFifoGate):
        raise TypeError("suggestion_gate는 BoundedFifoGate여야 합니다.")
    return gate


def get_upload_limiter(request: Request) -> ImmediateConcurrencyLimiter:
    limiter = getattr(request.app.state, "upload_limiter", None)
    if limiter is None:
        limiter = ImmediateConcurrencyLimiter(
            UPLOAD_POLICY,
            error_code="UPLOAD_CAPACITY_EXCEEDED",
            error_message="현재 업로드 요청이 많습니다. 잠시 후 다시 시도해 주세요.",
        )
        request.app.state.upload_limiter = limiter
    if not isinstance(limiter, ImmediateConcurrencyLimiter):
        raise TypeError("upload_limiter는 ImmediateConcurrencyLimiter여야 합니다.")
    return limiter


SuggestionGateDep = Annotated[BoundedFifoGate, Depends(get_suggestion_gate)]
UploadLimiterDep = Annotated[
    ImmediateConcurrencyLimiter,
    Depends(get_upload_limiter),
]
