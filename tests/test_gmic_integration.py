"""End-to-end regressions for the G'MIC integration.

Most tests run a real ``#@gui`` filter from the cached G'MIC standard library
through :class:`GraphExecutor`, so a wrong argument list fails loudly instead
of silently shifting the filter's parameters.
"""

import os
import shutil

import pytest
from PIL import Image, ImageChops

from gmic.cli import GmicCLI
from gmic.parser import GmicFilterParser
from gmic.stdlib import gmic_version, stdlib_cache_path, CACHE_COMMUNITY
from nodes import FilterNode, InputNode, NodeGraph, OutputNode
from processing.graph_executor import GraphExecutor

pytestmark = pytest.mark.skipif(shutil.which("gmic") is None,
                                reason="gmic not installed")


@pytest.fixture(scope="session")
def stdlib_filters():
    """Filters parsed from the cached main and community standard libraries."""
    cache = stdlib_cache_path(gmic_version())
    if not cache.is_file():
        pytest.skip(f"G'MIC stdlib cache missing ({cache})")
    texts = [cache.read_text(encoding="utf-8", errors="replace")]
    if CACHE_COMMUNITY.is_file():
        texts.append(CACHE_COMMUNITY.read_text(encoding="utf-8", errors="replace"))
    parser = GmicFilterParser()
    filters = {}
    for text in texts:
        for filter_def in parser.parse_gui(text):
            filters.setdefault(filter_def.name, filter_def)
    return filters


@pytest.fixture
def gmic_image(tmp_path):
    path = tmp_path / "input.png"
    Image.new("RGB", (200, 200), (90, 120, 60)).save(str(path))
    return str(path)


def run_filter(image_path, filter_def, timeout=60, params=None, reverse_edges=False):
    if isinstance(image_path, str):
        image_path = [image_path]
    graph = NodeGraph()
    sources = []
    for index, path in enumerate(image_path):
        source = InputNode(f"in{index}")
        source.file_path = path
        graph.add_node(source)
        sources.append(source)
    node = FilterNode("flt", filter_def)
    for name, value in (params or {}).items():
        node.set_param(name, value)
    graph.add_node(node)
    output = OutputNode("out")
    graph.add_node(output)
    ports = ["image"]
    ports.extend(f"image_{index + 1}"
                 for index in range(1, filter_def.image_input_count))
    pairs = list(zip(sources, ports))
    if reverse_edges:
        pairs.reverse()
    for source, port in pairs:
        graph.add_edge(source.id, "image", node.id, port)
    graph.add_edge(node.id, "image", output.id, "image")

    executor = GraphExecutor(GmicCLI(), None)
    return executor.execute(graph, output_format="png", timeout=timeout)


BUTTON_FILTER = """\
#@gui Button Check : btncheck
#@gui : Amount = float(1,0,10)
#@gui : Press Me = button()
#@gui : Scale = float(2,0,10)

btncheck :
  if $#!=3 error "expected 3 arguments, got "$# fi
  blur $1

#@gui _
"""


POINT_FILTER = """\
#@gui Point Check : ptcheck
#@gui : Center = point(50,50,0,1,255,255,255,200,10)
#@gui : Zoom = float(0.75,0,1)

#@gui _
"""


class TestPointParameter:
    def test_only_the_coordinates_are_the_value(self):
        # The trailing arguments are widget options (removable, burst,
        # color, radius), not command arguments.
        params = GmicFilterParser().parse_gui(POINT_FILTER)[0].parameters
        assert params[0].kind == "point"
        assert params[0].default == [50, 50]
        assert [p.kind for p in params] == ["point", "float"]

    def test_point_options_do_not_shift_later_arguments(self, stdlib_filters,
                                                        gmic_image):
        # 'fx_distort_rbf' takes four points followed by three more
        # parameters; extra point arguments made G'MIC reject 'warp'.
        filter_def = stdlib_filters["fx_distort_rbf"]
        points = [p for p in filter_def.parameters if p.kind == "point"]
        assert points and all(len(p.default) == 2 for p in points)

        result = run_filter(gmic_image, filter_def, timeout=120)
        assert result.success, result.error


CONTINUED_FILTER = """\
#@gui Plot [Y=f(X)] : plotcmd, plotcmd_preview
#@gui : F(X) = text{"X*c+10*cos(X+c+u)"}
#@gui : Mode = choice(0,"Nil",
#@gui : "Lines","Splines")
#@gui : Resolution = int(100,2,1024)

plotcmd :
  blur 1

#@gui _
"""


def _parse_gui_params(text):
    gui = "#@gui Check : checkcmd\n" + text + "\ncheckcmd :\n  blur 1\n\n#@gui _\n"
    return GmicFilterParser().parse_gui(gui)[0].parameters


