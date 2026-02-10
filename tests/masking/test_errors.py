"""Tests for masking error hierarchy."""

from mcp_zero.masking.errors import (
    MaskingConfigError,
    MaskingEngineError,
    MaskingError,
)


class TestMaskingError:
    def test_is_exception(self):
        assert issubclass(MaskingError, Exception)

    def test_message(self):
        err = MaskingError("something broke")
        assert str(err) == "something broke"


class TestMaskingEngineError:
    def test_inherits_masking_error(self):
        assert issubclass(MaskingEngineError, MaskingError)

    def test_engine_attr(self):
        err = MaskingEngineError("init failed", engine="presidio")
        assert err.engine == "presidio"
        assert str(err) == "init failed"

    def test_engine_default(self):
        err = MaskingEngineError("oops")
        assert err.engine == ""

    def test_engine_keyword_only(self):
        try:
            MaskingEngineError("msg", "presidio")  # type: ignore[misc]
            assert False, "Should have raised TypeError"
        except TypeError:
            pass


class TestMaskingConfigError:
    def test_inherits_masking_error(self):
        assert issubclass(MaskingConfigError, MaskingError)

    def test_field_attr(self):
        err = MaskingConfigError("bad entities", field="masking.presidio.entities")
        assert err.field == "masking.presidio.entities"
        assert str(err) == "bad entities"

    def test_field_default(self):
        err = MaskingConfigError("generic")
        assert err.field == ""

    def test_field_keyword_only(self):
        try:
            MaskingConfigError("msg", "field_name")  # type: ignore[misc]
            assert False, "Should have raised TypeError"
        except TypeError:
            pass
