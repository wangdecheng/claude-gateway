"""Cloude Gateway — Entry Point.

Run with: uv run uvicorn server:app --host 0.0.0.0 --port 8082
"""

from api.app import create_app

app = create_app()

__all__ = ["app"]

if __name__ == "__main__":
    import uvicorn

    from config.settings import get_settings

    settings = get_settings()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="debug")
