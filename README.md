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

## Launch

Drop uses a single Compose file and relies on the shared `shide-observability`
stack for Prometheus, Grafana, Loki and Promtail. Start the observability stack
first:

```powershell
make observability-up
# or manually:
docker network create shide-observability
docker compose -f ../shide-observability/docker-compose.yml up -d
```

Then start Drop:

```powershell
docker compose up -d --build
# or: make up
```

The application is available at `http://localhost:4917` (or the configured
`NGINX_PORT`). Stop Drop with:

```powershell
docker compose down
# or: make down
```

Stop the observability stack with:

```powershell
make observability-down
```

Local peppers and passwords are development-only values and must not be reused
in production.

The observability stack is available without authentication:

- `http://localhost:3000` — Grafana with the Drop dashboard;
- Drop logs are shipped to Loki and searchable in Grafana.

## Production deployment

Only Nginx is published by the Compose file. PostgreSQL, Redis, RabbitMQ, MinIO,
exporters and the FastAPI port remain on the internal Docker network. Nginx
publicly proxies the showcase endpoint `/stats`; observability is provided by
the separate `shide-observability` stack.
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

Use URL-safe passwords containing only letters, digits, `-` or `_`. The
Compose file derives the PostgreSQL, RabbitMQ and S3 application credentials
from these three passwords, so duplicate URL and access-key variables are not
needed.

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
