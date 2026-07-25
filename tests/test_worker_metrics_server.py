from pathlib import Path

from drop.workers.metrics_server import metrics_app


def test_worker_metrics_server_returns_prometheus_response(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    captured: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = headers

    response = metrics_app({"PATH_INFO": "/metrics"}, start_response)

    assert captured["status"] == "200 OK"
    assert response == [b""]


def test_worker_metrics_server_returns_404_for_other_paths() -> None:
    captured: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = headers

    response = metrics_app({"PATH_INFO": "/not-found"}, start_response)

    assert captured["status"] == "404 Not Found"
    assert response == [b"Not found\n"]
