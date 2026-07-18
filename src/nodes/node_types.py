import math
import os
import re
import gettext
from typing import Optional

from models.filter import FilterDef, ParamValue, ParamKind
from nodes.graph import Node, Port, PortDirection, PortType

try:
    _ = gettext.gettext
except Exception:
    _ = lambda s: s


class InputNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        outputs = [
            Port(id, "image", "Image", PortDirection.OUTPUT, PortType.IMAGE),
        ]
        super().__init__(id, "Image Input", "input", [], outputs, x, y)
        self.width = 180
        self.height = 80
        self._file_path: Optional[str] = None

    @property
    def file_path(self) -> Optional[str]:
        return self._file_path

    @file_path.setter
    def file_path(self, value: Optional[str]):
        self._file_path = value
        if value:
            self.label = os.path.basename(value)
        self.cache_dirty = True


class OutputNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "image", "Image", PortDirection.INPUT, PortType.IMAGE),
        ]
        super().__init__(id, "Output", "output", inputs, [], x, y)
        self.width = 180
        self.height = 70


class FilterNode(Node):
    def __init__(self, id: str, filter_def: FilterDef, x: float = 0, y: float = 0):
        inputs = []
        for i in range(filter_def.image_input_count):
            label = "Image" if i == 0 else f"Image {i + 1}"
            name = "image" if i == 0 else f"image_{i + 1}"
            inputs.append(Port(id, name, label, PortDirection.INPUT, PortType.IMAGE))
        for p in filter_def.parameters:
            if p.kind in (ParamKind.INT, ParamKind.FLOAT) and not p.is_hidden:
                inputs.append(Port(id, p.name, p.label, PortDirection.INPUT, PortType.NUMERIC))
        outputs = [
            Port(id, "image", "Image", PortDirection.OUTPUT, PortType.IMAGE),
        ]
        super().__init__(id, filter_def.display_name, "filter", inputs, outputs, x, y)
        self.width = 220
        self.height = 100
        self._filter_def = filter_def
        self._param_values: dict[str, ParamValue] = {
            p.name: p.default for p in filter_def.parameters
        }
        if filter_def.name == "fx_drawn_montage":
            for p in filter_def.parameters:
                if p.name == "Layer":
                    p.is_hidden = True
            self._param_values["Layer"] = 1

    @property
    def filter_def(self) -> FilterDef:
        return self._filter_def

    @property
    def param_values(self) -> dict[str, ParamValue]:
        return self._param_values

    def set_param(self, name: str, value: ParamValue):
        self._param_values[name] = value
        self.cache_dirty = True


class BlendNode(Node):
    def __init__(self, id: str, mode: str = "over", x: float = 0, y: float = 0):
        inputs = [
            Port(id, "base", "Base", PortDirection.INPUT, PortType.IMAGE),
            Port(id, "blend", "Blend", PortDirection.INPUT, PortType.IMAGE),
        ]
        outputs = [
            Port(id, "image", "Image", PortDirection.OUTPUT, PortType.IMAGE),
        ]
        super().__init__(id, "Blend", "blend", inputs, outputs, x, y)
        self.width = 180
        self.height = 90
        self.mode: str = mode
        self._extra_input_counter = 0

    def add_input_port(self) -> Port:
        self._extra_input_counter += 1
        n = self._extra_input_counter
        name = f"blend_{n}"
        label = f"Blend {n}"
        p = Port(self.id, name, label, PortDirection.INPUT, PortType.IMAGE)
        self._inputs.append(p)
        self.height += 20
        return p

    BLEND_MODES = [
        "over", "multiply", "screen", "overlay",
        "darken", "lighten", "color-dodge", "color-burn",
        "hard-light", "soft-light", "difference", "exclusion",
    ]

    BLEND_LABELS = [
        "Over", "Multiply", "Screen", "Overlay",
        "Darken", "Lighten", "Color Dodge", "Color Burn",
        "Hard Light", "Soft Light", "Difference", "Exclusion",
    ]


class BrightnessContrastNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "image", "Image", PortDirection.INPUT, PortType.IMAGE),
            Port(id, "brightness", "Brightness", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "contrast", "Contrast", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "image", "Image", PortDirection.OUTPUT, PortType.IMAGE),
        ]
        super().__init__(id, "Brightness/Contrast", "brightness_contrast", inputs, outputs, x, y)
        self.width = 200
        self.height = 150
        self.brightness: float = 0.0
        self.contrast: float = 0.0


class LevelsNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "image", "Image", PortDirection.INPUT, PortType.IMAGE),
            Port(id, "black_point", "Black Point", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "white_point", "White Point", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "gamma", "Gamma", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "image", "Image", PortDirection.OUTPUT, PortType.IMAGE),
        ]
        super().__init__(id, "Levels", "levels", inputs, outputs, x, y)
        self.width = 200
        self.height = 170
        self.black_point: float = 0.0
        self.white_point: float = 100.0
        self.gamma: float = 1.0


class HSLNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "image", "Image", PortDirection.INPUT, PortType.IMAGE),
            Port(id, "hue", "Hue", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "saturation", "Saturation", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "lightness", "Lightness", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "image", "Image", PortDirection.OUTPUT, PortType.IMAGE),
        ]
        super().__init__(id, "HSL", "hsl", inputs, outputs, x, y)
        self.width = 200
        self.height = 180
        self.hue: float = 0.0
        self.saturation: float = 0.0
        self.lightness: float = 0.0


class OpacityNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "image", "Image", PortDirection.INPUT, PortType.IMAGE),
            Port(id, "opacity", "Opacity", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "image", "Image", PortDirection.OUTPUT, PortType.IMAGE),
        ]
        super().__init__(id, "Opacity", "opacity", inputs, outputs, x, y)
        self.width = 180
        self.height = 120
        self.opacity: float = 1.0


class MaskNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "base", "Base", PortDirection.INPUT, PortType.IMAGE),
            Port(id, "mask", "Mask", PortDirection.INPUT, PortType.IMAGE),
            Port(id, "threshold", "Threshold", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "image", "Image", PortDirection.OUTPUT, PortType.IMAGE),
        ]
        super().__init__(id, "Mask", "mask", inputs, outputs, x, y)
        self.width = 180
        self.height = 120
        self.invert: bool = False
        self.threshold: float = 0.5


class ConstantNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        outputs = [
            Port(id, "value", "Value", PortDirection.OUTPUT, PortType.NUMERIC),
        ]
        super().__init__(id, "Constant", "constant", [], outputs, x, y)
        self.width = 160
        self.height = 80
        self.value: float = 0.0


class AddNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "a", "A", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "b", "B", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "result", "Result", PortDirection.OUTPUT, PortType.NUMERIC),
        ]
        super().__init__(id, "Add", "add", inputs, outputs, x, y)
        self.width = 160
        self.height = 80


class SubtractNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "a", "A", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "b", "B", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "result", "Result", PortDirection.OUTPUT, PortType.NUMERIC),
        ]
        super().__init__(id, "Subtract", "subtract", inputs, outputs, x, y)
        self.width = 160
        self.height = 80


class MultiplyNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "a", "A", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "b", "B", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "result", "Result", PortDirection.OUTPUT, PortType.NUMERIC),
        ]
        super().__init__(id, "Multiply", "multiply", inputs, outputs, x, y)
        self.width = 160
        self.height = 80


class DivideNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "a", "A", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "b", "B", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "result", "Result", PortDirection.OUTPUT, PortType.NUMERIC),
        ]
        super().__init__(id, "Divide", "divide", inputs, outputs, x, y)
        self.width = 160
        self.height = 80


class CeilNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "a", "A", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "result", "Result", PortDirection.OUTPUT, PortType.NUMERIC),
        ]
        super().__init__(id, "Ceiling", "ceil", inputs, outputs, x, y)
        self.width = 160
        self.height = 80


class FloorNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "a", "A", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "result", "Result", PortDirection.OUTPUT, PortType.NUMERIC),
        ]
        super().__init__(id, "Floor", "floor", inputs, outputs, x, y)
        self.width = 160
        self.height = 80


class RoundNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "a", "A", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "result", "Result", PortDirection.OUTPUT, PortType.NUMERIC),
        ]
        super().__init__(id, "Round", "round", inputs, outputs, x, y)
        self.width = 160
        self.height = 80


class SumNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "a", "A", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "b", "B", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "result", "Result", PortDirection.OUTPUT, PortType.NUMERIC),
        ]
        super().__init__(id, "Sum", "sum", inputs, outputs, x, y)
        self.width = 160
        self.height = 80


class ProductNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "a", "A", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "b", "B", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "result", "Result", PortDirection.OUTPUT, PortType.NUMERIC),
        ]
        super().__init__(id, "Product", "product", inputs, outputs, x, y)
        self.width = 160
        self.height = 80


LABEL_COLORS = [
    ("None", None),
    ("Blue", "#62a0ea"),
    ("Green", "#2ec27e"),
    ("Yellow", "#f6d32d"),
    ("Orange", "#ffa348"),
    ("Red", "#c01c28"),
    ("Purple", "#9141ac"),
    ("Brown", "#b5835a"),
    ("Grey", "#5e5c64"),
]


class LabelNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        super().__init__(id, "Label", "label", [], [], x, y)
        self.width = 220
        self.height = 100
        self._color = None
        self._text = _("Label")

    @property
    def color(self):
        return self._color

    @color.setter
    def color(self, value):
        self._color = value

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        self._text = value


class CommentNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        super().__init__(id, "Comment", "comment", [], [], x, y)
        self.width = 280
        self.height = 120
        self._color = None
        self._text = _("Comment")

    @property
    def color(self):
        return self._color

    @color.setter
    def color(self, value):
        self._color = value

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        self._text = value
