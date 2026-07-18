from nodes import (
    InputNode, OutputNode, FilterNode, BlendNode,
    OpacityNode, MaskNode, BrightnessContrastNode, LevelsNode, HSLNode,
    ConstantNode, AddNode, SubtractNode, MultiplyNode, DivideNode,
    CeilNode, FloorNode, RoundNode, SumNode, ProductNode,
    LabelNode, CommentNode,
    PortDirection, PortType,
)
from nodes.node_types import LABEL_COLORS
from models.filter import FilterDef, ParamDef

import pytest


class TestInputNode:
    def test_construction(self):
        n = InputNode("in")
        assert n.id == "in"
        assert n.label == "Image Input"
        assert n.node_type == "input"
        assert len(n.outputs) == 1
        assert n.outputs[0].name == "image"
        assert n.outputs[0].port_type == PortType.IMAGE
        assert n.file_path is None
        assert n.cache_dirty is True

    def test_file_path_updates_label(self):
        n = InputNode("in")
        n.file_path = "/photos/test.png"
        assert n.file_path == "/photos/test.png"
        assert n.label == "test.png"
        assert n.cache_dirty is True

    def test_file_path_clear(self):
        n = InputNode("in")
        n.file_path = "/photos/test.png"
        n.file_path = None
        assert n.file_path is None

    def test_no_inputs(self):
        n = InputNode("in")
        assert len(n.inputs) == 0


class TestOutputNode:
    def test_construction(self):
        n = OutputNode("out")
        assert n.id == "out"
        assert n.node_type == "output"
        assert len(n.inputs) == 1
        assert n.inputs[0].name == "image"
        assert n.inputs[0].port_type == PortType.IMAGE
        assert len(n.outputs) == 0


class TestFilterNode:
    def test_construction(self, filter_def):
        n = FilterNode("flt", filter_def)
        assert n.id == "flt"
        assert n.node_type == "filter"
        assert n.filter_def is filter_def
        assert len(n.outputs) == 1
        assert n.outputs[0].name == "image"
        assert n.outputs[0].port_type == PortType.IMAGE

    def test_ports_from_filter_def(self):
        fd = FilterDef(
            name="test", parameters=[
                ParamDef("radius", "Radius", kind="float", default=5.0),
                ParamDef("threshold", "Threshold", kind="int", default=128),
            ],
            image_input_count=2,
        )
        n = FilterNode("flt", fd)
        input_names = {p.name for p in n.inputs}
        assert "image" in input_names
        assert "image_2" in input_names
        assert "radius" in input_names
        assert "threshold" in input_names

    def test_set_param(self, filter_def):
        n = FilterNode("flt", filter_def)
        n.set_param("strength", 0.8)
        assert n.param_values["strength"] == 0.8
        assert n.cache_dirty is True

    def test_param_values_include_defaults(self, filter_def):
        n = FilterNode("flt", filter_def)
        assert n.param_values.get("strength") == 0.5
        assert n.param_values.get("invert") is False


class TestBlendNode:
    def test_construction(self):
        n = BlendNode("bl", "over")
        assert n.id == "bl"
        assert n.node_type == "blend"
        assert n.mode == "over"
        input_names = {p.name for p in n.inputs}
        assert "base" in input_names
        assert "blend" in input_names
        assert len(n.outputs) == 1

    def test_add_input_port(self):
        n = BlendNode("bl", "over")
        original_count = len(n.inputs)
        n.add_input_port()
        assert len(n.inputs) == original_count + 1
        added = n.inputs[-1]
        assert added.port_type == PortType.IMAGE
        assert added.direction == PortDirection.INPUT

    def test_add_input_port_multiple(self):
        n = BlendNode("bl", "multiply")
        for _ in range(5):
            n.add_input_port()
        image_inputs = [p for p in n.inputs if p.port_type == PortType.IMAGE]
        assert len(image_inputs) >= 7

    def test_default_mode(self):
        n = BlendNode("bl")
        assert n.mode == "over"

    def test_blend_modes_constant(self):
        assert len(BlendNode.BLEND_MODES) > 0
        assert "over" in BlendNode.BLEND_MODES
        assert "multiply" in BlendNode.BLEND_MODES


class TestBrightnessContrastNode:
    def test_construction(self):
        n = BrightnessContrastNode("bc")
        assert n.node_type == "brightness_contrast"
        assert n.brightness == 0.0
        assert n.contrast == 0.0

    def test_image_input(self):
        n = BrightnessContrastNode("bc")
        inputs = {p.name: p for p in n.inputs}
        assert inputs["image"].port_type == PortType.IMAGE

    def test_numeric_inputs(self):
        n = BrightnessContrastNode("bc")
        numeric = [p for p in n.inputs if p.port_type == PortType.NUMERIC]
        assert len(numeric) == 2

    def test_output(self):
        n = BrightnessContrastNode("bc")
        assert n.outputs[0].name == "image"


