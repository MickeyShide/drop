# Drop Statistics Prometheus Scope Design

## Problem

The `/stats` page queries the shared Prometheus instance. Several expressions
aggregate `http_requests_*` and `up` without label matchers, so metrics from
unrelated services are included in Drop statistics.

## Scope

The statistics page must report only Drop-owned targets:

- `drop_api`
- `celery_worker`
- `nginx`

Shared infrastructure targets such as PostgreSQL, Redis, RabbitMQ, MinIO, and
Prometheus itself are outside the Drop statistics scope.

## Selected Approach

Use the existing Prometheus `job` label in every statistics query. This avoids
changes to the shared Prometheus deployment and uses the labels already defined
by the repository's scrape configuration.

Alternative approaches were rejected:

- Adding a new `service="drop"` label would require coordinating and deploying
  a Prometheus configuration change together with the frontend change.
- Matching `instance` values would couple the page to container addresses and
  make future deployment changes more fragile.

## Query Design

Application counters and HTTP metrics originate from the Drop API target and
must use `job="drop_api"`:

- Successful uploads: `sum(drop_uploads_total{job="drop_api",status="success"})`
- Downloads: `sum(drop_downloads_total{job="drop_api"})`
- Requests per minute: `sum(rate(http_requests_total{job="drop_api"}[1m])) * 60`
- Requests by status: `sum by (status_code) (rate(http_requests_total{job="drop_api"}[1m]))`
- p95 latency: `histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{job="drop_api"}[5m]))) * 1000`

Target availability covers every Drop-owned scrape target and must use the
matcher `job=~"drop_api|celery_worker|nginx"`:

- Available targets: `sum(up{job=~"drop_api|celery_worker|nginx"})`
- Total targets: `count(up{job=~"drop_api|celery_worker|nginx"})`

The existing rendering, aggregation, error handling, and empty states remain
unchanged.

## Verification

Add a regression test for the frontend query contract. It must assert that:

- All seven expressions include the intended Drop job matcher.
- Application and HTTP expressions select only `drop_api`.
- Availability expressions select exactly the three Drop-owned jobs.
- The previous global `sum(up)`, `count(up)`, and unfiltered HTTP expressions
  are absent.

Run the focused observability tests and then the complete automated test suite.

## Deployment

The change is frontend-only and does not require a Prometheus restart or data
migration. Existing time series remain usable because filtering relies on their
current `job` labels.
