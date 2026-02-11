"""Unit tests for JsonFormatter, TextFormatter, and FlushStreamHandler."""

from __future__ import annotations

import json
import logging
import sys
from unittest.mock import patch

from mcp_zero.logging import SERVICE_NAME, FlushStreamHandler, JsonFormatter, TextFormatter


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


class TestTextFormatterOperationalLogs:
    """TextFormatter renders plain messages in human-readable format."""

    def test_contains_level_label(self):
        record = _make_record("Starting gateway...")
        formatter = TextFormatter(use_color=False)

        result = formatter.format(record)

        assert "INFO " in result
        assert "Starting gateway..." in result

    def test_warning_level_label(self):
        record = _make_record("something wrong", level=logging.WARNING)
        formatter = TextFormatter(use_color=False)

        result = formatter.format(record)

        assert "WARN " in result

    def test_error_level_label(self):
        record = _make_record("failure", level=logging.ERROR)
        formatter = TextFormatter(use_color=False)

        result = formatter.format(record)

        assert "ERROR" in result

    def test_debug_level_label(self):
        record = _make_record("trace detail", level=logging.DEBUG)
        formatter = TextFormatter(use_color=False)

        result = formatter.format(record)

        assert "DEBUG" in result

    def test_timestamp_format(self):
        record = _make_record("hello")
        formatter = TextFormatter(use_color=False)

        result = formatter.format(record)

        # Should have HH:MM:SS.mmm format
        import re

        assert re.search(r"\d{2}:\d{2}:\d{2}\.\d{3}", result)

    def test_abbreviated_logger_name(self):
        record = _make_record("msg", name="mcp_zero.governance.hook")
        formatter = TextFormatter(use_color=False)

        result = formatter.format(record)

        assert "[governance.hook]" in result
        assert "mcp_zero." not in result

    def test_non_mcp_logger_name_preserved(self):
        record = _make_record("msg", name="uvicorn.server")
        formatter = TextFormatter(use_color=False)

        result = formatter.format(record)

        assert "[uvicorn.server]" in result

    def test_color_mode_includes_ansi_codes(self):
        record = _make_record("hello")
        formatter = TextFormatter(use_color=True)

        result = formatter.format(record)

        assert "\033[" in result  # ANSI escape sequences present

    def test_no_color_mode_clean(self):
        record = _make_record("hello")
        formatter = TextFormatter(use_color=False)

        result = formatter.format(record)

        assert "\033[" not in result  # No ANSI escape sequences

    def test_warning_gutter_marker_no_color(self):
        record = _make_record("watch out", level=logging.WARNING)
        formatter = TextFormatter(use_color=False)

        result = formatter.format(record)

        assert "! WARN " in result

    def test_error_gutter_marker_no_color(self):
        record = _make_record("broken", level=logging.ERROR)
        formatter = TextFormatter(use_color=False)

        result = formatter.format(record)

        assert "! ERROR" in result

    def test_info_no_gutter_marker(self):
        record = _make_record("all good")
        formatter = TextFormatter(use_color=False)

        result = formatter.format(record)

        # INFO and DEBUG get blank gutter (two spaces), no "!"
        assert "! INFO" not in result

    def test_debug_no_gutter_marker(self):
        record = _make_record("detail", level=logging.DEBUG)
        formatter = TextFormatter(use_color=False)

        result = formatter.format(record)

        assert "! DEBUG" not in result

    def test_warning_gutter_marker_with_color(self):
        record = _make_record("caution", level=logging.WARNING)
        formatter = TextFormatter(use_color=True)

        result = formatter.format(record)

        # The "!" should be present in the colored output
        assert "!" in result

    def test_error_body_colored_red(self):
        """ERROR message body should include red ANSI codes when color is on."""
        record = _make_record("something broke", level=logging.ERROR)
        formatter = TextFormatter(use_color=True)

        result = formatter.format(record)

        # The message body should have red coloring (ESC[31m)
        assert "\033[31m" in result
        assert "something broke" in result

    def test_warning_body_colored_yellow(self):
        """WARNING message body should include yellow ANSI codes when color is on."""
        record = _make_record("heads up", level=logging.WARNING)
        formatter = TextFormatter(use_color=True)

        result = formatter.format(record)

        # The message body should have yellow coloring (ESC[33m)
        assert "\033[33m" in result
        assert "heads up" in result

    def test_info_uses_green_color(self):
        """INFO level should use green ANSI code."""
        record = _make_record("operational")
        formatter = TextFormatter(use_color=True)

        result = formatter.format(record)

        # Green is ESC[32m
        assert "\033[32m" in result


