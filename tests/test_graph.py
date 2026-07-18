from nodes import (
    NodeGraph, InputNode, OutputNode, FilterNode, BlendNode, ColorNode,
    OpacityNode, ColoringNode, MaskNode, ConstantNode,
    AddNode, SubtractNode, MultiplyNode, DivideNode,
    CeilNode, FloorNode, RoundNode, SumNode, ProductNode,
    LabelNode, CommentNode,
    Edge, Port, PortDirection, PortType, Node,
)
from models.filter import FilterDef, ParamDef


class TestPort:
    def test_construction(self):
        p = Port("n1", "image", "Image", PortDirection.INPUT, PortType.IMAGE)
        assert p.node_id == "n1"
        assert p.name == "image"
        assert p.label == "Image"
        assert p.direction == PortDirection.INPUT
        assert p.port_type == PortType.IMAGE

    def test_output_port(self):
        p = Port("n1", "out", "Output", PortDirection.OUTPUT, PortType.NUMERIC)
        assert p.direction == PortDirection.OUTPUT
        assert p.port_type == PortType.NUMERIC


class TestEdge:
    def test_construction(self):
        e = Edge("e1", "src", "out", "dst", "in")
        assert e.id == "e1"
        assert e.src_node == "src"
        assert e.src_port == "out"
        assert e.dst_node == "dst"
        assert e.dst_port == "in"


class TestNodeGraphConstruction:
    def test_empty_graph(self, empty_graph):
        assert len(empty_graph.nodes) == 0
        assert len(empty_graph.edges) == 0

    def test_add_node(self, empty_graph):
        n = InputNode("n1")
        empty_graph.add_node(n)
        assert empty_graph.get_node("n1") is n
        assert len(empty_graph.nodes) == 1

    def test_get_node_nonexistent(self, empty_graph):
        assert empty_graph.get_node("nope") is None

    def test_clear(self, empty_graph):
        empty_graph.add_node(InputNode("n1"))
        empty_graph.add_node(OutputNode("n2"))
        empty_graph.clear()
        assert len(empty_graph.nodes) == 0
        assert len(empty_graph.edges) == 0
        assert empty_graph._edge_counter == 0

    def test_remove_node(self, empty_graph):
        n1 = InputNode("n1")
        n2 = OutputNode("n2")
        empty_graph.add_node(n1)
        empty_graph.add_node(n2)
        empty_graph.add_edge("n1", "image", "n2", "image")
        assert len(empty_graph.edges) == 1
        empty_graph.remove_node("n1")
        assert empty_graph.get_node("n1") is None
        assert len(empty_graph.edges) == 0

    def test_remove_node_with_bypass_no_reconnect(self, empty_graph):
        n1 = InputNode("n1")
        n2 = OutputNode("n2")
        empty_graph.add_node(n1)
        empty_graph.add_node(n2)
        empty_graph.add_edge("n1", "image", "n2", "image")
        empty_graph.remove_node_with_bypass("n2")
        assert empty_graph.get_node("n2") is None
        assert len(empty_graph.edges) == 0

    def test_remove_nonexistent_node(self, empty_graph):
        empty_graph.remove_node("nope")
        assert len(empty_graph.nodes) == 0

    def test_remove_node_with_bypass_nonexistent(self, empty_graph):
        empty_graph.remove_node_with_bypass("nope")
        assert len(empty_graph.nodes) == 0


