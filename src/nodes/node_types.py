import os
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


class VideoInputNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        outputs = [
            Port(id, "image", "Image", PortDirection.OUTPUT, PortType.IMAGE),
        ]
        super().__init__(id, "Video Input", "video_input", [], outputs, x, y)
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


class TimeNode(Node):
    TIME_MODE_FRAME = "frame"
    TIME_MODE_SECONDS = "seconds"

    def __init__(self, id: str, x: float = 0, y: float = 0):
        outputs = [
            Port(id, "value", "Frame", PortDirection.OUTPUT, PortType.NUMERIC),
        ]
        super().__init__(id, "Clock", "time", [], outputs, x, y)
        self.width = 180
        self.height = 130
        self.mode: str = self.TIME_MODE_FRAME
        self.fps: float = 12.0
        self.length: int = 24
        self._last_frame: int = 0

    def value_for(self, frame: int) -> float:
        if self.mode == self.TIME_MODE_SECONDS:
            return frame / self.fps if self.fps else 0.0
        return float(frame)


class RawInputNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        outputs = [
            Port(id, "raw", "Raw Data", PortDirection.OUTPUT, PortType.RAW),
        ]
        super().__init__(id, "Raw Input", "raw_input", [], outputs, x, y)
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


class RawDecodeNode(Node):
    DECODE_METHODS = [
        "1-bit (monochrome)",
        "8-bit grayscale",
        "8-bit RGB (24-bit)",
        "8-bit RGBA (32-bit)",
        "16-bit grayscale LE",
        "16-bit grayscale BE",
        "16-bit RGB (48-bit) LE",
        "16-bit RGB (48-bit) BE",
        "16-bit RGBA (64-bit) LE",
        "16-bit RGBA (64-bit) BE",
        "32-bit float grayscale",
        "32-bit float RGB",
        "32-bit float RGBA",
    ]

    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "raw", "Raw Data", PortDirection.INPUT, PortType.RAW),
            Port(id, "decode_width", "Width", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "decode_height", "Height", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "image", "Image", PortDirection.OUTPUT, PortType.IMAGE),
        ]
        super().__init__(id, "Raw Decode", "raw_decode", inputs, outputs, x, y)
        self.width = 200
        self.height = 200
        self.decode_method: str = "8-bit grayscale"
        self.decode_width: int = 512
        self.decode_height: int = 512
        self.byte_offset: int = 0


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
        self._extra_image_ports = 0
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
    def extra_image_ports(self) -> int:
        return self._extra_image_ports

    def add_input_port(self) -> Port:
        """Add one more image input after the declared ones.

        Filters such as 'fx_jfif' need more layers than their '#@gui' flags
        declare; the extra ports are named 'image_N' like the declared ones.
        """
        self._extra_image_ports += 1
        number = self._filter_def.image_input_count + self._extra_image_ports
        port = Port(self.id, f"image_{number}", f"Image {number}",
                    PortDirection.INPUT, PortType.IMAGE)
        # Keep the image inputs together, before any numeric parameter port.
        index = len(self._inputs)
        for position, existing in enumerate(self._inputs):
            if existing.port_type != PortType.IMAGE:
                index = position
                break
        self._inputs.insert(index, port)
        self.height += 20
        return port

    def remove_input_port(self) -> Optional[Port]:
        """Remove the last extra image input (declared inputs stay)."""
        if self._extra_image_ports == 0:
            return None
        number = self._filter_def.image_input_count + self._extra_image_ports
        self._extra_image_ports -= 1
        for position, existing in enumerate(self._inputs):
            if existing.name == f"image_{number}":
                self.height = max(100, self.height - 20)
                return self._inputs.pop(position)
        return None

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


class ModuloNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "a", "A", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "b", "B", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "result", "Result", PortDirection.OUTPUT, PortType.NUMERIC),
        ]
        super().__init__(id, "Modulo", "modulo", inputs, outputs, x, y)
        self.width = 160
        self.height = 80


class PowerNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "a", "A", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "b", "B", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "result", "Result", PortDirection.OUTPUT, PortType.NUMERIC),
        ]
        super().__init__(id, "Power", "power", inputs, outputs, x, y)
        self.width = 160
        self.height = 80


class SquareRootNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "a", "A", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "result", "Result", PortDirection.OUTPUT, PortType.NUMERIC),
        ]
        super().__init__(id, "Square Root", "square_root", inputs, outputs, x, y)
        self.width = 160
        self.height = 80


class AbsoluteNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "a", "A", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "result", "Result", PortDirection.OUTPUT, PortType.NUMERIC),
        ]
        super().__init__(id, "Absolute", "absolute", inputs, outputs, x, y)
        self.width = 160
        self.height = 80


class LogNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "a", "A", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "result", "Result", PortDirection.OUTPUT, PortType.NUMERIC),
        ]
        super().__init__(id, "Log", "log", inputs, outputs, x, y)
        self.width = 160
        self.height = 80


class ExpNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "a", "A", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "result", "Result", PortDirection.OUTPUT, PortType.NUMERIC),
        ]
        super().__init__(id, "Exp", "exp", inputs, outputs, x, y)
        self.width = 160
        self.height = 80


class RandomNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0,
                 min_val: float = 0.0, max_val: float = 1.0, seed: Optional[int] = None):
        outputs = [
            Port(id, "value", "Value", PortDirection.OUTPUT, PortType.NUMERIC),
        ]
        super().__init__(id, "Random", "random", [], outputs, x, y)
        self.width = 160
        self.height = 130
        self.min_val: float = min_val
        self.max_val: float = max_val
        self.seed: Optional[int] = seed
        self._current_value: float = self._generate()

    def _generate(self) -> float:
        import random
        if self.seed is not None:
            random.seed(self.seed)
        return random.uniform(self.min_val, self.max_val)

    def randomize(self):
        self._current_value = self._generate()
        self.cache_dirty = True

    @property
    def value(self) -> float:
        return self._current_value


LABEL_COLORS = [
    ("None", None),
    ("Blue",  "#3584e4"),
    ("Green", "#3a944a"),
    ("Yellow", "#c88800"),
    ("Orange", "#ed5b00"),
    ("Red",   "#e62d42"),
    ("Purple", "#9141ac"),
    ("Brown", "#986a44"),
    ("Grey",  "#5e5c64"),
]

NODE_CATEGORY_MAP = {
    "input": "source", "color_source": "source",
    "gradient": "source", "noise": "source",
    "video_input": "source",
    "time": "math",
    "output": "output",
    "raw_input": "raw_input", "raw_decode": "raw_input",
    "filter": "effect",
    "brightness_contrast": "effect", "levels": "effect", "hsl": "effect",
    "color_balance": "effect", "exposure_gamma": "effect", "curves": "effect",
    "crop": "effect", "resize": "effect", "rotate": "effect",
    "flip": "effect", "distort": "effect",
    "blur": "effect", "sharpen": "effect", "edge_detect": "effect",
    "opacity": "composite", "blend": "composite", "mask": "composite",
    "histogram": "analysis", "waveform_monitor": "analysis",
    "vectorscope": "analysis", "frequency_domain": "analysis",
    "constant": "math", "add": "math", "subtract": "math",
    "multiply": "math", "divide": "math",
    "ceil": "math", "floor": "math", "round": "math",
    "sum": "math", "product": "math",
    "modulo": "math", "power": "math",
    "square_root": "math", "absolute": "math",
    "log": "math", "exp": "math", "random": "math",
    "compare": "math", "clamp": "math", "map_range": "math",
    "not": "logic", "and": "logic", "or": "logic",
    "nand": "logic", "nor": "logic", "xor": "logic", "xnor": "logic",
}

CATEGORY_GDK_RGBA = {
    "source": (0.15, 0.64, 0.41, 1.0),
    "output": (0.65, 0.11, 0.18, 1.0),
    "raw_input": (0.53, 0.37, 0.24, 1.0),
    "effect": (0.10, 0.37, 0.71, 1.0),
    "composite": (0.13, 0.56, 0.64, 1.0),
    "analysis": (0.47, 0.46, 0.48, 1.0),
    "math": (0.78, 0.53, 0.00, 1.0),
    "logic": (0.51, 0.24, 0.61, 1.0),
}


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
        inputs = [
            Port(id, "source_width", "Width", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "source_height", "Height", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "image", "Image", PortDirection.OUTPUT, PortType.IMAGE),
        ]
        super().__init__(id, "Color Source", "color_source", inputs, outputs, x, y)
        self.width = 180
        self.height = 160
        self.source_width: int = 512
        self.source_height: int = 512
        self.color: str = "#FFFFFFFF"


class GradientNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "source_width", "Width", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "source_height", "Height", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "image", "Image", PortDirection.OUTPUT, PortType.IMAGE),
        ]
        super().__init__(id, "Gradient", "gradient", inputs, outputs, x, y)
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
        inputs = [
            Port(id, "source_width", "Width", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "source_height", "Height", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "image", "Image", PortDirection.OUTPUT, PortType.IMAGE),
        ]
        super().__init__(id, "Noise", "noise", inputs, outputs, x, y)
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


# --- Analysis nodes ---

class HistogramNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "image", "Image", PortDirection.INPUT, PortType.IMAGE),
        ]
        outputs: list[Port] = []
        super().__init__(id, "Histogram", "histogram", inputs, outputs, x, y)
        self.width = 220
        self.height = 200
        self.analysis_data: Optional[dict] = None


class WaveformMonitorNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "image", "Image", PortDirection.INPUT, PortType.IMAGE),
        ]
        outputs: list[Port] = []
        super().__init__(id, "Waveform Monitor", "waveform_monitor", inputs, outputs, x, y)
        self.width = 220
        self.height = 200
        self.analysis_data: Optional[dict] = None


class VectorscopeNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "image", "Image", PortDirection.INPUT, PortType.IMAGE),
        ]
        outputs: list[Port] = []
        super().__init__(id, "Vectorscope", "vectorscope", inputs, outputs, x, y)
        self.width = 220
        self.height = 220
        self.analysis_data: Optional[dict] = None


class FrequencyDomainNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "image", "Image", PortDirection.INPUT, PortType.IMAGE),
        ]
        outputs: list[Port] = []
        super().__init__(id, "Frequency Domain", "frequency_domain", inputs, outputs, x, y)
        self.width = 220
        self.height = 220
        self.analysis_data: Optional[dict] = None


class NotNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "a", "A", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "result", "Result", PortDirection.OUTPUT, PortType.NUMERIC),
        ]
        super().__init__(id, "NOT", "not", inputs, outputs, x, y)
        self.width = 160
        self.height = 80


class AndNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "a", "A", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "b", "B", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "result", "Result", PortDirection.OUTPUT, PortType.NUMERIC),
        ]
        super().__init__(id, "AND", "and", inputs, outputs, x, y)
        self.width = 160
        self.height = 80


class OrNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "a", "A", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "b", "B", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "result", "Result", PortDirection.OUTPUT, PortType.NUMERIC),
        ]
        super().__init__(id, "OR", "or", inputs, outputs, x, y)
        self.width = 160
        self.height = 80


class NandNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "a", "A", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "b", "B", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "result", "Result", PortDirection.OUTPUT, PortType.NUMERIC),
        ]
        super().__init__(id, "NAND", "nand", inputs, outputs, x, y)
        self.width = 160
        self.height = 80


class NorNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "a", "A", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "b", "B", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "result", "Result", PortDirection.OUTPUT, PortType.NUMERIC),
        ]
        super().__init__(id, "NOR", "nor", inputs, outputs, x, y)
        self.width = 160
        self.height = 80


class XorNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "a", "A", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "b", "B", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "result", "Result", PortDirection.OUTPUT, PortType.NUMERIC),
        ]
        super().__init__(id, "XOR", "xor", inputs, outputs, x, y)
        self.width = 160
        self.height = 80


class XnorNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0):
        inputs = [
            Port(id, "a", "A", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "b", "B", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "result", "Result", PortDirection.OUTPUT, PortType.NUMERIC),
        ]
        super().__init__(id, "XNOR", "xnor", inputs, outputs, x, y)
        self.width = 160
        self.height = 80


class CompareNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0, operator: str = "=="):
        inputs = [
            Port(id, "a", "A", PortDirection.INPUT, PortType.NUMERIC),
            Port(id, "b", "B", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "result", "Result", PortDirection.OUTPUT, PortType.NUMERIC),
        ]
        super().__init__(id, "Compare", "compare", inputs, outputs, x, y)
        self.width = 160
        self.height = 100
        self.operator: str = operator


class ClampNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0, min_val: float = 0.0, max_val: float = 1.0):
        inputs = [
            Port(id, "a", "A", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "result", "Result", PortDirection.OUTPUT, PortType.NUMERIC),
        ]
        super().__init__(id, "Clamp", "clamp", inputs, outputs, x, y)
        self.width = 160
        self.height = 100
        self.min_val: float = min_val
        self.max_val: float = max_val


class MapRangeNode(Node):
    def __init__(self, id: str, x: float = 0, y: float = 0,
                 in_min: float = 0.0, in_max: float = 1.0,
                 out_min: float = 0.0, out_max: float = 1.0):
        inputs = [
            Port(id, "a", "A", PortDirection.INPUT, PortType.NUMERIC),
        ]
        outputs = [
            Port(id, "result", "Result", PortDirection.OUTPUT, PortType.NUMERIC),
        ]
        super().__init__(id, "Map Range", "map_range", inputs, outputs, x, y)
        self.width = 160
        self.height = 120
        self.in_min: float = in_min
        self.in_max: float = in_max
        self.out_min: float = out_min
        self.out_max: float = out_max
