import uuid
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from drop.domain.exceptions import (
    DropConsumedError,
    DropExpiredError,
    DropNotFoundError,
    DropNotReadyError,
    FileTooLargeError,
)


def _get_request_id(request: Request) -> str:
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _build_error_response(
    status_code: int,
    code: str,
    message: str,
    request: Request,
    details: dict | list | None = None,
) -> JSONResponse:
    request_id = _get_request_id(request)
    headers = {"X-Request-ID": request_id}

    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details,
            },
            "request_id": request_id,
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DropNotFoundError)
    async def drop_not_found(request: Request, exc: DropNotFoundError) -> JSONResponse:
        return _build_error_response(
            status_code=404,
            code="DROP_NOT_FOUND",
            message="Drop not found.",
            request=request,
        )

    @app.exception_handler(DropExpiredError)
    async def drop_expired(request: Request, exc: DropExpiredError) -> JSONResponse:
        return _build_error_response(
            status_code=410,
            code="DROP_EXPIRED",
            message="This drop has expired.",
            request=request,
        )

    @app.exception_handler(DropConsumedError)
    async def drop_consumed(request: Request, exc: DropConsumedError) -> JSONResponse:
        return _build_error_response(
            status_code=410,
            code="DROP_CONSUMED",
            message="This drop has reached its download limit.",
            request=request,
        )

    @app.exception_handler(DropNotReadyError)
    async def drop_not_ready(request: Request, exc: DropNotReadyError) -> JSONResponse:
        return _build_error_response(
            status_code=409,
            code="DROP_NOT_READY",
            message="This drop is not ready.",
            request=request,
        )

    @app.exception_handler(FileTooLargeError)
    async def file_too_large(request: Request, exc: FileTooLargeError) -> JSONResponse:
        return _build_error_response(
            status_code=413,
            code="FILE_TOO_LARGE",
            message="File size exceeds maximum allowed limit.",
            request=request,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _build_error_response(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Request validation failed.",
            request=request,
            details=exc.errors(),  # type: ignore[arg-type]
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        code = "TOO_MANY_REQUESTS" if exc.status_code == 429 else "HTTP_ERROR"
        return _build_error_response(
            status_code=exc.status_code,
            code=code,
            message=str(exc.detail),
            request=request,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        return _build_error_response(
            status_code=500,
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected error occurred on the server.",
            request=request,
        )
