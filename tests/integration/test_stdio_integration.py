"""End-to-end integration tests for stdio transport flows.

These tests spawn a real MCP server subprocess (``echo_server.py``) and wire
it through the full gateway stack: ProxyServer → Pipeline (governance, masking,
audit) → StdioTransport → subprocess → response.

Each test class focuses on a distinct flow:
- Tool listing through stdio
- Happy-path tool calls
- Governance deny (policy blocks before reaching upstream)
- PII masking on inputs and outputs
- Audit trail correctness
- Fail-closed masking behaviour
- Session reuse across multiple tool calls
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from mcp_zero.audit.event import AuditEventType
from mcp_zero.audit.hook import AuditHook
from mcp_zero.governance.config import (
    PolicyConfig,
    PolicyEffect,
    PolicyRule,
    PolicyServerAccess,
    PolicySubjects,
    PresidioConfig,
)
from mcp_zero.governance.engine import PolicyEngine
from mcp_zero.governance.hook import GovernanceHook
from mcp_zero.masking.engine import MaskingEvent, MaskingResult
from mcp_zero.masking.errors import MaskingEngineError
from mcp_zero.masking.hook import MaskingHook
from mcp_zero.pipeline.pipeline import Pipeline
from mcp_zero.pipeline.registry import HookRegistry
from mcp_zero.proxy.proxy_server import ProxyServer
from mcp_zero.proxy.server_manager import ServerManager
from mcp_zero.transport.config import ServerConfig, TransportType

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ECHO_SERVER = str(Path(__file__).resolve().parent.parent / "fixtures" / "echo_server.py")
_PYTHON = sys.executable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stdio_config(
    name: str = "test-stdio",
    timeout: float = 10.0,
) -> ServerConfig:
    """Build a ServerConfig pointing at the test echo server."""
    return ServerConfig(
        name=name,
        transport=TransportType.STDIO,
        command=_PYTHON,
        args=[_ECHO_SERVER],
        timeout_seconds=timeout,
        max_retries=0,
    )


def _allow_all_policy() -> PolicyConfig:
    """Policy that allows everything."""
    return PolicyConfig(
        version=1,
        default=PolicyEffect.ALLOW,
        policies=[],
    )


def _deny_all_policy() -> PolicyConfig:
    """Policy that denies everything."""
    return PolicyConfig(
        version=1,
        default=PolicyEffect.DENY,
        policies=[],
    )


def _selective_policy(
    *,
    allowed_servers: list[str] | None = None,
    denied_servers: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    denied_tools: list[str] | None = None,
) -> PolicyConfig:
    """Policy with specific allow/deny rules."""
    rules: list[PolicyRule] = []
    if allowed_servers:
        for server in allowed_servers:
            rules.append(
                PolicyRule(
                    id=f"allow-{server}",
                    description=f"Allow access to {server}",
                    effect=PolicyEffect.ALLOW,
                    subjects=PolicySubjects(),  # matches everyone
                    mcp_servers=[PolicyServerAccess(name=server, tools=allowed_tools or [])],
                )
            )
    if denied_servers:
        for server in denied_servers:
            rules.append(
                PolicyRule(
                    id=f"deny-{server}",
                    description=f"Deny access to {server}",
                    effect=PolicyEffect.DENY,
                    subjects=PolicySubjects(),
                    mcp_servers=[PolicyServerAccess(name=server, tools=denied_tools or [])],
                )
            )
    return PolicyConfig(version=1, default=PolicyEffect.DENY, policies=rules)


def _noop_masking_engine() -> AsyncMock:
    """Masking engine that passes text through unchanged."""
    engine = AsyncMock()
    engine.mask_text.side_effect = lambda text, entities, direction: MaskingResult(
        masked_text=text, events=[], has_masked=False
    )
    return engine


def _pii_masking_engine() -> AsyncMock:
    """Masking engine that replaces known PII patterns."""
    engine = AsyncMock()

    async def _mask(text: str, entities: list[str], direction: str) -> MaskingResult:
        masked = text
        events: list[MaskingEvent] = []

        # Simple replacements for testing
        pii_patterns = {
            "John Smith": ("<PERSON>", "PERSON"),
            "john.smith@example.com": ("<EMAIL_ADDRESS>", "EMAIL_ADDRESS"),
            "555-123-4567": ("<PHONE_NUMBER>", "PHONE_NUMBER"),
        }
        for pattern, (replacement, entity_type) in pii_patterns.items():
            if pattern in masked:
                masked = masked.replace(pattern, replacement)
                events.append(MaskingEvent(entity_type=entity_type, count=1, status="masked"))

        return MaskingResult(
            masked_text=masked,
            events=events,
            has_masked=bool(events),
        )

    engine.mask_text.side_effect = _mask
    return engine


def _build_pipeline(
    *,
    policy: PolicyConfig | None = None,
    masking_engine: AsyncMock | None = None,
    masking_enabled: bool = True,
    audit_hook: AuditHook | None = None,
    identity_required: bool = False,
) -> tuple[Pipeline, AuditHook]:
    """Assemble a full pipeline with governance, masking, and audit hooks."""
    if audit_hook is None:
        audit_hook = AuditHook()

    registry = HookRegistry()

    # Governance (priority 50)
    if policy is not None:
        gov_engine = PolicyEngine(policy)
        gov_hook = GovernanceHook(gov_engine, identity_required=identity_required)
        registry.register(gov_hook, priority=50)

    # Masking (priority 75)
    if masking_engine is not None:
        presidio_cfg = PresidioConfig(enabled=masking_enabled, entities=["PERSON", "EMAIL_ADDRESS"])
        masking_hook = MaskingHook(masking_engine, presidio_cfg)
        registry.register(masking_hook, priority=75)

    # Audit (priority 150)
    registry.register(audit_hook, priority=150)

    registry.build()
    return Pipeline(registry), audit_hook


# ---------------------------------------------------------------------------
# Test: Tool listing
# ---------------------------------------------------------------------------


class TestStdioToolListing:
    """Verify that list_tools works through the stdio transport."""

    @pytest.mark.asyncio
    async def test_list_tools_returns_namespaced_tools(self):
        """Gateway lists tools from the subprocess and namespaces them."""
        config = _stdio_config()
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr)
            tools = await proxy._list_tools()

        tool_names = [t.name for t in tools]
        assert "test-stdio__echo" in tool_names
        assert "test-stdio__greet" in tool_names
        assert "test-stdio__get_secret_data" in tool_names
        assert "test-stdio__reverse" in tool_names
        assert len(tools) == 4

    @pytest.mark.asyncio
    async def test_list_tools_includes_descriptions(self):
        """Each tool carries its description from the upstream server."""
        config = _stdio_config()
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr)
            tools = await proxy._list_tools()

        by_name = {t.name: t for t in tools}
        assert "input text unchanged" in by_name["test-stdio__echo"].description.lower()

    @pytest.mark.asyncio
    async def test_list_tools_includes_input_schema(self):
        """Each tool carries its input schema from the upstream server."""
        config = _stdio_config()
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr)
            tools = await proxy._list_tools()

        by_name = {t.name: t for t in tools}
        echo_schema = by_name["test-stdio__echo"].input_schema
        assert echo_schema["type"] == "object"
        assert "text" in echo_schema["properties"]


# ---------------------------------------------------------------------------
# Test: Happy-path tool calls
# ---------------------------------------------------------------------------


class TestStdioHappyPath:
    """End-to-end tool call with an allow-all policy and no-op masking."""

    @pytest.mark.asyncio
    async def test_echo_returns_input_text(self):
        """echo tool returns the exact text sent."""
        config = _stdio_config()
        pipeline, audit_hook = _build_pipeline(
            policy=_allow_all_policy(),
            masking_engine=_noop_masking_engine(),
        )
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            result = await proxy._call_tool("test-stdio__echo", {"text": "hello world"})

        assert len(result) == 1
        assert result[0].type == "text"
        assert result[0].text == "hello world"

    @pytest.mark.asyncio
    async def test_greet_returns_greeting(self):
        """greet tool returns a greeting with the provided name."""
        config = _stdio_config()
        pipeline, _ = _build_pipeline(
            policy=_allow_all_policy(),
            masking_engine=_noop_masking_engine(),
        )
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            result = await proxy._call_tool("test-stdio__greet", {"name": "Alice"})

        assert result[0].text == "Hello, Alice!"

    @pytest.mark.asyncio
    async def test_reverse_returns_reversed_text(self):
        """reverse tool returns the text reversed."""
        config = _stdio_config()
        pipeline, _ = _build_pipeline(
            policy=_allow_all_policy(),
            masking_engine=_noop_masking_engine(),
        )
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            result = await proxy._call_tool("test-stdio__reverse", {"text": "abcd"})

        assert result[0].text == "dcba"

    @pytest.mark.asyncio
    async def test_call_without_pipeline(self):
        """Tool call works when no pipeline is configured (raw passthrough)."""
        config = _stdio_config()
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr)
            result = await proxy._call_tool("test-stdio__echo", {"text": "raw"})

        assert result[0].text == "raw"


# ---------------------------------------------------------------------------
# Test: Governance deny
# ---------------------------------------------------------------------------


class TestStdioGovernanceDeny:
    """Verify that governance policy blocks tool calls before reaching upstream."""

    @pytest.mark.asyncio
    async def test_deny_all_returns_access_denied(self):
        """A default-deny policy blocks the call and returns access denied."""
        config = _stdio_config()
        pipeline, audit_hook = _build_pipeline(policy=_deny_all_policy())
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            result = await proxy._call_tool("test-stdio__echo", {"text": "should not reach"})

        assert len(result) == 1
        assert "Access denied" in result[0].text

    @pytest.mark.asyncio
    async def test_deny_emits_policy_decision_audit_event(self):
        """Governance deny produces a POLICY_DECISION audit event."""
        config = _stdio_config()
        pipeline, audit_hook = _build_pipeline(policy=_deny_all_policy())
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            await proxy._call_tool("test-stdio__echo", {"text": "blocked"})

        policy_events = [
            e for e in audit_hook.events if e.event_type == AuditEventType.POLICY_DECISION
        ]
        assert len(policy_events) >= 1
        assert policy_events[0].short_circuited is True

    @pytest.mark.asyncio
    async def test_selective_deny_blocks_specific_server(self):
        """A deny rule targeting a specific server blocks that server's tools."""
        config = _stdio_config()
        policy = _selective_policy(denied_servers=["test-stdio"])
        pipeline, _ = _build_pipeline(policy=policy)
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            result = await proxy._call_tool("test-stdio__echo", {"text": "no"})

        assert "Access denied" in result[0].text

    @pytest.mark.asyncio
    async def test_selective_allow_permits_specific_server(self):
        """An allow rule for a server permits tool calls to that server."""
        config = _stdio_config()
        policy = _selective_policy(allowed_servers=["test-stdio"])
        pipeline, _ = _build_pipeline(
            policy=policy,
            masking_engine=_noop_masking_engine(),
        )
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            result = await proxy._call_tool("test-stdio__echo", {"text": "yes"})

        assert result[0].text == "yes"


