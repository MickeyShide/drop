import ipaddress
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from redis.exceptions import RedisError

from drop.api.errors import register_exception_handlers
from drop.api.rate_limit import (
    _RATE_LIMIT_SCRIPT,
    _rate_limit_policies,
    RateLimiter,
    RateLimitScope,
    get_client_ip,
)
from drop.config import get_settings
from drop.domain.exceptions import RateLimitExceededError


class LuaRedisDouble:
    """Small Redis double implementing the rate-limit Lua contract used in production."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.ttls: dict[str, int] = {}
        self.bans: dict[str, int] = {}
        self.calls: list[tuple[object, ...]] = []

    async def eval(self, script: str, numkeys: int, *args: object) -> list[int]:
        assert script == _RATE_LIMIT_SCRIPT
        assert numkeys == 2
        self.calls.append(args)

        key, ban_key, window, limit, ban_seconds, cost = args
        assert isinstance(key, str)
        assert isinstance(ban_key, str)
        assert all(
            isinstance(value, int) for value in (window, limit, ban_seconds, cost)
        )
        assert isinstance(window, int)
        assert isinstance(limit, int)
        assert isinstance(ban_seconds, int)
        assert isinstance(cost, int)

        if ban_key in self.bans:
            return [-1, self.bans[ban_key]]

        current = self.counts.get(key, 0) + cost
        self.counts[key] = current
        ttl = self.ttls.get(key, -2)
        if current == cost or ttl < 0:
            ttl = window
            self.ttls[key] = ttl

        if ban_seconds > 0 and current > limit:
            self.bans[ban_key] = ban_seconds
            return [-1, ban_seconds]
        return [current, ttl]


def make_request(
    *,
    peer: str | None = "198.51.100.1",
    headers: dict[str, str] | None = None,
    public_id: str = "drop-123",
    cookies: dict[str, str] | None = None,
) -> MagicMock:
    request = MagicMock(spec=Request)
    request.headers = headers or {}
    request.path_params = {"public_id": public_id}
    request.cookies = cookies or {}
    request.client = None if peer is None else MagicMock(host=peer)
    return request


def test_get_client_ip_uses_valid_forwarded_for_from_trusted_proxy() -> None:
    request = make_request(
        peer="127.0.0.1",
        headers={"X-Forwarded-For": "203.0.113.195, 70.41.3.18"},
    )
    networks = (ipaddress.ip_network("127.0.0.1/32"),)
    with patch("drop.api.rate_limit.trusted_proxy_networks", return_value=networks):
        assert get_client_ip(request) == "203.0.113.195"


def test_get_client_ip_ignores_invalid_forwarded_for() -> None:
    request = make_request(
        peer="127.0.0.1",
        headers={"X-Forwarded-For": "not-an-ip", "X-Real-IP": "also-not-an-ip"},
    )
    networks = (ipaddress.ip_network("127.0.0.1/32"),)
    with patch("drop.api.rate_limit.trusted_proxy_networks", return_value=networks):
        assert get_client_ip(request) == "127.0.0.1"


def test_get_client_ip_uses_valid_real_ip_from_trusted_proxy() -> None:
    request = make_request(
        peer="127.0.0.1",
        headers={"X-Forwarded-For": "not-an-ip", "X-Real-IP": "203.0.113.195"},
    )
    networks = (ipaddress.ip_network("127.0.0.1/32"),)
    with patch("drop.api.rate_limit.trusted_proxy_networks", return_value=networks):
        assert get_client_ip(request) == "203.0.113.195"


def test_get_client_ip_ignores_headers_from_untrusted_peer() -> None:
    request = make_request(
        peer="198.51.100.1",
        headers={"X-Forwarded-For": "203.0.113.195"},
    )
    assert get_client_ip(request) == "198.51.100.1"


def test_get_client_ip_returns_unknown_without_peer() -> None:
    assert get_client_ip(make_request(peer=None)) == "unknown"


@pytest.mark.asyncio
async def test_byte_cost_sets_ttl_and_is_passed_to_lua() -> None:
    limiter = RateLimiter(name="upload_bytes", max_requests=100, window_seconds=60)
    redis = LuaRedisDouble()

    with patch("drop.api.rate_limit.get_redis_client", return_value=redis):
        await limiter.check(make_request(), cost=50)

    key = next(iter(redis.counts))
    assert redis.counts[key] == 50
    assert redis.ttls[key] == 60
    assert redis.calls[0][-1] == 50
    assert "current == cost" in _RATE_LIMIT_SCRIPT


@pytest.mark.asyncio
async def test_rate_limiter_returns_retry_after_when_limit_is_exceeded() -> None:
    limiter = RateLimiter(name="test_route", max_requests=2, window_seconds=60)
    redis = LuaRedisDouble()

    with patch("drop.api.rate_limit.get_redis_client", return_value=redis):
        await limiter.check(make_request())
        await limiter.check(make_request())
        with pytest.raises(RateLimitExceededError) as exc_info:
            await limiter.check(make_request())

    assert exc_info.value.retry_after == 60


@pytest.mark.asyncio
async def test_temporary_ban_is_enforced_by_lua_contract() -> None:
    limiter = RateLimiter(
        name="invalid_token",
        max_requests=1,
        window_seconds=60,
        ban_seconds=120,
    )
    redis = LuaRedisDouble()

    with patch("drop.api.rate_limit.get_redis_client", return_value=redis):
        await limiter.check(make_request())
        with pytest.raises(RateLimitExceededError) as first_error:
            await limiter.check(make_request())
        with pytest.raises(RateLimitExceededError) as banned_error:
            await limiter.check(make_request())

    assert first_error.value.retry_after == 120
    assert banned_error.value.retry_after == 120
    assert len(redis.calls) == 3


@pytest.mark.asyncio
async def test_session_drop_scope_does_not_include_ip() -> None:
    limiter = RateLimiter(
        name="download_per_session",
        max_requests=10,
        window_seconds=60,
        scope=RateLimitScope.SESSION_DROP,
    )
    redis = LuaRedisDouble()

    with patch("drop.api.rate_limit.get_redis_client", return_value=redis):
        await limiter.check(make_request(peer="198.51.100.1"), session_id="session-1")
        await limiter.check(make_request(peer="203.0.113.2"), session_id="session-1")

    assert len(redis.counts) == 1
    assert next(iter(redis.counts.values())) == 2


@pytest.mark.asyncio
async def test_ip_drop_scope_partitions_by_drop() -> None:
    limiter = RateLimiter(
        name="download_per_drop",
        max_requests=10,
        window_seconds=60,
        scope=RateLimitScope.IP_DROP,
    )
    redis = LuaRedisDouble()

    with patch("drop.api.rate_limit.get_redis_client", return_value=redis):
        await limiter.check(make_request(public_id="drop-a"))
        await limiter.check(make_request(public_id="drop-b"))

    assert len(redis.counts) == 2


@pytest.mark.asyncio
async def test_rate_limiter_fails_open_when_configured() -> None:
    limiter = RateLimiter(
        name="metadata",
        max_requests=2,
        window_seconds=60,
        fail_closed=False,
    )
    redis = AsyncMock(spec=Redis)
    redis.eval.side_effect = RedisError("Connection refused")

    with patch("drop.api.rate_limit.get_redis_client", return_value=redis):
        await limiter.check(make_request())


@pytest.mark.asyncio
async def test_rate_limiter_fails_closed_on_security_routes() -> None:
    limiter = RateLimiter(name="download", max_requests=2, window_seconds=60)
    redis = AsyncMock(spec=Redis)
    redis.eval.side_effect = RedisError("Connection refused")

    with patch("drop.api.rate_limit.get_redis_client", return_value=redis):
        with pytest.raises(HTTPException) as exc_info:
            await limiter.check(make_request())

    assert exc_info.value.status_code == 503


def test_rate_limiter_rejects_invalid_configuration() -> None:
    with pytest.raises(ValueError, match="max_requests"):
        RateLimiter(name="test", max_requests=0, window_seconds=60)
    with pytest.raises(ValueError, match="window_seconds"):
        RateLimiter(name="test", max_requests=1, window_seconds=0)
    with pytest.raises(ValueError, match="ban_seconds"):
        RateLimiter(name="test", max_requests=1, window_seconds=60, ban_seconds=-1)


@pytest.mark.asyncio
async def test_rate_limiter_rejects_non_positive_cost() -> None:
    limiter = RateLimiter(name="test", max_requests=1, window_seconds=60)
    with pytest.raises(ValueError, match="cost"):
        await limiter.check(make_request(), cost=0)


def test_create_policy_uses_create_configuration() -> None:
    settings = get_settings()
    _rate_limit_policies.cache_clear()
    assert _rate_limit_policies().create.max_requests == settings.rate_limit_create_max
    assert (
        _rate_limit_policies().create.window_seconds
        == settings.rate_limit_create_window
    )


def test_rate_limit_response_includes_retry_after() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/limited")
    async def limited() -> None:
        raise RateLimitExceededError(retry_after=37)

    response = TestClient(app).get("/limited")
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "37"
