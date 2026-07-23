# Drop — Ephemeral File Sharing Microservice

**Drop** is a minimalistic, secure, ephemeral file-sharing backend built with Python, FastAPI, PostgreSQL, Redis, RabbitMQ, Celery, and S3-compatible Object Storage (MinIO).

> **Core Philosophy**: Upload a file. Share the link. The file disappears automatically.

---

## Architecture Overview

```text
                        ┌───────────┐
                        │  Client   │
                        └─────┬─────┘
                              │
                              ▼
                        ┌───────────┐
                        │   Nginx   │ (Reverse Proxy, Security Headers, Upload Limits)
                        └─────┬─────┘
                              │
                              ▼
                        ┌───────────┐
                        │ FastAPI   │
                        │ Drop API  │ (Stream handling, Rate Limiting, Atomic Updates)
                        └─────┬─────┘
                              │
             ┌────────────────┼────────────────┐
             │                │                │
             ▼                ▼                ▼
       ┌──────────┐      ┌────────┐       ┌─────────┐
       │PostgreSQL│      │ Redis  │       │  MinIO  │
       │ (State)  │      │(Limiter│       │  (S3)   │
       └──────────┘      └────────┘       └─────────┘
             │
             ▼ (Transactional Outbox)
       ┌──────────┐
       │ RabbitMQ │
       └─────┬────┘
             │
             ▼
       ┌──────────┐
       │  Celery  │ (Idempotent S3 Cleanup & Expiration Sweeps)
       │ Workers  │
       └──────────┘
```

---

## Key Business Invariants & Guarantees

1. **Strict Download Limit (`download_count <= max_downloads`)**:
   - Atomic PostgreSQL `UPDATE` query guarantees that concurrent download requests (e.g. 100 simultaneous clients) can NEVER exceed the allowed download limit.

2. **API-Enforced Immediate Expiration**:
   - Drops with `NOW() >= expires_at` are immediately rejected by the API with `HTTP 410 Gone`, regardless of whether the Celery cleanup worker has run.

3. **PostgreSQL as Source of Truth**:
   - Redis is used strictly for volatile IP rate limiting counters. All business state and concurrency bounds reside in PostgreSQL.

4. **Transactional Outbox Pattern**:
   - File deletion events are written to the `outbox_events` PostgreSQL table within the exact same database transaction as status updates, eliminating dual-write failure windows.

5. **Idempotent Background Workers**:
   - Celery worker tasks (`delete_drop_file`, `cleanup_expired_drops`) are idempotent. Deleting an already removed S3 object succeeds gracefully and preserves the initial `deleted_at` timestamp.

---

## Dedicated Host Port Range (`4910 - 4917`)

To avoid collisions with other projects on shared servers, Drop uses a dedicated host port range:

- **API Service**: `http://localhost:4910` (Swagger Docs: `http://localhost:4910/docs`)
- **Nginx Entrypoint**: `http://localhost:4917`
- **PostgreSQL**: `localhost:4911`
- **Redis**: `localhost:4912`
- **MinIO S3 API**: `http://localhost:4913`
- **MinIO Console**: `http://localhost:4914` (User: `drop`, Password: `dropdropdrop`)
- **RabbitMQ AMQP**: `localhost:4915`
- **RabbitMQ Management**: `http://localhost:4916` (User: `drop`, Password: `dropdropdrop`)

---

## Quick Start (Docker Compose)

Start the entire architecture with a single command:

```powershell
docker compose up -d --build
```

---

## Running Tests & Demonstrations

### 1. Run Automated Test Suite

```powershell
uv run pytest -v
```

### 2. Concurrency Race Condition Demonstration (`make race-test`)

Creates a 1-download limit drop and fires 100 concurrent HTTP requests:

```powershell
make race-test
```

### 3. Expiration Lifecycle Demonstration (`make expiration-test`)

Creates a 5-second TTL drop, verifies HTTP 200 before expiration, waits 6 seconds, and verifies HTTP 410 Gone:

```powershell
make expiration-test
```

---

## Code Quality

```powershell
make lint       # Runs ruff check .
make typecheck  # Runs mypy src
```
