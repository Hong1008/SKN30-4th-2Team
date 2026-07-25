"""익명 세션에 사용할 추측 불가능한 접근 토큰을 관리한다."""

import hashlib
import hmac
import secrets
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SessionAccessToken:
    """클라이언트에 전달할 원본 토큰과 DB에 저장할 해시."""

    raw: str
    digest: str


def hash_access_token(token: str) -> str:
    """원본 접근 토큰의 SHA-256 해시를 반환한다."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_access_token() -> SessionAccessToken:
    """최소 256비트 엔트로피를 갖는 새 접근 토큰을 발급한다."""
    raw = secrets.token_urlsafe(32)
    return SessionAccessToken(raw=raw, digest=hash_access_token(raw))


def access_token_matches(token: str, expected_digest: str) -> bool:
    """타이밍 공격을 피하며 접근 토큰과 저장 해시를 비교한다."""
    return hmac.compare_digest(hash_access_token(token), expected_digest)