# ---------------------------------------------------------------------------
# Test: PII masking on inputs
# ---------------------------------------------------------------------------


class TestStdioInputMasking:
    """Verify that PII in request arguments is masked before reaching upstream."""

    @pytest.mark.asyncio
    async def test_pii_in_arguments_is_masked(self):
        """PII in tool arguments gets masked — the upstream server sees masked text."""
        config = _stdio_config()
        pipeline, audit_hook = _build_pipeline(
            policy=_allow_all_policy(),
            masking_engine=_pii_masking_engine(),
        )
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            # The echo tool returns whatever it receives — so if masking works,
            # the response will contain the masked version.
            result = await proxy._call_tool(
                "test-stdio__echo", {"text": "Contact John Smith at john.smith@example.com"}
            )

        response_text = result[0].text
        # The upstream received masked text and echoed it back
        assert "John Smith" not in response_text
        assert "<PERSON>" in response_text or "john.smith@example.com" not in response_text

    @pytest.mark.asyncio
    async def test_input_masking_audit_records(self):
        """Audit events reflect that input masking was applied."""
        config = _stdio_config()
        pipeline, audit_hook = _build_pipeline(
            policy=_allow_all_policy(),
            masking_engine=_pii_masking_engine(),
        )
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            await proxy._call_tool("test-stdio__echo", {"text": "Call John Smith at 555-123-4567"})

        # Find the TOOL_INVOCATION events (request phase)
        tool_events = [
            e for e in audit_hook.events if e.event_type == AuditEventType.TOOL_INVOCATION
        ]
        assert len(tool_events) >= 1
        # First event is the request phase
        req_event = tool_events[0]
        assert req_event.input_masking.applied is True
        assert req_event.input_masking.masked_field_count >= 1


