from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request
from redis.exceptions import RedisError

from drop.api.rate_limit import RateLimiter, get_client_ip
from drop.domain.exceptions import RateLimitExceededError


def test_get_client_ip_from_x_forwarded_for() -> None:
    request = MagicMock(spec=Request)
    request.headers = {"X-Forwarded-For": "203.0.113.195, 70.41.3.18, 150.172.238.178"}
    assert get_client_ip(request) == "203.0.113.195"


def test_get_client_ip_from_client_host() -> None:
    request = MagicMock(spec=Request)
    request.headers = {}
    request.client.host = "198.51.100.1"
    assert get_client_ip(request) == "198.51.100.1"


def test_get_client_ip_fallback() -> None:
    request = MagicMock(spec=Request)
    request.headers = {}
    request.client = None
    assert get_client_ip(request) == "127.0.0.1"


@pytest.mark.asyncio
async def test_rate_limiter_exceeded_raises_exception() -> None:
    limiter = RateLimiter(name="test_route", max_requests=2, window_seconds=60)
    request = MagicMock(spec=Request)
    request.headers = {}
    request.client.host = "192.0.2.45"

    mock_redis = AsyncMock()
    mock_redis.incr.return_value = 3  # Count exceeds limit of 2

    with patch("drop.api.rate_limit.get_redis_client", return_value=mock_redis):
        with pytest.raises(RateLimitExceededError):
            await limiter(request)


@pytest.mark.asyncio
async def test_rate_limiter_fails_open_on_redis_error() -> None:
    limiter = RateLimiter(name="test_route", max_requests=2, window_seconds=60)
    request = MagicMock(spec=Request)
    request.headers = {}
    request.client.host = "192.0.2.45"

    mock_redis = AsyncMock()
    mock_redis.incr.side_effect = RedisError("Connection refused")

    with patch("drop.api.rate_limit.get_redis_client", return_value=mock_redis):
        # Should not raise RateLimitExceededError or RedisError (fails open)
        await limiter(request)
