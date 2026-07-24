from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from drop.api.dependencies import get_drop_service
from drop.infrastructure.database.engine import get_session
from drop.main import app


@pytest.fixture
def client():
    with (
        patch("drop.api.rate_limit.get_redis_client") as mock_redis,
        patch("drop.api.dependencies.S3Storage"),
    ):
        mock_instance = AsyncMock()
        mock_instance.eval.return_value = [1, 60]
        mock_redis.return_value = mock_instance

        async def override_get_session():
            yield AsyncMock()

        app.dependency_overrides[get_session] = override_get_session
        try:
            with TestClient(app) as c:
                yield c
        finally:
            app.dependency_overrides.clear()


def test_request_id_middleware_generates_header(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert len(response.headers["X-Request-ID"]) > 0


def test_request_id_middleware_preserves_client_header(client: TestClient) -> None:
    custom_id = "custom-client-request-id-12345"
    response = client.get("/health/live", headers={"X-Request-ID": custom_id})
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == custom_id


def test_unified_error_response_format_404(client: TestClient) -> None:
    custom_id = "test-req-id-404"

    async def override_get_session():
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        yield mock_session

    app.dependency_overrides[get_session] = override_get_session
    try:
        response = client.get(
            "/api/v1/drops/non-existent-id",
            headers={"X-Request-ID": custom_id, "X-Drop-Token": "dummy_token"},
        )

        assert response.status_code == 404
        data = response.json()

        assert "error" in data
        assert data["error"]["code"] == "DROP_NOT_FOUND"
        assert "message" in data["error"]
        assert data["request_id"] == custom_id
    finally:
        app.dependency_overrides.clear()


def test_validation_error_response_format_422(client: TestClient) -> None:
    response = client.post(
        "/api/v1/drops",
        data={"expires_in_seconds": "-5"},
    )

    assert response.status_code == 422
    data = response.json()

    assert "error" in data
    assert data["error"]["code"] == "VALIDATION_ERROR"
    assert "details" in data["error"]
    assert "request_id" in data


def test_logs_dashboard_data_is_public(client: TestClient) -> None:
    service = AsyncMock()
    expected_data: dict[str, list[object]] = {
        "drops": [],
        "download_events": [],
        "tasks": [],
    }
    service.get_admin_logs.return_value = expected_data
    app.dependency_overrides[get_drop_service] = lambda: service

    try:
        response = client.get("/api/v1/drops/logs/data")

        assert response.status_code == 200
        assert response.json() == expected_data
        service.get_admin_logs.assert_awaited_once()
    finally:
        app.dependency_overrides.clear()
