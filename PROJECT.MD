# Drop — фактическое описание проекта

> Состояние репозитория на 2026-07-25. Source of truth для этого документа —
> текущий код, миграции, конфигурация, Docker Compose, CI и тесты. Документ
> намеренно разделяет реализованные возможности, частичные решения и
> неиспользуемые заготовки.

## 1. Project summary

**Название:** Drop.

Drop — анонимный сервис временного обмена файлами. Отправитель загружает файл,
задаёт срок жизни и необязательное число получателей, получает capability-ссылку
и передаёт её получателю. Регистрация, пользователи, пароли, роли, JWT, OAuth и
email в продукте отсутствуют.

Основной сценарий:

```text
upload
  → создание Drop и capability-ссылки
  → передача ссылки
  → проверка токена и выдача download grant
  → потоковая загрузка из MinIO через API
  → истечение TTL или исчерпание max_downloads
  → Outbox
  → Celery
  → физическое удаление объекта
```

Проект решает задачу короткоживущей передачи файлов без постоянных аккаунтов и
одновременно демонстрирует backend-задачи, которых нет в обычном CRUD:

- конкурентное соблюдение лимита скачиваний;
- capability-based access без хранения исходных токенов;
- отделение метаданных от бинарных объектов;
- безопасная работа за reverse proxy;
- распределённый rate limiting;
- временные download grants и защита активного стрима;
- transactional Outbox и идемпотентная очистка;
- периодическая обработка истёкших объектов;
- интеграционные тесты на реальном PostgreSQL.

## 2. Current implementation status

### Implemented

- Однофайловый frontend на HTML/CSS/JavaScript для загрузки, получения ссылки и
  скачивания файла.
- Создание Drop через multipart upload.
- TTL и необязательный `max_downloads`.
- 128-битный случайный `public_id` как locator.
- Отдельный 256-битный capability token.
- HMAC-SHA256 токена с server-side `DROP_TOKEN_PEPPER`; raw token в БД не
  сохраняется.
- Share URL вида `/d/{public_id}#{access_token}`; fragment не отправляется
  браузером на сервер.
- Metadata-only GET, который не изменяет счётчики и grants.
- Потоковое скачивание через FastAPI без публичного MinIO URL.
- Анонимная session cookie `drop_sid` и HMAC-хеш с `SESSION_PEPPER`.
- Уникальный download grant на `(drop_id, client_session_hash)`.
- `SELECT ... FOR UPDATE` при выдаче grants.
- Redis rate limits с атомарным Lua-скриптом.
- Redis stream lock на одну одновременно активную загрузку для session + Drop.
- Проверка доверенного reverse proxy перед использованием forwarded IP headers.
- Псевдонимизация IP в download events.
- PostgreSQL, MinIO, Redis, RabbitMQ, Celery worker и Celery Beat.
- Transactional Outbox для задач удаления.
- Периодическая обработка expiration и stale grants.
- Идемпотентная Celery-задача удаления с recoverable `DELETING` state.
- Outbox claims через `FOR UPDATE SKIP LOCKED`, lease, attempts, last error и
  terminal `FAILED` state.
- JSON-логирование API/Celery, request IDs, отдельные Prometheus exporters API и
  Celery worker, health checks PostgreSQL, Redis, RabbitMQ и MinIO.
- Nginx, production Compose, полностью автономный local Compose и GitHub
  Actions CI/CD.
- Публичная панель `/logs` с последними Drop, download events и Outbox events.
- Полностью публичный observability showcase: `/stats`, raw `/metrics`,
  Prometheus UI и read-only Grafana dashboard.
- Prometheus собирает API, PostgreSQL, Redis, RabbitMQ, MinIO и Nginx через
  exporters; Grafana dashboard provision-ится из репозитория.
- Реальные Redis, MinIO и RabbitMQ Testcontainers checks.
- 70 проходящих автоматических тестов.

### Partially implemented

Следующие части существуют и работают, но имеют важные ограничения:

- **Outbox имеет recoverable at-least-once delivery**, но не может дать
  exactly-once гарантию поверх PostgreSQL и RabbitMQ: crash после broker publish
  и до `PROCESSED` всё ещё приводит к допустимому duplicate delete task.
- **`Idempotency-Key` принимается**, валидируется по длине и попадает в
  `download_events.request_id`, но отдельного idempotency store и replay
  response нет. Неизменность download counter обеспечивается session grant, а
  не этим заголовком.
- **Публичная logs dashboard** показывает только последние 50 записей каждого
  типа, не имеет pagination/filtering и намеренно не имеет авторизации.
- **Download duration в dashboard** измеряется до входа в service и не является
  полной длительностью передачи файла клиенту.
- **S3 abstraction содержит presigned URL method**, но production download flow
  его не использует.
- **Upload rate settings `RATE_LIMIT_UPLOAD_MAX/WINDOW` присутствуют**, но
  отдельная политика по ним не создаётся. Фактически upload ограничивается
  create policy и byte-budget policy.
- **Integration tests соединяются с настоящими Redis, MinIO и RabbitMQ
  containers**, но не запускают полноценный отдельный Celery worker process и
  не проверяют delivery task end-to-end через broker.

### Planned / documented only

Явного roadmap в репозитории нет. Следующие элементы присутствуют как schema или
code artifacts, но фактического workflow за ними нет; их нельзя показывать как
реализованные возможности:

- `DownloadResponse` и `S3Storage.create_download_url()` существуют, но endpoint
  выдачи presigned URL отсутствует.
- Отдельный request-count limiter из `RATE_LIMIT_UPLOAD_MAX/WINDOW` отсутствует.

Также важно: старый текст `PROJECT.MD` называл create limit `5 / 60s`, но
production/local Compose и CI фактически задают `10 / 60s`. В классе `Settings`
нет встроенных default values: все поля обязательны и должны прийти из
environment или `.env`.

## 3. Tech stack

| Технология | Фактическое назначение |
| --- | --- |
| Python 3.13+ | Основной язык API, domain/application services и workers |
| FastAPI | HTTP API, dependency injection, validation, streaming responses |
| asyncio | Асинхронная работа API, SQLAlchemy и service orchestration |
| Pydantic / pydantic-settings | Response schemas и обязательная env-конфигурация |
| PostgreSQL 16 | Source of truth для Drop, grants, events и Outbox |
| SQLAlchemy 2 Async | ORM, транзакции, row locks и atomic SQL updates |
| asyncpg | Async PostgreSQL driver |
| Alembic | Пять последовательных schema migrations |
| Redis 7 | Rate-limit counters, temporary penalties и stream locks |
| Lua в Redis | Атомарный `INCRBY` + TTL + temporary ban |
| RabbitMQ 3.13 | Celery broker |
| Celery 5 | Фоновые и периодические задачи |
| Celery Beat | Планирование expiration scan и Outbox publishing |
| MinIO / S3 API | Хранение бинарных объектов |
| boto3 | Synchronous S3 client, вызываемый через thread pool |
| Nginx | Единственная production ingress-точка, static frontend и reverse proxy |
| Prometheus | Сбор, хранение и публичный query UI метрик |
| Grafana | Публичный read-only dashboard, provisioned из репозитория |
| Docker / Docker Compose | Четырнадцать production/local services |
| uv | Управление зависимостями и запуск команд |
| pytest / pytest-asyncio | Unit и integration tests |
| Testcontainers | Реальные PostgreSQL, Redis, MinIO и RabbitMQ для integration tests |
| Ruff | Linting |
| mypy | Static type checking |
| prometheus-client | Counters, histogram и `/metrics` |
| GitHub Actions | Lint, typecheck, tests, Docker build и SSH deployment |

