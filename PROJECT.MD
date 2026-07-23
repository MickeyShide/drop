# DROP — Technical Specification

## 1. Краткое описание

**Drop** — минималистичный сервис временной передачи файлов.

Основной сценарий:

1. Пользователь открывает сайт.
2. Загружает файл.
3. Выбирает условия жизни файла:

   * срок хранения;
   * максимальное количество скачиваний.
4. Получает уникальную публичную ссылку.
5. Передаёт ссылку другому человеку.
6. Получатель скачивает файл.
7. Когда истекает срок хранения или исчерпывается лимит скачиваний, ссылка становится недействительной, а файл удаляется из хранилища.

Пример:

```text
photo.zip

Expires in: 24 hours
Downloads: 1

[ Create Drop ]

↓

https://drop.example/d/a8Fk29Qx
```

Получатель:

```text
photo.zip
148 MB

Expires in 17h 42m
1 download remaining

[ Download ]
```

После скачивания:

```text
This drop is no longer available.
```

Главная идея проекта:

> Upload a file. Share the link. The file disappears automatically.

Продукт должен быть предельно простым снаружи, но технически качественным внутри.

---

# 2. Цель проекта

Проект создаётся как backend engineering showcase.

Он должен демонстрировать:

* Python;
* FastAPI;
* asyncio;
* PostgreSQL;
* SQLAlchemy 2.x Async;
* Alembic;
* Redis;
* RabbitMQ;
* Celery;
* объектное файловое хранилище;
* конкурентный доступ;
* транзакции;
* атомарные операции;
* идемпотентность;
* фоновые задачи;
* обработку ошибок;
* retries;
* dead-letter сценарии;
* rate limiting;
* Docker;
* Nginx;
* тестирование;
* structured logging;
* health checks;
* metrics;
* CI.

При этом архитектура не должна усложняться исключительно ради демонстрации технологий.

Каждый компонент должен иметь понятную ответственность.

---

# 3. Что проект НЕ является

Drop не является:

* облачным диском;
* аналогом Google Drive;
* постоянным файловым хранилищем;
* социальной сетью;
* мессенджером;
* системой совместной работы;
* файловым менеджером;
* системой аккаунтов.

В проекте отсутствуют:

* регистрация;
* авторизация;
* профили;
* личный кабинет;
* каталоги;
* контакты;
* комментарии;
* подписки;
* платежи;
* роли пользователей.

Основная сущность системы — **Drop**.

---

# 4. Основной принцип архитектуры

Архитектура должна оставаться небольшой.

Не следует создавать отдельный микросервис для каждой операции.

Логическое устройство:

```text
                         Internet
                            │
                            ▼
                         Nginx
                            │
                            ▼
                      ┌──────────┐
                      │ Drop API │
                      └────┬─────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
              ▼            ▼            ▼
         PostgreSQL      Redis       Object Storage
                                      (MinIO / S3)
              │
              │
              ▼
           RabbitMQ
              │
              ▼
        Celery Workers
```

Основные исполняемые компоненты:

```text
drop-api
drop-worker
```

Инфраструктура:

```text
postgres
redis
rabbitmq
minio
nginx
```

Это намеренно небольшая распределённая система.

---

# 5. Почему это не набор микросервисов

Не создавать:

```text
upload-service
download-service
expiration-service
metadata-service
link-service
```

Такое разделение не соответствует сложности предметной области.

API является одним сервисом.

Фоновые операции выполняются отдельными worker-процессами.

Таким образом разделяются:

```text
HTTP workload
```

и

```text
background workload
```

без искусственного дробления бизнес-логики.

---

# 6. Технологический стек

Backend:

```text
Python 3.13+
FastAPI
Pydantic v2
SQLAlchemy 2.x
asyncpg
Alembic
```

Database:

```text
PostgreSQL
```

Cache / coordination:

```text
Redis
```

Message broker:

```text
RabbitMQ
```

Background processing:

```text
Celery
```

Object storage:

```text
MinIO locally
S3-compatible interface
```

Infrastructure:

```text
Docker
Docker Compose
Nginx
```

Testing:

```text
pytest
pytest-asyncio
httpx
testcontainers where appropriate
```

Code quality:

```text
ruff
mypy
```

CI:

```text
GitHub Actions
```

---

# 7. Ограничения первой версии

Для первой версии:

```text
MAX_FILE_SIZE = 500 MB
```

Допустимые сроки:

```text
1 hour
6 hours
24 hours
72 hours
7 days
```

Допустимые лимиты скачиваний:

