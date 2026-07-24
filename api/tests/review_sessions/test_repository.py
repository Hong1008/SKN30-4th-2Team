"""검토 세션 ORM 매핑과 Repository 계약을 검증한다."""

from datetime import UTC, datetime, timedelta

from app.db.database import Database
from app.review_sessions.domain import (
    ReviewSession,
    ReviewSessionState,
    ScopeStatus,
    SelectionSource,
)
from app.review_sessions.mapper import review_session_from_row, review_session_to_row
from app.review_sessions.repository import SqlAlchemyReviewSessionRepository


def review_session_entity(
    session_id: str = "ses_repository",
) -> ReviewSession:
    """Repository 테스트용 검토 세션 엔티티를 만든다."""
    now = datetime.now(UTC)
    return ReviewSession(
        id=session_id,
        access_token_hash=f"hash-{session_id}",
        state=ReviewSessionState.TYPE_SELECTION_REQUIRED,
        original_file_name="계약서.pdf",
        file_size_bytes=421_398,
        storage_path=f"/tmp/{session_id}.pdf",
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(hours=1),
        scope_status=ScopeStatus.IN_SCOPE,
        scope_result={"matched_clause_count": 8},
        suggested_contract_type="SW_FREELANCE",
    )


def test_review_session_mapper_round_trip() -> None:
    entity = review_session_entity()

    restored = review_session_from_row(review_session_to_row(entity))

    assert restored == entity


def test_review_session_repository_add_get_and_save(database: Database) -> None:
    entity = review_session_entity()
    with database.session() as session:
        repository = SqlAlchemyReviewSessionRepository(session)
        repository.add(entity)
        session.commit()

        restored = repository.get(entity.id)
        assert restored == entity

        entity.selected_contract_type = "SW_FREELANCE"
        entity.selection_source = SelectionSource.SUGGESTED
        entity.state = ReviewSessionState.READY_TO_REVIEW
        repository.save(entity)
        session.commit()

    with database.session() as session:
        restored = SqlAlchemyReviewSessionRepository(session).get(entity.id)

    assert restored == entity


def test_review_session_repository_does_not_commit(database: Database) -> None:
    entity = review_session_entity("ses_no_commit")

    with database.session() as session:
        SqlAlchemyReviewSessionRepository(session).add(entity)

    with database.session() as session:
        restored = SqlAlchemyReviewSessionRepository(session).get(entity.id)

    assert restored is None


def test_review_session_repository_delete_cascades_reviews(
    database: Database,
) -> None:
    from app.reviews.domain import Review, ReviewState
    from app.reviews.repository import SqlAlchemyReviewRepository

    entity = review_session_entity("ses_delete")
    now = datetime.now(UTC)
    review = Review(
        id="rev_delete",
        session_id=entity.id,
        idempotency_key="idem-delete",
        state=ReviewState.QUEUED,
        contract_type="SW_FREELANCE",
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    with database.session() as session:
        session_repository = SqlAlchemyReviewSessionRepository(session)
        review_repository = SqlAlchemyReviewRepository(session)
        session_repository.add(entity)
        session.commit()
        review_repository.add(review)
        session.commit()

        assert session_repository.delete(entity.id) is True
        session.commit()

    with database.session() as session:
        assert SqlAlchemyReviewRepository(session).get(review.id) is None
