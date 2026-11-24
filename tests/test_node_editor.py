"""Canvas affordances for filter image inputs (right-click menu actions).

These need a display: GTK widgets cannot be built in a headless container, so
the module skips there (the node-level API is covered by the node tests).
"""

import shutil

import pytest

from models.filter import FilterDef


def _canvas_available() -> bool:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
    return bool(Gtk.init_check())


pytestmark = pytest.mark.skipif(not _canvas_available(),
                                reason="GTK cannot open a display")


@pytest.fixture
def canvas():
    from nodes import NodeGraph
    from widgets.node_editor import NodeCanvas
    return NodeCanvas(NodeGraph())


@pytest.fixture
def filter_node(canvas):
    from nodes import FilterNode
    from models.filter import ParamDef
    filter_def = FilterDef(
        name="test_filter", display_name="Test Filter", image_input_count=1,
        parameters=[ParamDef("radius", "Radius", kind="float", default=1.0)])
    node = FilterNode("f1", filter_def)
    canvas.add_node(node)
    return node


class TestCanvasImageInputs:
    def test_add_image_input_updates_node_and_widget(self, canvas, filter_node):
        canvas.add_filter_input_port(filter_node)

        assert filter_node.extra_image_ports == 1
        assert filter_node.get_input_port("image_2") is not None
        widget = canvas._node_widgets["f1"]
        assert "image_2" in widget._input_port_widgets
        assert widget._logical_h == int(filter_node.height)

    def test_remove_image_input_drops_connected_wire(self, canvas, filter_node):
        from nodes import InputNode
        canvas.add_filter_input_port(filter_node)
        source = InputNode("in")
        source.file_path = "/tmp/layer.png"
        canvas.add_node(source)
        canvas._graph.add_edge("in", "image", "f1", "image_2")
        assert len(canvas._graph.edges) == 1

        canvas.remove_filter_input_port(filter_node)

        assert filter_node.extra_image_ports == 0
        assert filter_node.get_input_port("image_2") is None
        assert canvas._graph.edges == []
        assert "image_2" not in canvas._node_widgets["f1"]._input_port_widgets

    def test_remove_without_extra_ports_does_nothing(self, canvas, filter_node):
        canvas.remove_filter_input_port(filter_node)
        assert filter_node.extra_image_ports == 0
        assert filter_node.get_input_port("image") is not None