```text
1
3
5
10
unlimited until expiration
```

Значения должны задаваться конфигурацией там, где это разумно.

---

# 8. Главная сущность — Drop

Drop представляет временно опубликованный файл.

Минимальные данные:

```text
id
public_id
original_filename
storage_key
content_type
size_bytes
status
max_downloads
download_count
expires_at
created_at
consumed_at
deleted_at
```

Пример:

```text
id = UUID
public_id = "a8Fk29Qx"

original_filename = "photos.zip"

storage_key =
"drops/0198.../source"

content_type =
"application/zip"

size_bytes =
155189248

status =
ACTIVE

max_downloads =
1

download_count =
0

expires_at =
2026-07-24T18:00:00Z
```

---

# 9. public_id

Внутренний UUID никогда не используется в публичной ссылке.

Публичный URL:

```text
/d/{public_id}
```

Например:

```text
/d/a8Fk29Qx
```

`public_id` должен:

* генерироваться криптографически безопасно;
* иметь достаточную энтропию;
* быть URL-safe;
* иметь UNIQUE constraint;
* быть практически невозможным для перебора.

Не использовать:

```text
1
2
3
4
```

или последовательные идентификаторы.

---

# 10. Состояния Drop

Основные состояния:

```text
UPLOADING
PROCESSING
ACTIVE
CONSUMED
EXPIRED
DELETING
DELETED
FAILED
```

Переходы:

```text
UPLOADING
    │
    ▼
PROCESSING
    │
    ├──────────────► FAILED
    │
    ▼
ACTIVE
    │
    ├──────────────► CONSUMED
    │
    └──────────────► EXPIRED
                         │
                         ▼
                     DELETING
                         │
                         ▼
                      DELETED
```

`CONSUMED` также должен приводить к удалению файла:

```text
CONSUMED
   │
   ▼
DELETING
   │
   ▼
DELETED
```

---

# 11. Значение состояний

## UPLOADING

Drop создан, загрузка файла ещё не завершена.

Файл нельзя скачать.

---

## PROCESSING

Файл получен, выполняются необходимые фоновые действия.

Файл нельзя скачать.

---

## ACTIVE

Файл готов.

Ссылка работает.

Скачивание разрешено при соблюдении ограничений.

---

## CONSUMED

Лимит скачиваний исчерпан.

Новые скачивания запрещены.

---

## EXPIRED

Наступил `expires_at`.

Скачивания запрещены независимо от `download_count`.

---

## DELETING

Физическое удаление файла запущено.

---

## DELETED

Файл удалён из object storage.

Метаданные могут временно оставаться в PostgreSQL для технического аудита.

---

## FAILED

Загрузка или обработка завершилась неисправимой ошибкой.

Файл недоступен.

---

# 12. Создание Drop

Основной endpoint:

```http
POST /api/v1/drops
```

Пользователь передаёт:

```text
file
expires_in
max_downloads
```

Пример conceptual request:

```text
file = photo.zip
expires_in = 86400
max_downloads = 1
```

Backend:

1. Валидирует параметры.
2. Проверяет размер.
3. Создаёт Drop.
4. Генерирует `public_id`.
5. Загружает файл в object storage.
6. Сохраняет metadata.
7. Переводит Drop в дальнейшее состояние.
8. Запускает необходимую фоновую обработку.
9. Возвращает публичную ссылку.

---

# 13. Работа с большими файлами

Backend не должен делать:

```python
content = await file.read()
```

для файла размером 500 MB.

Файл должен обрабатываться потоково.

Нельзя без необходимости держать весь файл в RAM.

Использовать streaming/chunked processing.

Цель:

```text
500 MB file
```

не должен приводить к:

```text
+500 MB RAM
```

на API worker.

---

# 14. Object Storage

Сами бинарные файлы не хранятся в PostgreSQL.

PostgreSQL хранит metadata.

Файл хранится в:

```text
MinIO
```

через S3-compatible API.

Структура ключей:

```text
drops/{drop_uuid}/source
```

Например:

```text
drops/019c1e.../source
```

Нельзя использовать оригинальное имя файла непосредственно как storage key.

Оригинальное имя хранится отдельно.

---

# 15. Почему object storage

Это разделяет:

```text
metadata
```

и:

```text
binary data
```

PostgreSQL отвечает за состояние системы.

Object storage отвечает за хранение бинарных объектов.

---

# 16. Получение информации о Drop

Endpoint:

```http
GET /api/v1/drops/{public_id}
```

Возвращает только публичную информацию.

