from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from drop.domain.exceptions import (
    DropConsumedError,
    DropExpiredError,
    DropNotFoundError,
    DropNotReadyError,
    FileTooLargeError,
)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DropNotFoundError)
    async def drop_not_found(
        request: Request,
        exc: DropNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": "DROP_NOT_FOUND",
                    "message": "Drop not found.",
                }
            },
        )

    @app.exception_handler(DropExpiredError)
    async def drop_expired(
        request: Request,
        exc: DropExpiredError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=410,
            content={
                "error": {
                    "code": "DROP_EXPIRED",
                    "message": "This drop has expired.",
                }
            },
        )

    @app.exception_handler(DropConsumedError)
    async def drop_consumed(
        request: Request,
        exc: DropConsumedError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=410,
            content={
                "error": {
                    "code": "DROP_CONSUMED",
                    "message": "This drop has reached its download limit.",
                }
            },
        )

    @app.exception_handler(DropNotReadyError)
    async def drop_not_ready(
        request: Request,
        exc: DropNotReadyError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "DROP_NOT_READY",
                    "message": "This drop is not ready.",
                }
            },
        )

    @app.exception_handler(FileTooLargeError)
    async def file_too_large(
        request: Request,
        exc: FileTooLargeError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": "FILE_TOO_LARGE",
                    "message": "File size exceeds maximum allowed limit.",
                }
            },
        )

