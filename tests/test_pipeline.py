from models.filter import ParamDef
from gmic.pipeline import _serialize_param


class TestSerializeParam:
    def test_none_no_default(self):
        assert _serialize_param(None) == "0"

    def test_none_with_default(self):
        p = ParamDef("x", "X", kind="int", default=42)
        assert _serialize_param(None, p) == "42"

    def test_none_with_string_default(self):
        p = ParamDef("x", "X", kind="text", default=" .oO0")
        assert _serialize_param(None, p) == ".oO0"

    def test_empty_string(self):
        assert _serialize_param("") == "0"

    def test_empty_string_with_default(self):
        p = ParamDef("x", "X", kind="text", default=" .oO0")
        assert _serialize_param("", p) == ".oO0"

    def test_bool_true(self):
        assert _serialize_param(True) == "1"

    def test_bool_false(self):
        assert _serialize_param(False) == "0"

    def test_int(self):
        assert _serialize_param(42) == "42"

    def test_float(self):
        assert _serialize_param(3.14) == "3.14"

    def test_list(self):
        assert _serialize_param([255, 0, 0, 255]) == "255,0,0,255"

    def test_string_strips_leading_whitespace(self):
        assert _serialize_param(" .oO0") == ".oO0"

    def test_string_strips_trailing_whitespace(self):
        assert _serialize_param("abc  ") == "abc"

    def test_string_strips_both(self):
        assert _serialize_param("  hello  ") == "hello"

    def test_string_no_whitespace_unchanged(self):
        assert _serialize_param("hello") == "hello"
