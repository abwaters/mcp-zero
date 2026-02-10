"""Tests for governance error hierarchy."""

from mcp_zero.governance.errors import (
    GovernanceError,
    PolicyFileError,
    PolicyReferenceError,
    PolicyValidationError,
)


class TestGovernanceError:
    def test_is_exception(self):
        assert issubclass(GovernanceError, Exception)

    def test_message(self):
        err = GovernanceError("something broke")
        assert str(err) == "something broke"


class TestPolicyFileError:
    def test_inherits_governance_error(self):
        assert issubclass(PolicyFileError, GovernanceError)

    def test_file_path_attr(self):
        err = PolicyFileError("not found", file_path="/tmp/bad.yaml")
        assert err.file_path == "/tmp/bad.yaml"
        assert str(err) == "not found"

    def test_file_path_default(self):
        err = PolicyFileError("oops")
        assert err.file_path == ""

    def test_file_path_keyword_only(self):
        """file_path must be passed as keyword argument."""
        try:
            PolicyFileError("msg", "/tmp/x.yaml")  # type: ignore[misc]
            assert False, "Should have raised TypeError"
        except TypeError:
            pass


class TestPolicyValidationError:
    def test_inherits_governance_error(self):
        assert issubclass(PolicyValidationError, GovernanceError)

    def test_field_attr(self):
        err = PolicyValidationError("bad version", field="version")
        assert err.field == "version"
        assert str(err) == "bad version"

    def test_field_default(self):
        err = PolicyValidationError("generic")
        assert err.field == ""


class TestPolicyReferenceError:
    def test_inherits_validation_error(self):
        assert issubclass(PolicyReferenceError, PolicyValidationError)

    def test_inherits_governance_error(self):
        assert issubclass(PolicyReferenceError, GovernanceError)

    def test_attrs(self):
        err = PolicyReferenceError(
            "unknown server 'x'", field="policies.rule1.mcp_servers", reference="x"
        )
        assert err.field == "policies.rule1.mcp_servers"
        assert err.reference == "x"
        assert str(err) == "unknown server 'x'"

    def test_defaults(self):
        err = PolicyReferenceError("msg")
        assert err.field == ""
        assert err.reference == ""
