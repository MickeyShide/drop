from collections.abc import Awaitable, Callable
import logging
import time
import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from drop.logging import request_id_var

logger = logging.getLogger("drop.api")


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("X-Request-ID")

        if not request_id or not request_id.strip():
            request_id = str(uuid.uuid4())

        request.state.request_id = request_id
        token = request_id_var.set(request_id)

        start_time = time.perf_counter()

        try:
            response = await call_next(request)
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

            logger.info(
                "HTTP Request",
                extra={
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )

            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            request_id_var.reset(token)
