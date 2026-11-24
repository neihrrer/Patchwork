import gettext
import re
from enum import Enum, auto
from typing import TYPE_CHECKING, Optional

try:
    _ = gettext.gettext
except Exception:
    _ = lambda s: s

if TYPE_CHECKING:
    from models.filter import FilterDef


def size_port_kind(name: str) -> Optional[str]:
    """Return ``"width"``/``"height"`` when a port name describes that size.

    Filter parameter labels are free text ("Width (px)", "2. Height",
    "Dimension 1 (% Width)"), so match on words instead of suffixes; when a
    label mentions both, the last one wins.
    """
    kind = None
    for word in re.split(r"[^a-z]+", (name or "").lower()):
        if word in ("width", "height"):
            kind = word
    return kind


class PortDirection(Enum):
    INPUT = auto()
    OUTPUT = auto()


class PortType(Enum):
    IMAGE = auto()
    NUMERIC = auto()
    RAW = auto()


class Port:
    def __init__(self, node_id: str, name: str, label: str, direction: PortDirection, port_type: PortType = PortType.IMAGE):
        self.node_id = node_id
        self.name = name
        self.label = label
        self.direction = direction
        self.port_type = port_type

    def __repr__(self):
        return f"Port({self.node_id}/{self.name})"


class Edge:
    def __init__(self, id: str, src_node: str, src_port: str, dst_node: str, dst_port: str):
        self.id = id
        self.src_node = src_node
        self.src_port = src_port
        self.dst_node = dst_node
        self.dst_port = dst_port

    def __repr__(self):
        return f"Edge({self.src_node}/{self.src_port} -> {self.dst_node}/{self.dst_port})"


class Node:
    def __init__(self, id: str, label: str, node_type: str,
                 inputs: list[Port], outputs: list[Port],
                 x: float = 0, y: float = 0):
        self.id = id
        self.label = label
        self.node_type = node_type
        self._inputs = inputs
        self._outputs = outputs
        self.x = x
        self.y = y
        self.width: float = 200
        self.height: float = 120
        self.minimized: bool = False
        self.cached_output_path: Optional[str] = None
        self.cache_dirty: bool = True

    @property
    def inputs(self) -> list[Port]:
        return self._inputs

    @property
    def outputs(self) -> list[Port]:
        return self._outputs

    def get_input_port(self, name: str) -> Optional[Port]:
        for p in self._inputs:
            if p.name == name:
                return p
        return None

    def get_output_port(self, name: str) -> Optional[Port]:
        for p in self._outputs:
            if p.name == name:
                return p
        return None

    def __repr__(self):
        return f"Node({self.id}, {self.node_type}, ({self.x},{self.y}))"


