from fastapi import FastAPI

from drop.api.health import router as health_router
from drop.api.routes.drops import router as drops_router
from drop.config import get_settings
from drop.api.errors import register_exception_handlers


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        version="0.1.0",
    )

    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(drops_router)

    return app


app = create_app()
