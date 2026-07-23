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

## Tech Stack

- **Language & Core**: Python 3.13+, FastAPI, Pydantic v2, `uv`
- **Database & Migration**: PostgreSQL 16, SQLAlchemy 2.x Async, Alembic
- **Caching & Rate Limiting**: Redis 7
- **Messaging & Background**: RabbitMQ 4, Celery 5 (Worker & Beat)
- **Object Storage**: MinIO (S3-compatible)
- **Infrastructure**: Nginx, Docker, Docker Compose
- **Observability**: Prometheus Metrics (`/metrics`), Structured JSON Logging (`contextvars`), Health Checks (`/health/live`, `/health/ready`)

---

## Quick Start (Docker Compose)

Start the entire 8-container architecture with a single command:

```powershell
docker compose up -d --build
```

Access services:
- **API Service**: `http://localhost:8000` (or `http://localhost` via Nginx)
- **Swagger Documentation**: `http://localhost:8000/docs`
- **Prometheus Metrics**: `http://localhost:8000/metrics`
- **Health / Readiness**: `http://localhost:8000/health/ready`
- **MinIO Web Console**: `http://localhost:9001` (User: `drop`, Password: `dropdropdrop`)
- **RabbitMQ Management**: `http://localhost:15672` (User: `drop`, Password: `dropdropdrop`)

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
