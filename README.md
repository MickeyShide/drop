# Drop — anonymous ephemeral file sharing

Drop is an anonymous file-sharing service built with FastAPI, PostgreSQL,
Redis, Celery/RabbitMQ, MinIO and Nginx.

## Security model

Access is capability-based: a Drop has a public locator and a separate,
256-bit random access token. The token is returned only when the Drop is
created and is placed in the share-link fragment:

```text
https://host/d/{public_id}#{access_token}
```

The browser keeps the fragment client-side and sends the token in
`X-Drop-Token`. The database stores only an HMAC-SHA256 token digest. Do not
put capability tokens in query strings, logs, localStorage or referrers.

`DROP_TOKEN_PEPPER` and `SESSION_PEPPER` must be supplied through environment
secrets in production.

## API contract

- `POST /api/v1/drops` creates a Drop and returns `access_token` and
  `share_url` once.
- `GET /api/v1/drops/{public_id}` returns metadata only and requires
  `X-Drop-Token`.
- `POST /api/v1/drops/{public_id}/download` performs the intentional download.
  It requires `X-Drop-Token`, `X-Drop-Action: download`, and an
  `Idempotency-Key` is recommended.

GET never consumes a slot, creates a grant or starts cleanup. Download POSTs
use an anonymous `drop_sid` cookie. One session can create at most one
`download_grant` for a Drop, so retries and repeated clicks do not consume
additional slots. `max_downloads` counts unique recipient grants, not raw HTTP
requests.

PostgreSQL is the source of truth for grants and counters. Redis provides
atomic rate limits and a short-lived per-session stream lock; Redis failure
fails closed on security-sensitive operations.

## Local launch

The local stack has all development values embedded in a separate Compose file;
no `.env` file or shell variables are required:

```powershell
docker compose -f docker-compose.local.yml up -d --build
# or: make up-local
```

The application is available at `http://localhost:4917`. Stop it with:

```powershell
docker compose -f docker-compose.local.yml down
```

Local peppers and passwords are development-only values and must not be reused
in production.

The local public showcase is available without authentication:

- `http://localhost:4917/stats` — compact public statistics page;
- `http://localhost:4917/grafana/` — provisioned Grafana dashboard;
- `http://localhost:4917/prometheus/` — Prometheus UI and query API;
- `http://localhost:4917/metrics` — raw Prometheus exposition format.

## Production deployment

Only Nginx is published by the production Compose file. PostgreSQL, Redis,
RabbitMQ, MinIO, exporters and the FastAPI port remain on the internal Docker
network. Nginx publicly proxies the showcase endpoints `/stats`, `/metrics`,
`/prometheus/` and `/grafana/`; Grafana is intentionally anonymous Viewer-only.
Production deployment is performed by GitHub Actions. Before SSH deployment,
the workflow validates every required GitHub Variable and Secret and fails if
even one is empty. It then writes a protected `.env` on the target host and
starts Compose. There are no GitHub fallbacks or default deployment values.

Required GitHub Variables:

- `SERVER_HOST`
- `SERVER_USER`
- `SERVER_PORT`
- `TARGET_DIR`
- `NGINX_PORT`
- `PUBLIC_BASE_URL` — full externally reachable URL, for example `https://drop.example.com`

Required GitHub Secrets:

- `SERVER_SSH_KEY`
- `DROP_TOKEN_PEPPER`
- `SESSION_PEPPER`
- `POSTGRES_PASSWORD`
- `RABBITMQ_PASSWORD`
- `MINIO_PASSWORD`
- `GRAFANA_ADMIN_PASSWORD`

Use URL-safe passwords containing only letters, digits, `-` or `_`. The
Compose file derives the PostgreSQL, RabbitMQ and S3 application credentials
from these three passwords, so duplicate URL and access-key variables are not
needed.

`GRAFANA_ADMIN_PASSWORD` protects the private Grafana administrator account.
It does not affect the public showcase dashboard, which is visible without a
login. Since Prometheus and Grafana are intentionally public in this project,
do not put secrets, personal data or sensitive labels into application metrics.

Use a real secret manager for production rather than shell history. MinIO
must remain private and should not be exposed directly to the Internet.

## Development and verification

```powershell
uv run pytest -v
uv run ruff format --check .
uv run ruff check .
uv run mypy src
```

The integration suite covers capability verification, generic enumeration
errors, GET safety, same-session spam, different-session concurrency,
idempotent cleanup, rate-limit failure policy and security headers.

## Anonymous-service limitation

Without user authentication, the service cannot prove that different
cookies, IPs or proxy networks belong to the same physical person. The
security promise is therefore an unguessable capability link plus layered
anti-abuse controls, not absolute prevention against an attacker who already
possesses the complete link and can create new identities.