class TestLevelsNode:
    def test_construction(self):
        n = LevelsNode("lv")
        assert n.node_type == "levels"
        assert n.black_point == 0.0
        assert n.white_point == 100.0
        assert n.gamma == 1.0

    def test_image_input(self):
        n = LevelsNode("lv")
        assert n.inputs[0].name == "image"

    def test_numeric_inputs(self):
        n = LevelsNode("lv")
        numeric = [p for p in n.inputs if p.port_type == PortType.NUMERIC]
        assert len(numeric) == 3


class TestHSLNode:
    def test_construction(self):
        n = HSLNode("hsl")
        assert n.node_type == "hsl"
        assert n.hue == 0.0
        assert n.saturation == 0.0
        assert n.lightness == 0.0

    def test_image_input(self):
        n = HSLNode("hsl")
        assert n.inputs[0].name == "image"

    def test_numeric_inputs(self):
        n = HSLNode("hsl")
        numeric = [p for p in n.inputs if p.port_type == PortType.NUMERIC]
        assert len(numeric) == 3


class TestOpacityNode:
    def test_construction(self):
        n = OpacityNode("op")
        assert n.node_type == "opacity"
        assert n.opacity == 1.0

    def test_image_input(self):
        n = OpacityNode("op")
        assert n.inputs[0].name == "image"
        assert n.inputs[0].port_type == PortType.IMAGE

    def test_numeric_input(self):
        n = OpacityNode("op")
        numeric = [p for p in n.inputs if p.port_type == PortType.NUMERIC]
        assert len(numeric) == 1


class TestMaskNode:
    def test_construction(self):
        n = MaskNode("mask")
        assert n.node_type == "mask"
        assert n.invert is False
        assert n.threshold == 0.5

    def test_two_image_inputs(self):
        n = MaskNode("mask")
        image_ports = [p for p in n.inputs if p.port_type == PortType.IMAGE]
        assert len(image_ports) == 2


class TestConstantNode:
    def test_construction(self):
        n = ConstantNode("cn")
        assert n.node_type == "constant"
        assert n.value == 0.0
        assert len(n.inputs) == 0
        assert len(n.outputs) == 1
        assert n.outputs[0].port_type == PortType.NUMERIC


class TestArithmeticNodes:
    @pytest.mark.parametrize("cls,name", [
        (AddNode, "add"), (SubtractNode, "subtract"),
        (MultiplyNode, "multiply"), (DivideNode, "divide"),
    ])
    def test_two_numeric_inputs_one_output(self, cls, name):
        n = cls("n")
        assert n.node_type == name
        assert len(n.inputs) == 2
        assert all(p.port_type == PortType.NUMERIC for p in n.inputs)
        assert len(n.outputs) == 1
        assert n.outputs[0].port_type == PortType.NUMERIC

    @pytest.mark.parametrize("cls,name", [
        (CeilNode, "ceil"), (FloorNode, "floor"), (RoundNode, "round"),
    ])
    def test_one_numeric_input_one_output(self, cls, name):
        n = cls("n")
        assert n.node_type == name
        assert len(n.inputs) == 1
        assert n.inputs[0].port_type == PortType.NUMERIC
        assert len(n.outputs) == 1
        assert n.outputs[0].port_type == PortType.NUMERIC

    @pytest.mark.parametrize("cls,name", [
        (SumNode, "sum"), (ProductNode, "product"),
    ])
    def test_two_numeric_inputs_one_output_v2(self, cls, name):
        n = cls("n")
        assert n.node_type == name
        assert len(n.inputs) == 2
        assert all(p.port_type == PortType.NUMERIC for p in n.inputs)
        assert len(n.outputs) == 1
        assert n.outputs[0].port_type == PortType.NUMERIC


class TestLabelNode:
    def test_construction(self):
        n = LabelNode("lbl")
        assert n.node_type == "label"
        assert n.text == "Label"
        assert n.color is None

    def test_text_property(self):
        n = LabelNode("lbl")
        n.text = "Hello World"
        assert n.text == "Hello World"

    def test_color_property(self):
        n = LabelNode("lbl")
        n.color = "#ff0"
        assert n.color == "#ff0"


class TestCommentNode:
    def test_construction(self):
        n = CommentNode("cmt")
        assert n.node_type == "comment"
        assert n.text == "Comment"
        assert n.color is None

    def test_text_color(self):
        n = CommentNode("cmt")
        n.text = "TODO"
        n.color = "#0ff"
        assert n.text == "TODO"
        assert n.color == "#0ff"


class TestLabelColors:
    def test_label_colors_exists(self):
        assert len(LABEL_COLORS) > 0