class TestEdges:
    def test_add_edge(self, empty_graph):
        n1 = InputNode("n1")
        n2 = OutputNode("n2")
        empty_graph.add_node(n1)
        empty_graph.add_node(n2)
        e = empty_graph.add_edge("n1", "image", "n2", "image")
        assert e is not None
        assert e.src_node == "n1"
        assert e.dst_node == "n2"
        assert len(empty_graph.edges) == 1

    def test_add_edge_type_mismatch(self, empty_graph):
        n1 = InputNode("n1")
        cn = ConstantNode("cn")
        empty_graph.add_node(n1)
        empty_graph.add_node(cn)
        e = empty_graph.add_edge("n1", "image", "cn", "value")
        assert e is None

    def test_add_edge_self_loop(self, empty_graph):
        n1 = InputNode("n1")
        empty_graph.add_node(n1)
        e = empty_graph.add_edge("n1", "image", "n1", "image")
        assert e is None

    def test_add_edge_duplicate_input(self, empty_graph):
        n1 = InputNode("n1")
        n2 = InputNode("n2")
        out = OutputNode("out")
        empty_graph.add_node(n1)
        empty_graph.add_node(n2)
        empty_graph.add_node(out)
        e1 = empty_graph.add_edge("n1", "image", "out", "image")
        assert e1 is not None
        e2 = empty_graph.add_edge("n2", "image", "out", "image")
        assert e2 is None

    def test_add_edge_nonexistent_node(self, empty_graph):
        e = empty_graph.add_edge("nope", "image", "nope2", "image")
        assert e is None

    def test_add_edge_nonexistent_port(self, empty_graph):
        n1 = InputNode("n1")
        out = OutputNode("out")
        empty_graph.add_node(n1)
        empty_graph.add_node(out)
        e = empty_graph.add_edge("n1", "nonexistent", "out", "image")
        assert e is None

    def test_remove_edge(self, empty_graph):
        n1 = InputNode("n1")
        n2 = OutputNode("n2")
        empty_graph.add_node(n1)
        empty_graph.add_node(n2)
        e = empty_graph.add_edge("n1", "image", "n2", "image")
        assert len(empty_graph.edges) == 1
        empty_graph.remove_edge(e.id)
        assert len(empty_graph.edges) == 0

    def test_remove_edges_for_port_input(self, empty_graph):
        n1 = InputNode("n1")
        out = OutputNode("out")
        empty_graph.add_node(n1)
        empty_graph.add_node(out)
        empty_graph.add_edge("n1", "image", "out", "image")
        empty_graph.remove_edges_for_port("out", "image", PortDirection.INPUT)
        assert len(empty_graph.edges) == 0

    def test_remove_edges_for_port_output(self, empty_graph):
        n1 = InputNode("n1")
        out = OutputNode("out")
        empty_graph.add_node(n1)
        empty_graph.add_node(out)
        empty_graph.add_edge("n1", "image", "out", "image")
        empty_graph.remove_edges_for_port("n1", "image", PortDirection.OUTPUT)
        assert len(empty_graph.edges) == 0

    def test_get_incoming_edges(self, empty_graph):
        n1 = InputNode("n1")
        flt = FilterNode("flt", FilterDef(name="f", gmic_command="f"))
        n2 = OutputNode("n2")
        empty_graph.add_node(n1)
        empty_graph.add_node(flt)
        empty_graph.add_node(n2)
        empty_graph.add_edge("n1", "image", "flt", "image")
        empty_graph.add_edge("flt", "image", "n2", "image")
        incoming = empty_graph.get_incoming_edges("flt")
        assert len(incoming) == 1
        assert incoming[0].src_node == "n1"

    def test_get_outgoing_edges(self, empty_graph):
        n1 = InputNode("n1")
        out = OutputNode("out")
        empty_graph.add_node(n1)
        empty_graph.add_node(out)
        empty_graph.add_edge("n1", "image", "out", "image")
        outgoing = empty_graph.get_outgoing_edges("n1")
        assert len(outgoing) == 1
        assert outgoing[0].dst_node == "out"

    def test_get_connected_input(self, empty_graph):
        n1 = InputNode("n1")
        out = OutputNode("out")
        empty_graph.add_node(n1)
        empty_graph.add_node(out)
        empty_graph.add_edge("n1", "image", "out", "image")
        e = empty_graph.get_connected_input("out", "image")
        assert e is not None
        assert e.src_node == "n1"

    def test_get_connected_input_none(self, empty_graph):
        out = OutputNode("out")
        empty_graph.add_node(out)
        assert empty_graph.get_connected_input("out", "image") is None


class TestCycleDetection:
    def test_no_cycle_simple(self, empty_graph):
        n1 = InputNode("n1")
        n2 = OutputNode("n2")
        empty_graph.add_node(n1)
        empty_graph.add_node(n2)
        assert not empty_graph._would_create_cycle("n1", "n2")

    def test_no_cycle_chain(self, empty_graph):
        n1 = InputNode("n1")
        n2 = FilterNode("n2", FilterDef(name="f", gmic_command="f"))
        n3 = OutputNode("n3")
        empty_graph.add_node(n1)
        empty_graph.add_node(n2)
        empty_graph.add_node(n3)
        empty_graph.add_edge("n1", "image", "n2", "image")
        empty_graph.add_edge("n2", "image", "n3", "image")
        assert not empty_graph._would_create_cycle("n1", "n3")

    def test_cycle_detected(self, empty_graph):
        n1 = FilterNode("n1", FilterDef(name="f1", gmic_command="f1"))
        n2 = FilterNode("n2", FilterDef(name="f2", gmic_command="f2"))
        n3 = OutputNode("n3")
        empty_graph.add_node(n1)
        empty_graph.add_node(n2)
        empty_graph.add_node(n3)
        empty_graph.add_edge("n1", "image", "n2", "image")
        empty_graph.add_edge("n2", "image", "n3", "image")
        assert empty_graph._would_create_cycle("n3", "n1")

    def test_disconnected_no_cycle(self, empty_graph):
        n1 = InputNode("n1")
        n2 = OutputNode("n2")
        n3 = InputNode("n3")
        n4 = OutputNode("n4")
        empty_graph.add_node(n1)
        empty_graph.add_node(n2)
        empty_graph.add_node(n3)
        empty_graph.add_node(n4)
        empty_graph.add_edge("n1", "image", "n2", "image")
        empty_graph.add_edge("n3", "image", "n4", "image")
        assert not empty_graph._would_create_cycle("n1", "n4")


