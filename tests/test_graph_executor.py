from unittest.mock import MagicMock, patch

from nodes import NodeGraph, InputNode, OutputNode, ConstantNode
from nodes import (
    AddNode, SubtractNode, DivideNode,
)


def make_executor():
    gmic = MagicMock()
    gmic.available = True
    im = MagicMock()
    im.available = True
    from processing.graph_executor import GraphExecutor
    return GraphExecutor(gmic, im)


class TestGraphExecutorCoreLogic:
    def test_empty_graph_fails(self):
        executor = make_executor()
        from nodes import NodeGraph
        result = executor.execute(NodeGraph(), "png")
        assert result.success is False

    def test_cyclic_graph_fails(self):
        executor = make_executor()
        graph = NodeGraph()
        n1 = InputNode("n1")
        n2 = OutputNode("n2")
        n3 = OutputNode("n3")
        graph.add_node(n1)
        graph.add_node(n2)
        graph.add_node(n3)
        from nodes import Edge
        graph._edges = [
            Edge("e1", "n1", "image", "n2", "image"),
            Edge("e2", "n2", "image", "n3", "image"),
            Edge("e3", "n3", "image", "n1", "image"),
        ]
        result = executor.execute(graph, "png")
        assert result.success is False

    def test_input_node_no_file_fails(self):
        executor = make_executor()
        graph = NodeGraph()
        inp = InputNode("in")
        out = OutputNode("out")
        graph.add_node(inp)
        graph.add_node(out)
        graph.add_edge("in", "image", "out", "image")
        result = executor.execute(graph, "png")
        assert result.success is False

    def test_numeric_graphs_produce_no_image_output(self):
        executor = make_executor()
        graph = NodeGraph()
        c1 = ConstantNode("c1")
        c1.value = 10.0
        c2 = ConstantNode("c2")
        c2.value = 20.0
        add = AddNode("add")
        graph.add_node(c1)
        graph.add_node(c2)
        graph.add_node(add)
        graph.add_edge("c1", "value", "add", "a")
        graph.add_edge("c2", "value", "add", "b")
        result = executor.execute(graph, "png")
        assert result.success is False

    def test_output_node_passthrough_needs_real_image(self, graph_with_filter, tmp_path):
        executor = make_executor()
        out_path = tmp_path / "out.png"
        out_path.write_text("fake")
        executor._gmic.run_pipeline.return_value = MagicMock(
            success=True, output_path=str(out_path), error="",
            stdout="", stderr=""
        )
        with patch("os.path.isfile", return_value=True):
            result = executor.execute(graph_with_filter, "png")
            assert result.success is True

    def test_executor_handles_timeout(self, graph_with_filter):
        executor = make_executor()
        executor._gmic.run_pipeline.return_value = MagicMock(
            success=False, error="Processing timed out"
        )
        with patch("os.path.isfile", return_value=True):
            result = executor.execute(graph_with_filter, "png", timeout=1)
        assert result.success is False

    def test_subtract_node_no_crash(self):
        executor = make_executor()
        graph = NodeGraph()
        c1 = ConstantNode("c1")
        c1.value = 30.0
        c2 = ConstantNode("c2")
        c2.value = 10.0
        sub = SubtractNode("sub")
        graph.add_node(c1)
        graph.add_node(c2)
        graph.add_node(sub)
        graph.add_edge("c1", "value", "sub", "a")
        graph.add_edge("c2", "value", "sub", "b")
        result = executor.execute(graph, "png")
        assert result.success is False
        assert "output" in (result.error or "").lower()

    def test_divide_by_zero(self):
        executor = make_executor()
        graph = NodeGraph()
        c1 = ConstantNode("c1")
        c1.value = 10.0
        c2 = ConstantNode("c2")
        c2.value = 0.0
        div = DivideNode("div")
        graph.add_node(c1)
        graph.add_node(c2)
        graph.add_node(div)
        graph.add_edge("c1", "value", "div", "a")
        graph.add_edge("c2", "value", "div", "b")
        result = executor.execute(graph, "png")
        assert result.success is False
        assert "zero" in (result.error or "").lower()


class TestHelperMethods:
    def test_first_input_finds_connected(self, simple_graph):
        executor = make_executor()
        outputs = {"n1": "/tmp/n1.png"}
        with patch("os.path.isfile", return_value=True):
            result = executor._first_input(
                simple_graph.get_node("n2"), simple_graph, outputs
            )
            assert result == "/tmp/n1.png"

    def test_first_input_none_when_disconnected(self, empty_graph):
        executor = make_executor()
        out = OutputNode("out")
        empty_graph.add_node(out)
        result = executor._first_input(out, empty_graph, {})
        assert result is None

    def test_get_numeric_input_finds_value(self, empty_graph):
        executor = make_executor()
        c = ConstantNode("c")
        c.value = 42.0
        add = AddNode("add")
        empty_graph.add_node(c)
        empty_graph.add_node(add)
        empty_graph.add_edge("c", "value", "add", "a")
        numeric_outputs = {"c": 42.0}
        result = executor._get_numeric_input(add, "a", empty_graph, numeric_outputs)
        assert result == 42.0

    def test_get_numeric_input_not_connected(self, empty_graph):
        executor = make_executor()
        add = AddNode("add")
        empty_graph.add_node(add)
        result = executor._get_numeric_input(add, "a", empty_graph, {})
        assert result is None
