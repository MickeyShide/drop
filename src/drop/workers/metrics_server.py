from wsgiref.simple_server import make_server

from prometheus_client import CollectorRegistry, generate_latest, multiprocess
from prometheus_client.exposition import CONTENT_TYPE_LATEST


def metrics_app(environ: dict[str, object], start_response: object) -> list[bytes]:
    if environ["PATH_INFO"] != "/metrics":
        start_response("404 Not Found", [("Content-Type", "text/plain")])  # type: ignore[operator]
        return [b"Not found\n"]

    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)
    payload = generate_latest(registry)
    start_response(  # type: ignore[operator]
        "200 OK",
        [("Content-Type", CONTENT_TYPE_LATEST), ("Content-Length", str(len(payload)))],
    )
    return [payload]


def main() -> None:
    with make_server("0.0.0.0", 8001, metrics_app) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
