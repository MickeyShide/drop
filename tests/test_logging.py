import json
import logging

from drop.logging import (
    JSONFormatter,
    drop_id_var,
    request_id_var,
    task_id_var,
)


def test_json_formatter_valid_structure() -> None:
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="drop.test",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Test log message",
        args=(),
        exc_info=None,
    )

    output = formatter.format(record)
    data = json.loads(output)

    assert data["level"] == "INFO"
    assert data["logger"] == "drop.test"
    assert data["message"] == "Test log message"
    assert "timestamp" in data


def test_json_formatter_includes_contextvars() -> None:
    formatter = JSONFormatter()

    r_token = request_id_var.set("req-12345")
    d_token = drop_id_var.set("drop-abc")
    t_token = task_id_var.set("task-xyz")

    try:
        record = logging.LogRecord(
            name="drop.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Context log message",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        data = json.loads(output)

        assert data["request_id"] == "req-12345"
        assert data["drop_id"] == "drop-abc"
        assert data["task_id"] == "task-xyz"
    finally:
        request_id_var.reset(r_token)
        drop_id_var.reset(d_token)
        task_id_var.reset(t_token)


def test_json_formatter_masks_sensitive_data() -> None:
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="drop.test",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Security log test",
        args=(),
        exc_info=None,
    )
    record.__dict__["secret_key"] = "super-secret-123"
    record.__dict__["password"] = "my_pass"
    record.__dict__["safe_field"] = "visible_value"

    output = formatter.format(record)
    data = json.loads(output)

    assert data["secret_key"] == "***MASKED***"
    assert data["password"] == "***MASKED***"
    assert data["safe_field"] == "visible_value"
