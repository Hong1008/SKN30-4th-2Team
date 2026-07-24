# WorkShield 백엔드 개발 가이드

이 문서는 WorkShield API를 함께 개발할 때 지켜야 할 구조, 구현 순서,
트랜잭션 규칙과 테스트 기준을 설명한다.

대상은 백엔드 개발자 전원이며, 비전공자도 기존 코드를 따라 기능을 추가할
수 있도록 현재 프로젝트에서 실제 사용하는 방식만 다룬다.

관련 문서:

- [API 초안](./api-draft.md)
- [SQLite 영속성 결정 기록](../adr/0724-sqlite-persistence.md)
- [API 실행 안내](../../api/README.md)

## 1. 먼저 기억할 원칙

새 기능을 개발할 때는 다음 다섯 가지를 우선 확인한다.

1. 테스트를 먼저 작성한다.
2. 도메인 규칙을 FastAPI와 SQLAlchemy에서 분리한다.
3. Router는 요청과 응답만 처리한다.
4. Repository는 `commit`과 `rollback`을 호출하지 않는다.
5. MCP·LLM 호출 중에는 DB 트랜잭션을 열어두지 않는다.

현재 프로젝트는 학습과 협업이 목적이므로 복잡한 설계 패턴을 사용하지
않는다. CQRS, Event Sourcing, 범용 Repository, 별도 DI 컨테이너는
필요해질 때까지 추가하지 않는다.

## 2. 현재 구현 범위

현재 공통 기반에는 다음 기능이 구현되어 있다.

- FastAPI 애플리케이션 팩토리와 lifespan
- `/api/v1` 라우터 진입점
- 공통 성공·오류 응답과 Request ID
- 파일형 SQLite Engine과 요청 단위 Session
- `review_sessions`, `reviews` 테이블
- 검토 세션·검토 도메인 엔티티
- ORM Row와 도메인 엔티티 Mapper
- 도메인별 Repository
- LLM과 WorkShield MCP 연결

아직 구현하지 않은 범위:

- 업로드·유형 선택·검토 API Router와 Pydantic DTO
- Application Service
- 파일 검증과 임시 파일 수명주기
- 검토 작업 실행기
- 결과 정규화
- SSE

구현되지 않은 계층을 예시 코드와 혼동하지 않도록 주의한다. 이 문서의
Application Service와 Router 예시는 이후 기능 개발 시 적용할 규칙이다.

## 3. 요청 처리 구조

기능 하나는 다음 방향으로 호출된다.

```text
HTTP Request
    ↓
Router / Pydantic DTO
    ↓
Application Service
    ↓
Domain Entity / Rule
    ↓
Repository Interface
    ↓
SQLAlchemy Repository
    ↓
Mapper
    ↓
ORM Row / SQLite
```

응답은 반대 방향으로 올라온다.

각 계층은 바로 아래 계층의 역할만 알아야 한다. 예를 들어 Router가
`ReviewSessionRow`를 직접 조회하거나 Domain Entity가 `Session`을
import하면 계층이 섞인 것이다.

## 4. 프로젝트 구조와 책임

```text
api/app/
├── factory.py
├── lifespan.py
├── config.py
├── api/
│   ├── router.py
│   ├── system.py
│   └── v1/
│       └── router.py
├── common/
│   ├── errors.py
│   ├── exception_handlers.py
│   ├── request_id.py
│   └── responses.py
├── db/
│   ├── base.py
│   ├── database.py
│   ├── dependencies.py
│   └── models.py
├── review_sessions/
│   ├── domain.py
│   ├── mapper.py
│   └── repository.py
├── reviews/
│   ├── domain.py
│   ├── mapper.py
│   └── repository.py
└── llm/
```

| 위치 | 책임 |
| --- | --- |
| `factory.py` | FastAPI 앱과 공통 미들웨어·예외 처리 등록 |
| `lifespan.py` | SQLite와 MCP 연결의 시작·종료 |
| `config.py` | 환경 설정과 `SettingsDep` |
| `api/` | 시스템 API와 버전별 Router 조립 |
| `common/` | 공통 응답·오류·Request ID |
| `db/` | Engine, Session, ORM Row |
| `*/domain.py` | 순수 도메인 Enum과 Entity |
| `*/mapper.py` | ORM Row와 Domain Entity 변환 |
| `*/repository.py` | 도메인별 저장 계약과 SQLAlchemy 구현 |
| `llm/` | 기존 LLM provider와 WorkShield MCP 연결 |

