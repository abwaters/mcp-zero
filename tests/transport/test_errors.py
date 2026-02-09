"""Tests for transport error hierarchy."""

from mcp_zero.transport.errors import (
    ProcessError,
    SessionError,
    TransportClosedError,
    TransportConnectionError,
    TransportError,
    TransportTimeoutError,
)


class TestErrorHierarchy:
    def test_all_inherit_from_transport_error(self):
        assert issubclass(TransportConnectionError, TransportError)
        assert issubclass(TransportTimeoutError, TransportError)
        assert issubclass(SessionError, TransportError)
        assert issubclass(TransportClosedError, TransportError)
        assert issubclass(ProcessError, TransportError)

    def test_transport_error_is_exception(self):
        assert issubclass(TransportError, Exception)

    def test_server_name_attribute(self):
        err = TransportError("something failed", server_name="test-server")
        assert err.server_name == "test-server"
        assert str(err) == "something failed"

    def test_server_name_default(self):
        err = TransportError("fail")
        assert err.server_name == ""

    def test_connection_error_server_name(self):
        err = TransportConnectionError("refused", server_name="remote")
        assert err.server_name == "remote"

    def test_process_error_server_name(self):
        err = ProcessError("not found", server_name="local-tool")
        assert err.server_name == "local-tool"

    def test_correlation_id_default(self):
        err = TransportError("fail")
        assert err.correlation_id == ""

    def test_correlation_id_stored(self):
        err = TransportError("fail", correlation_id="abc-123")
        assert err.correlation_id == "abc-123"

    def test_subclasses_accept_correlation_id(self):
        for cls in (
            TransportConnectionError,
            TransportTimeoutError,
            SessionError,
            TransportClosedError,
            ProcessError,
        ):
            err = cls("msg", server_name="s", correlation_id="cid-1")
            assert err.correlation_id == "cid-1"
            assert err.server_name == "s"

    def test_catchable_as_base(self):
        try:
            raise TransportConnectionError("refused", server_name="x")
        except TransportError as e:
            assert e.server_name == "x"
