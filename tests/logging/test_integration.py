"""Integration tests for configure_json_logging."""

from __future__ import annotations

import io
import json
import logging

from mcp_zero.logging import SERVICE_NAME, configure_json_logging


class TestConfigureJsonLogging:
    """Verify configure_json_logging wires up correctly."""

    def test_writes_to_provided_stream(self):
        stream = io.StringIO()
        configure_json_logging(level="INFO", stream=stream)

        logger = logging.getLogger("test.integration.stream")
        logger.info("hello from test")

        output = stream.getvalue().strip()
        result = json.loads(output)
        assert result["message"] == "hello from test"
        assert result["service"] == SERVICE_NAME

    def test_writes_to_stdout_by_default(self, capsys):
        configure_json_logging(level="INFO")

        logger = logging.getLogger("test.integration.stdout")
        logger.info("stdout test")

        captured = capsys.readouterr()
        assert captured.err == ""  # nothing on stderr
        result = json.loads(captured.out.strip())
        assert result["message"] == "stdout test"

    def test_level_applied_to_root_logger(self):
        stream = io.StringIO()
        configure_json_logging(level="WARNING", stream=stream)

        logger = logging.getLogger("test.integration.level")
        logger.info("should be filtered")
        logger.warning("should appear")

        lines = [line for line in stream.getvalue().strip().split("\n") if line]
        assert len(lines) == 1
        result = json.loads(lines[0])
        assert result["message"] == "should appear"

    def test_replaces_existing_handlers(self):
        root = logging.getLogger()
        dummy_handler = logging.StreamHandler(io.StringIO())
        root.addHandler(dummy_handler)

        stream = io.StringIO()
        configure_json_logging(level="INFO", stream=stream)

        assert dummy_handler not in root.handlers

    def test_mixed_audit_and_operational_all_valid_jsonl(self):
        stream = io.StringIO()
        configure_json_logging(level="INFO", stream=stream)

        ops_logger = logging.getLogger("test.integration.mixed")
        audit_logger = logging.getLogger("mcp_zero.audit.hook")

        ops_logger.info("operational message")
        audit_event = json.dumps({"event_type": "TOOL_INVOCATION", "correlation_id": "xyz"})
        audit_logger.info(audit_event)
        ops_logger.warning("another operational")

        lines = [line for line in stream.getvalue().strip().split("\n") if line]
        assert len(lines) == 3

        for line in lines:
            parsed = json.loads(line)
            assert "service" in parsed
            assert "level" in parsed

        # Check specific lines
        assert json.loads(lines[0])["message"] == "operational message"
        assert json.loads(lines[1])["event_type"] == "TOOL_INVOCATION"
        assert json.loads(lines[2])["message"] == "another operational"

    def test_immediate_flush(self):
        stream = io.StringIO()
        configure_json_logging(level="INFO", stream=stream)

        logger = logging.getLogger("test.integration.flush")
        logger.info("first")

        # After a single log call the output should already be available
        assert stream.getvalue().strip() != ""

    def test_env_var_level_fallback(self, monkeypatch):
        """Simulate the env var fallback used in main.py."""
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")

        stream = io.StringIO()
        configure_json_logging(level="DEBUG", stream=stream)

        logger = logging.getLogger("test.integration.env")
        logger.debug("debug message")

        lines = [line for line in stream.getvalue().strip().split("\n") if line]
        assert len(lines) == 1
        assert json.loads(lines[0])["message"] == "debug message"

    def test_policy_level_override(self):
        """Simulate the two-phase approach: env var first, then policy override."""
        stream = io.StringIO()
        configure_json_logging(level="DEBUG", stream=stream)

        logger = logging.getLogger("test.integration.policy")
        logger.debug("should appear before override")

        # Simulate policy overriding the level
        logging.getLogger().setLevel("WARNING")
        logger.debug("should be filtered after override")
        logger.warning("should appear after override")

        lines = [line for line in stream.getvalue().strip().split("\n") if line]
        assert len(lines) == 2
        assert json.loads(lines[0])["message"] == "should appear before override"
        assert json.loads(lines[1])["message"] == "should appear after override"
