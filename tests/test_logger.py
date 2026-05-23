import json
import logging
from logger import get_logger, JSONFormatter


def test_json_formatter_emits_required_fields(caplog):
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="cabax", level=logging.INFO, pathname="x", lineno=1,
        msg="hello", args=(), exc_info=None
    )
    record.request_id = "abc-123"
    record.store_id = 7
    record.user_id = 42
    record.method = "GET"
    record.path = "/api/casts"
    record.status_code = 200
    record.duration_ms = 12.5

    output = formatter.format(record)
    parsed = json.loads(output)

    assert parsed["request_id"] == "abc-123"
    assert parsed["store_id"] == 7
    assert parsed["user_id"] == 42
    assert parsed["method"] == "GET"
    assert parsed["path"] == "/api/casts"
    assert parsed["status_code"] == 200
    assert parsed["duration_ms"] == 12.5
    assert parsed["level"] == "INFO"
    assert "timestamp" in parsed


def test_json_formatter_handles_missing_optional_fields():
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="cabax", level=logging.INFO, pathname="x", lineno=1,
        msg="hello", args=(), exc_info=None
    )
    output = formatter.format(record)
    parsed = json.loads(output)

    assert parsed["store_id"] is None
    assert parsed["user_id"] is None
    assert parsed["request_id"] is None


def test_json_formatter_includes_exception_on_error(caplog):
    formatter = JSONFormatter()
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        record = logging.LogRecord(
            name="cabax", level=logging.ERROR, pathname="x", lineno=1,
            msg="failed", args=(), exc_info=sys.exc_info()
        )

    output = formatter.format(record)
    parsed = json.loads(output)
    assert "exception" in parsed
    assert "ValueError: boom" in parsed["exception"]