Например:

```json
{
  "public_id": "a8Fk29Qx",
  "filename": "photos.zip",
  "size_bytes": 155189248,
  "status": "ACTIVE",
  "expires_at": "2026-07-24T18:00:00Z",
  "downloads_remaining": 1
}
```

Не возвращать:

```text
database id
storage_key
internal errors
worker information
```

---

# 17. Скачивание

Endpoint:

```http
GET /api/v1/drops/{public_id}/download
```

Перед выдачей файла система проверяет:

```text
drop exists
AND
status == ACTIVE
AND
current_time < expires_at
AND
download limit is not exhausted
```

Если любое условие нарушено — файл не выдаётся.

---

# 18. Ключевой concurrency scenario

Это центральный технический сценарий проекта.

Имеется:

```text
max_downloads = 1
download_count = 0
```

Одновременно приходят:

```text
Client A ─┐
Client B ─┼────► DOWNLOAD
Client C ─┤
Client D ─┘
```

Правильный результат:

```text
Client A → SUCCESS

Client B → GONE
Client C → GONE
Client D → GONE
```

Не допускается:

```text
A → SUCCESS
B → SUCCESS
C → SUCCESS
```

---

# 19. PostgreSQL является источником истины

Корректность лимита скачиваний нельзя строить исключительно на Redis lock.

Основное бизнес-состояние хранится в PostgreSQL.

Критическая операция должна выполняться атомарно.

Возможный подход:

```sql
UPDATE drops
SET download_count = download_count + 1
WHERE public_id = :public_id
  AND status = 'ACTIVE'
  AND expires_at > NOW()
  AND (
      max_downloads IS NULL
      OR download_count < max_downloads
  )
RETURNING ...;
```

Это пример требуемой семантики, а не обязательная буквальная реализация.

Главное свойство:

> Проверка доступности и резервирование одного скачивания должны происходить атомарно.

---

# 20. Что означает успешное скачивание

Скачивание имеет две разные стадии:

```text
permission granted
```

и:

```text
bytes delivered
```

Для MVP используется простая модель:

> Лимит считается использованным после успешного получения права на скачивание.

То есть если пользователь получил разрешение, но оборвал соединение через секунду, download slot считается использованным.

Это сознательное упрощение.

Не пытаться реализовать distributed acknowledgement полного получения файла клиентом.

---

# 21. Одноразовый Drop

При:

```text
max_downloads = 1
```

первый успешный запрос атомарно переводит Drop из:

```text
ACTIVE
```

в:

```text
CONSUMED
```

или эквивалентно увеличивает счётчик до лимита и фиксирует состояние.

Все последующие запросы получают:

```http
410 Gone
```

---

# 22. HTTP semantics

Использовать HTTP статусы осмысленно.

Примеры:

```text
200 OK
201 Created
202 Accepted
400 Bad Request
404 Not Found
409 Conflict
410 Gone
413 Content Too Large
422 Unprocessable Entity
429 Too Many Requests
500 Internal Server Error
503 Service Unavailable
```

`410 Gone` используется для Drop, который существовал, но больше недоступен из-за expiration/consumption.

---

# 23. Ошибки API

Единый формат:

```json
{
  "error": {
    "code": "DROP_EXPIRED",
    "message": "This drop has expired.",
    "request_id": "..."
  }
}
```

Примеры codes:

```text
DROP_NOT_FOUND
DROP_EXPIRED
DROP_CONSUMED
DROP_NOT_READY
FILE_TOO_LARGE
INVALID_EXPIRATION
INVALID_DOWNLOAD_LIMIT
RATE_LIMIT_EXCEEDED
STORAGE_UNAVAILABLE
INTERNAL_ERROR
```

---

# 24. Expiration

Каждый Drop имеет:

```text
expires_at
```

Например:

```text
created_at:
2026-07-23 18:00

expires_at:
2026-07-24 18:00
```

После `expires_at` файл недоступен.

Это правило должно соблюдаться непосредственно API.

Нельзя полагаться только на Celery.

Даже если cleanup worker не работает:

```text
GET /download
```

после expiration должен быть запрещён.

---

# 25. Cleanup worker

Celery периодически ищет Drop:

```text
expires_at <= NOW()
AND
status in relevant states
```

и переводит их в expiration/deletion lifecycle.

Затем удаляет объект из object storage.

---

# 26. Почему expiration проверяется дважды

API обеспечивает:

```text
correctness
```

Worker обеспечивает:

```text
physical cleanup
```

То есть:

```text
expired file
```

