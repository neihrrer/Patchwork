"""End-to-end regressions for the G'MIC integration.

Most tests run a real ``#@gui`` filter from the cached G'MIC standard library
through :class:`GraphExecutor`, so a wrong argument list fails loudly instead
of silently shifting the filter's parameters.
"""

import shutil

import pytest
from PIL import Image

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
    Image.new("RGB", (64, 64), (90, 120, 60)).save(str(path))
    return str(path)


def run_filter(image_path, filter_def, timeout=60):
    graph = NodeGraph()
    source = InputNode("in")
    source.file_path = image_path
    graph.add_node(source)
    node = FilterNode("flt", filter_def)
    graph.add_node(node)
    output = OutputNode("out")
    graph.add_node(output)
    graph.add_edge("in", "image", "flt", "image")
    for index in range(1, filter_def.image_input_count):
        graph.add_edge("in", "image", "flt", f"image_{index + 1}")
    graph.add_edge("flt", "image", "out", "image")

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