# ---------------------------------------------------------------------------
# Test: PII masking on outputs
# ---------------------------------------------------------------------------


class TestStdioOutputMasking:
    """Verify that PII in upstream responses is masked before reaching the client."""

    @pytest.mark.asyncio
    async def test_pii_in_response_is_masked(self):
        """PII in the upstream response gets masked before the client sees it."""
        config = _stdio_config()
        pipeline, audit_hook = _build_pipeline(
            policy=_allow_all_policy(),
            masking_engine=_pii_masking_engine(),
        )
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            # get_secret_data returns text with PII
            result = await proxy._call_tool("test-stdio__get_secret_data", {})

        response_text = result[0].text
        assert "John Smith" not in response_text
        assert "john.smith@example.com" not in response_text

    @pytest.mark.asyncio
    async def test_output_masking_audit_records(self):
        """Audit events reflect that output masking was applied."""
        config = _stdio_config()
        pipeline, audit_hook = _build_pipeline(
            policy=_allow_all_policy(),
            masking_engine=_pii_masking_engine(),
        )
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            await proxy._call_tool("test-stdio__get_secret_data", {})

        # The response phase produces its own TOOL_INVOCATION event
        tool_events = [
            e for e in audit_hook.events if e.event_type == AuditEventType.TOOL_INVOCATION
        ]
        # Should have both request-phase and response-phase events
        assert len(tool_events) >= 2
        # Response-phase event should show output masking
        resp_event = tool_events[1]
        assert resp_event.output_masking.applied is True