может физически существовать ещё несколько минут в MinIO, но получить его через публичный API уже невозможно.

---

# 27. Celery

Celery используется только для задач, которые действительно не должны выполняться внутри HTTP request lifecycle.

Основные задачи:

```text
process_uploaded_file
delete_drop_file
cleanup_expired_drops
cleanup_failed_uploads
```

При необходимости:

```text
collect_file_metadata
```

---

# 28. RabbitMQ

RabbitMQ используется как broker для фоновых задач.

Основная причина:

HTTP API не должен ждать выполнения фоновых операций.

Пример:

```text
POST /drops
     │
     ▼
store file
     │
     ▼
publish processing task
     │
     ▼
return response
```

Worker:

```text
RabbitMQ
   │
   ▼
Celery worker
   │
   ▼
process
```

---

# 29. Retry policy

Временные ошибки должны повторяться.

Например:

```text
MinIO temporarily unavailable
network timeout
temporary database connection failure
```

Использовать exponential backoff.

Conceptually:

```text
1st retry → 5 sec
2nd retry → 15 sec
3rd retry → 45 sec
...
```

Не делать бесконечные retries.

После исчерпания лимита задача должна считаться failed и быть наблюдаемой.

---

# 30. Idempotency фоновых задач

Worker-задачи должны быть безопасны при повторном выполнении.

Например:

```text
delete_drop_file(drop_id)
```

может быть вызвана дважды.

Результат должен оставаться:

```text
file deleted
drop.status = DELETED
```

а не:

```text
500 because object does not exist
```

Удаление уже отсутствующего объекта считается успешным конечным состоянием.

---

# 31. Redis

Redis используется ограниченно и по назначению.

Основные применения:

```text
rate limiting
short-lived technical state
optional caching
coordination where useful
```

Redis НЕ является основным источником бизнес-данных.

---

# 32. Rate limiting

Так как авторизации нет, публичный API должен иметь базовую защиту.

Rate limit определяется преимущественно по IP.

Отдельные лимиты:

```text
create drop
download
metadata lookup
```

Например:

```text
POST /drops
10 requests / minute / IP
```

Конкретные значения должны находиться в конфигурации.

При превышении:

```http
429 Too Many Requests
```

---

# 33. Redis failure

Падение Redis не должно повреждать Drop или позволять превысить download limit.

PostgreSQL остаётся источником истины.

Допустимо временное ухудшение:

```text
rate limiter unavailable
cache unavailable
```

но не нарушение бизнес-инвариантов.

---

# 34. Кэширование

Кэш не является центральной частью проекта.

Допустимо кэшировать metadata ACTIVE Drop на короткое время.

Однако проверки, влияющие на download counter, должны обращаться к authoritative state.

Не оптимизировать преждевременно.

---

# 35. Database schema

Основная таблица:

```text
drops
```

Поля:

```text
id UUID PRIMARY KEY

public_id VARCHAR UNIQUE NOT NULL

original_filename VARCHAR NOT NULL

storage_key VARCHAR NOT NULL

content_type VARCHAR

size_bytes BIGINT NOT NULL

status ENUM/VARCHAR NOT NULL

max_downloads INTEGER NULL

download_count INTEGER NOT NULL DEFAULT 0

expires_at TIMESTAMPTZ NOT NULL

created_at TIMESTAMPTZ NOT NULL

consumed_at TIMESTAMPTZ NULL

deleted_at TIMESTAMPTZ NULL

failure_reason VARCHAR/TEXT NULL
```

---

# 36. Download events

Добавить таблицу:

```text
download_events
```

Она нужна для технической истории и демонстрации SQL.

Поля:

```text
id UUID

drop_id UUID

created_at TIMESTAMPTZ

request_id VARCHAR

ip_hash VARCHAR

user_agent VARCHAR NULL

result VARCHAR
```

Возможные `result`:

```text
SUCCESS
EXPIRED
CONSUMED
NOT_FOUND
RATE_LIMITED
```

Не хранить IP в открытом виде без необходимости.

Для демонстрационного проекта достаточно hash IP.

---

# 37. Индексы

Минимально:

```text
UNIQUE(public_id)

INDEX(status)

INDEX(expires_at)

INDEX(status, expires_at)

INDEX(download_events.drop_id)

INDEX(download_events.created_at)
```

Не добавлять индексы «на всякий случай».

Каждый индекс должен соответствовать реальному query pattern.

---

# 38. Транзакции

Критические изменения состояния выполняются внутри транзакций.

Особенно:

```text
download permission
+
download_count update
+
status transition
```

Не допускать промежуточных состояний вида:

```text
download_count updated

but

status still ACTIVE despite exhausted limit
```

---

# 39. Удаление

Физическое удаление объекта и изменение PostgreSQL невозможно сделать одной ACID-транзакцией.

Поэтому операция должна быть идемпотентной.

Алгоритм:

```text
ACTIVE/EXPIRED/CONSUMED
          │
          ▼
      DELETING
          │
          ▼
 delete from storage
          │
          ▼
       DELETED
```

Если worker упал после удаления объекта, но до DB update:

```text
retry
↓
delete again
↓
object already absent
↓
treat as success
↓
DELETED
```

---

# 40. Upload failure

Если upload не завершился:

```text
UPLOADING
   ↓
FAILED
```

Частично загруженный объект должен быть удалён cleanup-механизмом.

Не оставлять orphaned objects бесконечно.

---

# 41. Security

Несмотря на отсутствие аккаунтов, необходимо учитывать базовую безопасность.

Обязательно:

* random public IDs;
* filename sanitization;
* MIME type не считать доверенным;
* ограничение размера;
* rate limiting;
* корректный Content-Disposition;
* защита от path traversal;
* отсутствие прямого доступа к bucket;
* отсутствие storage credentials на frontend;
* security headers через Nginx;
* request size limits;
* timeouts.

---

# 42. Filename

Пользовательский filename считается недоверенным.

Например:

```text
../../etc/passwd
```

не должен влиять на storage path.

Storage key генерируется исключительно backend.

При скачивании filename используется только как безопасно обработанное имя в:

```http
Content-Disposition
```

---

# 43. Content-Type

Не доверять полностью MIME type, который прислал браузер.

Для MVP глубокая антивирусная система не обязательна.

Файлы должны преимущественно скачиваться как attachment, а не исполняться браузером inline.

---

# 44. Прямой доступ к MinIO

Bucket не должен быть публичным.

Пользователь не должен иметь URL вида:

```text
minio:9000/bucket/file
```

Все решения о доступе принимает Drop backend.

Допустима выдача очень короткоживущего presigned URL только ПОСЛЕ атомарной проверки права на скачивание.

Если используется presigned URL:

```text
TTL ~ 1 minute
```

и URL нельзя считать долгосрочной публичной ссылкой.

---

# 45. Download delivery

Предпочтительная архитектура:

```text
Client
  │
  ▼
Drop API
  │
  ├── validate Drop
  ├── atomically consume download
  │
  ▼
short-lived download access
  │
  ▼
Object Storage
```

Для MVP допустимо streaming через backend.

Выбор должен быть задокументирован.

Для больших файлов предпочтительно не заставлять Python API проксировать все байты, если можно безопасно использовать presigned access.

---

# 46. Nginx

Nginx является внешней точкой входа.

Отвечает за:

```text
reverse proxy
TLS termination
request size limits
timeouts
security headers
basic connection protection
```

Маршрут:

```text
Internet
   │
   ▼
Nginx
   │
   ▼
FastAPI
```

---

# 47. Health checks

API предоставляет:

```http
GET /health/live
GET /health/ready
```

`live`:

```text
процесс запущен
```

`ready`:

```text
приложение готово обслуживать запросы
```

Readiness проверяет критические зависимости.

Не выполнять тяжёлые проверки.

---

# 48. Structured logging

Использовать структурированные логи.

Пример:

```json
{
  "timestamp": "...",
  "level": "INFO",
  "service": "drop-api",
  "request_id": "...",
  "event": "drop_downloaded",
  "drop_id": "...",
  "duration_ms": 42
}
```

Не логировать содержимое файлов.

Не логировать секретные storage credentials.

---

# 49. Request ID

Каждый HTTP request получает:

```text
X-Request-ID
```

Если клиент прислал корректный ID — можно использовать его.

Иначе backend генерирует новый.

ID добавляется:

```text
response headers
logs
download events
background task context where appropriate
```

Это позволяет проследить один запрос через систему.

---

# 50. Metrics

Минимальные metrics:

```text
http_requests_total

http_request_duration_seconds

drops_created_total

drops_active

drops_expired_total

drops_consumed_total

downloads_total

downloads_rejected_total

uploaded_bytes_total

downloaded_bytes_total

background_tasks_total

background_task_failures_total
```

Не делать десятки бессмысленных metrics.

---

# 51. Prometheus / Grafana

Если добавляется observability stack:

```text
Prometheus
Grafana
```

