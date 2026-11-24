import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gio", "2.0")

from models.filter import FilterDef, ParamDef
from nodes import NodeGraph, InputNode, OutputNode, FilterNode

import pytest
from PIL import Image, ImageDraw


@pytest.fixture(scope="session")
def filter_def():
    return FilterDef(
        name="test_filter",
        display_name="Test Filter",
        category=["Test"],
        description="A test filter",
        parameters=[
            ParamDef("strength", "Strength", kind="float", default=0.5, min_val=0, max_val=1),
            ParamDef("invert", "Invert", kind="bool", default=False),
        ],
        gmic_command="test_command",
        engine="gmic",
        image_input_count=1,
    )


@pytest.fixture
def test_image(tmp_path):
    path = tmp_path / "input.png"
    img = Image.new("RGB", (200, 200))
    for x in range(200):
        for y in range(200):
            r = x * 255 // 200
            g = y * 255 // 200
            b = 128
            img.putpixel((x, y), (r, g, b))
    draw = ImageDraw.Draw(img)
    draw.ellipse([50, 50, 150, 150], outline=(255, 255, 255), width=3)
    draw.rectangle([20, 20, 80, 80], outline=(0, 255, 0), width=2)
    draw.line([0, 0, 200, 200], fill=(255, 0, 0), width=2)
    img.save(str(path))
    return str(path)


@pytest.fixture
def empty_graph():
    return NodeGraph()


@pytest.fixture
def simple_graph(empty_graph):
    graph = empty_graph
    n1 = InputNode("n1")
    n1.file_path = "/path/to/img.png"
    graph.add_node(n1)
    n2 = OutputNode("n2")
    graph.add_node(n2)
    graph.add_edge("n1", "image", "n2", "image")
    return graph


@pytest.fixture
def graph_with_filter(filter_def, test_image):
    graph = NodeGraph()
    inp = InputNode("in")
    inp.file_path = test_image
    graph.add_node(inp)
    flt = FilterNode("flt", filter_def)
    graph.add_node(flt)
    out = OutputNode("out")
    graph.add_node(out)
    graph.add_edge("in", "image", "flt", "image")
    graph.add_edge("flt", "image", "out", "image")
    return graph
