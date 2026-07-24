import hashlib
import ipaddress
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache

from fastapi import HTTPException, Request, status
from redis.asyncio import Redis

from drop.config import get_settings
from drop.domain.exceptions import RateLimitExceededError
from drop.domain.security import pseudonymize_ip
from drop.infrastructure.redis import get_redis_client
from drop.metrics import RATE_LIMITED_REQUESTS_TOTAL

logger = logging.getLogger("drop.api.rate_limit")

TrustedProxyNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

_RATE_LIMIT_SCRIPT = """
local banned = redis.call('EXISTS', KEYS[2])
if banned == 1 then
    return {-1, math.max(redis.call('TTL', KEYS[2]), 0)}
end

local window_seconds = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local ban_seconds = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
local current = redis.call('INCRBY', KEYS[1], cost)
local ttl = redis.call('TTL', KEYS[1])

if current == cost or ttl < 0 then
    redis.call('EXPIRE', KEYS[1], window_seconds)
    ttl = window_seconds
end

if ban_seconds > 0 and current > limit then
    redis.call('SET', KEYS[2], '1', 'EX', ban_seconds)
    return {-1, ban_seconds}
end

return {current, math.max(ttl, 0)}
"""


class RateLimitScope(StrEnum):
    IP = "ip"
    IP_DROP = "ip_drop"
    SESSION_DROP = "session_drop"


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_ip(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


@lru_cache
def trusted_proxy_networks() -> tuple[TrustedProxyNetwork, ...]:
    configured = get_settings().trusted_proxy_ips
    networks: list[TrustedProxyNetwork] = []

    for raw_value in configured.split(","):
        value = raw_value.strip()
        if not value:
            continue
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            logger.warning("Ignoring invalid trusted proxy configuration")

    return tuple(networks)


def _is_trusted_proxy(peer: str) -> bool:
    address = _normalize_ip(peer)
    if address is None:
        return False
    normalized_address = ipaddress.ip_address(address)
    return any(normalized_address in network for network in trusted_proxy_networks())


def get_client_ip(request: Request) -> str:
    """Return a validated client address, honoring forwarded headers only from trusted peers."""
    client = request.client
    peer = _normalize_ip(client.host if client else None)
    if peer is None:
        return "unknown"

    if not _is_trusted_proxy(peer):
        return peer

    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        forwarded_ip = _normalize_ip(forwarded.split(",", 1)[0])
        if forwarded_ip is not None:
            return forwarded_ip

    real_ip = _normalize_ip(request.headers.get("X-Real-IP"))
    if real_ip is not None:
        return real_ip

    return peer


class RateLimiter:
    def __init__(
        self,
        *,
        name: str,
        max_requests: int,
        window_seconds: int,
        scope: RateLimitScope = RateLimitScope.IP,
        fail_closed: bool = True,
        ban_seconds: int = 0,
    ) -> None:
        if max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if ban_seconds < 0:
            raise ValueError("ban_seconds cannot be negative")

        self.name = name
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.scope = scope
        self.fail_closed = fail_closed
        self.ban_seconds = ban_seconds

    @staticmethod
    def _public_id(request: Request) -> str:
        path_params = request.path_params
        public_id = path_params.get("public_id") if path_params else None
        return public_id if isinstance(public_id, str) and public_id else "unknown"

    def _scope_identity(self, request: Request, session_id: str | None) -> str:
        if self.scope is RateLimitScope.IP:
            return "global"
        if self.scope is RateLimitScope.IP_DROP:
            return self._public_id(request)
        if self.scope is RateLimitScope.SESSION_DROP:
            if session_id is None:
                cookies: Mapping[str, str] = request.cookies
                session_id = cookies.get("drop_sid", "anonymous")
            return f"{session_id}|{self._public_id(request)}"
        raise RuntimeError(f"Unsupported rate-limit scope: {self.scope}")

    def _build_key(
        self,
        client_ip: str,
        scope_identity: str,
    ) -> str:
        if self.scope is RateLimitScope.SESSION_DROP:
            return f"rate_limit:{self.name}:session:{_hash_key(scope_identity)}"

        ip_key = pseudonymize_ip(client_ip, get_settings().session_pepper)
        if self.scope is RateLimitScope.IP:
            return f"rate_limit:{self.name}:ip:{ip_key}"
        return f"rate_limit:{self.name}:ip:{ip_key}:drop:{_hash_key(scope_identity)}"

    def _build_ip_ban_key(self, client_ip: str) -> str:
        ip_key = pseudonymize_ip(client_ip, get_settings().session_pepper)
        return f"rate_limit:{self.name}:ban:{ip_key}"

    async def _evaluate(
        self,
        redis: Redis,
        key: str,
        ip_ban_key: str,
        cost: int,
    ) -> tuple[int, int]:
        result = await redis.eval(
            _RATE_LIMIT_SCRIPT,
            2,
            key,
            ip_ban_key,
            self.window_seconds,
            self.max_requests,
            self.ban_seconds,
            cost,
        )
        if not isinstance(result, (list, tuple)) or len(result) != 2:
            raise TypeError("Rate-limit Lua script returned an invalid result")

        count, retry_after = result
        if not isinstance(count, (int, str, bytes)) or not isinstance(
            retry_after, (int, str, bytes)
        ):
            raise TypeError("Rate-limit Lua script returned non-scalar values")
        return int(count), max(int(retry_after), 0)

    async def check(
        self,
        request: Request,
        *,
        cost: int = 1,
        session_id: str | None = None,
    ) -> None:
        if cost <= 0:
            raise ValueError("Rate-limit cost must be positive")

        client_ip = get_client_ip(request)
        scope_identity = self._scope_identity(request, session_id)
        key = self._build_key(client_ip, scope_identity)
        ip_ban_key = self._build_ip_ban_key(client_ip)

        try:
            count, retry_after = await self._evaluate(
                get_redis_client(), key, ip_ban_key, cost
            )
            if count < 0 or count > self.max_requests:
                RATE_LIMITED_REQUESTS_TOTAL.inc()
                logger.warning(
                    "Rate limit exceeded",
                    extra={
                        "rate_limit_name": self.name,
                        "request_count": count,
                        "max_requests": self.max_requests,
                        "retry_after": retry_after,
                    },
                )
                raise RateLimitExceededError(retry_after=retry_after)
        except RateLimitExceededError:
            raise
        except Exception as exc:
            logger.warning(
                "Redis error during rate limit evaluation",
                extra={"rate_limit_name": self.name, "fail_closed": self.fail_closed},
            )
            if self.fail_closed:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Rate limiting protection service unavailable",
                ) from exc

    async def __call__(self, request: Request) -> None:
        await self.check(request)