Dashboard должен показывать:

```text
request rate

error rate

p95 latency

drops created

downloads

rejected downloads

uploaded data

worker failures
```

Это инфраструктурная часть проекта, а не пользовательский функционал.

---

# 52. Frontend

Frontend намеренно минимальный.

Основной экран:

```text
┌──────────────────────────────────────┐
│                                      │
│                 DROP                 │
│                                      │
│      Drop a file. Share a link.      │
│       It disappears automatically.   │
│                                      │
│        ┌────────────────────┐        │
│        │                    │        │
│        │   Drop file here   │        │
│        │                    │        │
│        └────────────────────┘        │
│                                      │
│  Expires       Downloads             │
│  [24 hours ▼]  [1 ▼]                 │
│                                      │
│          [ Create Drop ]             │
│                                      │
└──────────────────────────────────────┘
```

Не создавать dashboard.

Не создавать sidebar.

Не создавать аккаунты.

---

# 53. После создания

Экран:

```text
Your drop is ready.

photos.zip
148 MB

Expires in 24 hours
1 download

https://drop.example/d/a8Fk29Qx

[ Copy Link ]
```

---

# 54. Страница получателя

```text
photos.zip

148 MB

Expires in 17h 42m
1 download remaining

[ Download ]
```

---

# 55. Недоступный Drop

Одинаково простой экран:

```text
This drop is no longer available.

It may have expired or reached
its download limit.
```

Не раскрывать лишнюю информацию, если это ухудшает privacy/security.

---

# 56. Upload progress

Frontend показывает:

```text
Uploading...

██████████████░░░░░ 73%

108 MB / 148 MB
```

После завершения:

```text
Processing...
```

затем:

```text
Ready
```

Для MVP WebSocket не требуется.

Допустим polling:

```http
GET /drops/{public_id}
```

пока status:

```text
UPLOADING
PROCESSING
```

---

# 57. Почему нет WebSocket

Realtime communication здесь не является необходимой частью предметной области.

Добавлять WebSocket только для демонстрации технологии запрещено.

Polling для короткого processing lifecycle проще и надёжнее.

---

# 58. API

Минимальный публичный API:

```text
POST
/api/v1/drops

GET
/api/v1/drops/{public_id}

GET
/api/v1/drops/{public_id}/download
```

Infrastructure:

```text
GET /health/live
GET /health/ready
GET /metrics
```

Дополнительные endpoint'ы добавляются только при реальной необходимости.

---

# 59. Layering backend

Рекомендуемая структура:

```text
HTTP
 │
 ▼
Router
 │
 ▼
Application Service
 │
 ▼
Repository / Storage abstraction
 │
 ├──── PostgreSQL
 │
 ├──── Redis
 │
 └──── Object Storage
```

Router не содержит бизнес-логику.

Repository не принимает бизнес-решения.

Service координирует use cases.

---

# 60. Структура проекта

Пример:

```text
drop/
│
├── src/
│   └── drop/
│       │
│       ├── api/
│       │   ├── routes/
│       │   ├── dependencies/
│       │   ├── middleware/
│       │   └── errors/
│       │
│       ├── application/
│       │   ├── services/
│       │   └── schemas/
│       │
│       ├── domain/
│       │   ├── models/
│       │   ├── enums/
│       │   └── exceptions/
│       │
│       ├── infrastructure/
│       │   ├── database/
│       │   ├── repositories/
│       │   ├── redis/
│       │   ├── storage/
│       │   └── messaging/
│       │
│       ├── workers/
│       │
│       ├── config.py
│       └── main.py
│
├── migrations/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
│
├── infrastructure/
│   ├── nginx/
│   ├── prometheus/
│   └── grafana/
│
├── docker-compose.yml
├── Dockerfile
├── Makefile
├── pyproject.toml
└── README.md
```

Структура может немного отличаться, но ответственность слоёв должна сохраняться.

---

# 61. Не переусложнять architecture patterns

Не создавать абстракции без практической причины.

Не требуется:

```text
CQRS
Event Sourcing
Saga framework
DDD aggregate framework
Mediator
Command Bus
Service Mesh
Kubernetes
Kafka
GraphQL
gRPC
```

Если задача решается обычной транзакцией PostgreSQL — использовать транзакцию PostgreSQL.

---

# 62. Configuration

Все environment-dependent значения через environment/config:

```text
DATABASE_URL
REDIS_URL
RABBITMQ_URL

S3_ENDPOINT
S3_ACCESS_KEY
S3_SECRET_KEY
S3_BUCKET

MAX_FILE_SIZE

DEFAULT_EXPIRATION
MAX_EXPIRATION

RATE_LIMIT_*

LOG_LEVEL
```