Frontend не использует отдельный framework: это один `frontend/index.html` с
inline CSS и JavaScript.

## 4. Architecture

### Runtime architecture

```text
Browser
  │
  │ HTTP/HTTPS через внешний TLS terminator, если он настроен
  ▼
Nginx :80
  ├── /, /d/*, /logs, /stats ───────► static frontend
  ├── /api/*, /health/* ────────────► FastAPI :8000
  │                                     ├── PostgreSQL
  │                                     ├── Redis
  │                                     └── MinIO/S3
  ├── /metrics ─────────────────────► FastAPI :8000 Prometheus exposition
  ├── /prometheus/ ─────────────────► Prometheus :9090
  └── https://grafana.shide.world ──► Shared Grafana (anonymous Viewer)

Prometheus
  ├── FastAPI /metrics
  ├── worker-metrics :8001/metrics (private Celery multiprocess registry)
  ├── postgres-exporter, redis-exporter, nginx-exporter
  ├── RabbitMQ Prometheus plugin
  └── MinIO v3 metrics endpoint

Celery Beat
  │ schedules: 10s / 5min
  ▼
RabbitMQ
  ▼
Celery Worker
  ├── читает/изменяет PostgreSQL
  ├── читает Outbox и публикует delete task обратно в RabbitMQ
  └── удаляет объекты из MinIO
```

### Ответственность компонентов

- **Nginx** отдаёт SPA, ограничивает request body до 100 MB, выставляет security
  headers, переписывает forwarded IP headers и proxy-ит только API/health.
- **FastAPI** реализует upload/download contract, capability checks,
  rate-limiting orchestration, cookies, streaming и error mapping.
- **PostgreSQL** хранит долговременное состояние и сериализует конкурирующую
  выдачу grants.
- **Redis** хранит только краткоживущую защитную координацию. Он не решает, кому
  принадлежит download slot.
- **MinIO** хранит файл отдельно от реляционных метаданных.
- **RabbitMQ** доставляет Celery tasks.
- **Celery Beat** запускает регулярный scan и Outbox publisher.
- **Celery Worker** выполняет cleanup и служебные задачи.

## 5. Project structure

```text
src/drop/
├── api/
│   ├── routes/              HTTP endpoints
│   ├── dependencies.py      построение DropService
│   ├── errors.py            domain/HTTP exception mapping
│   ├── health.py            liveness/readiness
│   ├── middleware.py        request ID, access metrics, security headers
│   └── rate_limit.py        trusted proxy parsing и Redis policies
├── application/
│   ├── schemas.py           Pydantic response/error schemas
│   └── services/            upload/download, cleanup, Outbox publisher
├── domain/
│   ├── exceptions.py        domain errors
│   ├── public_id.py         secure locator generation
│   ├── sanitization.py      filename/content-type normalization
│   └── security.py          tokens, sessions, HMAC, IP pseudonyms
├── infrastructure/
│   ├── database/            Base, engine, SQLAlchemy models
│   ├── repositories/        Drop и Outbox persistence
│   ├── storage/             boto3 S3 adapter
│   └── redis.py             async Redis client
├── workers/                 Celery app, Beat schedule и tasks
├── config.py                обязательные settings
├── logging.py               JSON formatter и redaction
├── metrics.py               Prometheus collectors
└── main.py                  FastAPI composition root

migrations/                  Alembic history
frontend/                    static SPA
nginx/                       ingress/static/proxy configuration
docker/                      multi-command container entrypoint
tests/                       31 non-integration + 30 integration tests
scripts/                     ручные race/expiration demos
.github/workflows/           CI/CD
```

Слои разделены практически, хотя строгой domain-entity abstraction нет:
application services работают с SQLAlchemy models напрямую. Domain слой
содержит security primitives, sanitization и exceptions, а repositories
инкапсулируют SQL.

## 6. Drop lifecycle

### Реально используемые переходы Drop

```text
                     S3 upload failed
                    ┌──────────────────► FAILED
                    │
create ─► UPLOADING ┤
                    │ S3 upload succeeded
                    └──────────────────► ACTIVE
                                            │
                       max_downloads reached │
                                            ├────────► CONSUMED
                                            │             │
                                 TTL passed │             │ grants finished/
                                            ▼             │ lease expired
                                         EXPIRED          │
                                            │             │
                                            └──────┬──────┘
                                                   │ Outbox + Celery cleanup
                                                   ▼
                                               DELETING
                                                   │
                                                   ▼
                                                DELETED
```

Нюансы:

- TTL проверяется синхронно в metadata/download path. Поэтому объект может ещё
  иметь DB status `ACTIVE`, но API уже вернёт `410 DROP_EXPIRED`.
- Beat раз в 5 минут переводит такие строки в `EXPIRED`.
- `CONSUMED` устанавливается сразу при создании последнего разрешённого grant,
  но объект не удаляется, пока активные grants не завершатся или не протухнут.
- Cleanup фиксирует `DELETING` до внешнего S3 delete. Если worker падает в этом
  окне, periodic sweep заново ставит cleanup event.
- Stale `UPLOADING` rows старше часа проверяются по MinIO metadata: complete
  object активируется, а отсутствующий/несовпадающий — становится `FAILED` и
  попадает в cleanup workflow.
- `FAILED` rows тоже являются cleanup candidates, поэтому неудачная
  compensation upload не остаётся вечным orphan object.

### Download grant lifecycle

```text
ACTIVE ── stream completed ──► COMPLETED
   │
   └── lease expired ────────► EXPIRED
```

Grant lease по Compose равен 300 секундам. `COMPLETED` grant может быть
переиспользован той же session, пока сам Drop и объект ещё доступны.

## 7. Upload flow

1. Nginx принимает `POST /api/v1/drops` и отклоняет тело больше `100M`.
2. FastAPI ожидает multipart fields:
   - `file`;
   - `expires_in_seconds: int > 0`;
   - `max_downloads: int > 0 | null`.
3. Create rate limit проверяет IP.
4. Service генерирует:
   - UUID `drop.id`;
   - `public_id = secrets.token_urlsafe(16)` — около 128 бит entropy;
   - `access_token = secrets.token_urlsafe(32)` — около 256 бит entropy;
   - HMAC-SHA256 токена;
   - `storage_key = drops/{drop_uuid}/source`.
5. Filename очищается от path components, control characters, leading dots и
   обрезается до 255 символов. Filename не участвует в storage key.
6. Content-Type нормализуется, но не проверяется по allowlist.
7. UploadFile читается блоками по 1 MiB. Считаются фактические байты; доверия к
   `Content-Length` нет.
8. Если превышен `MAX_UPLOAD_SIZE_BYTES`, выбрасывается `FileTooLargeError`,
   объект и DB row не создаются.
9. После полного подсчёта применяется IP byte budget с `cost=size_bytes`.
10. Файл перематывается в начало.
11. В PostgreSQL создаётся `UPLOADING` row и делается commit.
12. `boto3.upload_fileobj` выполняется в thread pool.
13. При штатной S3-ошибке service пытается удалить partial object, переводит
    row в `FAILED`, commit-ит и повторно бросает exception.
14. При успехе status меняется на `ACTIVE`, выполняется commit и возвращается
    `201 CreateDropResponse`.

Response содержит metadata, raw `access_token` и:

```text
{scheme}://{host}/d/{public_id}#{access_token}
```

