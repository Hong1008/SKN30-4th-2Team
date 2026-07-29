"""검토 scheduler FastAPI 의존성."""

from typing import Annotated

from fastapi import Depends, Request

from app.config import SettingsDep
from app.core.admission.policy import REVIEW_POLICY
from app.core.db.dependencies import DatabaseDep
from app.core.llm.mcp.dependencies import WorkShieldMCPRuntimeDep
from app.core.storage.dependencies import FileStorageDep
from app.domains.review_sessions.dependencies import ReviewSessionPolicyDep
from app.domains.reviews.runner import execute_review
from app.domains.reviews.scheduler import ReviewScheduler


async def get_review_scheduler(
    request: Request,
    database: DatabaseDep,
    storage: FileStorageDep,
    runtime: WorkShieldMCPRuntimeDep,
    settings: SettingsDep,
    policy: ReviewSessionPolicyDep,
) -> ReviewScheduler:
    """lifespan scheduler를 반환하고 lifespan 없는 테스트 앱에도 동일 구조를 만든다."""
    scheduler = getattr(request.app.state, "review_scheduler", None)
    if scheduler is None:
        scheduler = ReviewScheduler(
            database,
            lambda review_id: execute_review(
                database=database,
                storage=storage,
                runtime=runtime,
                settings=settings,
                review_id=review_id,
                policy=policy,
            ),
            REVIEW_POLICY,
        )
        await scheduler.reconcile()
        await scheduler.start()
        request.app.state.review_scheduler = scheduler
    if not isinstance(scheduler, ReviewScheduler):
        raise TypeError("review_scheduler는 ReviewScheduler여야 합니다.")
    return scheduler


ReviewSchedulerDep = Annotated[ReviewScheduler, Depends(get_review_scheduler)]
