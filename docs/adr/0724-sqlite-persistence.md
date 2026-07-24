# 0724 파일형 SQLite와 영속성 계층

- 상태: 승인됨
- 날짜: 2026-07-24

## 맥락

WorkShield는 부트캠프 5인 팀 프로젝트이며 API 서버를 여러 대 운영하지
않는다. 팀에는 비전공자가 포함되어 있어 DB 구성과 트랜잭션 동작을 쉽게
이해하고 테스트할 수 있어야 한다.

검토 세션과 비동기 검토 상태는 새로고침 후 복구해야 한다. 인메모리 DB는
프로세스가 종료되면 모든 상태가 사라지므로 시연과 디버깅에 불편하다.

동시에 Domain Entity가 FastAPI나 SQLAlchemy에 직접 의존하지 않도록
최소한의 DDD 계층을 유지해야 한다.

## 결정

### SQLite

- 파일형 SQLite를 사용한다.
- 기본 경로는 `api/data/workshield.db`다.
- SQLAlchemy 2.x 동기 API를 사용한다.
- 서버 시작 시 `Base.metadata.create_all()`로 테이블을 준비한다.
- 연결마다 `PRAGMA foreign_keys=ON`을 적용한다.
- SQLite DB 파일과 보조 파일은 Git으로 추적하지 않는다.

### 테이블

MVP에서는 다음 두 테이블만 사용한다.

- `review_sessions`: 파일, 범위 판별, 계약 유형 선택 상태
- `reviews`: 검토 상태, 진행 정보, 결과·오류 스냅샷

결과 배열은 별도 테이블로 정규화하지 않고 `reviews.result` JSON 컬럼에
임시 저장한다.

### DDD 영속성 경계

- Domain Entity는 SQLAlchemy를 import하지 않는다.
- ORM Row는 테이블 구조만 표현한다.
- Mapper가 ORM Row와 Domain Entity를 양방향으로 변환한다.
- 도메인별 Repository Protocol과 SQLAlchemy 구현을 둔다.
- 범용 Repository는 만들지 않는다.

### 트랜잭션

- Repository는 `commit`과 `rollback`을 호출하지 않는다.
- Application Service가 트랜잭션 경계를 관리한다.
- 기본 방식은 `with session.begin()`이다.
- MCP·LLM 호출 중에는 DB 트랜잭션을 유지하지 않는다.
- 트랜잭션 데코레이터는 현재 도입하지 않는다.

### 마이그레이션

초기 MVP에서는 Alembic을 도입하지 않는다. 기존 데이터를 유지하며
스키마를 변경해야 할 때 다시 검토한다.

## 결과

장점:

- 서버 재시작 후에도 검토 상태를 복구할 수 있다.
- 별도 DB 서버 없이 팀원 모두 같은 방식으로 실행할 수 있다.
- Repository 테스트가 실제 SQLite 제약조건을 검증한다.
- 도메인 규칙과 저장 기술의 경계가 명확하다.

제약:

- 다중 API 서버와 높은 동시성을 지원하지 않는다.
- `create_all()`은 기존 테이블의 컬럼 변경과 삭제를 처리하지 않는다.
- JSON 컬럼 내부 조건으로 복잡한 통계를 만들기 어렵다.
- 장시간 트랜잭션은 SQLite 잠금 오류를 만들 수 있다.

## 재검토 조건

다음 중 하나가 발생하면 PostgreSQL, Alembic 또는 트랜잭션 추상화를
재검토한다.

- API 서버를 여러 대 실행한다.
- 동시 검토 요청이 크게 증가한다.
- 기존 데이터를 보존하며 스키마를 변경해야 한다.
- 결과 항목을 DB에서 복잡하게 검색·집계해야 한다.
- `session.begin()` 반복이 실제 유지보수 문제로 확인된다.
