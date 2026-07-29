# WorkShield 백엔드 개발 가이드

새 백엔드 작업을 시작할 때 먼저 읽는 요약 가이드다. 세부 구현 규약, 예제와
문제 해결은 [백엔드 개발 상세 참고서](./backend-ref/backend-development-reference.md)에서
필요한 항목만 확인한다.

## 작업 전 확인 순서

1. [API 초안](./api-draft.md)에서 요청·응답·오류 코드를 확인한다.
2. `api/AGENTS.md`에서 제품 경계와 보안 규칙을 확인한다.
3. 이 문서의 원칙·작업 순서·검증 목록을 따른다.
4. 구현 중에는 아래 참고서의 해당 항목만 연다.
5. 코드, OpenAPI, API 초안의 내용이 다르면 `app/` 코드 → OpenAPI → API 초안 순으로 따른다.

관련 문서:

- [API 실행 안내](../../api/README.md)
- [SQLite 영속성 결정 기록](../adr/0724-sqlite-persistence.md)
- [익명 세션 접근 제어와 임시 파일 저장소](../adr/0724-anonymous-session-file-storage.md)

## 반드시 지킬 원칙

1. 테스트를 먼저 작성한다.
2. Domain 규칙은 FastAPI·Pydantic·SQLAlchemy와 분리한다.
3. Router는 HTTP 입출력만, Service는 사용 사례와 트랜잭션, Repository는 저장만 담당한다.
4. Repository와 Router는 `commit()`·`rollback()`을 호출하지 않는다.
5. MCP·LLM 호출 중에는 DB 트랜잭션을 열어두지 않는다.
6. 세션·검토 리소스는 소유권을 먼저 검증한다. `OwnedReviewSessionDep` 또는 `OwnedReviewDep`를 사용한다.
7. 파일은 `FileStorage`로만 다룬다. 저장 경로를 조합하거나 직접 삭제하지 않는다.
8. 계약서·결과·프롬프트 본문과 비밀값을 로그·오류 응답에 넣지 않는다.
9. API 계약을 바꾸면 OpenAPI를 함께 갱신한다.
10. 환경별 접속 정보·비밀값은 `Settings`로, 배포과 함께 변경하는 기능 규칙은
    도메인별 불변 policy 객체로 관리한다.

추가 패턴(CQRS, Event Sourcing, 범용 Repository, 별도 DI 컨테이너)은 실제
필요성과 ADR 합의 전에는 도입하지 않는다.

## 빠른 구조 지도

```text
HTTP Request → Router / DTO → Application Service → Domain Rule
             → Repository Interface → SQLAlchemy Repository → SQLite
```

| 위치 | 책임 |
| --- | --- |
| `api/app/api/` | 버전별 Router와 HTTP DTO 조립 |
| `api/app/domains/` | 도메인 엔티티, Service, Repository, Mapper |
| `api/app/core/` | DB, 접근 제어, 멱등성, 파일 저장소, LLM/MCP, 공통 오류 |
| `api/app/config.py` | 설정과 `SettingsDep` |
| `api/app/lifespan.py` | DB·MCP 등 공유 자원의 수명주기 |

새 비즈니스 기능은 `domains/`에, 공통 기술 기반은 `core/`에 둔다. 계층별
import·Mapper 규칙은 [계층과 영속성](./backend-ref/backend-development-reference.md#계층과-영속성)에서 확인한다.

## 기능 추가 순서

1. API 초안과 상태 코드를 확인한다.
2. Domain 상태 전이 테스트를 작성하고 필요한 메서드만 구현한다.
3. ORM/Mapper 변경과 Repository 저장 테스트를 작성한다.
4. Fake Repository로 Service 테스트를 작성하고, 명시적인 `session.begin()` 경계를 정한다.
5. Router 통합 테스트, DTO, Router를 구현한다.
6. API 변경이면 OpenAPI를 생성하고 전체 검증한다.

작은 PR로 나누고, DB·도메인·API를 한 번에 크게 바꾸지 않는다.

## 자주 찾는 상세 규약

| 상황 | 참고 항목 |
| --- | --- |
| Domain/ORM/Mapper/Repository 구현 | [계층과 영속성](./backend-ref/backend-development-reference.md#계층과-영속성) |
| 멱등 키, 재전송, 응답 재생 | [멱등성](./backend-ref/backend-development-reference.md#멱등성idempotency) |
| SQLite 경로·스키마 변경 | [SQLite](./backend-ref/backend-development-reference.md#sqlite) |
| DB와 MCP·LLM 호출 순서 | [트랜잭션](./backend-ref/backend-development-reference.md#트랜잭션) |
| 응답 Envelope·오류 코드 | [API 응답과 오류](./backend-ref/backend-development-reference.md#api-응답과-오류) |
| Settings와 기능 policy 구분 | [Settings와 기능 policy](./backend-ref/backend-development-reference.md#settings와-기능-policy) |
| 테스트 범위·실행 명령 | [테스트와 검증](./backend-ref/backend-development-reference.md#테스트와-검증) |
| FK, lock, OpenAPI, 스키마 문제 | [문제 해결](./backend-ref/backend-development-reference.md#문제-해결) |

## PR 전 체크

- [ ] API 초안, 상태 코드, 소유권 검증 경로를 확인했다.
- [ ] Router·Service·Repository 책임과 DB/외부 호출 경계를 분리했다.
- [ ] Domain이 FastAPI·Pydantic·SQLAlchemy에 의존하지 않는다.
- [ ] Mapper 양방향과 테스트를 DB 변경에 맞춰 수정했다.
- [ ] 오류는 공통 `AppError`를 사용하고 민감 본문을 노출하지 않는다.
- [ ] 환경별 설정과 코드로 고정할 기능 policy를 구분했다.
- [ ] 테스트와 린트를 통과했고, API 변경 시 OpenAPI를 갱신했다.

## 검증 명령

모든 명령은 `api/`에서 실행한다.

```bash
uv run pytest -q
uv run ruff check app main.py tests
```

API 계약 변경 시:

```bash
uv run python scripts/generate_openapi.py
```

## 문서 역할

| 문서 | 역할 |
| --- | --- |
| `api/README.md` | 설치·실행·빠른 구조 안내 |
| 이 문서 | 작업 시작용 핵심 원칙과 체크리스트 |
| `backend-ref/backend-development-reference.md` | 구현 시 찾아보는 상세 규약·예제·문제 해결 |
| `api-draft.md` | 프론트엔드와 합의하는 REST API 계약 |
| `docs/adr/` | 기술 선택의 배경과 결과 |
| `api/AGENTS.md` | AI 에이전트의 제품 경계·보안·구현 규칙 |

구현 방식이 바뀌면 코드뿐 아니라 이 문서 또는 상세 참고서, 관련 ADR을 함께 갱신한다.
