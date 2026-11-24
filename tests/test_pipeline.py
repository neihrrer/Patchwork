from models.filter import ParamDef
from gmic.pipeline import _serialize_param, _gmic_escape


class TestGmicEscape:
    def test_no_special_chars_unchanged(self):
        assert _gmic_escape("plain") == "plain"

    def test_space_becomes_octal(self):
        # The gmic CLI wraps any argument containing a space in quotes, which
        # would swallow the surrounding comma-separated argument list.
        assert _gmic_escape("a b") == "a\\040b"

    def test_leading_space_becomes_octal(self):
        assert _gmic_escape(" .oO0") == "\\040.oO0"

    def test_double_quote_is_escaped(self):
        assert _gmic_escape('a"b') == 'a\\"b'

    def test_backslash_is_escaped(self):
        assert _gmic_escape("a\\b") == "a\\\\b"

    def test_comma_is_escaped(self):
        assert _gmic_escape("0,1,0") == "0\\,1\\,0"

    def test_newline_becomes_octal(self):
        # A raw newline would split the command line into two lines.
        assert _gmic_escape("a\nb") == "a\\012b"

    def test_combined(self):
        assert _gmic_escape('a,b"c\\d') == 'a\\,b\\"c\\\\d'


class TestSerializeParam:
    def test_none_no_default(self):
        assert _serialize_param(None) == "0"

    def test_none_with_default(self):
        p = ParamDef("x", "X", kind="int", default=42)
        assert _serialize_param(None, p) == "42"

    def test_none_with_string_default_is_escaped(self):
        p = ParamDef("x", "X", kind="text", default=" .oO0")
        assert _serialize_param(None, p) == '"\\040.oO0"'

    def test_empty_string(self):
        assert _serialize_param("") == "0"

    def test_empty_string_with_default_is_escaped(self):
        p = ParamDef("x", "X", kind="text", default=" .oO0")
        assert _serialize_param("", p) == '"\\040.oO0"'

    def test_bool_true(self):
        assert _serialize_param(True) == "1"

    def test_bool_false(self):
        assert _serialize_param(False) == "0"

    def test_int(self):
        assert _serialize_param(42) == "42"

    def test_float(self):
        assert _serialize_param(3.14) == "3.14"

    def test_int_below_min_clamped(self):
        p = ParamDef("x", "X", kind="int", default=16, min_val=8, max_val=103)
        assert _serialize_param(0, p) == "8"

    def test_int_above_max_clamped(self):
        p = ParamDef("x", "X", kind="int", default=16, min_val=8, max_val=103)
        assert _serialize_param(200, p) == "103"

    def test_float_below_min_clamped(self):
        p = ParamDef("x", "X", kind="float", default=2.0, min_val=1.0, max_val=10.0)
        assert _serialize_param(0.0, p) == "1.0"

    def test_int_in_range_unchanged(self):
        p = ParamDef("x", "X", kind="int", default=16, min_val=8, max_val=103)
        assert _serialize_param(16, p) == "16"

    def test_numeric_without_range_unchanged(self):
        assert _serialize_param(42) == "42"

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

    def test_text_value_with_space_escaped_and_quoted(self):
        p = ParamDef("x", "X", kind="text", default=" .oO0")
        assert _serialize_param("a b", p) == '"a\\040b"'

    def test_text_value_with_quote_escaped(self):
        p = ParamDef("x", "X", kind="text", default=" .oO0")
        assert _serialize_param('a"b', p) == '"a\\"b"'

    def test_text_value_with_commas_escaped(self):
        p = ParamDef("x", "X", kind="text", default=" .oO0")
        assert _serialize_param("0,1,0", p) == '"0\\,1\\,0"'

    def test_text_value_leading_whitespace_kept(self):
        p = ParamDef("x", "X", kind="text", default=" .oO0")
        assert _serialize_param(" .oO0", p) == '"\\040.oO0"'

    def test_text_value_trailing_whitespace_kept(self):
        p = ParamDef("x", "X", kind="text", default=" .oO0")
        assert _serialize_param("abc  ", p) == '"abc\\040\\040"'

    def test_text_value_no_special_chars_quoted(self):
        p = ParamDef("x", "X", kind="text", default=" .oO0")
        assert _serialize_param("hello", p) == '"hello"'