class TestTextFormatterAuditEvents:
    """TextFormatter renders audit JSON as compact one-liners."""

    def test_audit_event_rendered_as_summary(self):
        audit = {
            "event_type": "mcp_tool_invocation",
            "server_name": "test-server",
            "tool_name": "read_file",
            "user": {"user_id": "alice", "groups": ["admin"]},
            "policy_decision": "allow",
            "correlation_id": "abc123def456",
            "duration_ms": 42.5,
            "request_size_bytes": 256,
            "response_size_bytes": 1024,
            "masking_events": [],
        }
        record = _make_record(json.dumps(audit), name="mcp_zero.audit.hook")
        formatter = TextFormatter(use_color=False)

        result = formatter.format(record)

        assert "-- TOOL_CALL --" in result
        assert "server=test-server" in result
        assert "tool=read_file" in result
        assert "user=alice" in result
        assert "decision=allow" in result
        assert "cid=abc123def456" in result
        assert "42ms" in result
        assert "req=256B" in result
        assert "resp=1.0K" in result

    def test_policy_decision_event(self):
        audit = {
            "event_type": "policy_decision",
            "server_name": "srv",
            "tool_name": "tool",
            "user": {"user_id": "bob"},
            "policy_decision": "deny",
            "short_circuit_reason": "Access denied",
            "correlation_id": "xyz789",
            "error_type": "ShortCircuitError",
            "error_message": "Access denied",
            "masking_events": [],
        }
        record = _make_record(json.dumps(audit), name="mcp_zero.audit.hook")
        formatter = TextFormatter(use_color=False)

        result = formatter.format(record)

        assert "-- POLICY --" in result
        assert 'reason="Access denied"' in result
        assert "error=ShortCircuitError: Access denied" in result

    def test_masking_event_summary(self):
        audit = {
            "event_type": "masking_event",
            "server_name": "srv",
            "tool_name": "tool",
            "correlation_id": "abc",
            "masking_events": [
                {"entity_type": "PERSON", "count": 2, "status": "success"},
                {"entity_type": "EMAIL", "count": 1, "status": "success"},
            ],
        }
        record = _make_record(json.dumps(audit), name="mcp_zero.audit.hook")
        formatter = TextFormatter(use_color=False)

        result = formatter.format(record)

        assert "-- MASKING --" in result
        assert "masked=[2x PERSON, 1x EMAIL]" in result

    def test_correlation_id_truncated(self):
        audit = {
            "event_type": "mcp_tool_invocation",
            "correlation_id": "abcdefghijklmnopqrstuvwxyz",
            "masking_events": [],
        }
        record = _make_record(json.dumps(audit))
        formatter = TextFormatter(use_color=False)

        result = formatter.format(record)

        assert "cid=abcdefghijkl" in result
        assert "abcdefghijklmnopqrstuvwxyz" not in result


class TestTextFormatterExceptions:
    """TextFormatter renders exceptions with visual indentation."""

    def test_exception_included(self):
        try:
            raise ValueError("test error")
        except ValueError:
            exc_info = sys.exc_info()

        record = _make_record("something failed", level=logging.ERROR, exc_info=exc_info)
        formatter = TextFormatter(use_color=False)

        result = formatter.format(record)

        assert "something failed" in result
        assert "+-- ValueError: test error" in result
        assert "test_formatter.py" in result

    def test_exception_with_color(self):
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            exc_info = sys.exc_info()

        record = _make_record("failure", level=logging.ERROR, exc_info=exc_info)
        formatter = TextFormatter(use_color=True)

        result = formatter.format(record)

        assert "RuntimeError: boom" in result
        # Should contain the visual connector
        assert "╰─" in result