@dataclass(frozen=True)
class RateLimitPolicies:
    create: RateLimiter
    upload_bytes: RateLimiter
    metadata: RateLimiter
    download: RateLimiter
    download_per_drop: RateLimiter
    download_per_session: RateLimiter
    invalid_token: RateLimiter


@lru_cache
def _rate_limit_policies() -> RateLimitPolicies:
    settings = get_settings()
    return RateLimitPolicies(
        create=RateLimiter(
            name="create",
            max_requests=settings.rate_limit_create_max,
            window_seconds=settings.rate_limit_create_window,
        ),
        upload_bytes=RateLimiter(
            name="upload_bytes",
            max_requests=settings.rate_limit_upload_bytes,
            window_seconds=settings.rate_limit_upload_bytes_window,
        ),
        metadata=RateLimiter(
            name="metadata",
            max_requests=settings.rate_limit_metadata_max,
            window_seconds=settings.rate_limit_metadata_window,
            fail_closed=False,
        ),
        download=RateLimiter(
            name="download",
            max_requests=settings.rate_limit_download_max,
            window_seconds=settings.rate_limit_download_window,
        ),
        download_per_drop=RateLimiter(
            name="download_per_drop",
            max_requests=settings.rate_limit_download_per_drop_max,
            window_seconds=settings.rate_limit_download_per_drop_window,
            scope=RateLimitScope.IP_DROP,
        ),
        download_per_session=RateLimiter(
            name="download_per_session",
            max_requests=settings.rate_limit_download_per_session_max,
            window_seconds=settings.rate_limit_download_per_session_window,
            scope=RateLimitScope.SESSION_DROP,
        ),
        invalid_token=RateLimiter(
            name="invalid_token",
            max_requests=settings.rate_limit_invalid_token_max,
            window_seconds=settings.rate_limit_invalid_token_window,
            ban_seconds=settings.rate_limit_invalid_token_ban_seconds,
        ),
    )


async def rate_limit_create(request: Request) -> None:
    await _rate_limit_policies().create(request)


async def rate_limit_upload_bytes(request: Request, *, cost: int) -> None:
    await _rate_limit_policies().upload_bytes.check(request, cost=cost)


async def rate_limit_metadata(request: Request) -> None:
    await _rate_limit_policies().metadata(request)


async def rate_limit_download(request: Request) -> None:
    await _rate_limit_policies().download(request)


async def rate_limit_download_per_drop(request: Request) -> None:
    await _rate_limit_policies().download_per_drop(request)


async def rate_limit_download_per_session(
    request: Request,
    *,
    session_id: str,
) -> None:
    await _rate_limit_policies().download_per_session.check(
        request, session_id=session_id
    )


async def rate_limit_invalid_token(request: Request) -> None:
    await _rate_limit_policies().invalid_token(request)