Не hardcode credentials.

---

# 63. Docker Compose

Одна команда:

```bash
docker compose up --build
```

должна поднять рабочую систему.

Минимальные containers:

```text
nginx
api
worker
postgres
redis
rabbitmq
minio
```

Опционально:

```text
prometheus
grafana
```

---

# 64. Startup

При запуске сервис не должен автоматически выполнять destructive migrations.

Alembic migrations запускаются отдельной командой/entrypoint step.

---

# 65. Graceful shutdown

API и worker должны корректно завершаться.

При SIGTERM:

```text
не принимать новую работу
завершить текущие операции где возможно
закрыть DB connections
закрыть Redis connections
закрыть storage clients
```

---

# 66. Tests

Тесты являются обязательной частью проекта.

Разделить:

```text
unit
integration
e2e
```

---

# 67. Unit tests

Проверяют бизнес-правила без реальной инфраструктуры.

Например:

```text
expiration calculation

allowed download limits

state transitions

filename sanitization

validation
```

---

# 68. Integration tests

Использовать реальные инфраструктурные зависимости там, где это важно.

Особенно:

```text
PostgreSQL
Redis
MinIO
```

RabbitMQ/Celery integration тестировать выборочно.

---

# 69. Критический concurrency test

Обязательный тест.

Создаётся:

```text
max_downloads = 1
```

Запускается, например:

```text
100 concurrent download attempts
```

Ожидаемый результат:

```text
successful permissions = 1

rejected = 99

download_count = 1
```

Ни при каких условиях:

```text
download_count > 1
```

---

# 70. Multi-download concurrency test

Например:

```text
max_downloads = 5

100 concurrent requests
```

Результат:

```text
success = 5
rejected = 95

download_count = 5
```

---

# 71. Expiration tests

Проверить:

```text
ACTIVE before expires_at

unavailable after expires_at

cleanup eventually deletes object
```

Даже если Celery worker остановлен:

```text
expired Drop
```

не должен скачиваться.

---

# 72. Worker idempotency tests

Например:

```text
delete_drop_file()
delete_drop_file()
delete_drop_file()
```

Итог всегда:

```text
status = DELETED
object absent
```

---

# 73. Failure tests

Проверить хотя бы:

```text
PostgreSQL unavailable

Redis unavailable

MinIO temporarily unavailable

worker retries

duplicate cleanup task

download after expiration

download after consumption
```

---

# 74. Load demonstration

Добавить простой script:

```bash
make race-test
```

Он создаёт одноразовый Drop и выполняет конкурентные запросы.

Вывод:

```text
DROP CONCURRENCY TEST

Concurrent clients: 100
Download limit:     1

Successful:          1
Rejected:           99

Final counter:       1
Invariant violated: NO
```

Это важная демонстрационная часть проекта.

---

# 75. Второй demo scenario

```bash
make expiration-test
```

Пример:

```text
Created drop
TTL: 10 seconds

Before expiration:
DOWNLOAD → 200

Waiting...

After expiration:
DOWNLOAD → 410

Object cleanup:
SUCCESS
```

---

# 76. Code quality

Обязательно:

```text
ruff
mypy
pytest
```

CI должен падать при:

```text
lint failure
type checking failure
test failure
```

---

# 77. CI pipeline

Минимально:

```text
checkout
   ↓
install dependencies
   ↓
ruff
   ↓
mypy
   ↓
pytest
   ↓
docker build
```

---

# 78. README

README не должен быть огромной документацией.

В начале:

```text
# Drop

Ephemeral file sharing service.

Upload a file, share the link,
and let it disappear automatically.
```

Затем:

```text
Features
Architecture
Concurrency guarantees
Tech stack
Run locally
Tests
Engineering decisions
```

---

# 79. Architecture diagram для README

```text
                        ┌───────────┐
                        │  Client   │
                        └─────┬─────┘
                              │
                              ▼
                        ┌───────────┐
                        │   Nginx   │
                        └─────┬─────┘
                              │
                              ▼
                        ┌───────────┐
                        │ FastAPI   │
                        │ Drop API  │
                        └─────┬─────┘
                              │
             ┌────────────────┼────────────────┐
             │                │                │
             ▼                ▼                ▼
       ┌──────────┐      ┌────────┐       ┌─────────┐
       │PostgreSQL│      │ Redis  │       │  MinIO  │
       └──────────┘      └────────┘       └─────────┘
             │
             ▼
       ┌──────────┐
       │ RabbitMQ │
       └─────┬────┘
             │
             ▼
       ┌──────────┐
       │  Celery  │
       │ Workers  │
       └──────────┘
```

