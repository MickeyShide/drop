import logging

from fastapi import Request

from drop.domain.exceptions import RateLimitExceededError
from drop.infrastructure.redis import get_redis_client

logger = logging.getLogger("drop.api.rate_limit")


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Extract first IP in X-Forwarded-For chain
        return forwarded.split(",")[0].strip()

    if request.client and request.client.host:
        return request.client.host

    return "127.0.0.1"


class RateLimiter:
    def __init__(
        self,
        name: str,
        max_requests: int,
        window_seconds: int = 60,
    ) -> None:
        self.name = name
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    async def __call__(self, request: Request) -> None:
        ip = get_client_ip(request)
        key = f"rate_limit:{self.name}:{ip}"

        try:
            redis = get_redis_client()
            count = await redis.incr(key)

            if count == 1:
                await redis.expire(key, self.window_seconds)

            if count > self.max_requests:
                logger.warning(
                    "Rate limit exceeded",
                    extra={
                        "rate_limit_name": self.name,
                        "client_ip": ip,
                        "request_count": count,
                        "max_requests": self.max_requests,
                    },
                )
                raise RateLimitExceededError

        except RateLimitExceededError:
            raise
        except Exception as e:
            # Fail open if Redis is down/unreachable or loop is closed to maintain availability
            logger.warning(
                "Redis unavailable for rate limiting, failing open",
                extra={"error": str(e)},
            )


RateLimitCreate = RateLimiter(name="create", max_requests=10, window_seconds=60)
RateLimitMetadata = RateLimiter(name="metadata", max_requests=60, window_seconds=60)
RateLimitDownload = RateLimiter(name="download", max_requests=30, window_seconds=60)
