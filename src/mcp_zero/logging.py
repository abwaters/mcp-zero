"""Structured JSON logging for EKS/Kubernetes log collection.

Emits all gateway output — audit events and operational logs — as
line-delimited JSON (JSONL) to stdout so that Fluentd, CloudWatch,
and similar collectors can ingest it without parsing.
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from datetime import UTC, datetime

SERVICE_NAME = "mcp-gateway"


class JsonFormatter(logging.Formatter):
    """Formats every log record as a single-line JSON object.

    * **Audit events** (message is already valid JSON from ``AuditHook``):
      parsed, enriched with ``service`` and ``level``, then re-serialised.
    * **Operational logs** (plain text): wrapped in a standard envelope with
      ``service``, ``level``, ``timestamp``, ``logger``, and ``message``.
    * **Exceptions**: stack traces are encoded as single-line strings in an
      ``error`` field (``type``, ``message``, ``traceback``).
    """

    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()

        # Try to detect pre-serialised JSON (audit events)
        obj = self._try_parse_json(msg)

        if obj is not None:
            # Audit event — merge in standard fields
            obj.setdefault("service", SERVICE_NAME)
            obj["level"] = record.levelname
        else:
            # Operational log — build envelope
            obj = {
                "service": SERVICE_NAME,
                "level": record.levelname,
                "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
                "logger": record.name,
                "message": msg,
            }

        # Attach exception info if present
        if record.exc_info and record.exc_info[0] is not None:
            obj["error"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": "".join(traceback.format_exception(*record.exc_info)).rstrip(),
            }

        return json.dumps(obj, default=str)

    @staticmethod
    def _try_parse_json(msg: str) -> dict | None:
        """Return parsed dict if *msg* is a JSON object, else ``None``."""
        if not msg or msg[0] != "{":
            return None
        try:
            parsed = json.loads(msg)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
        return None


class FlushStreamHandler(logging.StreamHandler):
    """StreamHandler that flushes after every ``emit()`` call.

    Ensures log lines are written immediately, which is critical
    when running inside containers where stdout may be block-buffered.
    """

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        self.flush()


def configure_json_logging(
    level: str = "INFO",
    stream: object = None,
) -> None:
    """Replace ``logging.basicConfig()`` with structured JSON logging.

    Args:
        level: Root logger level name (e.g. ``"INFO"``, ``"DEBUG"``).
        stream: Output stream; defaults to ``sys.stdout``.
    """
    if stream is None:
        stream = sys.stdout

    root = logging.getLogger()

    # Remove any existing handlers
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = FlushStreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)
