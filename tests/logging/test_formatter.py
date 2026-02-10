"""Unit tests for JsonFormatter and FlushStreamHandler."""

from __future__ import annotations

import json
import logging
from unittest.mock import patch

from mcp_zero.logging import SERVICE_NAME, FlushStreamHandler, JsonFormatter


def _make_record(
    msg: str,
    level: int = logging.INFO,
    name: str = "test.logger",
    exc_info: tuple | None = None,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname="test.py",
        lineno=1,
        msg=msg,
        args=(),
        exc_info=exc_info,
    )
    return record


class TestJsonFormatterAuditEvents:
    """Audit events (pre-serialised JSON) pass through with enrichment."""

    def test_audit_json_preserved(self):
        audit = {
            "event_type": "TOOL_INVOCATION",
            "correlation_id": "abc-123",
            "timestamp": "2025-01-01T00:00:00Z",
        }
        record = _make_record(json.dumps(audit))
        formatter = JsonFormatter()

        result = json.loads(formatter.format(record))

        assert result["event_type"] == "TOOL_INVOCATION"
        assert result["correlation_id"] == "abc-123"
        assert result["timestamp"] == "2025-01-01T00:00:00Z"

    def test_audit_json_adds_service(self):
        audit = {"event_type": "TOOL_INVOCATION"}
        record = _make_record(json.dumps(audit))
        formatter = JsonFormatter()

        result = json.loads(formatter.format(record))

        assert result["service"] == SERVICE_NAME

    def test_audit_json_adds_level(self):
        audit = {"event_type": "TOOL_INVOCATION"}
        record = _make_record(json.dumps(audit), level=logging.WARNING)
        formatter = JsonFormatter()

        result = json.loads(formatter.format(record))

        assert result["level"] == "WARNING"

    def test_audit_json_does_not_overwrite_existing_service(self):
        audit = {"event_type": "TOOL_INVOCATION", "service": "custom-service"}
        record = _make_record(json.dumps(audit))
        formatter = JsonFormatter()

        result = json.loads(formatter.format(record))

        # setdefault should keep existing value
        assert result["service"] == "custom-service"


class TestJsonFormatterOperationalLogs:
    """Plain-text messages are wrapped in a JSON envelope."""

    def test_plain_message_wrapped(self):
        record = _make_record("Starting gateway...")
        formatter = JsonFormatter()

        result = json.loads(formatter.format(record))

        assert result["message"] == "Starting gateway..."
        assert result["service"] == SERVICE_NAME
        assert result["level"] == "INFO"
        assert "timestamp" in result
        assert "logger" in result

    def test_logger_name_included(self):
        record = _make_record("hello", name="mcp_zero.main")
        formatter = JsonFormatter()

        result = json.loads(formatter.format(record))

        assert result["logger"] == "mcp_zero.main"

    def test_level_matches_record(self):
        record = _make_record("an error", level=logging.ERROR)
        formatter = JsonFormatter()

        result = json.loads(formatter.format(record))

        assert result["level"] == "ERROR"


class TestJsonFormatterExceptions:
    """Stack traces are encoded as single-line strings."""

    def test_exception_info_included(self):
        try:
            raise ValueError("test error")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        record = _make_record("something failed", exc_info=exc_info)
        formatter = JsonFormatter()

        result = json.loads(formatter.format(record))

        assert "error" in result
        assert result["error"]["type"] == "ValueError"
        assert result["error"]["message"] == "test error"
        assert "traceback" in result["error"]
        assert "ValueError" in result["error"]["traceback"]

    def test_exception_on_audit_event(self):
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            import sys

            exc_info = sys.exc_info()

        audit = {"event_type": "ERROR"}
        record = _make_record(json.dumps(audit), exc_info=exc_info)
        formatter = JsonFormatter()

        result = json.loads(formatter.format(record))

        assert result["event_type"] == "ERROR"
        assert result["error"]["type"] == "RuntimeError"


class TestJsonFormatterMalformedJson:
    """Malformed JSON is treated as an operational log."""

    def test_malformed_json_treated_as_text(self):
        record = _make_record("{not valid json")
        formatter = JsonFormatter()

        result = json.loads(formatter.format(record))

        assert result["message"] == "{not valid json"
        assert result["service"] == SERVICE_NAME

    def test_json_array_treated_as_text(self):
        record = _make_record("[1, 2, 3]")
        formatter = JsonFormatter()

        result = json.loads(formatter.format(record))

        assert result["message"] == "[1, 2, 3]"

    def test_empty_message_treated_as_text(self):
        record = _make_record("")
        formatter = JsonFormatter()

        result = json.loads(formatter.format(record))

        assert result["message"] == ""


class TestFlushStreamHandler:
    """FlushStreamHandler flushes after every emit."""

    def test_flush_called_after_emit(self):
        import io

        stream = io.StringIO()
        handler = FlushStreamHandler(stream)
        handler.setFormatter(JsonFormatter())

        record = _make_record("test message")

        with patch.object(handler, "flush", wraps=handler.flush) as mock_flush:
            handler.emit(record)
            assert mock_flush.call_count >= 1

    def test_output_is_valid_json(self):
        import io

        stream = io.StringIO()
        handler = FlushStreamHandler(stream)
        handler.setFormatter(JsonFormatter())

        record = _make_record("hello world")
        handler.emit(record)

        line = stream.getvalue().strip()
        result = json.loads(line)
        assert result["message"] == "hello world"