class TestTopologicalSort:
    def test_simple_chain(self, empty_graph):
        n1 = InputNode("n1")
        n2 = FilterNode("n2", FilterDef(name="f", gmic_command="f"))
        n3 = OutputNode("n3")
        empty_graph.add_node(n1)
        empty_graph.add_node(n2)
        empty_graph.add_node(n3)
        empty_graph.add_edge("n1", "image", "n2", "image")
        empty_graph.add_edge("n2", "image", "n3", "image")
        order = empty_graph.topological_sort()
        assert [n.id for n in order] == ["n1", "n2", "n3"]

    def test_empty_graph_order(self, empty_graph):
        assert empty_graph.topological_sort() == []

    def test_disconnected_nodes(self, empty_graph):
        empty_graph.add_node(InputNode("n1"))
        empty_graph.add_node(OutputNode("n2"))
        order = empty_graph.topological_sort()
        ids = [n.id for n in order]
        assert "n1" in ids
        assert "n2" in ids

    def test_cycle_returns_empty(self, empty_graph):
        n1 = InputNode("n1")
        n2 = OutputNode("n2")
        n3 = OutputNode("n3")
        empty_graph.add_node(n1)
        empty_graph.add_node(n2)
        empty_graph.add_node(n3)
        empty_graph._edges = [
            Edge("e1", "n1", "image", "n2", "image"),
            Edge("e2", "n2", "image", "n3", "image"),
            Edge("e3", "n3", "image", "n1", "image"),
        ]
        assert empty_graph.topological_sort() == []

    def test_branching_graph(self, empty_graph):
        inp = InputNode("in")
        flt1 = FilterNode("f1", FilterDef(name="f1", gmic_command="f1"))
        flt2 = FilterNode("f2", FilterDef(name="f2", gmic_command="f2"))
        out = OutputNode("out")
        empty_graph.add_node(inp)
        empty_graph.add_node(flt1)
        empty_graph.add_node(flt2)
        empty_graph.add_node(out)
        empty_graph.add_edge("in", "image", "f1", "image")
        empty_graph.add_edge("in", "image", "f2", "image")
        empty_graph.add_edge("f1", "image", "out", "image")
        empty_graph.add_edge("f2", "image", "out", "image")
        order = empty_graph.topological_sort()
        ids = [n.id for n in order]
        assert ids[0] == "in"
        assert ids[-1] == "out"
        assert set(ids[1:3]) == {"f1", "f2"}

    def test_numeric_graph(self, empty_graph):
        const = ConstantNode("c")
        add = AddNode("a")
        empty_graph.add_node(const)
        empty_graph.add_node(add)
        empty_graph.add_edge("c", "value", "a", "a")
        empty_graph.add_edge("c", "value", "a", "b")
        order = empty_graph.topological_sort()
        ids = [n.id for n in order]
        assert ids[0] == "c"
        assert ids[1] == "a"
        assert len(ids) == 2


