from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from drop.infrastructure.database.engine import get_session
from drop.main import app

client = TestClient(app)


def test_liveness() -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_success() -> None:
    mock_redis = AsyncMock()
    mock_redis.ping.return_value = True

    mock_session = AsyncMock()
    mock_session.execute.return_value = None

    async def override_get_session():
        yield mock_session

    app.dependency_overrides[get_session] = override_get_session
    try:
        with patch("drop.api.health.get_redis_client", return_value=mock_redis), \
             patch("drop.api.health.S3Storage"):
            response = client.get("/health/ready")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ready"
            assert data["checks"]["postgres"] == "ok"
            assert data["checks"]["redis"] == "ok"
            assert data["checks"]["minio"] == "ok"
    finally:
        app.dependency_overrides.clear()


def test_readiness_service_failure() -> None:
    async def override_get_session_fail():
        mock_session = AsyncMock()
        mock_session.execute.side_effect = Exception("DB Connection Refused")
        yield mock_session

    app.dependency_overrides[get_session] = override_get_session_fail
    try:
        response = client.get("/health/ready")
        assert response.status_code == 503
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "HTTP_ERROR"
    finally:
        app.dependency_overrides.clear()
