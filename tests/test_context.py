"""Tests for RequestContext."""

import re

import pytest

from mcp_zero.context import RequestContext

UUID4_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


class TestRequestContext:
    def test_correlation_id_is_uuid4(self):
        ctx = RequestContext()
        assert UUID4_RE.match(ctx.correlation_id)

    def test_trace_id_defaults_to_correlation_id(self):
        ctx = RequestContext()
        assert ctx.trace_id == ctx.correlation_id

    def test_explicit_trace_id_preserved(self):
        ctx = RequestContext(trace_id="my-trace")
        assert ctx.trace_id == "my-trace"
        assert ctx.trace_id != ctx.correlation_id

    def test_frozen_immutability(self):
        ctx = RequestContext()
        with pytest.raises(AttributeError):
            ctx.correlation_id = "new"  # type: ignore[misc]
        with pytest.raises(AttributeError):
            ctx.trace_id = "new"  # type: ignore[misc]

    def test_unique_ids_across_instances(self):
        a = RequestContext()
        b = RequestContext()
        assert a.correlation_id != b.correlation_id

    def test_child_context_new_correlation_id(self):
        parent = RequestContext()
        child = parent.child_context()
        assert child.correlation_id != parent.correlation_id
        assert UUID4_RE.match(child.correlation_id)

    def test_child_context_inherits_trace_id(self):
        parent = RequestContext()
        child = parent.child_context()
        assert child.trace_id == parent.trace_id

    def test_child_context_inherits_user_identity(self):
        parent = RequestContext(user_id="u1", user_email="u@x.com", user_groups=["admin"])
        child = parent.child_context()
        assert child.user_id == "u1"
        assert child.user_email == "u@x.com"
        assert child.user_groups == ["admin"]

    def test_child_context_groups_are_copied(self):
        parent = RequestContext(user_groups=["a", "b"])
        child = parent.child_context()
        assert child.user_groups is not parent.user_groups
        assert child.user_groups == ["a", "b"]
