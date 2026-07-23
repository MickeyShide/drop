from fastapi import FastAPI

from drop.api.errors import register_exception_handlers
from drop.api.health import router as health_router
from drop.api.middleware import RequestIDMiddleware
from drop.api.routes.drops import router as drops_router
from drop.api.routes.metrics import router as metrics_router
from drop.config import get_settings
from drop.logging import setup_logging


def create_app() -> FastAPI:
    setup_logging()
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description="Ephemeral secure file sharing microservice with atomic limits and automatic cleanup.",
        version="0.1.0",
        debug=settings.debug,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(drops_router)
    app.include_router(metrics_router)

    return app


app = create_app()