기능이 추가되면 해당 도메인 패키지에 `schemas.py`, `service.py`,
`router.py`, `dependencies.py`를 필요한 시점에 추가한다. 사용하지 않는
빈 파일을 미리 만들지 않는다.

## 5. 계층별 구현 규칙

### 5.1 Domain Entity

도메인 엔티티는 비즈니스 상태와 규칙을 표현한다.

허용하는 import:

- Python 표준 라이브러리
- 같은 도메인의 순수 타입

사용하지 않는 import:

- FastAPI
- Pydantic
- SQLAlchemy
- MCP·LLM client

현재 예시는 `app/review_sessions/domain.py`와
`app/reviews/domain.py`에서 확인할 수 있다.

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

상태 문자열은 코드 여러 곳에 직접 입력하지 않고 `StrEnum`으로 정의한다.

### 5.2 ORM Row

ORM Row는 SQLite 테이블 모양만 표현한다. 비즈니스 판단을 넣지 않는다.

```python
class ReviewRow(Base):
    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[str] = mapped_column(String(32))
```

ORM Row에 다음 기능을 넣지 않는다.

- 상태 전이
- 사용자 권한 판단
- MCP 호출
- API 응답 생성
- 오류 메시지 결정

현재 ORM Row는 `app/db/models.py`에서 관리한다. 테이블이 많아져 파일을
읽기 어려워질 때 도메인별 파일로 분리한다.

### 5.3 Mapper

Mapper는 ORM Row와 Domain Entity를 명시적으로 변환한다.

```text
review_to_row()
review_from_row()
update_review_row()
```

Mapper를 두는 이유:

- Domain Entity가 SQLAlchemy를 몰라도 된다.
- DB 컬럼과 API·도메인 이름을 독립적으로 변경할 수 있다.
- Enum과 JSON, UTC 시간 변환을 한곳에서 처리할 수 있다.

DB 컬럼을 추가하면 다음 네 곳을 함께 확인한다.

1. Domain Entity
2. ORM Row
3. Mapper의 생성·조회·갱신 함수
4. Mapper와 Repository 테스트

### 5.4 Repository

Repository는 도메인에서 필요한 저장 기능만 제공한다.

```python
class ReviewRepository(Protocol):
    def add(self, entity: Review) -> None: ...
    def get(self, review_id: str) -> Review | None: ...
    def save(self, entity: Review) -> None: ...
```

구현체는 SQLAlchemy Session과 Mapper를 사용한다.

```python
class SqlAlchemyReviewRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, entity: Review) -> None:
        self._session.add(review_to_row(entity))
```

Repository 규칙:

- `commit()`을 호출하지 않는다.
- `rollback()`을 호출하지 않는다.
- FastAPI `HTTPException`을 발생시키지 않는다.
- Pydantic DTO를 받거나 반환하지 않는다.
- MCP·LLM을 호출하지 않는다.
- 조회 결과는 Domain Entity로 반환한다.

저장 대상을 찾지 못한 경우 Repository는 `None`이나 저장 계층 오류를
반환하고, 사용자에게 보여줄 오류 코드는 Application Service가 결정한다.

### 5.5 Application Service

Application Service는 하나의 사용자 행동을 완성한다.

예:

- 계약 유형 선택
- 범위 외 계속 진행 확인
- 검토 요청 접수
- 재시도 요청

Application Service의 책임:

- Repository 조회와 저장
- 도메인 규칙 실행
- 트랜잭션 경계 결정
- MCP·LLM 호출 순서 제어
- 저장 계층 오류를 애플리케이션 오류로 변환

Application Service는 `Request`, `Response`, `HTTPException`을 사용하지
않는다.

### 5.6 Router와 Schema

Router는 다음 일만 처리한다.

1. Path, Query, Body, Header를 Pydantic DTO로 검증한다.
2. FastAPI Dependency로 Service나 Session을 받는다.
3. Application Service를 호출한다.
4. 결과를 API DTO와 공통 응답으로 변환한다.

```python
@router.get("/review-sessions/{session_id}")
async def get_review_session(
    request: Request,
    session_id: str,
    session: DbSessionDep,
) -> ApiResponse[ReviewSessionResponse]:
    service = ReviewSessionService(
        repository=SqlAlchemyReviewSessionRepository(session),
    )
    result = service.get(session_id)
    return success_response(request, ReviewSessionResponse.from_domain(result))
```

