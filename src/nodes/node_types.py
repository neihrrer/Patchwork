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


# --- Source nodes ---

class ColorSourceNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        outputs = [
            Port(id, "image", "Image", PortDirection.OUTPUT, PortType.IMAGE),
        ]
        super().__init__(id, "Color Source", "color_source", [], outputs, x, y)
        self.width = 180
        self.height = 160
        self.source_width: int = 512
        self.source_height: int = 512
        self.color: str = "#FFFFFFFF"


class GradientNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        outputs = [
            Port(id, "image", "Image", PortDirection.OUTPUT, PortType.IMAGE),
        ]
        super().__init__(id, "Gradient", "gradient", [], outputs, x, y)
        self.width = 180
        self.height = 180
        self.source_width: int = 512
        self.source_height: int = 512
        self.gradient_type: str = "linear"
        self.start_color: str = "#000000FF"
        self.end_color: str = "#FFFFFFFF"
        self.angle: float = 0.0


class NoiseNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        outputs = [
            Port(id, "image", "Image", PortDirection.OUTPUT, PortType.IMAGE),
        ]
        super().__init__(id, "Noise", "noise", [], outputs, x, y)
        self.width = 180
        self.height = 160
        self.source_width: int = 512
        self.source_height: int = 512
        self.noise_type: str = "gaussian"
        self.scale: float = 64.0
        self.seed: int = -1


# --- Adjust nodes ---

class ColorBalanceNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "image", "Image", PortDirection.INPUT, PortType.IMAGE),
            Port(id, "cyan_red", "Cyan/Red", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "magenta_green", "Magenta/Green", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "yellow_blue", "Yellow/Blue", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "image", "Image", PortDirection.OUTPUT, PortType.IMAGE),
        ]
        super().__init__(id, "Color Balance", "color_balance", inputs, outputs, x, y)
        self.width = 200
        self.height = 180
        self.cyan_red: float = 0.0
        self.magenta_green: float = 0.0
        self.yellow_blue: float = 0.0


class ExposureGammaNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "image", "Image", PortDirection.INPUT, PortType.IMAGE),
            Port(id, "exposure", "Exposure", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "gamma", "Gamma", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "image", "Image", PortDirection.OUTPUT, PortType.IMAGE),
        ]
        super().__init__(id, "Exposure/Gamma", "exposure_gamma", inputs, outputs, x, y)
        self.width = 200
        self.height = 160
        self.exposure: float = 0.0
        self.gamma: float = 1.0


class CurvesNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "image", "Image", PortDirection.INPUT, PortType.IMAGE),
            Port(id, "shadows", "Shadows", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "dark_midtones", "Dark Midtones", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "midtones", "Midtones", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "light_midtones", "Light Midtones", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "highlights", "Highlights", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "image", "Image", PortDirection.OUTPUT, PortType.IMAGE),
        ]
        super().__init__(id, "Curves", "curves", inputs, outputs, x, y)
        self.width = 200
        self.height = 220
        self.shadows: float = 0.0
        self.dark_midtones: float = 64.0
        self.midtones: float = 128.0
        self.light_midtones: float = 192.0
        self.highlights: float = 255.0


# --- Transform nodes ---

class CropNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "image", "Image", PortDirection.INPUT, PortType.IMAGE),
            Port(id, "crop_x", "X", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "crop_y", "Y", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "crop_width", "Width", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "crop_height", "Height", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "image", "Image", PortDirection.OUTPUT, PortType.IMAGE),
        ]
        super().__init__(id, "Crop", "crop", inputs, outputs, x, y)
        self.width = 200
        self.height = 200
        self.crop_x: float = 0.0
        self.crop_y: float = 0.0
        self.crop_width: float = 256.0
        self.crop_height: float = 256.0


class ResizeNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "image", "Image", PortDirection.INPUT, PortType.IMAGE),
            Port(id, "resize_width", "Width", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "resize_height", "Height", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "image", "Image", PortDirection.OUTPUT, PortType.IMAGE),
        ]
        super().__init__(id, "Resize", "resize", inputs, outputs, x, y)
        self.width = 200
        self.height = 180
        self.resize_width: float = 512.0
        self.resize_height: float = 512.0
        self.resize_mode: str = "stretch"


class RotateNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "image", "Image", PortDirection.INPUT, PortType.IMAGE),
            Port(id, "angle", "Angle", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "image", "Image", PortDirection.OUTPUT, PortType.IMAGE),
        ]
        super().__init__(id, "Rotate", "rotate", inputs, outputs, x, y)
        self.width = 180
        self.height = 140
        self.angle: float = 0.0


class FlipNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "image", "Image", PortDirection.INPUT, PortType.IMAGE),
        ]
        outputs = [
            Port(id, "image", "Image", PortDirection.OUTPUT, PortType.IMAGE),
        ]
        super().__init__(id, "Flip", "flip", inputs, outputs, x, y)
        self.width = 180
        self.height = 120
        self.direction: str = "horizontal"


class DistortNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "image", "Image", PortDirection.INPUT, PortType.IMAGE),
            Port(id, "dist_x0", "Top-Left X", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "dist_y0", "Top-Left Y", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "dist_x1", "Top-Right X", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "dist_y1", "Top-Right Y", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "dist_x2", "Bottom-Right X", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "dist_y2", "Bottom-Right Y", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "dist_x3", "Bottom-Left X", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "dist_y3", "Bottom-Left Y", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "image", "Image", PortDirection.OUTPUT, PortType.IMAGE),
        ]
        super().__init__(id, "Distort", "distort", inputs, outputs, x, y)
        self.width = 200
        self.height = 280
        self.dist_x0: float = 0.0
        self.dist_y0: float = 0.0
        self.dist_x1: float = 512.0
        self.dist_y1: float = 0.0
        self.dist_x2: float = 512.0
        self.dist_y2: float = 512.0
        self.dist_x3: float = 0.0
        self.dist_y3: float = 512.0


# --- Filter nodes ---

class BlurNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "image", "Image", PortDirection.INPUT, PortType.IMAGE),
            Port(id, "radius", "Radius", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "image", "Image", PortDirection.OUTPUT, PortType.IMAGE),
        ]
        super().__init__(id, "Blur", "blur", inputs, outputs, x, y)
        self.width = 180
        self.height = 140
        self.radius: float = 5.0


class SharpenNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "image", "Image", PortDirection.INPUT, PortType.IMAGE),
            Port(id, "amount", "Amount", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "radius", "Radius", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "image", "Image", PortDirection.OUTPUT, PortType.IMAGE),
        ]
        super().__init__(id, "Sharpen", "sharpen", inputs, outputs, x, y)
        self.width = 200
        self.height = 170
        self.amount: float = 1.0
        self.radius: float = 2.0


class EdgeDetectNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "image", "Image", PortDirection.INPUT, PortType.IMAGE),
            Port(id, "threshold", "Threshold", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "image", "Image", PortDirection.OUTPUT, PortType.IMAGE),
        ]
        super().__init__(id, "Edge Detect", "edge_detect", inputs, outputs, x, y)
        self.width = 200
        self.height = 140
        self.threshold: float = 0.0