class TestBypassReconnect:
    def test_bypass_reconnects_nodes(self, empty_graph):
        inp = InputNode("in")
        flt = FilterNode("flt", FilterDef(name="f", gmic_command="f"))
        out = OutputNode("out")
        empty_graph.add_node(inp)
        empty_graph.add_node(flt)
        empty_graph.add_node(out)
        empty_graph.add_edge("in", "image", "flt", "image")
        empty_graph.add_edge("flt", "image", "out", "image")
        empty_graph.remove_node_with_bypass("flt")
        assert empty_graph.get_node("flt") is None
        assert len(empty_graph.edges) == 1
        assert empty_graph.edges[0].src_node == "in"
        assert empty_graph.edges[0].dst_node == "out"

    def test_bypass_no_reconnect_on_type_mismatch(self, empty_graph):
        flt = FilterNode("flt", FilterDef(name="f", gmic_command="f"))
        cn = ConstantNode("cn")
        out = OutputNode("out")
        empty_graph.add_node(flt)
        empty_graph.add_node(cn)
        empty_graph.add_node(out)
        empty_graph.add_edge("cn", "value", "flt", "strength")
        empty_graph.add_edge("flt", "image", "out", "image")
        empty_graph.remove_node_with_bypass("flt")
        assert len(empty_graph.edges) == 0

    def test_bypass_skips_if_node_missing(self, empty_graph):
        empty_graph.remove_node_with_bypass("nope")
        assert len(empty_graph.nodes) == 0

    def test_bypass_with_multiple_connections(self, empty_graph):
        inp = InputNode("in")
        blend = BlendNode("bl", "over")
        out1 = OutputNode("o1")
        out2 = OutputNode("o2")
        empty_graph.add_node(inp)
        empty_graph.add_node(blend)
        empty_graph.add_node(out1)
        empty_graph.add_node(out2)
        empty_graph.add_edge("in", "image", "bl", "base")
        empty_graph.add_edge("in", "image", "bl", "blend")
        empty_graph.add_edge("bl", "image", "o1", "image")
        empty_graph.add_edge("bl", "image", "o2", "image")
        empty_graph.remove_node_with_bypass("bl")
        assert empty_graph.get_node("bl") is None
        assert len(empty_graph.edges) == 2
        assert all(e.src_node == "in" for e in empty_graph.edges)


class TestCacheDirty:
    def test_new_node_is_dirty(self, empty_graph):
        n = InputNode("n1")
        empty_graph.add_node(n)
        assert n.cache_dirty is True

    def test_add_edge_marks_dst_dirty(self, empty_graph):
        n1 = InputNode("n1")
        n2 = FilterNode("n2", FilterDef(name="f", gmic_command="f"))
        n2.cache_dirty = False
        empty_graph.add_node(n1)
        empty_graph.add_node(n2)
        empty_graph.add_edge("n1", "image", "n2", "image")
        assert n2.cache_dirty is True

    def test_remove_edge_marks_dst_dirty(self, empty_graph):
        n1 = InputNode("n1")
        n2 = OutputNode("n2")
        empty_graph.add_node(n1)
        empty_graph.add_node(n2)
        e = empty_graph.add_edge("n1", "image", "n2", "image")
        n2.cache_dirty = False
        empty_graph.remove_edge(e.id)
        assert n2.cache_dirty is True


