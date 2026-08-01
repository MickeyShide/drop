from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_prometheus_proxy_matches_shared_route_contract() -> None:
    nginx = (ROOT / "nginx" / "nginx.conf").read_text(encoding="utf-8")

    assert "location = /prometheus {" in nginx
    assert "absolute_redirect off;" in nginx
    assert 'set $prometheus_backend "http://shide-prometheus:9090";' in nginx
    assert "rewrite ^/prometheus/(.*) /$1 break;" in nginx
    assert "proxy_pass $prometheus_backend;" in nginx


def test_grafana_uses_shared_external_domain() -> None:
    nginx = (ROOT / "nginx" / "nginx.conf").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "location = /grafana" not in nginx
    assert "location /grafana/" not in nginx
    assert "$grafana_backend" not in nginx
    assert 'href="https://grafana.shide.world"' in frontend


def test_drop_dashboard_links_to_drop_observability_endpoints() -> None:
    dashboard = (
        ROOT / "observability" / "grafana" / "dashboards" / "drop-showcase.json"
    ).read_text(encoding="utf-8")

    assert '"url": "https://drop.shide.world/metrics"' in dashboard
    assert '"url": "https://drop.shide.world/prometheus/graph"' in dashboard


def test_stats_queries_are_scoped_to_drop_targets() -> None:
    frontend = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    expected_queries = (
        'sum(drop_uploads_total{job="drop_api",status="success"})',
        'sum(drop_downloads_total{job="drop_api"})',
        'sum(rate(http_requests_total{job="drop_api"}[1m])) * 60',
        'sum(up{job=~"drop_api|celery_worker|nginx"})',
        'count(up{job=~"drop_api|celery_worker|nginx"})',
        'sum by (status_code) (rate(http_requests_total{job="drop_api"}[1m]))',
        (
            "histogram_quantile(0.95, sum by (le) "
            '(rate(http_request_duration_seconds_bucket{job="drop_api"}[5m]))) '
            "* 1000"
        ),
    )

    for query in expected_queries:
        assert query in frontend

    unscoped_queries = (
        "sum(rate(http_requests_total[1m])) * 60",
        "sum(up)",
        "count(up)",
        "sum by (status_code) (rate(http_requests_total[1m]))",
        (
            "histogram_quantile(0.95, sum by (le) "
            "(rate(http_request_duration_seconds_bucket[5m]))) * 1000"
        ),
    )

    for query in unscoped_queries:
        assert query not in frontend
