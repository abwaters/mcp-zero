"""Tests for pipeline error hierarchy."""

from mcp_zero.pipeline.errors import HookError, PipelineError, ShortCircuitError


class TestErrorHierarchy:
    def test_all_inherit_from_pipeline_error(self):
        assert issubclass(ShortCircuitError, PipelineError)
        assert issubclass(HookError, PipelineError)

    def test_pipeline_error_is_exception(self):
        assert issubclass(PipelineError, Exception)


class TestShortCircuitError:
    def test_reason(self):
        err = ShortCircuitError("policy denied")
        assert err.reason == "policy denied"
        assert str(err) == "policy denied"

    def test_deny_default_false(self):
        err = ShortCircuitError("stopped")
        assert err.deny is False

    def test_deny_true(self):
        err = ShortCircuitError("blocked", deny=True)
        assert err.deny is True
        assert err.reason == "blocked"

    def test_catchable_as_pipeline_error(self):
        try:
            raise ShortCircuitError("halt")
        except PipelineError as e:
            assert isinstance(e, ShortCircuitError)


class TestHookError:
    def test_attributes(self):
        err = HookError("boom", hook_name="AuthHook", hook_point="pre_validation")
        assert err.hook_name == "AuthHook"
        assert err.hook_point == "pre_validation"
        assert str(err) == "boom"

    def test_defaults(self):
        err = HookError("fail")
        assert err.hook_name == ""
        assert err.hook_point == ""

    def test_catchable_as_pipeline_error(self):
        try:
            raise HookError("oops", hook_name="X")
        except PipelineError as e:
            assert isinstance(e, HookError)
