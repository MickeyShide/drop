from fastapi.testclient import TestClient

from drop.main import app

client = TestClient(app)


def test_request_id_middleware_generates_header() -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert len(response.headers["X-Request-ID"]) > 0


def test_request_id_middleware_preserves_client_header() -> None:
    custom_id = "custom-client-request-id-12345"
    response = client.get("/health/live", headers={"X-Request-ID": custom_id})
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == custom_id


def test_unified_error_response_format_404() -> None:
    custom_id = "test-req-id-404"
    response = client.get(
        "/api/v1/drops/non-existent-id",
        headers={"X-Request-ID": custom_id},
    )

    assert response.status_code == 404
    data = response.json()

    assert "error" in data
    assert data["error"]["code"] == "DROP_NOT_FOUND"
    assert "message" in data["error"]
    assert data["request_id"] == custom_id


def test_validation_error_response_format_422() -> None:
    response = client.post(
        "/api/v1/drops",
        data={"expires_in_seconds": -5},
    )

    assert response.status_code == 422
    data = response.json()

    assert "error" in data
    assert data["error"]["code"] == "VALIDATION_ERROR"
    assert "details" in data["error"]
    assert "request_id" in data
