from fastapi.testclient import TestClient

from drop.main import app


client = TestClient(app)


def test_openapi_docs_are_public() -> None:
    response = client.get("/docs")

    assert response.status_code == 200
    assert "Swagger UI" in response.text


def test_openapi_schema_is_public() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Drop"