Frontend хранит token только в JS memory, удаляет fragment из address bar через
`history.replaceState` и отправляет token в `X-Drop-Token`.

### Upload limitations

- API не задаёт максимальный TTL: принимается любое положительное число секунд.
- API не задаёт верхний предел `max_downloads`.
- Нулевой файл разрешён.
- Нет antivirus/malware scan и file-type allowlist.
- DB и S3 не участвуют в одной транзакции. Crash после commit `UPLOADING`, но до
  upload, оставит stuck row. Crash после S3 upload, но до `ACTIVE` commit, может
  оставить orphan object/stuck row.
- Host/scheme share URL доверяют headers. В intended production topology Nginx
  переписывает forwarded scheme, а API не опубликован напрямую.

Frontend предлагает TTL `1h`, `6h`, `24h`, `72h`, `7d` и limits
`1`, `3`, `5`, `10`, unlimited, но это UI choices, а не server-side whitelist.

## 8. Download flow

### Metadata request

`GET /api/v1/drops/{public_id}`:

1. Metadata IP rate limit.
2. Проверка `X-Drop-Token`.
3. Lookup по `public_id`.
4. Constant-time HMAC verification.
5. Проверка TTL/status.
6. Возврат metadata.

Этот endpoint не создаёт grant, не меняет `download_count` и не запускает
cleanup.

### Intentional download

`POST /api/v1/drops/{public_id}/download`:

1. Глобальный download limiter по IP.
2. Download limiter по IP + Drop.
3. Требование `X-Drop-Action: download`.
4. Проверка optional `Idempotency-Key` длиной 1–128 символов.
5. Вычисление client IP:
   - forwarded headers учитываются только от direct peer из
     `TRUSTED_PROXY_IPS`;
   - берётся первый валидный адрес `X-Forwarded-For`;
   - fallback — валидный `X-Real-IP`;
   - иначе direct peer.
6. Чтение `drop_sid`; при отсутствии генерируется новый 256-битный session ID.
7. Session + Drop rate limit.
8. Redis lock:

   ```text
   download_stream:{public_id}:{HMAC(session_id)}
   SET NX EX 300
   ```

   Повторный параллельный stream той же session получает `409`.
9. Capability verification.
10. HMAC session ID.
11. PostgreSQL `SELECT ... FOR UPDATE` Drop row.
12. Reuse существующего grant либо создание нового.
13. Только новый grant увеличивает `download_count`.
14. При достижении `max_downloads` Drop становится `CONSUMED`.
15. Создаётся `download_events` row. IP хранится как 32 hex characters
    HMAC-псевдонима.
16. Grant/counter/event commit-ятся.
17. MinIO object открывается через `get_object`.
18. FastAPI отдаёт `StreamingResponse`, читая body блоками по 1 MiB в thread
    pool.
19. Response содержит `Content-Disposition: attachment`, `Content-Length` и
    `X-Content-Type-Options: nosniff`.
20. Новая session получает HttpOnly, SameSite=Strict cookie; production cookie
    имеет `Secure`.
21. В generator `finally` закрывается S3 body, grant переводится в `COMPLETED`,
    при необходимости создаётся Outbox event и Redis lock удаляется.

### Реальная семантика `max_downloads`

`download_count` — число уникальных session grants, а не число HTTP requests и
не гарантированное число полностью переданных файлов.

- Повторный click/retry из той же cookie-session reuse-ит grant.
- Такой retry создаёт новый `download_event`, но не увеличивает counter.
- Новая cookie-session создаёт новый grant и занимает slot.
- Последний grant переводит Drop в `CONSUMED`; новые sessions больше не
  допускаются.
- Уже выданные grants могут завершить stream до cleanup.
- Удаление cookie позволяет анонимному пользователю выглядеть новой session.
  Это фундаментальное ограничение anonymous model.

Если S3 `get_object` падает после DB commit, slot уже занят. Grant останется
`ACTIVE` до lease expiration, даже если клиент не получил файл.

## 9. Concurrency

### Production path

Главная race condition:

```text
две sessions одновременно видят download_count = 0
обе считают slot доступным
обе увеличивают counter
max_downloads = 1 оказывается нарушен
```

Обычный `SELECT`, проверка в Python и отдельный `UPDATE` без lock были бы
небезопасны.

Фактический grant path сериализует операции на Drop row:

```python
result = await session.execute(
    select(DropModel)
    .where(DropModel.public_id == public_id)
    .execution_options(populate_existing=True)
    .with_for_update()
)
```

Под row lock code:

1. повторно проверяет status, TTL и limit;
2. ищет grant текущей session;
3. reuse-ит существующий grant;
4. либо создаёт новый grant и увеличивает counter;
5. flush-ит изменения до снятия lock.

Вторая защита:

```text
UNIQUE(download_grants.drop_id, download_grants.client_session_hash)
```

PostgreSQL является concurrency authority. Redis lock решает другую задачу —
не позволяет одной session одновременно держать два stream-а, но не является
source of truth для `max_downloads`.

Обеспечиваемый application invariant:

```text
число grants == download_count
download_count <= max_downloads, если max_downloads задан
одна session имеет не более одного grant на Drop
```

В БД нет `CHECK(download_count <= max_downloads)`, поэтому прямые
внеприложенческие записи могут нарушить invariant.

### Legacy atomic counter path

Repository также содержит `consume_download()` с единым conditional:

```text
UPDATE drops
SET download_count = download_count + 1, ...
WHERE status = ACTIVE
  AND expires_at > now
  AND (max_downloads IS NULL OR download_count < max_downloads)
RETURNING *
```

Этот метод атомарен и покрыт concurrency tests, но текущий HTTP/service download
flow его не вызывает: production semantics построена на grants + row lock.
Portfolio showcase должен демонстрировать `acquire_download_grant()`, а
`consume_download()` можно показать как более простой альтернативный/legacy
atomic approach.

## 10. Anti-fraud / Security

### Threat → Protection

| Threat | Реализованная защита |
| --- | --- |
| Угадывание URL | 128-битный random `public_id` плюс отдельный 256-битный token |
| Утечка token из БД | В БД только HMAC-SHA256 с server-side pepper |
| Timing comparison | `secrets.compare_digest` |
| Token в HTTP URL/log/referrer | Token находится в fragment, затем передаётся header-ом |
| Enumeration по ответам | Unknown ID, missing/wrong token и недоступные Drop до проверки capability дают одинаковый 404 |
| Безопасный preview | GET metadata не меняет state |
| CSRF/случайный download | Token header, `X-Drop-Action`, SameSite=Strict cookie, same-origin frontend |
| Cookie theft через JS | HttpOnly cookie |
| Session ID в БД | HMAC session ID |
| Повторные clicks/retries | Unique session grant |
| Same-session concurrent streams | Redis `SET NX EX` lock |
| Race между recipients | PostgreSQL row lock + unique constraint |
| Brute force capability | Общий rate limit плюс отдельный invalid-token limiter и 600s penalty |
| Upload flood | Request count limiter, 500 MiB/hour byte budget, Nginx/app 100 MiB limit |
| Download flood | IP, IP+Drop и session+Drop limits |
| Forwarded-header spoofing | Headers учитываются только от configured trusted proxy |
| Raw IP в public logs | HMAC-псевдоним; одинаковый IP коррелируется без раскрытия адреса |
| Path traversal | Sanitized filename и UUID-only storage key |
| Browser content sniffing | Attachment disposition + `nosniff` |
| Прямой доступ к object storage | MinIO ports не опубликованы, API stream only |
| Token/secret в structured extras | Sensitive-key redaction |
| Clickjacking/indexing/referrer leakage | DENY, noindex, no-referrer, CSP |
| Redis outage bypass | Security-sensitive limits и stream lock fail closed |

