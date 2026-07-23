from contextvars import ContextVar
from datetime import UTC, datetime
import json
import logging
import sys
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
drop_id_var: ContextVar[str | None] = ContextVar("drop_id", default=None)
task_id_var: ContextVar[str | None] = ContextVar("task_id", default=None)

SENSITIVE_KEYS = {
    "password",
    "secret",
    "secret_key",
    "access_key",
    "authorization",
    "token",
    "s3_secret_key",
    "s3_access_key",
}


def sanitize_value(key: str, value: Any) -> Any:
    if isinstance(key, str) and key.lower() in SENSITIVE_KEYS:
        return "***MASKED***"
    if isinstance(value, dict):
        return {k: sanitize_value(k, v) for k, v in value.items()}
    return value


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include contextvars if set
        req_id = request_id_var.get()
        if req_id:
            log_data["request_id"] = req_id

        drop_id = drop_id_var.get()
        if drop_id:
            log_data["drop_id"] = drop_id

        task_id = task_id_var.get()
        if task_id:
            log_data["task_id"] = task_id

        # Include extra fields passed to logger.info(..., extra={...})
        standard_attrs = {
            "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
            "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
            "created", "msecs", "relativeCreated", "thread", "threadName",
            "processName", "process", "taskName",
        }

        for key, value in record.__dict__.items():
            if key not in standard_attrs and not key.startswith("_"):
                log_data[key] = sanitize_value(key, value)

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, ensure_ascii=False)


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Align uvicorn and celery loggers
    for logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error", "celery", "celery.task"):
        lg = logging.getLogger(logger_name)
        lg.handlers.clear()
        lg.addHandler(handler)
        lg.propagate = False