# ---------------------------------------------------------------------------
# Test: Audit trail
# ---------------------------------------------------------------------------


class TestStdioAuditTrail:
    """Verify audit events carry correct metadata for stdio flows."""

    @pytest.mark.asyncio
    async def test_audit_event_has_transport_stdio(self):
        """Audit events record transport='stdio'."""
        config = _stdio_config()
        pipeline, audit_hook = _build_pipeline(
            policy=_allow_all_policy(),
            masking_engine=_noop_masking_engine(),
        )
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            await proxy._call_tool("test-stdio__echo", {"text": "audit test"})

        tool_events = [
            e for e in audit_hook.events if e.event_type == AuditEventType.TOOL_INVOCATION
        ]
        assert len(tool_events) >= 1
        assert tool_events[0].transport == "stdio"

    @pytest.mark.asyncio
    async def test_audit_event_has_server_and_tool_names(self):
        """Audit events carry the correct server and tool names."""
        config = _stdio_config()
        pipeline, audit_hook = _build_pipeline(
            policy=_allow_all_policy(),
            masking_engine=_noop_masking_engine(),
        )
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            await proxy._call_tool("test-stdio__echo", {"text": "names"})

        event = audit_hook.events[0]
        assert event.server_name == "test-stdio"
        assert event.tool_name == "echo"

    @pytest.mark.asyncio
    async def test_audit_event_has_correlation_id(self):
        """Audit events have a non-empty correlation ID."""
        config = _stdio_config()
        pipeline, audit_hook = _build_pipeline(
            policy=_allow_all_policy(),
            masking_engine=_noop_masking_engine(),
        )
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            await proxy._call_tool("test-stdio__echo", {"text": "corr"})

        event = audit_hook.events[0]
        assert event.correlation_id
        assert len(event.correlation_id) > 0

    @pytest.mark.asyncio
    async def test_audit_event_has_policy_decision(self):
        """Audit events record the policy decision from the governance hook."""
        config = _stdio_config()
        pipeline, audit_hook = _build_pipeline(
            policy=_allow_all_policy(),
            masking_engine=_noop_masking_engine(),
        )
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            await proxy._call_tool("test-stdio__echo", {"text": "decision"})

        event = audit_hook.events[0]
        assert event.policy_decision == "allow"

    @pytest.mark.asyncio
    async def test_audit_event_has_duration(self):
        """Audit events measure request duration."""
        config = _stdio_config()
        pipeline, audit_hook = _build_pipeline(
            policy=_allow_all_policy(),
            masking_engine=_noop_masking_engine(),
        )
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            await proxy._call_tool("test-stdio__echo", {"text": "timing"})

        event = audit_hook.events[0]
        assert event.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_audit_event_has_request_size(self):
        """Audit events measure request payload size."""
        config = _stdio_config()
        pipeline, audit_hook = _build_pipeline(
            policy=_allow_all_policy(),
            masking_engine=_noop_masking_engine(),
        )
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            await proxy._call_tool("test-stdio__echo", {"text": "size test"})

        event = audit_hook.events[0]
        assert event.request_size_bytes > 0


