# WorkShield 백엔드 개발 상세 참고서

작업 시작 시에는 [백엔드 개발 가이드](./backend-development-guide.md)만 읽고,
구현 중 필요한 항목만 이 문서에서 확인한다.

## 계층과 영속성

### Domain Entity

Domain Entity는 비즈니스 상태와 규칙만 표현한다. Python 표준 라이브러리와
같은 도메인의 순수 타입만 import하며 FastAPI, Pydantic, SQLAlchemy, MCP·LLM
client는 import하지 않는다. 상태 문자열은 `StrEnum`으로 정의한다.

```python
@dataclass(slots=True)
class Review:
    id: str
    session_id: str
    state: ReviewState
    expires_at: datetime

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at
```

### ORM Row와 Mapper

ORM Row는 SQLite 테이블 모양만 나타내며 상태 전이, 권한, MCP 호출, API 응답,
오류 메시지를 포함하지 않는다. 현재 Row는 `app/core/db/models.py`에 있다.

Mapper는 `review_to_row()`, `review_from_row()`, `update_review_row()`처럼
ORM Row와 Domain Entity를 명시적으로 변환한다. DB 컬럼을 바꾸면 Domain,
ORM Row, Mapper의 생성·조회·갱신 함수, Mapper/Repository 테스트를 모두 확인한다.

### Repository와 Service

Repository는 저장 기능만 제공하고 조회 결과는 Domain Entity로 반환한다.
`commit()`, `rollback()`, `HTTPException`, Pydantic DTO, MCP·LLM 호출은 사용하지
않는다. 대상이 없으면 `None` 또는 저장 계층 오류를 반환하고, 사용자용 오류는
Service가 결정한다.

Application Service는 하나의 사용자 행동을 완성한다. Repository 조회·저장,
도메인 규칙 실행, 트랜잭션 경계, MCP·LLM 호출 순서, 저장 오류의 애플리케이션
오류 변환을 담당한다. `Request`, `Response`, `HTTPException`은 사용하지 않는다.

### Router, 소유권, 파일

Router는 입력 검증, Dependency 주입, Service 호출, API DTO/공통 응답 변환만
수행한다. `select()`, `session.get()`, `session.commit()`을 직접 호출하지 않는다.

세션 또는 검토 하위 리소스는 `OwnedReviewSessionDep` 또는 `OwnedReviewDep`로
익명 세션 Cookie의 소유권을 먼저 확인한다. 존재하지 않는 리소스와 타 세션
리소스는 모두 404, 소유권이 확인된 만료 세션만 410으로 처리한다.

사용자 파일은 `app/core/storage/protocol.py`의 `FileStorage`로만 저장·열기·삭제한다.
저장 루트 조합이나 `Path.unlink()` 직접 호출은 금지한다.

## 멱등성(Idempotency)

재요청이 작업을 중복 생성·실행하지 않도록 `Idempotency-Key`와
`app/core/idempotency`의 `@idempotent` 데코레이터를 사용한다.

- `require_idempotency_key()`가 헤더 존재와 128자 이하 길이를 검증한다.
- canonical JSON 기반 SHA-256 `request_fingerprint`로 같은 요청인지 판별한다.
- 같은 키·지문의 기존 성공 응답은 `find_replay`로 즉시 재생한다.
- 새 성공 응답은 `save_response`로 세션 TTL 동안 저장한다.

```python
@router.post("/{review_id}/chat/messages", response_model=ApiResponse[ChatResponse])
@idempotent(
    scope="reviews.chat",
    response_model=ChatResponse,
    get_session_id=lambda *, owned, **kw: owned.session_id,
    get_fingerprint_payload=lambda *, owned, payload, **kw: {
        "review_id": owned.id,
        "payload": payload.model_dump(mode="json"),
    },
    use_guard=True,
)
async def chat_message(
    owned: OwnedReviewDep,
    payload: ChatRequest,
    idem_ctx: IdempotencyContextDep,
) -> ChatResponse:
    ...
```

핸들러는 `IdempotencyContextDep`를 주입한다. DB Unique 제약을 직접 사용할
경우 `use_guard=False`로 설정하고, commit 후 작업이 필요하면 `post_commit` 훅을 쓴다.

## SQLite

기본 파일은 `api/data/workshield.db`이며 `DATABASE_URL` 기본값은
`sqlite+pysqlite:///./data/workshield.db`다. `lifespan.py`가 Engine·테이블을
만들고 종료 시 풀을 정리하며, `database.py`는 상대 경로를 `api/` 기준으로
해석한다. `api/data/*.db`와 `api/data/*.db-*`는 Git에 커밋하지 않는다.

