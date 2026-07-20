from gmic.parser import (
    _strip_html, _strip_name, _find_matching_close, _split_args,
    _parse_param_value, _parse_param_def,
    _join_continuations, _munge_gui_command, GmicFilterParser,
)


class TestStripHtml:
    def test_no_html(self):
        assert _strip_html("hello world") == "hello world"

    def test_strips_tags(self):
        assert _strip_html("<b>bold</b>") == "bold"

    def test_strips_nested(self):
        assert _strip_html("<div><span>text</span></div>") == "text"

    def test_empty_result(self):
        assert _strip_html("<tag></tag>") == ""


class TestStripName:
    def test_no_entities(self):
        assert _strip_name("hello") == "hello"

    def test_unescape_html(self):
        assert _strip_name("a &amp; b") == "a & b"

    def test_combined(self):
        assert _strip_name("<b>hello &amp; world</b>") == "hello & world"


class TestFindMatchingClose:
    def test_simple(self):
        result = _find_matching_close("(a(b)c)", 0)
        assert result == 6

    def test_no_match_returns_minus_one(self):
        result = _find_matching_close("(a(b)", 0)
        assert result == -1


class TestSplitArgs:
    def test_simple(self):
        assert _split_args("a,b,c") == ["a", "b", "c"]

    def test_nested_parens(self):
        assert _split_args("a,(b,c),d") == ["a", "(b,c)", "d"]

    def test_quoted_string(self):
        result = _split_args('a,"b,c",d')
        assert result == ["a", '"b,c"', "d"]

    def test_empty_string(self):
        assert _split_args("") == []


class TestParseParamValue:
    def test_int(self):
        assert _parse_param_value("42") == 42

    def test_float(self):
        assert _parse_param_value("3.14") == 3.14

    def test_quoted_string(self):
        assert _parse_param_value('"hello"') == "hello"

    def test_none(self):
        assert _parse_param_value("None") is None

    def test_negative_int(self):
        assert _parse_param_value("-5") == -5


class TestParseParamDef:
    def test_returns_none_for_empty(self):
        assert _parse_param_def("") is None

    def test_returns_none_for_non_gui_line(self):
        result = _parse_param_def("some random text")
        assert result is None


class TestJoinContinuations:
    def test_no_continuations(self):
        lines = ["line1", "line2"]
        assert _join_continuations(lines) == ["line1", "line2"]

    def test_backslash_continuation(self):
        lines = ["line1 \\", "continuation", "line2"]
        result = _join_continuations(lines)
        assert len(result) == 2


class TestMungeGuiCommand:
    def test_no_preview(self):
        assert _munge_gui_command("test") == "test"

    def test_strips_preview_suffix(self):
        result = _munge_gui_command("test, preview(2) *")
        assert result == "test"


class TestGmicFilterParser:
    def test_builtin_filters_not_empty(self):
        parser = GmicFilterParser()
        filters = parser.get_builtin_filters()
        assert len(filters) > 0

    def test_builtin_filters_have_required_attrs(self):
        parser = GmicFilterParser()
        filters = parser.get_builtin_filters()
        for fd in filters:
            assert fd.name
            assert fd.display_name
            assert fd.category
            assert fd.engine == "gmic"

    def test_builtin_parse_gui_empty(self):
        parser = GmicFilterParser()
        result = parser.parse_gui("")
        assert result == parser.get_builtin_filters()
