"""Tests for RequestContext."""

import re

import pytest

from mcp_zero.context import RequestContext, UserIdentity

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
        identity = UserIdentity(user_id="u1", email="u@x.com", groups=["admin"])
        parent = RequestContext(identity=identity)
        child = parent.child_context()
        assert child.identity is not None
        assert child.identity.user_id == "u1"
        assert child.identity.email == "u@x.com"
        assert child.identity.groups == ["admin"]

    def test_child_context_identity_is_same_frozen_instance(self):
        identity = UserIdentity(user_id="u1", groups=["a", "b"])
        parent = RequestContext(identity=identity)
        child = parent.child_context()
        # UserIdentity is frozen, so sharing the same instance is safe
        assert child.identity is parent.identity