class TestValueParameter:
    def test_multiple_values_are_kept_as_one_argument(self):
        # 'value(25,25)' is a single argument holding two numbers (G'MIC
        # commands bind it to two variables, e.g. 'sx,sy=25,25').
        params = _parse_gui_params(
            '#@gui : Keypoints = value(25,25)\n'
            '#@gui : Mode = value(-1)\n')
        assert params[0].kind == "text"
        assert params[0].is_hidden is True
        assert params[0].default == "25,25"
        assert params[1].default == "-1"

    def test_warp_rbf_runs(self, stdlib_filters, gmic_image):
        # 'fx_warp_rbf' binds 13 keypoints of six numbers each from
        # 'point(...), value(25,25), value(25,25)'; dropping the second
        # number of each value misaligned the binding and G'MIC reported
        # "Unknown command or filename '1-83'".
        filter_def = stdlib_filters["fx_warp_rbf"]
        values = [p.default for p in filter_def.parameters
                  if p.kind == "text" and "," in str(p.default)]
        assert values

        result = run_filter(gmic_image, filter_def, timeout=120)
        assert result.success, result.error


class TestFileParameter:
    def test_filein_and_fileout_are_file_parameters(self):
        params = _parse_gui_params(
            '#@gui : Filename = filein()\n'
            '#@gui : Save As = _fileout("out.png")\n'
            '#@gui : Normalize = bool(1)\n')
        assert [p.kind for p in params] == ["file", "file", "bool"]
        assert params[1].default == "out.png"

    def test_import_data_keeps_its_argument_positions(self, stdlib_filters,
                                                     tmp_path, gmic_image):
        # 'Filename = filein()' was dropped, so 'Normalize' landed in '$1'
        # and G'MIC complained "Undefined argument '$2' (for 1 argument)".
        filter_def = stdlib_filters["fx_import_image"]
        assert [p.kind for p in filter_def.parameters] == ["file", "bool"]

        source = tmp_path / "imported.png"
        Image.new("RGB", (64, 64), (200, 10, 10)).save(str(source))
        result = run_filter(gmic_image, filter_def, timeout=120,
                            params={"Filename": str(source)})
        assert result.success, result.error


class TestParameterSeparators:
    def test_separator_does_not_prefix_the_next_parameter_name(self, stdlib_filters):
        # 'sep = separator(), Preview type = choice(...)' produced parameters
        # named ', Preview type' for every filter that shares a line with a
        # separator.
        names = [p.name for p in stdlib_filters["fx_gamify"].parameters]
        assert "Preview type" in names
        assert not any(name.startswith(",") for name in names)


class TestChoiceLabels:
    def test_quoted_first_choice_is_not_dropped(self, stdlib_filters):
        # 'Tiled Preview = choice(3,"None","2x1",...)' lost the "None" label,
        # shifting every option by one.
        param = next(p for p in stdlib_filters["fx_make_seamless"].parameters
                     if p.name == "Tiled Preview")
        assert param.choices[0] == "None"
        assert param.default == 3


class TestGuiLineJoining:
    def test_equals_sign_in_filter_name_is_not_a_parameter(self):
        # 'Plot [Y=f(X)]' used to absorb the parameter lines into the
        # command because its name contains '='.
        filter_def = GmicFilterParser().parse_gui(CONTINUED_FILTER)[0]
        assert filter_def.gmic_command == "plotcmd"
        assert [p.name for p in filter_def.parameters] == [
            "F(X)", "Mode", "Resolution"]

    def test_parameter_definition_continues_on_the_next_line(self):
        params = GmicFilterParser().parse_gui(CONTINUED_FILTER)[0].parameters
        assert params[1].choices == ["Nil", "Lines", "Splines"]

    def test_equation_plot_filter_runs(self, stdlib_filters, gmic_image):
        # The command used to be "fx_equation_plot, fx_equation_plot
        # Description = note{...", so G'MIC got one argument instead of
        # seven ("Undefined argument '$4' ... (for 1 argument specified)").
        filter_def = stdlib_filters["fx_equation_plot"]
        assert filter_def.gmic_command == "fx_equation_plot"
        assert len(filter_def.parameters) == 7

        result = run_filter(gmic_image, filter_def, timeout=120)
        assert result.success, result.error


class TestMultiImageOutput:
    def test_first_output_image_is_kept_when_gmic_numbers_them(
            self, stdlib_filters, gmic_image):
        # 'fx_ball' returns several layers, which G'MIC writes as
        # out_000000.png, out_000001.png, ... while the pre-created output
        # file stays empty (the run used to "succeed" with a 0-byte image).
        filter_def = stdlib_filters["fx_ball"]
        result = run_filter(gmic_image, filter_def, timeout=120)
        assert result.success, result.error
        assert os.path.getsize(result.output_path) > 0
        assert Image.open(result.output_path).size == (200, 200)


