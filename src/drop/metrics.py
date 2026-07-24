from prometheus_client import Counter, Histogram

# HTTP Metrics
HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests processed",
    ["method", "endpoint", "status_code"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# Domain Metrics
DROP_UPLOADS_TOTAL = Counter(
    "drop_uploads_total",
    "Total drop file upload attempts",
    ["status"],  # success, failed, rejected
)

DROP_DOWNLOADS_TOTAL = Counter(
    "drop_downloads_total",
    "Total successful drop downloads",
)

DROP_DOWNLOADS_REJECTED_TOTAL = Counter(
    "drop_downloads_rejected_total",
    "Rejected drop download attempts",
    ["reason"],  # not_found, expired, consumed, not_ready
)

INVALID_CAPABILITY_TOTAL = Counter(
    "invalid_capability_total",
    "Invalid capability token attempts",
)

RATE_LIMITED_REQUESTS_TOTAL = Counter(
    "rate_limited_requests_total",
    "Requests rejected by a rate limiter",
)

DOWNLOAD_GRANTS_CREATED_TOTAL = Counter(
    "download_grants_created_total",
    "Unique recipient download grants created",
)

DOWNLOAD_GRANTS_REUSED_TOTAL = Counter(
    "download_grants_reused_total",
    "Existing recipient grants reused",
)

CONCURRENT_DOWNLOAD_REJECTED_TOTAL = Counter(
    "concurrent_download_rejected_total",
    "Downloads rejected because a stream is already active",
)

# Celery Worker & Cleanup Metrics
CELERY_TASK_FAILURES_TOTAL = Counter(
    "celery_task_failures_total",
    "Celery task execution failures",
    ["task_name"],
)

CLEANUP_RETRIES_TOTAL = Counter(
    "cleanup_retries_total",
    "Cleanup task retry attempts",
    ["task_name"],
)
