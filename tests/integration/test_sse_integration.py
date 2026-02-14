"""End-to-end integration tests for SSE transport flows.

These tests start a real MCP server over SSE (``echo_server_sse.py``) and wire
it through the full gateway stack: ProxyServer -> Pipeline (governance, masking,
audit) -> SSETransport -> upstream SSE server -> response.

Each test class mirrors the structure of ``test_stdio_integration.py``:
- Tool listing through SSE
- Happy-path tool calls
- Governance deny (policy blocks before reaching upstream)
- PII masking on inputs and outputs
- Audit trail correctness
- Session reuse across multiple tool calls
"""

from __future__ import annotations

import asyncio
import socket
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio

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
from mcp_zero.masking.hook import MaskingHook
from mcp_zero.pipeline.pipeline import Pipeline
from mcp_zero.pipeline.registry import HookRegistry
from mcp_zero.proxy.proxy_server import ProxyServer
from mcp_zero.proxy.server_manager import ServerManager
from mcp_zero.transport.config import ServerConfig, TransportType

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ECHO_SERVER_SSE = str(Path(__file__).resolve().parent.parent / "fixtures" / "echo_server_sse.py")
_PYTHON = sys.executable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    """Find a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _start_sse_server(port: int) -> asyncio.subprocess.Process:
    """Start the echo SSE server as a subprocess and wait for it to be ready."""
    proc = await asyncio.create_subprocess_exec(
        _PYTHON,
        _ECHO_SERVER_SSE,
        str(port),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    # Wait for the server to be fully ready using an HTTP health check.
    # A plain TCP connect is not sufficient — the ASGI app may not have
    # finished mounting its routes yet, leading to flaky SSE failures on CI.
    url = f"http://127.0.0.1:{port}/health"
    async with httpx.AsyncClient() as client:
        for _ in range(100):  # up to 10 seconds
            await asyncio.sleep(0.1)
            try:
                resp = await client.get(url, timeout=2.0)
                if resp.status_code == 200:
                    return proc
            except (httpx.ConnectError, httpx.ReadError, OSError):
                continue
    raise RuntimeError(f"SSE test server failed to start on port {port}")


def _sse_config(
    port: int,
    name: str = "test-sse",
    timeout: float = 15.0,
) -> ServerConfig:
    """Build a ServerConfig pointing at the test SSE echo server."""
    return ServerConfig(
        name=name,
        transport=TransportType.SSE,
        url=f"http://127.0.0.1:{port}/sse",
        timeout_seconds=timeout,
        max_retries=1,
        allow_insecure=True,
    )


def _allow_all_policy() -> PolicyConfig:
    return PolicyConfig(version=1, default=PolicyEffect.ALLOW, policies=[])


def _deny_all_policy() -> PolicyConfig:
    return PolicyConfig(version=1, default=PolicyEffect.DENY, policies=[])


def _selective_policy(
    *,
    allowed_servers: list[str] | None = None,
    denied_servers: list[str] | None = None,
) -> PolicyConfig:
    rules: list[PolicyRule] = []
    if allowed_servers:
        for server in allowed_servers:
            rules.append(
                PolicyRule(
                    id=f"allow-{server}",
                    description=f"Allow access to {server}",
                    effect=PolicyEffect.ALLOW,
                    subjects=PolicySubjects(),
                    mcp_servers=[PolicyServerAccess(name=server, tools=[])],
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
                    mcp_servers=[PolicyServerAccess(name=server, tools=[])],
                )
            )
    return PolicyConfig(version=1, default=PolicyEffect.DENY, policies=rules)


def _noop_masking_engine() -> AsyncMock:
    engine = AsyncMock()
    engine.mask_text.side_effect = lambda text, entities, direction: MaskingResult(
        masked_text=text, events=[], has_masked=False
    )
    return engine


def _pii_masking_engine() -> AsyncMock:
    engine = AsyncMock()

    async def _mask(text: str, entities: list[str], direction: str) -> MaskingResult:
        masked = text
        events: list[MaskingEvent] = []
        pii_patterns = {
            "John Smith": ("<PERSON>", "PERSON"),
            "john.smith@example.com": ("<EMAIL_ADDRESS>", "EMAIL_ADDRESS"),
            "555-123-4567": ("<PHONE_NUMBER>", "PHONE_NUMBER"),
        }
        for pattern, (replacement, entity_type) in pii_patterns.items():
            if pattern in masked:
                masked = masked.replace(pattern, replacement)
                events.append(MaskingEvent(entity_type=entity_type, count=1, status="masked"))
        return MaskingResult(masked_text=masked, events=events, has_masked=bool(events))

    engine.mask_text.side_effect = _mask
    return engine


def _build_pipeline(
    *,
    policy: PolicyConfig | None = None,
    masking_engine: AsyncMock | None = None,
    masking_enabled: bool = True,
    audit_hook: AuditHook | None = None,
) -> tuple[Pipeline, AuditHook]:
    if audit_hook is None:
        audit_hook = AuditHook()
    registry = HookRegistry()
    if policy is not None:
        gov_engine = PolicyEngine(policy)
        gov_hook = GovernanceHook(gov_engine, identity_required=False)
        registry.register(gov_hook, priority=50)
    if masking_engine is not None:
        presidio_cfg = PresidioConfig(enabled=masking_enabled, entities=["PERSON", "EMAIL_ADDRESS"])
        masking_hook = MaskingHook(masking_engine, presidio_cfg)
        registry.register(masking_hook, priority=75)
    registry.register(audit_hook, priority=150)
    registry.build()
    return Pipeline(registry), audit_hook


# ---------------------------------------------------------------------------
# Fixture: SSE server process
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sse_server():
    """Start an SSE echo server subprocess and yield its port."""
    port = _find_free_port()
    proc = await _start_sse_server(port)
    yield port
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        proc.kill()
    # Allow OS to fully release the process resources
    await asyncio.sleep(0.2)


# ---------------------------------------------------------------------------
# Test: Tool listing
# ---------------------------------------------------------------------------


class TestSSEToolListing:
    @pytest.mark.asyncio
    async def test_list_tools_returns_namespaced_tools(self, sse_server):
        config = _sse_config(sse_server)
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr)
            tools = await proxy._list_tools()

        tool_names = [t.name for t in tools]
        assert "test-sse__echo" in tool_names
        assert "test-sse__greet" in tool_names
        assert "test-sse__get_secret_data" in tool_names
        assert "test-sse__reverse" in tool_names
        assert len(tools) == 4


# ---------------------------------------------------------------------------
# Test: Happy-path tool calls
# ---------------------------------------------------------------------------


class TestSSEHappyPath:
    @pytest.mark.asyncio
    async def test_echo_returns_input_text(self, sse_server):
        config = _sse_config(sse_server)
        pipeline, _ = _build_pipeline(
            policy=_allow_all_policy(), masking_engine=_noop_masking_engine()
        )
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            result = await proxy._call_tool("test-sse__echo", {"text": "hello world"})

        assert len(result) == 1
        assert result[0].text == "hello world"

    @pytest.mark.asyncio
    async def test_greet_returns_greeting(self, sse_server):
        config = _sse_config(sse_server)
        pipeline, _ = _build_pipeline(
            policy=_allow_all_policy(), masking_engine=_noop_masking_engine()
        )
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            result = await proxy._call_tool("test-sse__greet", {"name": "Alice"})

        assert result[0].text == "Hello, Alice!"

    @pytest.mark.asyncio
    async def test_call_without_pipeline(self, sse_server):
        config = _sse_config(sse_server)
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr)
            result = await proxy._call_tool("test-sse__echo", {"text": "raw"})

        assert result[0].text == "raw"


# ---------------------------------------------------------------------------
# Test: Governance deny
# ---------------------------------------------------------------------------


class TestSSEGovernanceDeny:
    @pytest.mark.asyncio
    async def test_deny_all_returns_access_denied(self, sse_server):
        config = _sse_config(sse_server)
        pipeline, _ = _build_pipeline(policy=_deny_all_policy())
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            result = await proxy._call_tool("test-sse__echo", {"text": "should not reach"})

        assert "Access denied" in result[0].text

    @pytest.mark.asyncio
    async def test_selective_allow_permits_specific_server(self, sse_server):
        config = _sse_config(sse_server)
        policy = _selective_policy(allowed_servers=["test-sse"])
        pipeline, _ = _build_pipeline(policy=policy, masking_engine=_noop_masking_engine())
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            result = await proxy._call_tool("test-sse__echo", {"text": "yes"})

        assert result[0].text == "yes"


# ---------------------------------------------------------------------------
# Test: PII masking
# ---------------------------------------------------------------------------


class TestSSEMasking:
    @pytest.mark.asyncio
    async def test_pii_in_response_is_masked(self, sse_server):
        config = _sse_config(sse_server)
        pipeline, _ = _build_pipeline(
            policy=_allow_all_policy(), masking_engine=_pii_masking_engine()
        )
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            result = await proxy._call_tool("test-sse__get_secret_data", {})

        response_text = result[0].text
        assert "John Smith" not in response_text
        assert "john.smith@example.com" not in response_text

    @pytest.mark.asyncio
    async def test_pii_in_arguments_is_masked(self, sse_server):
        config = _sse_config(sse_server)
        pipeline, _ = _build_pipeline(
            policy=_allow_all_policy(), masking_engine=_pii_masking_engine()
        )
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            result = await proxy._call_tool(
                "test-sse__echo", {"text": "Contact John Smith at john.smith@example.com"}
            )

        response_text = result[0].text
        assert "John Smith" not in response_text


# ---------------------------------------------------------------------------
# Test: Audit trail
# ---------------------------------------------------------------------------


class TestSSEAuditTrail:
    @pytest.mark.asyncio
    async def test_audit_event_has_transport_sse(self, sse_server):
        config = _sse_config(sse_server)
        pipeline, audit_hook = _build_pipeline(
            policy=_allow_all_policy(), masking_engine=_noop_masking_engine()
        )
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)
            await proxy._call_tool("test-sse__echo", {"text": "audit test"})

        tool_events = [
            e for e in audit_hook.events if e.event_type == AuditEventType.TOOL_INVOCATION
        ]
        assert len(tool_events) >= 1
        assert tool_events[0].transport == "sse"


# ---------------------------------------------------------------------------
# Test: Session reuse
# ---------------------------------------------------------------------------


class TestSSESessionReuse:
    @pytest.mark.asyncio
    async def test_multiple_calls_on_same_session(self, sse_server):
        config = _sse_config(sse_server)
        pipeline, _ = _build_pipeline(
            policy=_allow_all_policy(), masking_engine=_noop_masking_engine()
        )
        async with ServerManager([config]) as mgr:
            proxy = ProxyServer(mgr, pipeline=pipeline)

            r1 = await proxy._call_tool("test-sse__echo", {"text": "first"})
            r2 = await proxy._call_tool("test-sse__reverse", {"text": "second"})
            r3 = await proxy._call_tool("test-sse__greet", {"name": "Bob"})

        assert r1[0].text == "first"
        assert r2[0].text == "dnoces"
        assert r3[0].text == "Hello, Bob!"
