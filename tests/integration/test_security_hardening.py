import asyncio
import json
import logging
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from drop.application.services.drop import DropService
from drop.config import get_settings
from drop.domain.exceptions import DropNotFoundError
from drop.domain.security import (
    compute_token_hash,
    generate_access_token,
    verify_access_token,
)
from drop.infrastructure.database.models import DownloadGrantModel, DropModel
from drop.infrastructure.repositories.drop import DropRepository
from drop.logging import JSONFormatter, sanitize_value
from drop.main import app
from tests.integration.factories import create_active_drop
from tests.integration.test_cleanup import DummyS3Storage


@pytest.mark.asyncio
async def test_capability_token_generation_and_hashing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    token = generate_access_token()
    assert len(token) >= 43  # 32 urlsafe bytes = 43+ chars

    settings = get_settings()
    token_hash = compute_token_hash(token, settings.drop_token_pepper)
    assert isinstance(token_hash, bytes)
    assert len(token_hash) == 32  # SHA256 = 32 bytes

    assert verify_access_token(token, token_hash, settings.drop_token_pepper) is True
    assert (
        verify_access_token("wrong_token", token_hash, settings.drop_token_pepper)
        is False
    )


@pytest.mark.asyncio
async def test_invalid_token_or_missing_id_returns_generic_not_found(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        drop, real_token = await create_active_drop(session, max_downloads=5)
        public_id = drop.public_id

    async with session_factory() as session:
        service = DropService(
            session=session,
            repository=DropRepository(session),
            storage=DummyS3Storage(),  # type: ignore[arg-type]
        )

        # Nonexistent public_id
        with pytest.raises(DropNotFoundError):
            await service.get_metadata("non-existent-id", real_token)

        # Invalid token for existing public_id
        with pytest.raises(DropNotFoundError):
            await service.get_metadata(public_id, "invalid_token_value")

        # Missing token
        with pytest.raises(DropNotFoundError):
            await service.get_metadata(public_id, None)

        # Valid token works
        meta = await service.get_metadata(public_id, real_token)
        assert meta.public_id == public_id


@pytest.mark.asyncio
async def test_safe_get_metadata_does_not_consume_slots(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        drop, token = await create_active_drop(session, max_downloads=1)
        public_id = drop.public_id

    # Perform 100 GET metadata queries
    for _ in range(100):
        async with session_factory() as session:
            service = DropService(
                session=session,
                repository=DropRepository(session),
                storage=DummyS3Storage(),  # type: ignore[arg-type]
            )
            meta = await service.get_metadata(public_id, token)
            assert meta.download_count == 0

    # Verify drop remains ACTIVE with 0 downloads and 0 grants
    async with session_factory() as session:
        persisted = (
            await session.execute(
                select(DropModel).where(DropModel.public_id == public_id)
            )
        ).scalar_one()
        assert persisted.download_count == 0
        assert persisted.status.value == "ACTIVE"

        grants = (
            (
                await session.execute(
                    select(DownloadGrantModel).where(
                        DownloadGrantModel.drop_id == persisted.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(grants) == 0


@pytest.mark.asyncio
async def test_same_session_spam_uses_single_grant_and_single_increment(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        drop, token = await create_active_drop(session, max_downloads=5)
        public_id = drop.public_id
        drop_id = drop.id

    async def session_download_attempt() -> bool:
        async with session_factory() as session:
            service = DropService(
                session=session,
                repository=DropRepository(session),
                storage=DummyS3Storage(),  # type: ignore[arg-type]
            )
            try:
                await service.get_download_stream(
                    public_id=public_id,
                    access_token=token,
                    session_id="same_browser_session_123",
                )
                return True
            except Exception:
                return False

    # 50 concurrent downloads from SAME session
    results = await asyncio.gather(*(session_download_attempt() for _ in range(50)))
    assert all(results)

    async with session_factory() as session:
        persisted = (
            await session.execute(select(DropModel).where(DropModel.id == drop_id))
        ).scalar_one()

        # download_count MUST be exactly 1, NOT 5 or 50!
        assert persisted.download_count == 1
        assert persisted.status.value == "ACTIVE"

        grants = (
            (
                await session.execute(
                    select(DownloadGrantModel).where(
                        DownloadGrantModel.drop_id == drop_id
                    )
                )
            )
            .scalars()
            .all()
        )
        # Exactly 1 grant created for this session
        assert len(grants) == 1


@pytest.mark.asyncio
async def test_different_sessions_concurrency_respects_max_downloads(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        drop, token = await create_active_drop(session, max_downloads=1)
        public_id = drop.public_id
        drop_id = drop.id

    async def session_download_attempt(session_idx: int) -> bool:
        async with session_factory() as session:
            service = DropService(
                session=session,
                repository=DropRepository(session),
                storage=DummyS3Storage(),  # type: ignore[arg-type]
            )
            try:
                await service.get_download_stream(
                    public_id=public_id,
                    access_token=token,
                    session_id=f"unique_session_{session_idx}",
                )
                return True
            except Exception:
                return False

    # 50 requests from 50 DIFFERENT sessions
    results = await asyncio.gather(*(session_download_attempt(i) for i in range(50)))

    # Exactly 1 session gets a grant, 49 are rejected
    assert sum(results) == 1

    async with session_factory() as session:
        persisted = (
            await session.execute(select(DropModel).where(DropModel.id == drop_id))
        ).scalar_one()

        assert persisted.download_count == 1
        assert persisted.status.value == "CONSUMED"

        grants = (
            (
                await session.execute(
                    select(DownloadGrantModel).where(
                        DownloadGrantModel.drop_id == drop_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(grants) == 1


def test_security_headers_present_on_api_responses() -> None:
    with (
        patch("drop.api.rate_limit.get_redis_client") as mock_redis,
        patch("drop.api.dependencies.S3Storage"),
    ):
        mock_instance = AsyncMock()
        mock_instance.eval.return_value = [1, 60]
        mock_redis.return_value = mock_instance

        with TestClient(app) as client:
            response = client.get("/health/live")
            assert response.status_code == 200
            assert (
                response.headers.get("Cache-Control")
                == "no-store, no-cache, must-revalidate"
            )
            assert response.headers.get("Referrer-Policy") == "no-referrer"
            assert response.headers.get("X-Content-Type-Options") == "nosniff"
            assert response.headers.get("X-Frame-Options") == "DENY"
            assert (
                response.headers.get("X-Robots-Tag") == "noindex, nofollow, noarchive"
            )
            assert "default-src 'self'" in response.headers.get(
                "Content-Security-Policy", ""
            )


def test_log_redaction_masks_sensitive_tokens() -> None:
    assert sanitize_value("access_token", "secret123") == "***MASKED***"
    assert sanitize_value("x-drop-token", "secret123") == "***MASKED***"
    assert sanitize_value("drop_sid", "session456") == "***MASKED***"
    assert sanitize_value("normal_key", "hello") == "hello"

    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Testing log redaction",
        args=(),
        exc_info=None,
    )
    record.__dict__["access_token"] = "super_secret_token"
    record.__dict__["drop_sid"] = "super_secret_cookie"

    formatted = formatter.format(record)
    log_json = json.loads(formatted)

    assert log_json.get("access_token") == "***MASKED***"
    assert log_json.get("drop_sid") == "***MASKED***"