---

# 80. Основные архитектурные решения

README должен кратко объяснять следующие решения.

### PostgreSQL as source of truth

Download limits — бизнес-инвариант.

Redis не используется как единственный механизм корректности.

---

### Object storage for binaries

PostgreSQL хранит metadata.

MinIO/S3 хранит файлы.

---

### Atomic download consumption

Concurrent requests не могут превысить `max_downloads`.

---

### API-enforced expiration

Expired Drop недоступен сразу после `expires_at`, независимо от состояния cleanup worker.

---

### Asynchronous cleanup

Физическое удаление не находится на критическом HTTP path.

---

### Idempotent background tasks

Повторная доставка/запуск задачи не нарушает состояние.

---

# 81. Главные бизнес-инварианты

Эти правила должны соблюдаться всегда.

## Invariant 1

```text
download_count <= max_downloads
```

если `max_downloads != NULL`.

---

## Invariant 2

Drop после:

```text
NOW() >= expires_at
```

не может выдавать новые download permissions.

---

## Invariant 3

`CONSUMED` Drop нельзя скачать.

---

## Invariant 4

`DELETED` Drop не имеет доступного binary object.

---

## Invariant 5

Повторная background task не должна изменять корректный конечный результат.

---

## Invariant 6

Недоступность Redis не должна позволять нарушить download limit.

---

## Invariant 7

Пользователь никогда не получает постоянный прямой доступ к object storage.

---

# 82. Definition of Done

Проект считается завершённым, когда:

* файл можно загрузить;
* можно выбрать expiration;
* можно выбрать download limit;
* создаётся случайная публичная ссылка;
* metadata хранится в PostgreSQL;
* binary хранится в MinIO;
* файл можно скачать;
* download counter корректно обновляется;
* одноразовый Drop нельзя скачать дважды;
* concurrent requests не нарушают лимит;
* expired Drop сразу становится недоступен;
* Celery удаляет expired/consumed files;
* cleanup идемпотентен;
* Redis используется для rate limiting;
* RabbitMQ используется для фоновых задач;
* API имеет единый error format;
* присутствует request ID;
* присутствуют structured logs;
* присутствуют health checks;
* присутствуют основные metrics;
* проект полностью запускается Docker Compose;
* Alembic migrations работают;
* unit tests проходят;
* integration tests проходят;
* concurrency test проходит;
* CI проходит;
* README содержит архитектурную схему;
* frontend позволяет пройти основной сценарий без объяснений.

---

# 83. Что специально НЕ делать

Не добавлять без отдельного решения:

* аккаунты;
* OAuth;
* JWT;
* платные тарифы;
* email;
* социальные функции;
* папки;
* историю файлов пользователя;
* WebSocket;
* Kubernetes;
* Kafka;
* Elasticsearch;
* MongoDB;
* микросервис на каждую сущность;
* сложную event-driven бизнес-оркестрацию;
* настоящий антивирусный кластер;
* собственный distributed storage;
* end-to-end encryption;
* мобильное приложение.

---

# 84. Основная инженерная идея проекта

Drop должен выглядеть очень просто:

```text
FILE
 ↓
UPLOAD
 ↓
LINK
 ↓
DOWNLOAD
 ↓
GONE
```

Инженерная сложность находится не в количестве функций, а в гарантиях:

```text
Можно ли скачать одноразовый файл дважды одновременно?

Что произойдёт при 100 конкурентных запросах?

Что произойдёт, если Redis упал?

Что произойдёт, если worker умер?

Что произойдёт, если задача удаления пришла дважды?

Что произойдёт, если MinIO временно недоступен?

Можно ли скачать файл через секунду после expiration?

Останутся ли потерянные файлы после неудачного upload?
```

Система должна иметь конкретный и проверяемый ответ на каждый из этих вопросов.

---

# 85. Итоговая формулировка проекта

**Drop is an ephemeral file-sharing service built around strict expiration and download guarantees.**

Пользовательская модель:

> Upload → Share → Download → Gone.

Инженерная модель:

> PostgreSQL-backed state, atomic concurrent access, S3-compatible object storage, asynchronous cleanup, idempotent workers, rate limiting, observability and containerized deployment.

Главный принцип разработки:

> **Keep the product simple. Make the guarantees strong.**
