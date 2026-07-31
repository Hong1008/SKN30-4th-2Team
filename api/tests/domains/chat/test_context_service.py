"""대화 원문 없는 후속 질문 상태의 수명주기를 검증한다."""

from datetime import UTC, datetime, timedelta

from app.core.db.models import ReviewRow, ReviewSessionRow
from app.domains.chat.context_service import (
    ChatContextState,
    ChatContextTargetKind,
    issue_chat_context,
    load_chat_context,
)


def test_context_is_bound_to_review_and_expires(database) -> None:
    now = datetime.now(UTC)
    with database.session() as session:
        session.add(
            ReviewSessionRow(
                id="ses_chat",
                access_token_hash="hash",
                state="REVIEW_COMPLETED",
                scope_status=None,
                scope_result=None,
                suggested_contract_type="SW_FREELANCE",
                selected_contract_type="SW_FREELANCE",
                selection_source="USER",
                out_of_scope_confirmed_at=None,
                original_file_name="test.pdf",
                file_size_bytes=1,
                storage_key=None,
                storage_path=None,
                created_at=now,
                updated_at=now,
                expires_at=now + timedelta(hours=1),
            )
        )
        session.flush()
        session.add(
            ReviewRow(
                id="rev_chat",
                session_id="ses_chat",
                retry_of_review_id=None,
                idempotency_key="review-key",
                state="COMPLETED",
                version=0,
                mcp_review_status="OK",
                contract_type="SW_FREELANCE",
                progress=None,
                result=None,
                error=None,
                created_at=now,
                started_at=now,
                completed_at=now,
                expires_at=now + timedelta(hours=1),
            )
        )
        session.flush()
        token = issue_chat_context(
            session,
            session_id="ses_chat",
            review_id="rev_chat",
            state=ChatContextState(
                category="조항 질문",
                target_kind=ChatContextTargetKind.SINGLE_CLAUSE,
                selected_clause_ids=["uc_11"],
                answer_scope="single_clause",
            ),
            expires_at=now + timedelta(minutes=1),
        )
        session.commit()
        assert load_chat_context(
            session,
            token=token,
            session_id="ses_chat",
            review_id="rev_chat",
            now=now,
        ) == ChatContextState(
            category="조항 질문",
            target_kind=ChatContextTargetKind.SINGLE_CLAUSE,
            selected_clause_ids=["uc_11"],
            answer_scope="single_clause",
        )
        assert load_chat_context(
            session,
            token=token,
            session_id="ses_chat",
            review_id="other_review",
            now=now,
        ) is None
        assert load_chat_context(
            session,
            token=token,
            session_id="ses_chat",
            review_id="rev_chat",
            now=now + timedelta(minutes=2),
        ) is None


def test_context_keeps_missing_candidates_separate_from_user_clause_group(database) -> None:
    now = datetime.now(UTC)
    state = ChatContextState(
        category="REVIEW_ANALYSIS",
        target_kind=ChatContextTargetKind.MISSING_STANDARD_CLAUSES,
        missing_standard_clause_ids=["std_1", "std_2", "std_3"],
        answer_scope="missing_standard_clauses",
    )
    with database.session() as session:
        session.add(
            ReviewSessionRow(
                id="ses_missing",
                access_token_hash="hash",
                state="REVIEW_COMPLETED",
                scope_status=None,
                scope_result=None,
                suggested_contract_type="SW_FREELANCE",
                selected_contract_type="SW_FREELANCE",
                selection_source="USER",
                out_of_scope_confirmed_at=None,
                original_file_name="test.pdf",
                file_size_bytes=1,
                storage_key=None,
                storage_path=None,
                created_at=now,
                updated_at=now,
                expires_at=now + timedelta(hours=1),
            )
        )
        session.flush()
        session.add(
            ReviewRow(
                id="rev_missing",
                session_id="ses_missing",
                retry_of_review_id=None,
                idempotency_key="review-key",
                state="COMPLETED",
                version=0,
                mcp_review_status="OK",
                contract_type="SW_FREELANCE",
                progress=None,
                result=None,
                error=None,
                created_at=now,
                started_at=now,
                completed_at=now,
                expires_at=now + timedelta(hours=1),
            )
        )
        session.flush()
        token = issue_chat_context(
            session,
            session_id="ses_missing",
            review_id="rev_missing",
            state=state,
            expires_at=now + timedelta(minutes=1),
        )
        session.commit()

        loaded = load_chat_context(
            session,
            token=token,
            session_id="ses_missing",
            review_id="rev_missing",
            now=now,
        )

    assert loaded == state
    assert loaded is not None
    assert loaded.selected_clause_ids == []
    assert loaded.missing_standard_clause_ids == ["std_1", "std_2", "std_3"]
