from fastapi.testclient import TestClient

from drop.main import app
from drop.metrics import (
    CELERY_TASK_FAILURES_TOTAL,
    CLEANUP_RETRIES_TOTAL,
    DROP_DOWNLOADS_REJECTED_TOTAL,
    DROP_DOWNLOADS_TOTAL,
    DROP_UPLOADS_TOTAL,
)

client = TestClient(app)


def test_metrics_endpoint_returns_prometheus_format() -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]

    content = response.text
    assert "http_requests_total" in content
    assert "http_request_duration_seconds" in content
    assert "drop_uploads_total" in content
    assert "drop_downloads_total" in content
    assert "drop_downloads_rejected_total" in content
    assert "celery_task_failures_total" in content
    assert "cleanup_retries_total" in content


def test_domain_metrics_counters_increment() -> None:
    initial_uploads = DROP_UPLOADS_TOTAL.labels(status="success")._value.get()
    DROP_UPLOADS_TOTAL.labels(status="success").inc()
    assert DROP_UPLOADS_TOTAL.labels(status="success")._value.get() == initial_uploads + 1

    initial_downloads = DROP_DOWNLOADS_TOTAL._value.get()
    DROP_DOWNLOADS_TOTAL.inc()
    assert DROP_DOWNLOADS_TOTAL._value.get() == initial_downloads + 1

    initial_rejected = DROP_DOWNLOADS_REJECTED_TOTAL.labels(reason="expired")._value.get()
    DROP_DOWNLOADS_REJECTED_TOTAL.labels(reason="expired").inc()
    assert DROP_DOWNLOADS_REJECTED_TOTAL.labels(reason="expired")._value.get() == initial_rejected + 1


def test_celery_metrics_counters_increment() -> None:
    initial_failures = CELERY_TASK_FAILURES_TOTAL.labels(task_name="drop.delete_file")._value.get()
    CELERY_TASK_FAILURES_TOTAL.labels(task_name="drop.delete_file").inc()
    assert CELERY_TASK_FAILURES_TOTAL.labels(task_name="drop.delete_file")._value.get() == initial_failures + 1

    initial_retries = CLEANUP_RETRIES_TOTAL.labels(task_name="drop.delete_file")._value.get()
    CLEANUP_RETRIES_TOTAL.labels(task_name="drop.delete_file").inc()
    assert CLEANUP_RETRIES_TOTAL.labels(task_name="drop.delete_file")._value.get() == initial_retries + 1