테스트는 `tests/conftest.py`가 만드는 임시 SQLite를 사용한다. 현재
`Base.metadata.create_all()`은 기존 컬럼의 변경·이름 변경·삭제를 처리하지
않는다. 기존 데이터 보존, 배포 스키마 추적, 기존 컬럼 변경이 필요해지면
Alembic 도입을 논의한다.

## 트랜잭션

Service가 명시적인 `session.begin()`으로 경계를 관리한다. 정상 종료는 commit,
예외는 rollback이며 Session 의존성은 예외 전파 시 안전하게 rollback·close한다.

```python
with session.begin():
    entity = repository.get(session_id)
    if entity is None:
        raise NotFoundError(code="SESSION_NOT_FOUND", message="검토 세션을 찾을 수 없습니다.")
    entity.state = ReviewSessionState.READY_TO_REVIEW
    repository.save(entity)
```

MCP·LLM 호출은 트랜잭션 밖에서 수행한다. 호출 전 상태 저장 → 외부 호출 → 결과와
최종 상태 저장의 짧은 트랜잭션 두 개로 나눈다. 트랜잭션 데코레이터는 경계를
숨기고 외부 호출을 감싸기 쉬우므로 현재 사용하지 않는다. 필요 시 DB 작업만 하는
Service 메서드로 한정하고 ADR로 결정한다.

## API 응답과 오류

`/api/v1` 성공 응답은 `data`와 `meta(request_id, timestamp)`, 오류 응답은
`error(code, message, field, retryable, next_action, details)`와 `meta`를 사용한다.
Service는 `app/core/common/errors.py`의 오류를 발생시키고 예외 처리기가 HTTP
상태와 공통 Envelope로 변환한다.

```python
raise NotFoundError(
    code="SESSION_NOT_FOUND",
    message="검토 세션을 찾을 수 없습니다.",
    next_action="START_NEW_REVIEW",
)
```

임의 JSON 오류 응답, 계약서·조항·프롬프트의 `details` 포함, 스택 트레이스·내부
경로 노출은 금지한다. 클라이언트 분기는 `message`나 `label`이 아닌 안정적인
`code`로 한다.

## 테스트와 검증

Red → Green → Refactor 순서를 지킨다. 구현할 행동을 작은 테스트로 먼저 쓰고,
의도한 비즈니스 조건으로 실패하는지 확인한 뒤 최소 구현을 작성한다. 통과 후
중복, 긴 함수, 계층 침범 import, 불명확한 도메인 용어를 정리한다.

| 테스트 | 확인 대상 | 외부 연결 |
| --- | --- | --- |
| Domain | 상태와 순수 규칙 | 없음 |
| Mapper | ORM↔Domain 변환 | 없음 또는 임시 SQLite |
| Repository | 실제 SQL·제약조건 | 임시 SQLite |
| Service | 사용 사례와 오류 | Fake Repository·Fake MCP |
| API 통합 | 요청·응답·DI | 테스트 App·임시 SQLite |
| MCP client | 연결·응답 계약 | Fake MCP |

Repository 테스트는 임시 파일형 SQLite를, Service 테스트는 Fake Repository를
우선 쓴다. 명령은 `api/`에서 실행한다.

```bash
uv run pytest -q
uv run pytest tests/domains/review_sessions -q
uv run ruff check app main.py tests
uv run python scripts/generate_openapi.py
```

Router 또는 DTO를 바꾸면 생성된 `docs/api/openapi.json`도 함께 반영한다.

## 문제 해결

### `FOREIGN KEY constraint failed`

`reviews.session_id`의 `review_sessions` 행을 먼저 저장했는지 확인한다. 테스트에서
두 Aggregate를 만들면 검토 세션을 먼저 commit한 뒤 검토를 추가한다.

### `database is locked`

MCP·LLM 호출 중 트랜잭션을 열지 않았는지, 작업 뒤 Session을 닫았는지, 서버를
여러 worker로 실행하지 않았는지 확인한다. 현재는 단일 API 프로세스 기준이다.

### 테스트가 실제 DB를 변경한다

전역 DB URL을 직접 쓰지 않았는지 확인하고 `tests/conftest.py`의 `database`
fixture를 사용한다.

### OpenAPI 테스트가 실패한다

`uv run python scripts/generate_openapi.py`를 실행한 뒤
`docs/api/openapi.json`을 구현과 함께 반영한다.

### DB 스키마 변경이 반영되지 않는다

`create_all()`은 기존 테이블을 바꾸지 않는다. 로컬 데이터가 불필요할 때만 기존
DB를 백업한 뒤 새 DB를 사용한다. 데이터를 유지해야 하면 임의 삭제 대신 Alembic
도입을 먼저 논의한다.
