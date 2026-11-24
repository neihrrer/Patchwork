import re
import shutil
import subprocess
import textwrap

import pytest

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


FOLDER_TREE = textwrap.dedent("""\
    #@gui ____<b>Artistic</b>
    #@gui Filter A : cmd_a
    #@gui ____<b>Various</b>
    #@gui Filter B : cmd_b
    #@gui _<i>Nature</i>
    #@gui Filter C : cmd_c
    #@gui Category Only
    #@gui Filter D : cmd_d

    cmd_a : blur 1
    cmd_b : blur 2
    cmd_c : blur 3
    cmd_d : blur 4
    #@gui _
    """)


class TestFolderNesting:
    """'#@gui' folder names are prefixed by N underscores, i.e. go up N levels."""

    def test_leading_underscores_pop_that_many_levels(self):
        filters = {f.name: f for f in GmicFilterParser().parse_gui(FOLDER_TREE)}
        assert filters["cmd_a"].category == ["Artistic"]
        assert filters["cmd_b"].category == ["Various"]
        assert filters["cmd_c"].category == ["Nature"]
        assert filters["cmd_d"].category == ["Nature", "Category Only"]

    @pytest.mark.skipif(shutil.which("gmic") is None, reason="gmic not installed")
    def test_matches_gmic_parse_gui(self, tmp_path):
        tree_file = tmp_path / "tree.gmic"
        tree_file.write_text(FOLDER_TREE)
        proc = subprocess.run(
            ["gmic", "-input_text", str(tree_file), "-parse_gui", "print"],
            capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL,
        )
        # Lines look like '  > [#0] Artistic/Filter A'.
        expected = {}
        text = re.sub(r"\x1b\[[0-9;]*m", "", proc.stderr).replace("\r", "\n")
        for line in text.splitlines():
            marker = line.find("[#")
            if ">" not in line or marker < 0:
                continue
            path = line[line.find("]", marker) + 2:].strip()
            expected[path.rsplit("/", 1)[-1]] = path.split("/")[:-1]

        filters = GmicFilterParser().parse_gui(FOLDER_TREE)
        assert len(expected) == len(filters)
        for fd in filters:
            assert expected[fd.display_name] == fd.category


def _parse_gui_params(text: str):
    gui = "#@gui Check : checkcmd\n" + text + "\ncheckcmd :\n  blur 1\n\n#@gui _\n"
    return GmicFilterParser().parse_gui(gui)[0].parameters


class TestParameterSeparators:
    def test_separator_before_a_parameter_does_not_leak_into_its_name(self):
        # 'sep = separator(), Preview type = choice(...)' used to name the
        # parameter ', Preview type'.
        params = _parse_gui_params(
            '#@gui : sep = separator(), Preview type = choice("Full","Half")\n'
            '#@gui : Amount = float(1,0,2)\n')
        assert [p.name for p in params] == ["Preview type", "Amount"]
        assert params[0].kind == "choice"

    def test_note_before_a_parameter_does_not_leak_into_its_name(self):
        params = _parse_gui_params(
            '#@gui : note = note("hello"), Angle = float(0,0,360)\n')
        assert [p.name for p in params] == ["Angle"]


class TestChoiceParameter:
    def test_quoted_first_argument_is_the_first_choice(self):
        # G'MIC-Qt keeps the first item as a choice when it is not an index
        # ('choice("X","Y","XY")' has three choices, defaulting to 'X').
        (param,) = _parse_gui_params(
            '#@gui : Mirror = choice("None","X-Axis","Y-Axis","XY-Axes")\n')
        assert param.choices == ["None", "X-Axis", "Y-Axis", "XY-Axes"]
        assert param.default == 0

    def test_numeric_first_argument_is_the_default_index(self):
        (param,) = _parse_gui_params(
            '#@gui : Mode = choice(2,"Gray","RGB","CMYK")\n')
        assert param.choices == ["Gray", "RGB", "CMYK"]
        assert param.default == 2

    def test_quoted_none_is_a_literal_label(self):
        assert _parse_param_value('"None"') == "None"
        assert _parse_param_value("'none'") == "none"
        assert _parse_param_value("None") is None


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