### Rate limits из production/local Compose

`Settings` не содержит defaults; ниже — фактический deployment profile:

| Policy | Scope | Значение | Redis failure |
| --- | --- | ---: | --- |
| create | IP | 10 requests / 60s | fail closed |
| upload bytes | IP | 524,288,000 bytes / 3600s | fail closed |
| metadata | IP | 60 requests / 60s | fail open |
| download | IP | 10 requests / 60s | fail closed |
| download per Drop | IP + Drop | 5 requests / 60s | fail closed |
| download per session | session + Drop | 10 requests / 60s | fail closed |
| invalid token | IP | 10 / 60s, затем ban 600s | fail closed |

Алгоритм — fixed window, а не sliding window. Lua выполняет `INCRBY`, создаёт
или восстанавливает TTL и при превышении ставит temporary ban key.

### Security headers

API middleware:

- `Cache-Control: no-store, no-cache, must-revalidate`;
- `Referrer-Policy: no-referrer`;
- `X-Content-Type-Options: nosniff`;
- `X-Frame-Options: DENY`;
- `X-Robots-Tag: noindex, nofollow, noarchive`;
- CSP с `default-src 'self'`, запретом objects и frames.

Nginx добавляет аналогичные headers и HSTS. Для static frontend CSP разрешает
`unsafe-inline`, потому что CSS/JS встроены в HTML.

### CORS и CSRF

- CORS middleware отсутствует; API рассчитан на same-origin frontend.
- Формального CSRF middleware/token нет.
- Download требует capability header и custom action header, а session cookie
  имеет SameSite=Strict. Cookie сама по себе не авторизует скачивание.

### Remaining limitations

- Обладатель полной ссылки может удалить cookies, менять браузеры/IP/VPN и
  создавать новые anonymous identities.
- Нет recipient authentication, second factor или account-level quotas.
- Нет malware scanning, content-type allowlist и DLP.
- TLS certificates/termination не настроены в репозитории. Compose публикует
  Nginx HTTP port; HSTS полезен только при фактическом HTTPS снаружи.
- Public `/logs` раскрывает filenames, public IDs, request IDs, statuses,
  Outbox payloads и коррелируемые IP pseudonyms всем посетителям. Capability
  token там отсутствует, но это всё равно metadata disclosure.
- Readiness возвращает строки исключений зависимостей, что может раскрыть
  внутренние детали.
- JSON redaction проверяет keys в structured extras, но не scrub-ит arbitrary
  message strings и values внутри lists.
- API access metrics используют raw path как Prometheus label, поэтому
  `public_id` создаёт high-cardinality series.
- Нет encryption-at-rest configuration в репозитории; это deployment concern.
- Нельзя гарантировать удаление из backups, replicas или MinIO version history
  без отдельной infrastructure policy.

## 11. Redis

Redis используется для двух классов краткоживущего состояния.

### Rate limiting

- shared counters между API replicas;
- fixed-window TTL;
- byte-weighted upload budget;
- temporary invalid-token ban;
- hashed/pseudonymized key material.

### Stream coordination

На session + Drop создаётся lock с TTL 300 секунд. Он удаляется после окончания
stream или истекает при crash.

### Source of truth

Redis нигде не является source of truth для:

- download counter;
- ownership grant;
- Drop status;
- expiration;
- cleanup requirement.

Его потеря может сбросить rate-limit history/locks, но не изменяет persistent
лимит grants. При недоступности Redis metadata limiter fail-open, а create,
download и abuse protection fail-closed с `503`.

`close_redis_client()` существует, но application shutdown hook его не вызывает.

## 12. PostgreSQL

PostgreSQL — authoritative persistent store и concurrency coordinator.

### Таблицы

```text
drops
  1 ──────── N download_grants
                  FK drops.id, ON DELETE CASCADE

drops
  1 ········ N download_events
                  drop_id indexed, но ForeignKey не объявлен

outbox_events
  payload["drop_id"] содержит UUID строкой, FK отсутствует
```

#### `drops`

- UUID primary key;
- unique indexed `public_id`;
- non-null HMAC `access_token_hash`;
- unique `storage_key`;
- filename, content type, size;
- `DropStatus`;
- max/count;
- expiration, creation, consumption и deletion timestamps.

#### `download_grants`

- UUID primary key;
- FK на `drops` с cascade delete;
- indexed `drop_id`;
- HMAC session;
- `GrantStatus`;
- lease timestamps;
- unique `(drop_id, client_session_hash)`.

#### `outbox_events`

- UUID primary key;
- event type;
- JSON payload;
- indexed `OutboxStatus`;
- created/processed timestamps.

#### `download_events`

- autoincrement integer primary key;
- indexed `drop_id`, но без FK;
- pseudonymized IP, user agent, request ID;
- snapshot download number и duration.

### Enums

- `DropStatus`: 8 values;
- `GrantStatus`: 3 values;
- `OutboxStatus`: 3 values.

### Constraints and indexes

Сильные DB constraints — unique public/storage identifiers, unique grant per
session, FK cascade для grants. Отсутствуют check constraints на positive size,
positive max downloads и `download_count <= max_downloads`.

### Transaction boundaries

- Upload row `UPLOADING` commit-ится до S3 upload.
- Grant, counter и download event commit-ятся вместе.
- Grant completion и Outbox insertion commit-ятся вместе.
- Expiration status и Outbox insertion commit-ятся вместе.
- S3 deletion выполняется до DB transition `DELETED`.
- Broker publish выполняется до Outbox transition `PROCESSED`.

Четыре Alembic revisions создают `drops`, `outbox_events`,
`download_events`, затем capability hash и `download_grants`.

## 13. Object storage

MinIO используется через S3 API.

- Bucket берётся из `S3_BUCKET`.
- При создании adapter выполняется `head_bucket`; при ошибке предпринимается
  `create_bucket`.
- Object key всегда `drops/{drop_uuid}/source`.
- Original filename не участвует в key.
- Production Compose не публикует ports 9000/9001.
- Bucket не получает public ACL/policy из кода.
- Upload выполняется через `upload_fileobj`.
- Download открывается через `get_object` и stream-ится API блоками 1 MiB.
- `create_download_url()` существует, но production flow его не вызывает.
- Delete вызывает S3 `delete_object`; повторный delete в S3 семантически
  безопасен.
- Cleanup service дополнительно early-return-ит для DB status `DELETED`.

`_ensure_bucket()` подавляет ошибки create bucket. Это упрощает конкурентный
startup, но может скрыть причину auth/network failure до первой реальной
операции.

Если процесс падает после S3 delete, но до DB commit, retry снова удалит тот же
key и затем сможет выставить `DELETED`. Это делает crash window восстанавливаемым.

## 14. Background processing

В коде четыре Celery task definitions.

| Task | Trigger | Назначение | Ack/retry/idempotency |
| --- | --- | --- | --- |
| `drop.ping` | Только вручную | Возвращает `pong` | Обычная task |
| `drop.delete_file` | Outbox publisher | Удаляет object и ставит `DELETED` | `acks_late`, autoretry, exponential backoff+jitter, max 5, idempotent |
| `drop.cleanup_expired` | Beat каждые 300s | Помечает expired Drop, expires stale grants, восстанавливает stale upload/delete и создаёт Outbox | `acks_late`, без autoretry; следующий Beat run повторит scan |
| `drop.publish_outbox` | Beat каждые 10s | Claim-ит до 100 events, ставит delete tasks в RabbitMQ и фиксирует delivery result | `acks_late`, без autoretry; следующий run reclaim-ит stale lease |