라우터에서 `select()`, `session.get()`, `session.commit()`을 직접 호출하지
않는다.

## 6. 파일형 SQLite 사용법

기본 DB 경로:

```text
api/data/workshield.db
```

설정:

```dotenv
DATABASE_URL=sqlite+pysqlite:///./data/workshield.db
DATABASE_ECHO=false
```

`app/lifespan.py`는 서버 시작 시 Engine과 테이블을 만들고 종료 시 연결
풀을 정리한다. `app/db/database.py`는 상대 경로를 `api/` 기준 절대경로로
바꾼다.

SQLite DB 파일과 보조 파일은 Git에 올리지 않는다.

```text
api/data/*.db
api/data/*.db-*
```

테스트는 실제 서비스 DB를 사용하지 않는다. `tests/conftest.py`가 테스트별
임시 디렉터리에 별도의 SQLite 파일을 생성한다.

### 스키마 변경

현재는 `Base.metadata.create_all()`을 사용한다. 기존 컬럼의 타입 변경,
이름 변경, 삭제는 `create_all()`이 처리하지 않는다.

다음 상황이 생기면 Alembic 도입을 검토한다.

- 기존 데이터를 유지하며 컬럼을 변경해야 한다.
- 시연·운영 데이터 보존이 필요하다.
- 배포 환경에서 스키마 버전을 추적해야 한다.

그전까지는 ORM Row와 새 DB 파일을 기준으로 개발한다.

## 7. 트랜잭션 규칙

### 7.1 책임 위치

| 계층 | commit/rollback |
| --- | --- |
| Router | 금지 |
| Domain Entity | 금지 |
| Mapper | 금지 |
| Repository | 금지 |
| Application Service | 트랜잭션 경계 관리 |
| DB Session 의존성 | 예외 전파 시 안전한 rollback과 close |

기본 방식은 트랜잭션 범위가 코드에 보이는 `session.begin()`이다.

```python
with session.begin():
    entity = repository.get(session_id)
    if entity is None:
        raise NotFoundError(
            code="SESSION_NOT_FOUND",
            message="검토 세션을 찾을 수 없습니다.",
        )
    entity.state = ReviewSessionState.READY_TO_REVIEW
    repository.save(entity)
```

`with` 블록이 정상 종료되면 commit하고, 예외가 발생하면 rollback한다.

### 7.2 MCP·LLM 호출과 트랜잭션 분리

외부 호출을 DB 트랜잭션 안에서 기다리지 않는다.

잘못된 예:

```python
with session.begin():
    entity.state = ReviewState.REVIEWING
    repository.save(entity)
    result = await mcp.review(...)  # 긴 호출 동안 DB transaction 유지
```

권장 흐름:

```python
with session.begin():
    entity.state = ReviewState.REVIEWING
    repository.save(entity)

result = await mcp.review(...)

with session.begin():
    entity = repository.get(review_id)
    entity.state = ReviewState.COMPLETED
    entity.result = result
    repository.save(entity)
```

### 7.3 트랜잭션 데코레이터

트랜잭션 데코레이터는 구현할 수 있지만 현재는 사용하지 않는다.

이유:

- 실제 commit 범위가 함수 선언 아래에 숨는다.
- MCP·LLM 호출까지 실수로 감싸기 쉽다.
- 중첩 트랜잭션과 재사용 Session 동작을 이해하기 어렵다.
- 동기 DB와 비동기 외부 호출이 섞인 메서드에서 경계가 불명확해진다.

팀원이 `session.begin()` 사용에 충분히 익숙해지고 반복 코드가 실제로
문제가 된 뒤 도입을 검토한다. 도입할 경우에도 DB 작업만 수행하는
Application Service 메서드에 한정하고 ADR로 결정한다.

## 8. 공통 API 응답과 오류

`/api/v1`의 JSON 성공 응답:

```json
{
  "data": {},
  "meta": {
    "request_id": "req_...",
    "timestamp": "2026-07-24T09:00:00Z"
  }
}
```

오류 응답:

```json
{
  "error": {
    "code": "SESSION_NOT_FOUND",
    "message": "검토 세션을 찾을 수 없습니다.",
    "field": null,
    "retryable": false,
    "next_action": "START_NEW_REVIEW",
    "details": {}
  },
  "meta": {
    "request_id": "req_...",
    "timestamp": "2026-07-24T09:00:00Z"
  }
}
```