# ---------------------------------------------------------------------------
# Test: Fail-closed masking
# ---------------------------------------------------------------------------


class TestStdioMaskingFailClosed:
    """Verify fail-closed behaviour when the masking engine fails."""

    @pytest.mark.asyncio
    async def test_masking_engine_failure_blocks_request(self):
        """When the masking engine raises, the request is denied (fail-closed)."""
        config = _stdio_config()
        failing_engine = AsyncMock()
        failing_engine.mask_text.side_effect = MaskingEngineError(
            "engine crashed", engine="presidio"
        )
        pipeline, audit_hook = _build_pipeline(
            policy=_allow_all_policy(),
            masking_engine=failing_engine,
        )
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            result = await proxy._call_tool("test-stdio__echo", {"text": "sensitive data"})

        assert "Access denied" in result[0].text

    @pytest.mark.asyncio
    async def test_masking_engine_failure_emits_policy_decision(self):
        """Masking failure emits a POLICY_DECISION audit event (fail-closed)."""
        config = _stdio_config()
        failing_engine = AsyncMock()
        failing_engine.mask_text.side_effect = MaskingEngineError(
            "engine crashed", engine="presidio"
        )
        pipeline, audit_hook = _build_pipeline(
            policy=_allow_all_policy(),
            masking_engine=failing_engine,
        )
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            await proxy._call_tool("test-stdio__echo", {"text": "fail test"})

        policy_events = [
            e for e in audit_hook.events if e.event_type == AuditEventType.POLICY_DECISION
        ]
        assert len(policy_events) >= 1


# ---------------------------------------------------------------------------
# Test: Session reuse / multiple calls
# ---------------------------------------------------------------------------


class TestStdioSessionReuse:
    """Verify that multiple tool calls reuse the same transport session."""

    @pytest.mark.asyncio
    async def test_multiple_calls_on_same_session(self):
        """Multiple tool calls work on the same transport session."""
        config = _stdio_config()
        pipeline, _ = _build_pipeline(
            policy=_allow_all_policy(),
            masking_engine=_noop_masking_engine(),
        )
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)

            r1 = await proxy._call_tool("test-stdio__echo", {"text": "first"})
            r2 = await proxy._call_tool("test-stdio__reverse", {"text": "second"})
            r3 = await proxy._call_tool("test-stdio__greet", {"name": "Bob"})

        assert r1[0].text == "first"
        assert r2[0].text == "dnoces"
        assert r3[0].text == "Hello, Bob!"

    @pytest.mark.asyncio
    async def test_different_tools_same_server(self):
        """Calling different tools on the same server all succeed."""
        config = _stdio_config()
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr)

            results = []
            for tool, args in [
                ("test-stdio__echo", {"text": "a"}),
                ("test-stdio__reverse", {"text": "ab"}),
                ("test-stdio__greet", {"name": "C"}),
                ("test-stdio__echo", {"text": "d"}),
            ]:
                r = await proxy._call_tool(tool, args)
                results.append(r[0].text)

        assert results == ["a", "ba", "Hello, C!", "d"]


