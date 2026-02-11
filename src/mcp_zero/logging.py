"""Structured logging for the MCP gateway.

Supports two output formats controlled by the ``LOG_FORMAT`` env var
or the ``logging.format`` policy field:

* **json** (default) — line-delimited JSON (JSONL) for EKS/Kubernetes
  log collectors (Fluentd, CloudWatch, etc.).
* **text** — human-readable, color-coded output for local development
  and debugging.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from datetime import UTC, datetime

SERVICE_NAME = "mcp-gateway"

# ANSI color codes — only used when the stream is a TTY.
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_WHITE = "\033[37m"
_RED_BG = "\033[41m"

_LEVEL_STYLES = {
    "DEBUG": (_DIM, "DEBUG"),
    "INFO": (_GREEN, "INFO "),
    "WARNING": (_YELLOW + _BOLD, "WARN "),
    "ERROR": (_RED + _BOLD, "ERROR"),
    "CRITICAL": (_RED_BG + _WHITE + _BOLD, "FATAL"),
}

# Audit event types → compact labels for text mode.
_AUDIT_LABELS = {
    "mcp_tool_invocation": "TOOL_CALL",
    "policy_decision": "POLICY",
    "masking_event": "MASKING",
    "error": "ERROR",
}


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
        obj = _try_parse_json(msg)

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


class TextFormatter(logging.Formatter):
    """Human-readable, color-coded formatter for local development.

    Operational logs::

        12:34:56.789 INFO  [governance.hook] Policy ALLOW: user=alice server=s1 tool=t1

    Audit events (pre-serialised JSON from AuditHook) are rendered as
    a compact one-liner::

        12:34:56.790 INFO  [audit] ── TOOL_CALL ── server=s1 tool=t1 user=alice ...

    Errors include a clearly separated traceback block::

        12:34:56.791 ERROR [masking.hook] Masking engine failure ...
                     ╰─ MaskingEngineError: Presidio analyzer failed
                        File "mcp_zero/masking/presidio.py", line 42
                        ...
    """

    def __init__(self, *, use_color: bool = True) -> None:
        super().__init__()
        self._color = use_color

    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        ts = datetime.fromtimestamp(record.created, tz=UTC).strftime("%H:%M:%S.%f")[:-3]
        logger_name = _short_logger(record.name)

        # Level tag
        style, label = _LEVEL_STYLES.get(record.levelname, ("", record.levelname.ljust(5)))
        if self._color:
            level_tag = f"{style}{label}{_RESET}"
        else:
            level_tag = label

        # Gutter marker — makes WARN/ERROR lines pop out when scanning
        if record.levelno >= logging.ERROR:
            gutter = f"{_RED}!{_RESET} " if self._color else "! "
        elif record.levelno >= logging.WARNING:
            gutter = f"{_YELLOW}!{_RESET} " if self._color else "! "
        else:
            gutter = "  "

        # Detect audit events (pre-serialised JSON)
        audit_obj = _try_parse_json(msg)
        if audit_obj is not None:
            body = self._format_audit(audit_obj)
        else:
            body = msg

        # Color the message body for WARN/ERROR to make the entire line stand out
        if self._color and record.levelno >= logging.ERROR:
            body = f"{_RED}{body}{_RESET}"
        elif self._color and record.levelno >= logging.WARNING:
            body = f"{_YELLOW}{body}{_RESET}"

        if self._color:
            line = f"{_DIM}{ts}{_RESET} {gutter}{level_tag} {_DIM}[{logger_name}]{_RESET} {body}"
        else:
            line = f"{ts} {gutter}{level_tag} [{logger_name}] {body}"

        # Append exception info with visual indentation
        if record.exc_info and record.exc_info[0] is not None:
            exc_block = self._format_exception(record.exc_info)
            line = f"{line}\n{exc_block}"

        return line

    def _format_audit(self, obj: dict) -> str:
        """Render an audit event dict as a compact, readable summary."""
        event_type = obj.get("event_type", "unknown")
        label = _AUDIT_LABELS.get(event_type, event_type.upper())

        parts: list[str] = []

        server = obj.get("server_name", "")
        tool = obj.get("tool_name", "")
        if server:
            parts.append(f"server={server}")
        if tool:
            parts.append(f"tool={tool}")

        user = obj.get("user", {})
        if isinstance(user, dict) and user.get("user_id"):
            parts.append(f"user={user['user_id']}")

        decision = obj.get("policy_decision", "")
        if decision:
            parts.append(f"decision={decision}")

        reason = obj.get("short_circuit_reason", "")
        if reason:
            parts.append(f'reason="{reason}"')

        cid = obj.get("correlation_id", "")
        if cid:
            parts.append(f"cid={cid[:12]}")

        duration = obj.get("duration_ms")
        if duration is not None:
            parts.append(f"{duration:.0f}ms")

        req_size = obj.get("request_size_bytes")
        resp_size = obj.get("response_size_bytes")
        if req_size:
            parts.append(f"req={_human_bytes(req_size)}")
        if resp_size:
            parts.append(f"resp={_human_bytes(resp_size)}")

        # Masking summary
        masking_events = obj.get("masking_events", [])
        if masking_events:
            masked_str = ", ".join(f"{e['count']}x {e['entity_type']}" for e in masking_events)
            parts.append(f"masked=[{masked_str}]")

        error_type = obj.get("error_type", "")
        error_msg = obj.get("error_message", "")
        if error_type:
            parts.append(f"error={error_type}: {error_msg}")

        summary = " ".join(parts)

        if self._color:
            return f"{_BOLD}── {label} ──{_RESET} {summary}"
        return f"-- {label} -- {summary}"

    def _format_exception(self, exc_info: tuple) -> str:
        """Format exception with indentation and visual connector."""
        exc_type, exc_value, exc_tb = exc_info
        indent = " " * 15  # align under the message text (accounts for gutter)
        lines = traceback.format_exception(exc_type, exc_value, exc_tb)
        formatted = "".join(lines).rstrip()

        if self._color:
            header = f"{indent}{_RED}╰─ {exc_type.__name__}: {exc_value}{_RESET}"
            tb_lines = formatted.split("\n")
            # Skip the last line (it's the exception message we already show)
            tb_body = "\n".join(
                f"{indent}   {_DIM}{line}{_RESET}" for line in tb_lines[:-1] if line.strip()
            )
            if tb_body:
                return f"{header}\n{tb_body}"
            return header

        header = f"{indent}+-- {exc_type.__name__}: {exc_value}"
        tb_lines = formatted.split("\n")
        tb_body = "\n".join(f"{indent}    {line}" for line in tb_lines[:-1] if line.strip())
        if tb_body:
            return f"{header}\n{tb_body}"
        return header


class FlushStreamHandler(logging.StreamHandler):
    """StreamHandler that flushes after every ``emit()`` call.

    Ensures log lines are written immediately, which is critical
    when running inside containers where stdout may be block-buffered.
    """

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        self.flush()


def configure_logging(
    level: str = "INFO",
    fmt: str = "json",
    stream: object = None,
) -> None:
    """Set up gateway logging with the chosen format.

    Args:
        level: Root logger level name (e.g. ``"INFO"``, ``"DEBUG"``).
        fmt: Output format — ``"json"`` for JSONL or ``"text"`` for
            human-readable colored output.
        stream: Output stream; defaults to ``sys.stdout``.
    """
    if stream is None:
        stream = sys.stdout

    root = logging.getLogger()

    # Remove any existing handlers
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = FlushStreamHandler(stream)

    if fmt == "text":
        use_color = hasattr(stream, "isatty") and stream.isatty()
        # Allow forcing color on/off via env var
        force = os.environ.get("FORCE_COLOR", "").strip().lower()
        if force in ("1", "true", "yes"):
            use_color = True
        elif force in ("0", "false", "no"):
            use_color = False
        handler.setFormatter(TextFormatter(use_color=use_color))
    else:
        handler.setFormatter(JsonFormatter())

    root.addHandler(handler)
    root.setLevel(level)


# Keep the old name as an alias for backward compatibility.
def configure_json_logging(
    level: str = "INFO",
    stream: object = None,
) -> None:
    """Legacy wrapper — delegates to :func:`configure_logging` with ``fmt="json"``."""
    configure_logging(level=level, fmt="json", stream=stream)


# -- Helpers ------------------------------------------------------------------


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


def _short_logger(name: str) -> str:
    """Abbreviate ``mcp_zero.governance.hook`` → ``governance.hook``."""
    if name.startswith("mcp_zero."):
        return name[len("mcp_zero.") :]
    return name


def _human_bytes(n: int) -> str:
    """Format bytes as a compact human string (e.g. ``1.2K``)."""
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f}K"
    return f"{n / (1024 * 1024):.1f}M"
