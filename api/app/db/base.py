"""모든 SQLAlchemy ORM Row가 공유하는 Declarative Base."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """WorkShield SQLite 테이블 메타데이터의 기준 클래스."""
