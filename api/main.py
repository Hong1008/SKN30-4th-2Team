"""WorkShield API 실행 진입점."""

from app.factory import create_app


app = create_app()


def main() -> None:
    """개발·운영 공통 ASGI 서버 실행 진입점."""
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
