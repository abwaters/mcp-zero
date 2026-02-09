"""Tests for proxy error hierarchy."""

from mcp_zero.proxy.errors import ProxyError, ProxyTimeoutError, RoutingError, UpstreamError


class TestProxyError:
    def test_base_error(self):
        err = ProxyError("something broke")
        assert str(err) == "something broke"
        assert err.server_name == ""
        assert err.correlation_id == ""

    def test_base_error_with_attrs(self):
        err = ProxyError("fail", server_name="srv", correlation_id="cid-1")
        assert err.server_name == "srv"
        assert err.correlation_id == "cid-1"

    def test_is_exception(self):
        assert issubclass(ProxyError, Exception)


class TestRoutingError:
    def test_inherits_proxy_error(self):
        assert issubclass(RoutingError, ProxyError)

    def test_carries_server_name(self):
        err = RoutingError("no route", server_name="unknown")
        assert err.server_name == "unknown"
        assert str(err) == "no route"


class TestUpstreamError:
    def test_inherits_proxy_error(self):
        assert issubclass(UpstreamError, ProxyError)

    def test_carries_correlation_id(self):
        err = UpstreamError("500", correlation_id="c-1", server_name="backend")
        assert err.correlation_id == "c-1"
        assert err.server_name == "backend"


class TestProxyTimeoutError:
    def test_inherits_proxy_error(self):
        assert issubclass(ProxyTimeoutError, ProxyError)

    def test_message_and_attrs(self):
        err = ProxyTimeoutError("timed out after 30s", server_name="slow", correlation_id="c-2")
        assert str(err) == "timed out after 30s"
        assert err.server_name == "slow"
        assert err.correlation_id == "c-2"
