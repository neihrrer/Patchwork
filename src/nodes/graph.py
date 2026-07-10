from enum import Enum, auto
from typing import Any, Optional


class PortDirection(Enum):
    INPUT = auto()
    OUTPUT = auto()


class PortType(Enum):
    IMAGE = auto()


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

    def add_node(self, node: Node):
        self._nodes[node.id] = node

    def remove_node(self, node_id: str):
        self._nodes.pop(node_id, None)
        self._edges = [e for e in self._edges
                       if e.src_node != node_id and e.dst_node != node_id]

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
        for e in self._edges:
            if e.dst_node == dst_node and e.dst_port == dst_port:
                return None
        self._edge_counter += 1
        edge = Edge(f"e{self._edge_counter}", src_node, src_port, dst_node, dst_port)
        self._edges.append(edge)
        return edge

    def remove_edge(self, edge_id: str):
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
                "params": {},
            }
            from nodes.node_types import (
                InputNode, FilterNode, BlendNode, ColorNode,
                OpacityNode, ColoringNode, MaskNode,
            )
            if isinstance(n, InputNode):
                nd["params"]["file_path"] = n.file_path
            elif isinstance(n, FilterNode):
                nd["params"]["filter_key"] = f"{n.filter_def.engine}:{n.filter_def.name}"
                nd["params"]["param_values"] = dict(n.param_values)
            elif isinstance(n, BlendNode):
                nd["params"]["mode"] = n.mode
                nd["params"]["extra_ports"] = len(n.inputs) - 2
            elif isinstance(n, ColorNode):
                nd["params"]["operation"] = n.operation
                nd["params"]["brightness"] = n.brightness
                nd["params"]["contrast"] = n.contrast
                nd["params"]["saturation"] = n.saturation
                nd["params"]["hue"] = n.hue
            elif isinstance(n, OpacityNode):
                nd["params"]["opacity"] = n.opacity
            elif isinstance(n, ColoringNode):
                nd["params"]["hue"] = n.hue
                nd["params"]["saturation"] = n.saturation
                nd["params"]["lightness"] = n.lightness
            elif isinstance(n, MaskNode):
                nd["params"]["invert"] = n.invert
                nd["params"]["threshold"] = n.threshold
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
            InputNode, OutputNode, FilterNode, BlendNode, ColorNode,
            OpacityNode, ColoringNode, MaskNode,
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
            elif typ == "blend":
                mode = params.get("mode", "over")
                node = BlendNode(nid, mode, x, y)
                extra = params.get("extra_ports", 0)
                for _ in range(extra):
                    node.add_input_port()
            elif typ == "color":
                node = ColorNode(nid, x, y)
                node.operation = params.get("operation", "brightness_contrast")
                node.brightness = params.get("brightness", 0.0)
                node.contrast = params.get("contrast", 0.0)
                node.saturation = params.get("saturation", 0.0)
                node.hue = params.get("hue", 0.0)
            elif typ == "opacity":
                node = OpacityNode(nid, x, y)
                node.opacity = params.get("opacity", 1.0)
            elif typ == "coloring":
                node = ColoringNode(nid, x, y)
                node.hue = params.get("hue", 0.0)
                node.saturation = params.get("saturation", 0.0)
                node.lightness = params.get("lightness", 0.0)
            elif typ == "mask":
                node = MaskNode(nid, x, y)
                node.invert = params.get("invert", False)
                node.threshold = params.get("threshold", 0.5)
            if node:
                node.width = nd.get("width", node.width)
                node.height = nd.get("height", node.height)
                label = nd.get("label")
                if label and typ != "input":
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
