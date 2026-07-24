# Drop — security and architecture contract

## Purpose

Drop is an anonymous, ephemeral file-sharing service. It does not have users,
registration, login, JWT, OAuth, email or roles. Possession of a complete
capability link authorizes access to one Drop.

## Capability access

`public_id` is only a locator. It is generated with cryptographically secure
randomness and is not the access credential. Creation also generates a
256-bit URL-safe `access_token`. PostgreSQL stores only:

```text
HMAC-SHA256(DROP_TOKEN_PEPPER, access_token)
```

The raw token is returned in the create response and in a fragment URL. A
fragment is not sent in HTTP requests, so the frontend reads it into memory
and sends `X-Drop-Token`. It is never persisted in localStorage or the
database.

Missing, malformed and incorrect capabilities, unknown IDs and deleted Drops
are intentionally presented as the same `404 DROP_NOT_FOUND` response. Only
after successful capability verification may expiration or consumption be
reported.

## Download semantics

`GET /api/v1/drops/{public_id}` is metadata-only. It does not mutate state.

`POST /api/v1/drops/{public_id}/download` is the only download operation. It
requires:

- `X-Drop-Token`;
- `X-Drop-Action: download`;
- the anonymous `drop_sid` cookie;
- Redis rate-limit and stream-lock checks.

The cookie contains a random 256-bit session value. The database stores only
its HMAC with `SESSION_PEPPER`. `download_grants` has a unique constraint on
`(drop_id, client_session_hash)`. A PostgreSQL row lock and this constraint
ensure that concurrent requests from one session create one grant and that
different sessions cannot exceed `max_downloads`.

`download_count` means the number of unique grants, not the number of HTTP
requests. `Idempotency-Key` is accepted for retries; it is supplementary and
never replaces the session/grant invariant.

The final grant changes the Drop to `CONSUMED`, preventing new sessions. The
object is not scheduled for deletion until active grants finish or their
lease expires. Cleanup is represented by the transactional Outbox and is
idempotent.

## Rate limiting and Redis

Policies are configured through settings rather than hardcoded route values:

| Policy | Default | Failure mode |
| --- | ---: | --- |
| create/upload per IP | 5 / 60s | fail closed |
| metadata per IP | 60 / 60s | fail open |
| download per IP | 10 / 60s | fail closed |
| download per IP + Drop | 5 / 60s | fail closed |
| download per session + Drop | 10 / 60s | fail closed |
| invalid capability per IP | 10 / 60s | fail closed, temporary penalty |

Production Redis uses a Lua script to increment and expire counters atomically.
Redis is not the source of truth for grants or download limits. A Redis outage
must not turn download, upload or capability-abuse protection into unlimited
access.

The application trusts `X-Forwarded-For` and `X-Real-IP` only when the direct
peer belongs to explicitly configured `TRUSTED_PROXY_IPS`. Nginx overwrites
these headers and the FastAPI port is not published in production Compose.

## Storage and infrastructure

MinIO objects use `drops/{drop_uuid}/source`; filenames never influence object
paths. The bucket is private, no public object endpoint is exposed, and the
API streams objects only after capability and grant checks. Downloads use
`Content-Disposition: attachment` and `X-Content-Type-Options: nosniff`.

Only Nginx is Internet-facing in the production Compose file. PostgreSQL,
Redis, RabbitMQ, RabbitMQ management, MinIO API/console and FastAPI are
internal. The public logs dashboard is available at `/logs`; its data endpoint
is rate-limited but intentionally does not require authentication. Metrics
remain an internal application endpoint and are not proxied by Nginx.

Sensitive responses receive no-store, no-referrer, nosniff, frame-deny,
noindex and CSP headers. Production Nginx also emits HSTS; TLS termination
must be configured in the deployment environment.

## Upload limits

Nginx caps request bodies at 100 MB by default. Application upload processing
reads the stream in 1 MB chunks and enforces `MAX_UPLOAD_SIZE_BYTES` against
actual bytes read; it does not trust `Content-Length` and does not buffer the
whole file in RAM.

## Data model changes

Migration `f3a4b5c6d7e8` adds `drops.access_token_hash`, `download_grants`, the
grant status enum and the unique `(drop_id, client_session_hash)` constraint.
Existing pre-capability rows receive no usable raw token and therefore cannot
be accessed through the new API; they should be migrated or removed as part
of deployment policy.

## Verification

Run:

```powershell
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest -v
```

The suite uses real PostgreSQL for grant/concurrency tests and covers token
randomness and hashing, generic enumeration responses, GET safety, same- and
different-session races, stream security headers, log redaction, rate-limit
failure policy, expiration and transactional cleanup.

## Limitations

An anonymous service cannot prove that different cookies/IPs/proxies are one
physical person. A holder of the complete link can intentionally create new
sessions or use new networks. Stronger guarantees require a second factor or
recipient authentication, which are intentionally outside this project.

Backups, replicas and object-store versioning are deployment concerns; Drop
must not claim that deletion removes every historical copy unless those
systems are separately configured and verified.