Celery:

- JSON serializer;
- JSON-only accepted content;
- UTC;
- remote control disabled;
- RabbitMQ broker;
- result backend не настроен.

`drop.delete_file` учитывает task failures/retries метриками. Две periodic tasks
при ошибке будут снова запущены Beat по расписанию, но не имеют собственной
`autoretry_for`.

## 15. Transactional Outbox

Outbox реализован.

### Flow

```text
DB transaction
  ├── complete/expire grant or change Drop state
  └── INSERT outbox_events(PENDING, DROP_CLEANUP_REQUIRED)
          │
          │ commit
          ▼
Beat → RabbitMQ → drop.publish_outbox
          │
          ├── SELECT ... FOR UPDATE SKIP LOCKED
          ├── PENDING/stale PROCESSING → PROCESSING + lease + commit
          ├── delete_drop_file.apply_async(drop_id, task_id=event_id)
          └── PROCESSED or PENDING/FAILED + commit
                         │
                         ▼
                    RabbitMQ
                         │
                         ▼
                 drop.delete_file worker
                         │
                         ├── MinIO delete
                         └── PostgreSQL DELETED
```

### Решаемая проблема

Без Outbox API мог бы:

1. commit-нуть `CONSUMED`;
2. упасть до publish в RabbitMQ;
3. навсегда оставить object без cleanup task.

Outbox сохраняет cleanup intent в той же PostgreSQL transaction, что и
grant-completion/expiration state. Publisher атомарно claim-ит rows с
`FOR UPDATE SKIP LOCKED`, commit-ит lease перед broker I/O и восстанавливает
зависший `PROCESSING` event через минуту.

### Delivery semantics and limitations

- Crash до broker publish: `PROCESSING` lease протухает и event reclaim-ится.
- Broker error: event возвращается в `PENDING` с `last_error`; после 10 попыток
  становится `FAILED`.
- Crash после broker publish, но до mark processed: возможен duplicate task.
- Duplicate task безопасен благодаря idempotent delete.
- Несколько publisher-ов не claim-ят одну row одновременно благодаря
  `SKIP LOCKED`.
- Неизвестный event type/payload фиксируется как retryable/terminal delivery
  error, а не теряется как `PROCESSED`.
- Отдельного dead-letter queue и UI для ручного retry `FAILED` events пока нет.

То есть проект реализует практическую at-least-once Outbox pattern, но не
exactly-once delivery.

## 16. Expiration and cleanup

Expiration состоит из синхронной защиты и асинхронной физической очистки.

1. В Drop хранится timezone-aware `expires_at`.
2. Metadata и download сравнивают его с `datetime.now(UTC)` и сразу запрещают
   доступ после TTL.
3. Beat каждые 5 минут запускает `drop.cleanup_expired`.
4. Service:
   - находит `ACTIVE` rows с `expires_at <= now`;
   - переводит их в `EXPIRED`;
   - переводит stale `ACTIVE` grants в `EXPIRED`;
   - восстанавливает stale `UPLOADING` rows по фактическому MinIO object size;
   - повторно рассматривает `CONSUMED`, `EXPIRED`, `DELETING` и `FAILED` как
     cleanup candidates;
   - проверяет число активных grants;
   - создаёт `DROP_CLEANUP_REQUIRED`, если нет open `PENDING/PROCESSING` event;
   - commit-ит state и Outbox вместе.
5. Outbox publisher раз в 10 секунд dispatch-ит delete task.
6. Worker повторно проверяет active grants, удаляет MinIO object и commit-ит
   `DELETED`.

Если worker выключен, API всё равно запрещает expired download. DB rows и
объекты остаются до восстановления Beat/worker. Pending/processing Outbox
events и periodic candidate sweep сохраняют cleanup intent.

Если active stream пережил переход Drop в `CONSUMED`, удаление ждёт completion
или 300-second lease expiration плюс следующий 5-minute scan.

## 17. API

В FastAPI явно объявлено 7 endpoints, и все они доступны через production Nginx.
Помимо API публичны Prometheus, Grafana и SPA showcase routes.

### Public Drop endpoints

#### `POST /api/v1/drops`

- **Назначение:** создать Drop.
- **Input:** multipart `file`, positive `expires_in_seconds`, optional positive
  `max_downloads`.
- **Response:** `201`, metadata, one-time raw access token и share URL.
- **Errors:** 413, 422, 429, 500, 503.

#### `GET /api/v1/drops/logs/data`

- **Назначение:** данные public logs dashboard.
- **Input:** нет.
- **Response:** до 50 Drop, 50 download events и 50 Outbox tasks.
- **Auth:** отсутствует намеренно.
- **Protection:** metadata rate limit.
- **Errors:** 429/500, а при Redis failure limiter fail-open.

#### `GET /api/v1/drops/{public_id}`

- **Назначение:** metadata-only lookup.
- **Input:** `X-Drop-Token`.
- **Response:** Drop metadata.
- **Errors:** 404 invalid capability/not found, 409 not ready, 410
  expired/consumed, 429.

#### `POST /api/v1/drops/{public_id}/download`

- **Назначение:** intentional file stream.
- **Input:** `X-Drop-Token`, обязательный `X-Drop-Action: download`, optional
  `Idempotency-Key`, optional/new `drop_sid` cookie.
- **Response:** streamed bytes, attachment filename, optional Set-Cookie.
- **Errors:** 400 invalid key/cookie, 403 missing action, 404 invalid
  capability, 409 concurrent stream, 410 expired/consumed, 429, 503 Redis
  protection unavailable, 500/S3 failure.

### Health and internal endpoints

#### `GET /health/live`

Process liveness, всегда `{status: "ok"}` при работающем event loop.

#### `GET /health/ready`

Проверяет PostgreSQL `SELECT 1`, Redis `PING`, RabbitMQ broker connection и
MinIO `list_buckets`. Возвращает 503, если хотя бы одна проверка упала.

#### `GET /metrics`

Prometheus text format. Endpoint исключён из OpenAPI, но намеренно публично
proxy-ится Nginx как `/metrics` для showcase и внешнего scraping.

### Frontend routes

Nginx SPA fallback обслуживает `/`, `/d/{public_id}`, `/logs` и `/stats`. Это
не отдельные FastAPI routes. `/stats` запрашивает публичный Prometheus HTTP API
и показывает короткую витрину ключевых counters.

Автоматически генерируемые `/docs`, `/redoc` и `/openapi.json` включены во всех
окружениях и публично proxy-ятся production Nginx как часть showcase.

## 18. Error model

Domain exceptions:

- `DropNotFoundError`;
- `DropExpiredError`;
- `DropConsumedError`;
- `DropNotReadyError`;
- `FileTooLargeError`;
- `RateLimitExceededError`.

Единый JSON envelope:

```json
{
  "error": {
    "code": "DROP_NOT_FOUND",
    "message": "Drop not found.",
    "details": null
  },
  "request_id": "..."
}
```

Mapping:

