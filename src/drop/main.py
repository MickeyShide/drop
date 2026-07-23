from fastapi import FastAPI

from drop.api.health import router as health_router
from drop.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        version="0.1.0",
    )

    app.include_router(health_router)

    return app


app = create_app()