class NodeGraph:
    def __init__(self):
        self._nodes: dict[str, Node] = {}
        self._edges: list[Edge] = []
        self._edge_counter = 0

    def clear(self):
        self._nodes.clear()
        self._edges.clear()
        self._edge_counter = 0

    def replace_with(self, other: "NodeGraph"):
        """Replace the contents of this graph with those of another graph."""
        self._nodes.clear()
        self._edges.clear()
        self._nodes.update(other._nodes)
        self._edges[:] = other._edges
        self._edge_counter = other._edge_counter

    def add_node(self, node: Node):
        self._nodes[node.id] = node

    def remove_node(self, node_id: str):
        self._nodes.pop(node_id, None)
        self._edges = [e for e in self._edges
                       if e.src_node != node_id and e.dst_node != node_id]

    def remove_node_with_bypass(self, node_id: str):
        node = self._nodes.get(node_id)
        if not node:
            self.remove_node(node_id)
            return

        incoming = [e for e in self._edges if e.dst_node == node_id]
        outgoing = [e for e in self._edges if e.src_node == node_id]

        self.remove_node(node_id)

        for ie in incoming:
            ip = node.get_input_port(ie.dst_port)
            if not ip:
                continue
            for oe in outgoing:
                op = node.get_output_port(oe.src_port)
                if not op:
                    continue
                if ip.port_type == op.port_type:
                    self.add_edge(ie.src_node, ie.src_port,
                                  oe.dst_node, oe.dst_port)

    def get_node(self, node_id: str) -> Optional[Node]:
        return self._nodes.get(node_id)

    @property
    def nodes(self) -> dict[str, Node]:
        return self._nodes

    @property
    def edges(self) -> list[Edge]:
        return self._edges

    def add_edge(self, src_node: str, src_port: str, dst_node: str, dst_port: str) -> Optional[Edge]:
        if src_node == dst_node:
            return None
        if self._would_create_cycle(src_node, dst_node):
            return None
        existing = self.get_connected_input(dst_node, dst_port)
        if existing:
            self.remove_edge(existing.id)
        src_n = self._nodes.get(src_node)
        dst_n = self._nodes.get(dst_node)
        if not src_n or not dst_n:
            return None
        src_p = src_n.get_output_port(src_port)
        dst_p = dst_n.get_input_port(dst_port)
        if not src_p or not dst_p:
            return None
        if src_p.port_type != dst_p.port_type:
            # An image may drive a size parameter: connect an image output to
            # an input port named like 'width'/'height' (resize_width,
            # crop_height, a filter's Width, ...) and the executor takes that
            # dimension from the image.
            size_port = (dst_p.port_type == PortType.NUMERIC
                         and size_port_kind(dst_p.name) is not None)
            if not (src_p.port_type == PortType.IMAGE and size_port):
                return None
        self._edge_counter += 1
        edge = Edge(f"e{self._edge_counter}", src_node, src_port, dst_node, dst_port)
        self._edges.append(edge)
        if dst_n:
            dst_n.cache_dirty = True
        return edge

    def remove_edge(self, edge_id: str):
        for e in self._edges:
            if e.id == edge_id:
                dst = self._nodes.get(e.dst_node)
                if dst:
                    dst.cache_dirty = True
                break
        self._edges = [e for e in self._edges if e.id != edge_id]

    def remove_edges_for_port(self, node_id: str, port_name: str, direction: PortDirection):
        if direction == PortDirection.INPUT:
            self._edges = [e for e in self._edges
                           if not (e.dst_node == node_id and e.dst_port == port_name)]
        else:
            self._edges = [e for e in self._edges
                           if not (e.src_node == node_id and e.src_port == port_name)]

    def get_incoming_edges(self, node_id: str) -> list[Edge]:
        return [e for e in self._edges if e.dst_node == node_id]

    def get_outgoing_edges(self, node_id: str) -> list[Edge]:
        return [e for e in self._edges if e.src_node == node_id]

    def get_connected_input(self, node_id: str, port_name: str) -> Optional[Edge]:
        for e in self._edges:
            if e.dst_node == node_id and e.dst_port == port_name:
                return e
        return None

    def _would_create_cycle(self, from_node: str, to_node: str) -> bool:
        visited = set()
        stack = [to_node]
        while stack:
            current = stack.pop()
            if current == from_node:
                return True
            if current in visited:
                continue
            visited.add(current)
            for e in self._edges:
                if e.src_node == current:
                    stack.append(e.dst_node)
        return False

    def topological_sort(self) -> list[Node]:
        in_degree: dict[str, int] = {}
        for nid in self._nodes:
            in_degree[nid] = 0
        for e in self._edges:
            if e.dst_node in in_degree:
                in_degree[e.dst_node] = in_degree.get(e.dst_node, 0) + 1

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        result = []

        while queue:
            nid = queue.pop(0)
            node = self._nodes.get(nid)
            if node:
                result.append(node)
            for e in self._edges:
                if e.src_node == nid:
                    in_degree[e.dst_node] -= 1
                    if in_degree[e.dst_node] == 0:
                        queue.append(e.dst_node)

        if len(result) != len(self._nodes):
            return []
        return result

    def to_dict(self) -> dict:
        nodes_data = []
        for n in self._nodes.values():
            nd = {
                "id": n.id,
                "type": n.node_type,
                "label": n.label,
                "x": n.x,
                "y": n.y,
                "width": n.width,
                "height": n.height,
                "minimized": getattr(n, "minimized", False),
                "params": {},
            }
            from nodes.node_types import (
                InputNode, RawInputNode, RawDecodeNode, FilterNode, BlendNode,
                OpacityNode, MaskNode,
                VideoInputNode, TimeNode,
                BrightnessContrastNode, LevelsNode, HSLNode,
                ColorSourceNode, GradientNode, NoiseNode,
                ColorBalanceNode, ExposureGammaNode, CurvesNode,
                CropNode, ResizeNode, RotateNode, FlipNode, DistortNode,
                BlurNode, SharpenNode, EdgeDetectNode,
                ConstantNode, CompareNode, ClampNode, MapRangeNode, RandomNode,
                LabelNode, CommentNode,
            )
            if isinstance(n, InputNode):
                nd["params"]["file_path"] = n.file_path
            elif isinstance(n, VideoInputNode):
                nd["params"]["file_path"] = n.file_path
            elif isinstance(n, TimeNode):
                nd["params"]["mode"] = n.mode
                nd["params"]["fps"] = n.fps
                nd["params"]["length"] = n.length
            elif isinstance(n, RawInputNode):
                nd["params"]["file_path"] = n.file_path
            elif isinstance(n, RawDecodeNode):
                nd["params"]["decode_method"] = n.decode_method
                nd["params"]["decode_width"] = n.decode_width
                nd["params"]["decode_height"] = n.decode_height
                nd["params"]["byte_offset"] = n.byte_offset
            elif isinstance(n, FilterNode):
                nd["params"]["filter_key"] = f"{n.filter_def.engine}:{n.filter_def.name}"
                nd["params"]["param_values"] = dict(n.param_values)
                if n.extra_image_ports:
                    nd["params"]["extra_image_ports"] = n.extra_image_ports
            elif isinstance(n, BlendNode):
                nd["params"]["mode"] = n.mode
                nd["params"]["extra_ports"] = len(n.inputs) - 2
            elif isinstance(n, BrightnessContrastNode):
                nd["params"]["brightness"] = n.brightness
                nd["params"]["contrast"] = n.contrast
            elif isinstance(n, LevelsNode):
                nd["params"]["black_point"] = n.black_point
                nd["params"]["white_point"] = n.white_point
                nd["params"]["gamma"] = n.gamma
            elif isinstance(n, HSLNode):
                nd["params"]["hue"] = n.hue
                nd["params"]["saturation"] = n.saturation
                nd["params"]["lightness"] = n.lightness
            elif isinstance(n, ColorSourceNode):
                nd["params"]["source_width"] = n.source_width
                nd["params"]["source_height"] = n.source_height
                nd["params"]["color"] = n.color
            elif isinstance(n, GradientNode):
                nd["params"]["source_width"] = n.source_width
                nd["params"]["source_height"] = n.source_height
                nd["params"]["gradient_type"] = n.gradient_type
                nd["params"]["start_color"] = n.start_color
                nd["params"]["end_color"] = n.end_color
                nd["params"]["angle"] = n.angle
            elif isinstance(n, NoiseNode):
                nd["params"]["source_width"] = n.source_width
                nd["params"]["source_height"] = n.source_height
                nd["params"]["noise_type"] = n.noise_type
                nd["params"]["scale"] = n.scale
                nd["params"]["seed"] = n.seed
            elif isinstance(n, ColorBalanceNode):
                nd["params"]["cyan_red"] = n.cyan_red
                nd["params"]["magenta_green"] = n.magenta_green
                nd["params"]["yellow_blue"] = n.yellow_blue
            elif isinstance(n, ExposureGammaNode):
                nd["params"]["exposure"] = n.exposure
                nd["params"]["gamma"] = n.gamma
            elif isinstance(n, CurvesNode):
                nd["params"]["shadows"] = n.shadows
                nd["params"]["dark_midtones"] = n.dark_midtones
                nd["params"]["midtones"] = n.midtones
                nd["params"]["light_midtones"] = n.light_midtones
                nd["params"]["highlights"] = n.highlights
            elif isinstance(n, CropNode):
                nd["params"]["crop_x"] = n.crop_x
                nd["params"]["crop_y"] = n.crop_y
                nd["params"]["crop_width"] = n.crop_width
                nd["params"]["crop_height"] = n.crop_height
            elif isinstance(n, ResizeNode):
                nd["params"]["resize_width"] = n.resize_width
                nd["params"]["resize_height"] = n.resize_height
                nd["params"]["resize_mode"] = n.resize_mode
            elif isinstance(n, RotateNode):
                nd["params"]["angle"] = n.angle
            elif isinstance(n, FlipNode):
                nd["params"]["direction"] = n.direction
            elif isinstance(n, DistortNode):
                nd["params"]["dist_x0"] = n.dist_x0
                nd["params"]["dist_y0"] = n.dist_y0
                nd["params"]["dist_x1"] = n.dist_x1
                nd["params"]["dist_y1"] = n.dist_y1
                nd["params"]["dist_x2"] = n.dist_x2
                nd["params"]["dist_y2"] = n.dist_y2
                nd["params"]["dist_x3"] = n.dist_x3
                nd["params"]["dist_y3"] = n.dist_y3
            elif isinstance(n, BlurNode):
                nd["params"]["radius"] = n.radius
            elif isinstance(n, SharpenNode):
                nd["params"]["amount"] = n.amount
                nd["params"]["radius"] = n.radius
            elif isinstance(n, EdgeDetectNode):
                nd["params"]["threshold"] = n.threshold
            elif isinstance(n, OpacityNode):
                nd["params"]["opacity"] = n.opacity
            elif isinstance(n, MaskNode):
                nd["params"]["invert"] = n.invert
                nd["params"]["threshold"] = n.threshold
            elif isinstance(n, ConstantNode):
                nd["params"]["value"] = n.value
            elif isinstance(n, CompareNode):
                nd["params"]["operator"] = n.operator
            elif isinstance(n, ClampNode):
                nd["params"]["min_val"] = n.min_val
                nd["params"]["max_val"] = n.max_val
            elif isinstance(n, MapRangeNode):
                nd["params"]["in_min"] = n.in_min
                nd["params"]["in_max"] = n.in_max
                nd["params"]["out_min"] = n.out_min
                nd["params"]["out_max"] = n.out_max
            elif isinstance(n, RandomNode):
                nd["params"]["min_val"] = n.min_val
                nd["params"]["max_val"] = n.max_val
                nd["params"]["seed"] = n.seed
            elif isinstance(n, (LabelNode, CommentNode)):
                nd["params"]["text"] = n.text
                nd["params"]["color"] = n.color
            nodes_data.append(nd)

        edges_data = []
        for e in self._edges:
            edges_data.append({
                "id": e.id,
                "src_node": e.src_node,
                "src_port": e.src_port,
                "dst_node": e.dst_node,
                "dst_port": e.dst_port,
            })

        return {
            "version": 1,
            "nodes": nodes_data,
            "edges": edges_data,
        }

    @staticmethod
    def from_dict(data: dict, filter_def_map: dict[str, "FilterDef"] = {}) -> "NodeGraph":
        from nodes.node_types import (
            InputNode, VideoInputNode, TimeNode, RawInputNode, RawDecodeNode, OutputNode, FilterNode, BlendNode,
            OpacityNode, MaskNode,
            BrightnessContrastNode, LevelsNode, HSLNode,
            ColorSourceNode, GradientNode, NoiseNode,
            ColorBalanceNode, ExposureGammaNode, CurvesNode,
            CropNode, ResizeNode, RotateNode, FlipNode, DistortNode,
            BlurNode, SharpenNode, EdgeDetectNode,
            ConstantNode, AddNode, SubtractNode, MultiplyNode, DivideNode,
            CeilNode, FloorNode, RoundNode, SumNode, ProductNode,
            LabelNode, CommentNode,
            HistogramNode, WaveformMonitorNode, VectorscopeNode, FrequencyDomainNode,
            NotNode, AndNode, OrNode, NandNode, NorNode, XorNode, XnorNode,
            CompareNode, ClampNode, MapRangeNode,
            ModuloNode, PowerNode, SquareRootNode, AbsoluteNode, LogNode, ExpNode, RandomNode,
        )
        graph = NodeGraph()
        for nd in data.get("nodes", []):
            nid = nd["id"]
            typ = nd["type"]
            params = nd.get("params", {})
            x, y = nd.get("x", 0), nd.get("y", 0)
            node = None
            if typ == "input":
                node = InputNode(nid, x, y)
                fp = params.get("file_path")
                if fp:
                    node.file_path = fp
            elif typ == "video_input":
                node = VideoInputNode(nid, x, y)
                fp = params.get("file_path")
                if fp:
                    node.file_path = fp
            elif typ == "time":
                node = TimeNode(nid, x, y)
                node.mode = params.get("mode", node.mode)
                node.fps = params.get("fps", node.fps)
                node.length = params.get("length", node.length)
            elif typ == "raw_input":
                node = RawInputNode(nid, x, y)
                fp = params.get("file_path")
                if fp:
                    node.file_path = fp
            elif typ == "raw_decode":
                node = RawDecodeNode(nid, x, y)
                node.decode_method = params.get("decode_method", "8-bit grayscale")
                node.decode_width = params.get("decode_width", 512)
                node.decode_height = params.get("decode_height", 512)
                node.byte_offset = params.get("byte_offset", 0)
            elif typ == "output":
                node = OutputNode(nid, x, y)
            elif typ == "filter":
                fkey = params.get("filter_key", "")
                fdef = filter_def_map.get(fkey)
                if fdef:
                    node = FilterNode(nid, fdef, x, y)
                else:
                    continue
                for k, v in params.get("param_values", {}).items():
                    node.set_param(k, v)
                for _i in range(params.get("extra_image_ports", 0)):
                    node.add_input_port()
            elif typ == "blend":
                mode = params.get("mode", "over")
                node = BlendNode(nid, mode, x, y)
                extra = params.get("extra_ports", 0)
                for _i in range(extra):
                    node.add_input_port()
            elif typ == "brightness_contrast":
                node = BrightnessContrastNode(nid, x, y)
                node.brightness = params.get("brightness", 0.0)
                node.contrast = params.get("contrast", 0.0)
            elif typ == "levels":
                node = LevelsNode(nid, x, y)
                node.black_point = params.get("black_point", 0.0)
                node.white_point = params.get("white_point", 100.0)
                node.gamma = params.get("gamma", 1.0)
            elif typ == "hsl":
                node = HSLNode(nid, x, y)
                node.hue = params.get("hue", 0.0)
                node.saturation = params.get("saturation", 0.0)
                node.lightness = params.get("lightness", 0.0)
            elif typ == "color_source":
                node = ColorSourceNode(nid, x, y)
                node.source_width = params.get("source_width", 512)
                node.source_height = params.get("source_height", 512)
                node.color = params.get("color", "#FFFFFFFF")
            elif typ == "gradient":
                node = GradientNode(nid, x, y)
                node.source_width = params.get("source_width", 512)
                node.source_height = params.get("source_height", 512)
                node.gradient_type = params.get("gradient_type", "linear")
                node.start_color = params.get("start_color", "#000000FF")
                node.end_color = params.get("end_color", "#FFFFFFFF")
                node.angle = params.get("angle", 0.0)
            elif typ == "noise":
                node = NoiseNode(nid, x, y)
                node.source_width = params.get("source_width", 512)
                node.source_height = params.get("source_height", 512)
                node.noise_type = params.get("noise_type", "gaussian")
                node.scale = params.get("scale", 64.0)
                node.seed = params.get("seed", -1)
            elif typ == "color_balance":
                node = ColorBalanceNode(nid, x, y)
                node.cyan_red = params.get("cyan_red", 0.0)
                node.magenta_green = params.get("magenta_green", 0.0)
                node.yellow_blue = params.get("yellow_blue", 0.0)
            elif typ == "exposure_gamma":
                node = ExposureGammaNode(nid, x, y)
                node.exposure = params.get("exposure", 0.0)
                node.gamma = params.get("gamma", 1.0)
            elif typ == "curves":
                node = CurvesNode(nid, x, y)
                node.shadows = params.get("shadows", 0.0)
                node.dark_midtones = params.get("dark_midtones", 64.0)
                node.midtones = params.get("midtones", 128.0)
                node.light_midtones = params.get("light_midtones", 192.0)
                node.highlights = params.get("highlights", 255.0)
            elif typ == "crop":
                node = CropNode(nid, x, y)
                node.crop_x = params.get("crop_x", 0.0)
                node.crop_y = params.get("crop_y", 0.0)
                node.crop_width = params.get("crop_width", 256.0)
                node.crop_height = params.get("crop_height", 256.0)
            elif typ == "resize":
                node = ResizeNode(nid, x, y)
                node.resize_width = params.get("resize_width", 512.0)
                node.resize_height = params.get("resize_height", 512.0)
                node.resize_mode = params.get("resize_mode", "stretch")
            elif typ == "rotate":
                node = RotateNode(nid, x, y)
                node.angle = params.get("angle", 0.0)
            elif typ == "flip":
                node = FlipNode(nid, x, y)
                node.direction = params.get("direction", "horizontal")
            elif typ == "distort":
                node = DistortNode(nid, x, y)
                node.dist_x0 = params.get("dist_x0", 0.0)
                node.dist_y0 = params.get("dist_y0", 0.0)
                node.dist_x1 = params.get("dist_x1", 512.0)
                node.dist_y1 = params.get("dist_y1", 0.0)
                node.dist_x2 = params.get("dist_x2", 512.0)
                node.dist_y2 = params.get("dist_y2", 512.0)
                node.dist_x3 = params.get("dist_x3", 0.0)
                node.dist_y3 = params.get("dist_y3", 512.0)
            elif typ == "blur":
                node = BlurNode(nid, x, y)
                node.radius = params.get("radius", 5.0)
            elif typ == "sharpen":
                node = SharpenNode(nid, x, y)
                node.amount = params.get("amount", 1.0)
                node.radius = params.get("radius", 2.0)
            elif typ == "edge_detect":
                node = EdgeDetectNode(nid, x, y)
                node.threshold = params.get("threshold", 0.0)
            elif typ == "opacity":
                node = OpacityNode(nid, x, y)
                node.opacity = params.get("opacity", 1.0)
            elif typ == "mask":
                node = MaskNode(nid, x, y)
                node.invert = params.get("invert", False)
                node.threshold = params.get("threshold", 0.5)
            elif typ == "constant":
                node = ConstantNode(nid, x, y)
                node.value = params.get("value", 0.0)
            elif typ in ("add", "subtract", "multiply", "divide"):
                cls = {"add": AddNode, "subtract": SubtractNode, "multiply": MultiplyNode, "divide": DivideNode}[typ]
                node = cls(nid, x, y)
            elif typ in ("ceil", "floor", "round", "sum", "product"):
                cls = {"ceil": CeilNode, "floor": FloorNode, "round": RoundNode, "sum": SumNode, "product": ProductNode}[typ]
                node = cls(nid, x, y)
            elif typ in ("not", "and", "or", "nand", "nor", "xor", "xnor"):
                cls = {"not": NotNode, "and": AndNode, "or": OrNode, "nand": NandNode, "nor": NorNode, "xor": XorNode, "xnor": XnorNode}[typ]
                node = cls(nid, x, y)
            elif typ == "compare":
                node = CompareNode(nid, x, y)
                node.operator = params.get("operator", "==")
            elif typ == "clamp":
                node = ClampNode(nid, x, y)
                node.min_val = params.get("min_val", 0.0)
                node.max_val = params.get("max_val", 1.0)
            elif typ == "map_range":
                node = MapRangeNode(nid, x, y)
                node.in_min = params.get("in_min", 0.0)
                node.in_max = params.get("in_max", 1.0)
                node.out_min = params.get("out_min", 0.0)
                node.out_max = params.get("out_max", 1.0)
            elif typ in ("modulo", "power"):
                cls = {"modulo": ModuloNode, "power": PowerNode}[typ]
                node = cls(nid, x, y)
            elif typ in ("square_root", "absolute", "log", "exp"):
                cls = {"square_root": SquareRootNode, "absolute": AbsoluteNode, "log": LogNode, "exp": ExpNode}[typ]
                node = cls(nid, x, y)
            elif typ == "random":
                node = RandomNode(nid, x, y)
                node.min_val = params.get("min_val", 0.0)
                node.max_val = params.get("max_val", 1.0)
                node.seed = params.get("seed")
            elif typ == "label":
                node = LabelNode(nid, x, y)
                node.text = params.get("text", _("Label"))
                node.color = params.get("color")
            elif typ == "comment":
                node = CommentNode(nid, x, y)
                node.text = params.get("text", _("Comment"))
                node.color = params.get("color")
            elif typ == "histogram":
                node = HistogramNode(nid, x, y)
            elif typ == "waveform_monitor":
                node = WaveformMonitorNode(nid, x, y)
            elif typ == "vectorscope":
                node = VectorscopeNode(nid, x, y)
            elif typ == "frequency_domain":
                node = FrequencyDomainNode(nid, x, y)
            if node:
                node.width = nd.get("width", node.width)
                node.height = nd.get("height", node.height)
                node.minimized = nd.get("minimized", False)
                label = nd.get("label")
                if label and typ not in ("input", "video_input", "raw_input"):
                    node.label = label
                graph._nodes[node.id] = node

        for ed in data.get("edges", []):
            edge = Edge(
                ed["id"], ed["src_node"], ed["src_port"],
                ed["dst_node"], ed["dst_port"],
            )
            graph._edges.append(edge)
            eid_num = int(ed["id"].lstrip("e") or "0")
            if eid_num > graph._edge_counter:
                graph._edge_counter = eid_num

        return graph