# ---------------------------------------------------------------------------
# Test: Full pipeline composition
# ---------------------------------------------------------------------------


class TestStdioFullPipeline:
    """End-to-end test with all pipeline components active simultaneously."""

    @pytest.mark.asyncio
    async def test_governance_masking_audit_all_active(self):
        """Full pipeline: governance allows, masking cleans PII, audit records it all."""
        config = _stdio_config()
        pipeline, audit_hook = _build_pipeline(
            policy=_allow_all_policy(),
            masking_engine=_pii_masking_engine(),
        )
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            result = await proxy._call_tool("test-stdio__get_secret_data", {})

        # Response should have PII masked
        response_text = result[0].text
        assert "John Smith" not in response_text

        # Audit should have both request and response events
        tool_events = [
            e for e in audit_hook.events if e.event_type == AuditEventType.TOOL_INVOCATION
        ]
        assert len(tool_events) >= 2

        # Request phase
        req_event = tool_events[0]
        assert req_event.server_name == "test-stdio"
        assert req_event.tool_name == "get_secret_data"
        assert req_event.transport == "stdio"
        assert req_event.policy_decision == "allow"
        assert req_event.input_masking.masking_stage_completed is True

        # Response phase
        resp_event = tool_events[1]
        assert resp_event.output_masking.applied is True

    @pytest.mark.asyncio
    async def test_governance_deny_prevents_upstream_call(self):
        """When governance denies, the upstream server is never contacted.

        We verify this by checking that no response-phase audit event exists
        (the proxy never reaches the transport layer).
        """
        config = _stdio_config()
        pipeline, audit_hook = _build_pipeline(
            policy=_deny_all_policy(),
            masking_engine=_pii_masking_engine(),
        )
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            result = await proxy._call_tool("test-stdio__echo", {"text": "blocked"})

        assert "Access denied" in result[0].text

        # Only a POLICY_DECISION event — no TOOL_INVOCATION
        event_types = [e.event_type for e in audit_hook.events]
        assert AuditEventType.POLICY_DECISION in event_types
        assert AuditEventType.TOOL_INVOCATION not in event_types

    @pytest.mark.asyncio
    async def test_input_masking_then_output_masking(self):
        """Both input and output masking fire in sequence for a round-trip."""
        config = _stdio_config()
        pipeline, audit_hook = _build_pipeline(
            policy=_allow_all_policy(),
            masking_engine=_pii_masking_engine(),
        )
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            # Send PII as input; the echo server returns it.
            # Input masking replaces PII before upstream; output masking
            # processes the response (which now contains masked text).
            result = await proxy._call_tool(
                "test-stdio__echo",
                {"text": "Email john.smith@example.com for John Smith"},
            )

        response_text = result[0].text
        # Input masking should have replaced PII before it reached echo
        assert "john.smith@example.com" not in response_text
        assert "John Smith" not in response_text

    @pytest.mark.asyncio
    async def test_no_pii_passthrough(self):
        """Clean text passes through masking unchanged."""
        config = _stdio_config()
        pipeline, audit_hook = _build_pipeline(
            policy=_allow_all_policy(),
            masking_engine=_pii_masking_engine(),
        )
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            result = await proxy._call_tool("test-stdio__echo", {"text": "no sensitive data here"})

        assert result[0].text == "no sensitive data here"

        # Audit should show masking completed but not applied
        tool_events = [
            e for e in audit_hook.events if e.event_type == AuditEventType.TOOL_INVOCATION
        ]
        assert tool_events[0].input_masking.masking_stage_completed is True
        assert tool_events[0].input_masking.applied is False