class TestSerialization:
    def test_to_dict_round_trip(self, empty_graph):
        inp = InputNode("in")
        inp.file_path = "/path/to/img.png"
        out = OutputNode("out")
        empty_graph.add_node(inp)
        empty_graph.add_node(out)
        empty_graph.add_edge("in", "image", "out", "image")
        data = empty_graph.to_dict()
        assert data["version"] == 1
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1
        graph2 = NodeGraph.from_dict(data)
        assert len(graph2.nodes) == 2
        assert graph2.get_node("in") is not None
        assert graph2.get_node("out") is not None
        assert len(graph2.edges) == 1

    def test_to_dict_input_node_params(self, empty_graph):
        inp = InputNode("in")
        inp.file_path = "/photos/test.png"
        empty_graph.add_node(inp)
        data = empty_graph.to_dict()
        nd = data["nodes"][0]
        assert nd["type"] == "input"
        assert nd["params"]["file_path"] == "/photos/test.png"

    def test_to_dict_output_node(self, empty_graph):
        out = OutputNode("out")
        empty_graph.add_node(out)
        data = empty_graph.to_dict()
        assert data["nodes"][0]["type"] == "output"

    def test_to_dict_constant_node(self, empty_graph):
        cn = ConstantNode("cn")
        cn.value = 42.0
        empty_graph.add_node(cn)
        data = empty_graph.to_dict()
        assert data["nodes"][0]["params"]["value"] == 42.0

    def test_from_dict_label_node(self):
        data = {
            "version": 1,
            "nodes": [{"id": "l1", "type": "label", "label": "Note", "x": 0, "y": 0, "width": 150, "height": 80, "params": {"text": "Hello", "color": "#ff0"}}],
            "edges": []
        }
        graph = NodeGraph.from_dict(data)
        node = graph.get_node("l1")
        assert node is not None
        assert node.text == "Hello"
        assert node.color == "#ff0"

    def test_from_dict_comment_node(self):
        data = {
            "version": 1,
            "nodes": [{"id": "c1", "type": "comment", "label": "Note", "x": 0, "y": 0, "width": 150, "height": 80, "params": {"text": "TODO", "color": "#0ff"}}],
            "edges": []
        }
        graph = NodeGraph.from_dict(data)
        node = graph.get_node("c1")
        assert node is not None
        assert node.text == "TODO"
        assert node.color == "#0ff"

    def test_from_dict_blend_node_with_extra_ports(self):
        data = {
            "version": 1,
            "nodes": [{"id": "b1", "type": "blend", "label": "Blend", "x": 0, "y": 0, "width": 200, "height": 120, "params": {"mode": "multiply", "extra_ports": 3}}],
            "edges": []
        }
        graph = NodeGraph.from_dict(data)
        node = graph.get_node("b1")
        assert node is not None
        assert node.mode == "multiply"

    def test_from_dict_filter_node_skips_missing_def(self):
        data = {
            "version": 1,
            "nodes": [{"id": "f1", "type": "filter", "label": "F", "x": 0, "y": 0, "width": 200, "height": 120, "params": {"filter_key": "gmic:nonexistent_filter"}}],
            "edges": []
        }
        graph = NodeGraph.from_dict(data, filter_def_map={})
        assert graph.get_node("f1") is None

    def test_from_dict_preserves_positions(self):
        data = {
            "version": 1,
            "nodes": [{"id": "n1", "type": "output", "label": "Out", "x": 350.0, "y": 200.0, "width": 180, "height": 70, "params": {}}],
            "edges": []
        }
        graph = NodeGraph.from_dict(data)
        node = graph.get_node("n1")
        assert node.x == 350.0
        assert node.y == 200.0

    def test_from_dict_restores_edges(self):
        data = {
            "version": 1,
            "nodes": [
                {"id": "n1", "type": "input", "label": "In", "x": 0, "y": 0, "width": 180, "height": 80, "params": {"file_path": None}},
                {"id": "n2", "type": "output", "label": "Out", "x": 200, "y": 0, "width": 180, "height": 70, "params": {}},
            ],
            "edges": [{"id": "e1", "src_node": "n1", "src_port": "image", "dst_node": "n2", "dst_port": "image"}]
        }
        graph = NodeGraph.from_dict(data)
        assert len(graph.edges) == 1
        assert graph.edges[0].src_node == "n1"

    def test_edge_counter_restored(self):
        data = {
            "version": 1,
            "nodes": [
                {"id": "n1", "type": "input", "label": "In", "x": 0, "y": 0, "width": 180, "height": 80, "params": {}},
                {"id": "n2", "type": "output", "label": "Out", "x": 200, "y": 0, "width": 180, "height": 70, "params": {}},
            ],
            "edges": [{"id": "e42", "src_node": "n1", "src_port": "image", "dst_node": "n2", "dst_port": "image"}]
        }
        graph = NodeGraph.from_dict(data)
        assert graph._edge_counter >= 42

    def test_to_dict_all_node_types(self, empty_graph):
        empty_graph.add_node(InputNode("in"))
        empty_graph.add_node(OutputNode("out"))
        empty_graph.add_node(BlendNode("bl", "over"))
        empty_graph.add_node(ColorNode("col"))
        empty_graph.add_node(OpacityNode("op"))
        empty_graph.add_node(ColoringNode("colr"))
        empty_graph.add_node(MaskNode("mask"))
        empty_graph.add_node(ConstantNode("cnst"))
        empty_graph.add_node(AddNode("add"))
        empty_graph.add_node(SubtractNode("sub"))
        empty_graph.add_node(MultiplyNode("mul"))
        empty_graph.add_node(DivideNode("div"))
        empty_graph.add_node(CeilNode("ceil"))
        empty_graph.add_node(FloorNode("floor"))
        empty_graph.add_node(RoundNode("round"))
        empty_graph.add_node(SumNode("sum"))
        empty_graph.add_node(ProductNode("prod"))
        empty_graph.add_node(LabelNode("lbl"))
        empty_graph.add_node(CommentNode("cmt"))
        data = empty_graph.to_dict()
        types = {nd["type"] for nd in data["nodes"]}
        assert types == {
            "input", "output", "blend", "color", "opacity",
            "coloring", "mask", "constant", "add", "subtract",
            "multiply", "divide", "ceil", "floor", "round",
            "sum", "product", "label", "comment",
        }