Application Service는 `app/common/errors.py`의 오류를 사용한다.

```python
raise NotFoundError(
    code="SESSION_NOT_FOUND",
    message="검토 세션을 찾을 수 없습니다.",
    next_action="START_NEW_REVIEW",
)
```

FastAPI 예외 처리기가 HTTP 상태와 공통 오류 응답으로 변환한다.

금지 사항:

- Router나 Service에서 임의 JSON 오류 응답 생성
- 계약서·조항·프롬프트를 `details`에 포함
- 스택 트레이스나 내부 파일 경로 노출
- 사용자 분기에 `message`나 `label` 사용

사용자 분기는 항상 안정적인 `code`로 처리한다.

## 9. TDD 개발 순서

모든 기능은 Red → Green → Refactor 순서로 구현한다.

### 9.1 Red

구현할 동작을 작은 테스트로 먼저 작성한다.

예:

- 현재 상태에서 계약 유형을 선택할 수 있다.
- 만료된 세션은 선택할 수 없다.
- Repository는 선택 유형을 저장한다.
- 다른 세션의 idempotency key는 충돌하지 않는다.
- API 오류가 공통 Envelope를 사용한다.

테스트가 의도한 이유로 실패하는지 확인한다.

```bash
uv run pytest tests/review_sessions/test_service.py -q
```

Import 오류만 확인하고 끝내지 않는다. 최소 구조를 만든 뒤 비즈니스
조건 때문에 테스트가 실패하는 단계까지 확인하는 것이 좋다.

### 9.2 Green

테스트를 통과시키는 가장 작은 코드를 작성한다.

- 미래 기능을 미리 만들지 않는다.
- 요구사항에 없는 상태나 필드를 추가하지 않는다.
- 같은 코드를 두 번 썼다는 이유만으로 바로 공통화하지 않는다.

### 9.3 Refactor

테스트가 통과한 상태에서 다음을 정리한다.

- 중복된 이름과 변환
- 너무 긴 함수
- 계층을 침범한 import
- 불명확한 도메인 용어

Refactor 후 전체 테스트와 린트를 다시 실행한다.

## 10. 기능 하나를 추가하는 실제 순서

예를 들어 “계약 유형 선택”을 구현한다면 다음 순서로 작업한다.

1. API 초안에서 요청·응답·오류 코드를 확인한다.
2. Domain Entity 상태 전이 테스트를 작성한다.
3. 필요한 도메인 메서드만 구현한다.
4. Repository 저장 테스트를 작성한다.
5. ORM 컬럼이나 Mapper 변경이 필요하면 함께 수정한다.
6. Application Service 테스트를 Fake Repository로 작성한다.
7. Service를 구현하고 트랜잭션 범위를 정한다.
8. Router 통합 테스트를 작성한다.
9. Pydantic DTO와 Router를 구현한다.
10. OpenAPI를 갱신하고 전체 검증한다.

새 기능 PR에서 DB, 도메인, API를 한 번에 크게 변경하지 않는다. 가능한
한 위 순서에 따라 작게 나누어 리뷰한다.

## 11. 테스트 종류와 위치

```text
api/tests/
├── common/
├── db/
├── review_sessions/
├── reviews/
├── llm/
├── conftest.py
├── test_config.py
├── test_main.py
└── test_openapi.py
```

| 테스트 | 확인 대상 | 외부 연결 |
| --- | --- | --- |
| Domain 단위 테스트 | 상태와 순수 규칙 | 없음 |
| Mapper 테스트 | ORM↔Domain 변환 | 없음 또는 임시 SQLite |
| Repository 테스트 | 실제 SQL, 제약조건 | 임시 SQLite |
| Service 단위 테스트 | 사용 사례와 오류 | Fake Repository·Fake MCP |
| API 통합 테스트 | 요청·응답·DI | 테스트 App과 임시 SQLite |
| MCP client 테스트 | 연결·응답 계약 | Fake MCP |

Repository 테스트는 Mock DB 대신 임시 파일형 SQLite를 사용한다. 서비스
단위 테스트에서는 DB보다 Fake Repository를 우선 사용해 비즈니스 흐름에
집중한다.

## 12. 실행 명령

모든 명령은 `api/` 디렉터리에서 실행한다.

```bash
cd api
```

전체 테스트:

```bash
uv run pytest -q
```

특정 도메인 테스트:

```bash
uv run pytest tests/review_sessions -q
uv run pytest tests/reviews -q
```

린트:

```bash
uv run ruff check app main.py tests
```

OpenAPI 생성:

```bash
uv run python scripts/generate_openapi.py
```

전체 검증:

```bash
uv run pytest -q
uv run ruff check app main.py tests
```

## 13. 자주 발생하는 문제

### `FOREIGN KEY constraint failed`

`reviews.session_id`에 해당하는 `review_sessions` 행이 먼저 저장됐는지
확인한다. 사용자 흐름에서도 검토 세션 생성이 검토 생성보다 먼저다.

테스트에서 두 Aggregate를 한 번에 만들 경우 검토 세션을 먼저 commit한
뒤 검토를 추가한다.

### `database is locked`

다음을 확인한다.

- MCP·LLM 호출 중 트랜잭션을 열어두지 않았는가?
- `Session`을 요청이나 작업 종료 후 닫았는가?
- 서버를 여러 worker로 실행하지 않았는가?

현재 프로젝트는 단일 API 프로세스를 기준으로 한다.

### 테스트가 실제 DB 데이터를 변경한다

테스트에서 전역 설정의 DB URL을 직접 사용하지 않았는지 확인한다.
Repository 테스트는 `tests/conftest.py`의 `database` fixture를 사용한다.

### OpenAPI 테스트가 실패한다

Router나 Pydantic DTO 변경 후 다음 명령을 실행한다.

```bash
uv run python scripts/generate_openapi.py
```

생성된 `docs/api/openapi.json`을 구현과 함께 반영한다.

### DB 스키마 변경이 반영되지 않는다

`create_all()`은 기존 테이블을 수정하지 않는다. 로컬 개발 데이터가
필요하지 않다면 기존 DB 파일을 백업한 뒤 새 DB로 실행한다. 데이터를
유지해야 한다면 임의로 파일을 삭제하지 말고 Alembic 도입 여부를 먼저
논의한다.

## 14. 금지 사항

- Domain에서 FastAPI, Pydantic, SQLAlchemy import
- Router에서 SQLAlchemy 직접 조회
- Repository에서 commit 또는 rollback
- Repository에서 HTTP 응답·오류 결정
- 외부 호출 동안 DB 트랜잭션 유지
- 상태·오류 코드를 문자열로 여러 파일에 중복 정의
- 계약서·결과·프롬프트 본문 로그 기록
- 사용자 파일명을 저장 경로로 직접 사용
- `api/data/*.db` Git 커밋
- OpenAPI 파일을 갱신하지 않은 API 계약 변경
- 테스트 없이 상태 전이 또는 DB 제약조건 변경

## 15. PR 체크리스트

### 설계

- [ ] API 초안과 상태 코드를 확인했다.
- [ ] 변경할 Domain Entity와 Aggregate를 정했다.
- [ ] Router, Service, Repository 책임이 섞이지 않았다.
- [ ] MCP·LLM과 DB 트랜잭션 경계를 분리했다.

### 구현

- [ ] 실패하는 테스트를 먼저 작성했다.
- [ ] Domain은 FastAPI·Pydantic·SQLAlchemy에 의존하지 않는다.
- [ ] ORM 변경을 Mapper 양방향에 반영했다.
- [ ] Repository는 commit·rollback하지 않는다.
- [ ] 오류 응답은 공통 `AppError`를 사용한다.
- [ ] 계약서·결과 본문을 로그나 오류에 포함하지 않는다.

### 검증

- [ ] `uv run pytest -q`가 통과한다.
- [ ] `uv run ruff check app main.py tests`가 통과한다.
- [ ] API 변경 시 OpenAPI를 갱신했다.
- [ ] README 또는 개발 가이드 변경이 필요한지 확인했다.

## 16. 문서 관리

문서 역할을 다음처럼 나눈다.

| 문서 | 역할 |
| --- | --- |
| `api/README.md` | 설치, 실행, 빠른 구조 안내 |
| `docs/api/backend-development-guide.md` | 팀 공통 개발 방법 |
| `docs/api/api-draft.md` | 프론트엔드와 합의하는 REST API 계약 |
| `docs/adr/` | 기술 선택의 배경과 결과 |
| `api/AGENTS.md` | AI 에이전트가 지켜야 할 구현 규칙 |

구현 방식이 바뀌면 코드만 수정하지 말고 이 가이드와 관련 ADR을 함께
갱신한다.