| HTTP | Когда |
| ---: | --- |
| 400 | Invalid `Idempotency-Key` или слишком длинная session cookie |
| 403 | Нет `X-Drop-Action: download` |
| 404 | Unknown ID, missing/wrong capability, generic unavailable download |
| 409 | Valid capability, но Drop not ready; либо active same-session stream |
| 410 | Valid capability, но TTL прошёл или limit consumed |
| 413 | Реальный upload size превышает app limit |
| 422 | FastAPI/Pydantic validation |
| 429 | Redis rate limit, с `Retry-After` |
| 500 | Необработанная ошибка, включая часть storage/database failures |
| 503 | Readiness failed, fail-closed limiter/stream lock unavailable |

Все handlers добавляют `X-Request-ID`. Для 5xx logger получает exception
traceback. `HTTPException.detail` преобразуется в string, поэтому structured
readiness detail в unified error превращается в строковое сообщение.

## 19. Testing

На текущем состоянии:

- **70 tests total**;
- **36 tests** находятся в `tests/integration`;
- **32 tests** находятся вне integration directory;
- полный `pytest` проходит;
- Ruff проходит;
- Mypy проходит для 53 source/test files.

### Test infrastructure

- Testcontainers запускает `postgres:16-alpine`, если не задан
  `TEST_DATABASE_URL`.
- На PostgreSQL создаётся schema из SQLAlchemy metadata.
- Для каждого integration test очищаются `download_events`, `outbox_events` и
  `drops`; grants удаляются cascade-ом.
- Pool для concurrency tests: `pool_size=20`, `max_overflow=50`.
- Отдельный test запускает реальные Alembic migrations до head.
- Отдельные Testcontainers tests поднимают реальные Redis 7, MinIO и RabbitMQ
  и проверяют Lua limiter, S3 lifecycle и broker readiness.
- Mock/double tests остаются для быстрых локальных failure scenarios и не
  заменяют реальные external-service checks.

### Сильнейшие concurrency scenarios

1. **Atomic counter, limit 1**
   - 50 concurrent repository calls;
   - `max_downloads=1`;
   - ровно 1 success;
   - persisted count = 1, status = `CONSUMED`.

2. **Atomic counter, limit 5**
   - 50 concurrent calls;
   - ровно 5 success;
   - persisted count = 5.

3. **Unlimited counter**
   - 20 concurrent calls;
   - 20 success;
   - count = 20, status остаётся `ACTIVE`.

4. **Same-session grant spam**
   - 50 concurrent service calls с одним session ID;
   - все 50 reuse/получают доступ на service layer;
   - создаётся ровно 1 grant;
   - `download_count=1`.
   - Тест намеренно обходит HTTP Redis stream lock; на route layer параллельные
     streams той же session получили бы 409.

5. **Different sessions**
   - 50 concurrent service calls с 50 session IDs;
   - `max_downloads=1`;
   - ровно 1 success и 1 grant;
   - 49 rejected;
   - status = `CONSUMED`.

6. **Safe metadata**
   - 100 последовательных metadata reads;
   - 0 grants;
   - count остаётся 0.

### Other covered scenarios

- 256-bit token length, 32-byte HMAC и wrong-token verification.
- Одинаковая domain error для missing ID, wrong token и missing token.
- Expired access rejection.
- Expiration scan и единственный pending Outbox event.
- Grant completion → Outbox in DB.
- Outbox dispatch → task call → `PROCESSED`.
- Stale `PROCESSING` Outbox event reclaim-ится и terminal publish error получает
  `FAILED`/`last_error`.
- Cleanup idempotency и сохранение первого `deleted_at`.
- Stale complete upload восстанавливается в `ACTIVE`.
- S3 upload error → partial delete attempt → `FAILED`.
- S3 delete error не переводит Drop в `DELETED`.
- Filename path traversal/control character sanitization.
- 2 MiB upload при 1 MiB test limit → rejection и отсутствие DB row.
- Celery helper tasks.
- Structured logging/context/redaction.
- Request ID generation/preservation.
- Unified 404/422 responses.
- Public logs endpoint.
- Verified forwarded client IP передаётся в download logging.
- Security headers.
- Prometheus endpoint/counter increments.
- Worker counter, записанный в отдельном process, виден collector process через
  shared multiprocess directory.
- Readiness success/failure.
- Redis Lua byte cost/TTL, ban, Retry-After, scopes и failure policies.
- Настоящие Redis, MinIO и RabbitMQ containers.

### Manual scripts

- `scripts/race_test.py`: 100 HTTP download attempts against a running stack.
- `scripts/expiration_test.py`: 5-second TTL demonstration.

Это demo scripts, не часть 70 automated tests. `race_test.py` также сталкивается
с HTTP rate limits и считает не все возможные rejection codes, поэтому
автоматические PostgreSQL tests являются более надёжным доказательством
concurrency invariant.

## 20. Reliability / failure scenarios

| Failure | Фактическое поведение |
| --- | --- |
| Concurrent recipients | PostgreSQL row lock сериализует grant creation; unique constraint защищает same-session uniqueness |
| Concurrent same session | DB reuse-ит один grant; HTTP layer дополнительно разрешает один active stream через Redis |
| PostgreSQL failure | Операция падает; обычно unified 500, readiness 503; автоматического DB retry нет |
| Redis failure на metadata | Fail open: metadata остаётся доступным |
| Redis failure на upload/download/security | Fail closed: 503 |
| RabbitMQ failure при API request | API не пишет broker напрямую; cleanup intent остаётся в Outbox |
| RabbitMQ failure в publisher | Event возвращается в `PENDING` с ошибкой; после 10 попыток `FAILED`, а candidate sweep может создать новый cleanup intent |
| Worker выключен | Expired/consumed access уже запрещён, но object остаётся до восстановления worker |
| Delete worker exception | До 5 autoretries с backoff/jitter; task имеет `acks_late` |
| Duplicate delete task | Early return для `DELETED`, S3 delete idempotent |
| MinIO upload failure | Partial delete attempt, Drop → `FAILED`, exception наружу |
| MinIO download/get failure | Grant/event/counter уже commit-нуты; HTTP падает, grant ждёт lease cleanup |
| MinIO delete failure | DB не становится `DELETED`; exception позволяет task retry |
| Crash между DB event и broker | PENDING/leased Outbox остаётся в PostgreSQL и reclaim-ится |
| Crash после broker publish до Outbox commit | Duplicate task возможен и безопасен |
| Crash после object delete до DB commit | Retry повторит delete и сможет commit-нуть `DELETED` |
| Crash во время upload dual-write | Через час recovery scan сверяет MinIO size: complete object → ACTIVE, mismatch/absence → FAILED + cleanup |
| Beat выключен | TTL всё равно проверяется API, но DB status/physical cleanup задерживаются |

Отдельное ограничение: `cleanup_expired` и `publish_outbox` не имеют
`autoretry_for`. Их устойчивость основана на повторяющемся Beat schedule.

## 21. Observability

### Logging

- JSON formatter с UTC timestamp, level, logger и message.
- ContextVars: `request_id`, `drop_id`, `task_id`.
- HTTP method/path/status/duration.
- Sensitive-key masking.
- Nginx JSON access logs.
- Download events в PostgreSQL.
- Request ID принимается от клиента или генерируется UUID и возвращается в
  response.

Ограничения:

- Client-supplied request ID не ограничен по длине middleware-ом.
- Nginx `request_id` логирует только входящий header; сгенерированный API ID
  обратно в Nginx access log не попадает.
- Public dashboard — operational view, а не полноценный log backend.

### Metrics

Collectors:

- HTTP request counter;
- HTTP duration histogram;
- upload success/failed/rejected;
- successful unique grants/downloads;
- rejected downloads by reason;
- invalid capabilities;
- rate-limited requests;
- grants created/reused;
- concurrent stream rejections;
- Celery failures;
- cleanup retries.

Ограничения:

- API использует обычный in-process registry. Celery worker и отдельный
  `worker-metrics` разделяют private `PROMETHEUS_MULTIPROC_DIR`; entrypoint
  очищает его до старта Celery. Этот volume не используется API или Beat.
- Raw request path используется как label и создаёт high cardinality.
- Dashboard provisioned в Grafana; alert rules в репозитории пока нет.

### Health

- `/health/live`: process liveness.
- `/health/ready`: PostgreSQL + Redis + RabbitMQ broker + MinIO.
- Наличие работающего Celery worker и выполнение task всё ещё не проверяются.

## 22. Docker / deployment

### Production Compose: 14 services

| Service | Назначение | External port |
| --- | --- | --- |
| nginx | Static frontend + reverse proxy | `${NGINX_PORT}:80` |
| api | FastAPI/Uvicorn, startup Alembic migration | Нет |
| worker | Celery worker | Нет |
| beat | Celery Beat | Нет |
| postgres | PostgreSQL 16 | Нет |
| minio | S3 + console внутри сети | Нет |
| rabbitmq | Broker + management plugin внутри сети | Нет |
| redis | Counters/locks | Нет |
| worker-metrics | Private Celery multiprocess metrics endpoint | Нет |
| postgres-exporter | PostgreSQL metrics для Prometheus | Нет |
| redis-exporter | Redis metrics для Prometheus | Нет |
| nginx-exporter | Nginx stub-status metrics для Prometheus | Нет |
| prometheus | Time-series storage и public query UI через Nginx | Нет |
| grafana | Public anonymous Viewer dashboard через Nginx | Нет |

Persistent named volumes: PostgreSQL, MinIO, RabbitMQ, Redis, private worker
metrics, Prometheus TSDB и Grafana data.

API healthcheck вызывает `/health/live`. PostgreSQL, RabbitMQ и Redis имеют
healthchecks. MinIO только `service_started`, без Compose healthcheck.

Nginx:

- единственная опубликованная точка;
- `client_max_body_size 100M`;
- 300-second body/proxy read timeout;
- static SPA fallback;
- `/api/`, `/health/` и `/metrics` proxy;
- public `/prometheus/` reverse proxy и external link на `https://grafana.shide.world`;
- server tokens off;
- JSON access logs и security headers.

API отдаёт свой registry на `/metrics`. `worker-metrics` отдаёт private Celery
multiprocess registry на internal `:8001/metrics`; Prometheus scrape-ит оба
endpoints.

### Local Compose

- те же 14 services;
- из коробки работает без `.env`;
- development-only credentials встроены;
- frontend доступен на `http://localhost:4917`;
- public showcase: `/stats`, `/metrics`, `/prometheus/` и shared Grafana на
  `https://grafana.shide.world`;
- отдельные local volumes.

### Container startup

Один Docker image используется тремя commands:

- `api`: `alembic upgrade head`, затем Uvicorn;
- `worker`: Celery worker;
- `beat`: Celery Beat.

Worker/Beat не зависят от завершения API migrations, только от инфраструктуры.
На свежем параллельном startup существует небольшое окно, когда periodic task
может стартовать до завершения migrations.

### CI/CD

На push/PR в `main`/`master`:

1. checkout;
2. uv + Python 3.13;
3. dependency sync;
4. Ruff;
5. Mypy `src`;
6. Pytest;
7. Docker build.

После успешного CI на main/master выполняется SSH deployment:

- обязательные GitHub Variables:
  `SERVER_HOST`, `SERVER_USER`, `SERVER_PORT`, `TARGET_DIR`, `NGINX_PORT`;
- обязательные Secrets:
  `SERVER_SSH_KEY`, `DROP_TOKEN_PEPPER`, `SESSION_PEPPER`,
  `POSTGRES_PASSWORD`, `RABBITMQ_PASSWORD`, `MINIO_PASSWORD`;
- workflow падает при пустом значении;
- на сервере checkout синхронизируется с remote branch;
- защищённый `.env` создаётся с `umask 077`;
- запускается `docker compose up -d --build --remove-orphans`;
- Alembic вызывается повторно и выводится `docker compose ps`.

TLS deployment, backups, replicas, secret manager и monitoring stack в
репозитории не реализованы.

## 23. Strongest engineering decisions

### 1. Capability token отделён от public locator

**Проблема:** один угадываемый ID одновременно как адрес и credential облегчает
enumeration и делает DB leak опаснее.

**Решение:** 128-bit locator + отдельный 256-bit token, в БД только peppered
HMAC.

**Почему это важно:** демонстрирует capability security и минимизацию stored
secrets.

### 2. PostgreSQL управляет download limits

**Проблема:** конкурентные requests могут oversubscribe `max_downloads`.

**Решение:** row-level lock, повторная проверка под lock, grant insertion и
counter update в одной transaction.

**Почему это важно:** correctness не зависит от process-local state или
ненадёжного distributed lock.

### 3. Unique grant на anonymous session

**Проблема:** retry/double-click не должен сжигать дополнительные slots.

**Решение:** HMAC session cookie и unique `(drop_id, client_session_hash)`.

**Почему это важно:** DB constraint превращает бизнес-инвариант в
конкурентно-безопасную гарантию.

### 4. Активный stream отделён от consumed state

**Проблема:** последний разрешённый recipient должен закончить download, даже
если limit уже исчерпан.

**Решение:** grants имеют lease/status; cleanup ждёт отсутствие active grants.

**Почему это важно:** lifecycle учитывает длительные streaming operations.

### 5. Transactional Outbox

**Проблема:** DB commit и broker publish нельзя сделать одной обычной
транзакцией.

**Решение:** cleanup intent сохраняется в PostgreSQL и позже публикуется.

**Почему это важно:** crash не теряет обязательство удалить файл.

### 6. Идемпотентный cleanup

**Проблема:** at-least-once delivery создаёт duplicate tasks.

**Решение:** повторный delete безопасен, `deleted_at` не переписывается.

**Почему это важно:** worker можно ретраить без exactly-once infrastructure.

### 7. Layered Redis protection с разными failure modes

**Проблема:** abuse protection и metadata availability имеют разные приоритеты.

**Решение:** security-sensitive routes fail-closed, metadata fail-open; Lua
атомарно ведёт counters/TTL/ban.

**Почему это важно:** failure policy выбрана по риску, а не одинаково для всех
routes.

### 8. Private object storage и API streaming

**Проблема:** public bucket URL обошёл бы capability, grant и counters.

**Решение:** MinIO internal-only, object выдаёт API после всех checks.

**Почему это важно:** authorization остаётся в одной контролируемой точке.

### 9. Defense-in-depth upload validation

**Проблема:** `Content-Length` можно не прислать или подделать.

**Решение:** Nginx limit плюс подсчёт реально прочитанных bytes в application.

**Почему это важно:** защита работает на ingress и business layer.

### 10. Реальные PostgreSQL concurrency tests

**Проблема:** SQLite/mocks не воспроизводят row locks и PostgreSQL semantics.

**Решение:** Testcontainers PostgreSQL и 20–50 concurrent operations.

**Почему это важно:** главный invariant проверяется в подходящей СУБД.

## 24. What makes this more than CRUD

Drop показывает знания beyond basic create/read/update/delete:

- проектирование security contract без accounts;
- entropy, HMAC, constant-time verification и generic enumeration responses;
- корректная работа URL fragments и headers;
- транзакционное моделирование grants;
- row-level locking и unique constraints;
- различие между HTTP request count, unique recipient и active stream;
- обработка race conditions и retries;
- lifecycle с leases и deferred cleanup;
- dual-write problem и Outbox;
- idempotent background consumers;
- distributed fixed-window rate limits;
- explicit fail-open/fail-closed decisions;
- reverse-proxy trust boundary;
- separation PostgreSQL metadata / S3 binary data;
- recovery analysis для crash windows;
- integration testing на real PostgreSQL;
- operational concerns: health, metrics, request correlation, containers и CI.

Для junior Python Backend portfolio это хороший пример проекта, где ценность
заключается не в количестве endpoints, а в гарантиях при concurrency и partial
failures.

## 25. Interview talking points

1. **Почему `public_id` не является credential?**

   Потому что locator и authorization разделены; access даёт 256-bit token.

2. **Почему token хранится как HMAC, а не обычный SHA-256?**

   Pepper не позволяет эффективно проверять украденную БД независимо от server
   secret.

3. **Почему token находится после `#` в ссылке?**

   Fragment не отправляется HTTP server/proxy и не попадает в request line.

4. **Что произойдёт при 50 одновременных recipients и limit=1?**

   Row lock сериализует grants; только один новый grant увеличит counter.

5. **Почему не использовать Redis lock как единственную защиту limit?**

   Redis state временный; authoritative invariant и transaction уже находятся в
   PostgreSQL.

6. **Зачем unique constraint, если есть row lock?**

   Это второй DB-level guard для one-session-one-grant и защита от будущих
   обходных code paths.

7. **Почему metadata GET не уменьшает limit?**

   Safe/idempotent GET не должен иметь скрытый destructive side effect.

8. **Что означает `download_count`?**

   Число уникальных session grants, не число clicks и не число завершённых
   byte streams.

9. **Что будет, если клиент оборвёт последний download?**

   Generator пытается завершить grant; при process crash grant lease протухнет,
   periodic cleanup сможет продолжить.

10. **Зачем Outbox, если можно вызвать Celery после commit?**

    Crash между commit и publish потерял бы cleanup task.

11. **Что будет при duplicate Celery task?**

    Delete consumer идемпотентен; повторный вызов не меняет первый `deleted_at`.

12. **Что будет при RabbitMQ outage?**

    Cleanup intent остаётся PENDING в PostgreSQL; API download correctness не
    зависит от broker.

13. **Что будет при Redis outage?**

    Metadata остаётся доступным, security-sensitive operations возвращают 503.

14. **Почему файлы не лежат в PostgreSQL?**

    Object storage лучше подходит для больших binary streams; PostgreSQL хранит
    transactional metadata и invariants.

15. **Какие слабые места остались?**

    Anonymous identity bypass, допустимые at-least-once duplicate tasks,
    одночасовое окно до upload recovery, public logs metadata и отсутствие
    end-to-end Celery worker delivery test через настоящий broker.

## 26. Numbers and facts for portfolio

- **7** явно объявленных FastAPI endpoints.
- **7** endpoints доступны через production Nginx.
- **3** public observability routes: `/stats`, `/metrics`, `/prometheus/`, плюс
  external link на shared Grafana.
- **4** frontend SPA routes/screens: `/`, `/d/{public_id}`, `/logs`, `/stats`.
- **4** PostgreSQL tables.
- **5** Alembic revisions.
- **3** database enums, всего **14** enum values.
- **4** Celery tasks.
- **2** Beat schedules: каждые **10 секунд** и **5 минут**.
- **14** Docker Compose services.
- **7** persistent infrastructure volumes.
- **70** automated tests: **36 integration**, **34 non-integration**.
- **70/70** tests проходят на текущем состоянии.
- **50** concurrent attempts → **1** success при limit=1.
- **50** concurrent attempts → **5** success при limit=5.
- **20** concurrent attempts → **20** success для unlimited Drop.
- **50** same-session service calls → **1** grant и counter=1.
- **50** different sessions при limit=1 → **1** grant.
- **100** metadata reads → counter остаётся 0.
- **100 MiB** upload limit в Nginx и application Compose settings.
- **1 MiB** application read/stream chunk.
- **500 MiB/hour** upload byte budget по IP в Compose profile.
- **300 seconds** stream lock/grant lease.
- **128-bit** public locator entropy.
- **256-bit** access token и anonymous session entropy.
- **32-byte** HMAC-SHA256 token/session digest.
- **32 hex characters** сохраняемого IP pseudonym.
- UI TTL: **1h, 6h, 24h, 72h, 7d**.
- API TTL: любое положительное число секунд, server-side maximum отсутствует.
- UI download limits: **1, 3, 5, 10, unlimited**.
- Outbox batch: до **100** events.
- Public dashboard: до **50** Drop, **50** download events и **50** tasks.
- Delete task: до **5** autoretries, backoff capped at **60 seconds**.
- Outbox processing lease: **60 seconds**; terminal delivery attempts: **10**.
- Upload crash-recovery grace: **1 hour**.

## 27. Portfolio-ready summary

### One-line description

Drop — анонимный сервис временной передачи файлов с capability access,
конкурентно-безопасными download grants и автоматическим удалением через
transactional Outbox.

### Short description

FastAPI-сервис принимает файл, сохраняет metadata в PostgreSQL, объект в MinIO
и выдаёт ссылку с 256-битным capability token. PostgreSQL row locks и unique
session grants гарантируют соблюдение `max_downloads` при конкуренции, Redis
ограничивает abuse и активные streams, а RabbitMQ/Celery удаляют consumed и
expired objects через Outbox.

### Key engineering highlights

- capability token хранится только как peppered HMAC;
- generic 404 защищает от enumeration;
- PostgreSQL row lock + unique grant защищают download limit;
- anonymous retries не расходуют новые slots;
- active streams защищены lease и Redis lock;
- transactional Outbox переживает DB→broker crash window;
- cleanup consumer идемпотентен и retry-safe;
- 61 test, включая реальные PostgreSQL concurrency scenarios.

### Stack

Python 3.13, FastAPI, Pydantic, PostgreSQL, SQLAlchemy Async, asyncpg, Alembic,
Redis/Lua, RabbitMQ, Celery/Beat, MinIO/S3, Nginx, Docker Compose, pytest,
Testcontainers, Ruff, Mypy, Prometheus, GitHub Actions.

### Architecture

Nginx отдаёт static SPA и proxy-ит запросы в FastAPI; API использует PostgreSQL
как source of truth, Redis для временной защиты и MinIO для объектов; Beat и
Celery workers через RabbitMQ публикуют Outbox и выполняют cleanup.

### Best demo scenario

Создать Drop с `max_downloads=1`, показать capability link, затем запустить 50
параллельных запросов из разных sessions: ровно один получает grant, status
становится `CONSUMED`, после завершения stream появляется Outbox event и Celery
удаляет MinIO object.

### Best code/concurrency example

Лучший фрагмент для showcase — `DropRepository.acquire_download_grant()`:
`SELECT ... FOR UPDATE`, поиск/reuse session grant, проверка limit под lock,
создание unique grant и атомарное изменение Drop state. Рядом стоит показать
tests `same_session_spam` и `different_sessions_concurrency`, потому что они
демонстрируют не только код, но и проверяемый invariant.