class TestMultiInput:
    @staticmethod
    def _two_images(tmp_path):
        first = tmp_path / "first.png"
        second = tmp_path / "second.png"
        Image.new("RGB", (200, 200), (200, 30, 30)).save(str(first))
        Image.new("RGB", (200, 200), (30, 30, 200)).save(str(second))
        return first, second

    def test_two_layer_filter_renders(self, stdlib_filters, tmp_path):
        # 'fx_blend' declares two image inputs with ': *' and blends them.
        filter_def = stdlib_filters["fx_blend"]
        assert filter_def.image_input_count == 2
        first, second = self._two_images(tmp_path)

        result = run_filter([str(first), str(second)], filter_def, timeout=120)
        assert result.success, result.error
        assert Image.open(result.output_path).size == (200, 200)

    def test_inputs_are_passed_in_port_order(self, stdlib_filters, tmp_path,
                                             monkeypatch):
        # Feeding the ports out of order must not swap the layers.
        filter_def = stdlib_filters["fx_blend"]
        first, second = self._two_images(tmp_path)
        seen = []
        real = GmicCLI.run_pipeline

        def recording(self, input_paths, commands, output_path=None,
                      timeout=120, script_command=None):
            seen.append(list(input_paths))
            return real(self, input_paths, commands, output_path, timeout,
                        script_command)

        monkeypatch.setattr(GmicCLI, "run_pipeline", recording)
        result = run_filter([str(first), str(second)], filter_def,
                            timeout=120, reverse_edges=True)

        assert result.success, result.error
        assert seen and seen[0] == [str(first), str(second)]

    def test_single_input_filter_still_gets_one_layer(self, stdlib_filters,
                                                      gmic_image, monkeypatch):
        filter_def = stdlib_filters["fx_pills"]
        seen = []
        real = GmicCLI.run_pipeline

        def recording(self, input_paths, commands, output_path=None,
                      timeout=120, script_command=None):
            seen.append(list(input_paths))
            return real(self, input_paths, commands, output_path, timeout,
                        script_command)

        monkeypatch.setattr(GmicCLI, "run_pipeline", recording)
        result = run_filter(gmic_image, filter_def, timeout=120)

        assert result.success, result.error
        assert seen == [[gmic_image]]


class TestTextParameter:
    def test_filter_that_executes_its_text_parameter(self, stdlib_filters,
                                                     gmic_image):
        # 'iain_fast_formula' runs its text parameter as G'MIC code
        # ("apply_gamma 2.2").  The CLI cannot pass that space, so the
        # command runs from a temporary command file instead.
        filter_def = stdlib_filters.get("iain_fast_formula")
        if filter_def is None:
            pytest.skip("community stdlib cache missing")
        assert " " in filter_def.parameters[0].default

        result = run_filter(gmic_image, filter_def, timeout=120)

        assert result.success, result.error
        rendered = Image.open(result.output_path).convert("RGB")
        original = Image.open(gmic_image).convert("RGB")
        assert rendered.size == original.size
        assert ImageChops.difference(rendered, original).getbbox() is not None

    def test_command_list_text_parameter(self, stdlib_filters, gmic_image):
        # 'samj_Filtres_Sur_Tuiles' passes a whole command list ('shift 2,2,
        # 0,0,0 mirror y') as one parameter.
        filter_def = stdlib_filters.get("samj_Filtres_Sur_Tuiles")
        if filter_def is None:
            pytest.skip("community stdlib cache missing")

        result = run_filter(gmic_image, filter_def, timeout=120)
        assert result.success, result.error

    def test_code_parameter_with_escaped_newlines(self, stdlib_filters,
                                                  gmic_image):
        # 'Custom Code' defaults to a multi-line program written with '\n'
        # escapes; G'MIC-Qt decodes them (cimg::strunescape), so must we.
        filter_def = stdlib_filters["fx_custom_code"]
        code = next(p for p in filter_def.parameters if p.name == "Code")
        assert "\n" in code.default

        result = run_filter(gmic_image, filter_def, timeout=120)
        assert result.success, result.error

    def test_whitespace_in_a_text_value_is_not_stripped(self, stdlib_filters):
        # 'Ascii Art' defaults its dictionary to ' .oO0': the leading space
        # is one of the characters to draw with, and stripping it changed
        # the generated art.
        from gmic.pipeline import _serialize_param
        filter_def = stdlib_filters["fx_asciiart"]
        dictionary = next(p for p in filter_def.parameters
                          if p.name == "Custom Dictionary")
        assert dictionary.default.startswith(" ")
        assert _serialize_param(dictionary.default, dictionary) == '"\\040.oO0"'

    def test_newlines_do_not_break_the_command_line(self):
        from gmic.pipeline import _serialize_param
        from models.filter import ParamDef
        param = ParamDef("x", "X", kind="text", default="")
        serialized = _serialize_param("first\nsecond", param)
        assert "\n" not in serialized
        assert serialized == '"first\\012second"'


class TestButtonParameter:
    def test_button_is_parsed_as_a_boolean(self):
        params = GmicFilterParser().parse_gui(BUTTON_FILTER)[0].parameters
        assert [p.kind for p in params] == ["float", "bool", "float"]
        assert params[1].default is False

    def test_button_keeps_following_arguments_in_place(self, stdlib_filters,
                                                       gmic_image):
        # 'fx_random_pattern' has a button after its Seed parameter; losing
        # the button's argument makes G'MIC read '$9' as a command name
        # ("Unknown command or filename '5-9'").
        filter_def = stdlib_filters["fx_random_pattern"]
        kinds = [p.kind for p in filter_def.parameters]
        assert kinds[3] == "bool"

        result = run_filter(gmic_image, filter_def, timeout=120)
        assert result.success, result.error
