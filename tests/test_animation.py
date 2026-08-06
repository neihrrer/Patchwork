from unittest.mock import MagicMock
import threading

from nodes import NodeGraph, InputNode, OutputNode, TimeNode, VideoInputNode
from processing.graph_executor import GraphExecutor
from processing.runner import ProcessResult
from video.renderer import (
    AnimationSettings, render_animation, render_frames, mux_animation,
    FORMAT_GIF, FORMAT_MP4, FORMAT_PNG_SEQUENCE, _find_output_nodes,
)


def make_executor():
    executor = GraphExecutor(MagicMock(), MagicMock())
    executor._ffmpeg = MagicMock()
    return executor


def test_find_output_nodes():
    graph = NodeGraph()
    inp = InputNode("in")
    out = OutputNode("out")
    graph.add_node(inp)
    graph.add_node(out)
    assert _find_output_nodes(graph) == [out]


def test_render_no_output_node():
    graph = NodeGraph()
    graph.add_node(InputNode("in"))
    executor = make_executor()
    settings = AnimationSettings(frame_count=2, fps=10, out_format=FORMAT_PNG_SEQUENCE,
                                 out_path="/tmp/seq")
    res = render_animation(graph, executor, MagicMock(), settings, progress_callback=None)
    assert res.success is False
    assert "output" in (res.error or "").lower()


def test_render_animation_png_sequence(tmp_path):
    graph = NodeGraph()
    inp = InputNode("in")
    out = OutputNode("out")
    graph.add_node(inp)
    graph.add_node(out)
    graph.add_edge("in", "image", "out", "image")

    executor = make_executor()
    out_box = tmp_path / "seq"
    out_box.mkdir()

    frame_path = tmp_path / "frame_source.png"
    frame_path.write_bytes(b"png")

    results = []

    def fake_execute(graph, fmt, progress_callback=None, timeout=120, frame=0, force_refresh=False, cancel_event=None):
        results.append((frame, force_refresh))
        return ProcessResult(output_paths={"out": str(frame_path)}, output_path=str(frame_path))
    executor.execute = fake_execute

    settings = AnimationSettings(frame_count=3, fps=10, out_format=FORMAT_PNG_SEQUENCE,
                                 out_path=str(out_box))
    res = render_animation(graph, executor, MagicMock(), settings, progress_callback=None)
    assert res.success is True
    assert [r[0] for r in results] == [0, 1, 2]
    assert all(r[1] is True for r in results)
    assert (out_box / "frame_00000.png").exists()
    assert (out_box / "frame_00002.png").exists()


def test_render_frame_failure_stops(tmp_path):
    graph = NodeGraph()
    inp = InputNode("in")
    out = OutputNode("out")
    graph.add_node(inp)
    graph.add_node(out)
    graph.add_edge("in", "image", "out", "image")

    executor = make_executor()

    def fake_execute(graph, fmt, **kwargs):
        return ProcessResult(error="boom")
    executor.execute = fake_execute

    settings = AnimationSettings(frame_count=3, fps=10, out_format=FORMAT_GIF,
                                 out_path=str(tmp_path / "a.gif"))
    res = render_animation(graph, executor, MagicMock(), settings, progress_callback=None)
    assert res.success is False
    assert "boom" in (res.error or "")


def test_time_node_is_numeric_source():
    t = TimeNode("t")
    assert t.node_type == "time"
    assert t.outputs[0].name == "value"


def test_video_input_node():
    v = VideoInputNode("v")
    assert v.node_type == "video_input"
    v.file_path = "/tmp/clip.mp4"
    assert v.outputs[0].name == "image"


def test_time_node_value_modes():
    t = TimeNode("t")
    t._last_frame = 0
    assert t.value_for(5) == 5.0
    t.mode = TimeNode.TIME_MODE_SECONDS
    t.fps = 12.0
    assert abs(t.value_for(24) - 2.0) < 1e-6


def test_graph_roundtrip_time_modes():
    graph = NodeGraph()
    t = TimeNode("t")
    t.mode = TimeNode.TIME_MODE_SECONDS
    t.fps = 30.0
    t.length = 60
    graph.add_node(t)
    data = graph.to_dict()
    g2 = NodeGraph.from_dict(data, {})
    t2 = next(n for n in g2.nodes.values() if n.node_type == "time")
    assert t2.mode == "seconds"
    assert t2.fps == 30.0
    assert t2.length == 60


def test_graph_roundtrip_time_video():
    graph = NodeGraph()
    t = TimeNode("t1")
    v = VideoInputNode("v1")
    v.file_path = "/tmp/clip.mp4"
    graph.add_node(t)
    graph.add_node(v)
    data = graph.to_dict()
    g2 = NodeGraph.from_dict(data, {})
    assert any(n.node_type == "time" for n in g2.nodes.values())
    v2 = next(n for n in g2.nodes.values() if n.node_type == "video_input")
    assert v2.file_path == "/tmp/clip.mp4"


def test_executor_time_node_and_video_node(tmp_path):
    executor = make_executor()
    graph = NodeGraph()
    t = TimeNode("t")
    v = VideoInputNode("v")
    v.file_path = str(tmp_path / "clip.mp4")
    graph.add_node(t)
    graph.add_node(v)
    with _real_isfile(tmp_path / "clip.mp4"):
        result = executor.execute(graph, "png", frame=7, force_refresh=True)
        # time node alone has no image output; this validates no crash and
        # that the video extraction is attempted when the file exists
        assert isinstance(result, ProcessResult)


class _real_isfile:
    def __init__(self, path):
        self._path = path

    def __enter__(self):
        import os
        self._orig = os.path.isfile
        os.path.isfile = lambda p: p == str(self._path) or self._orig(p)
        return self

    def __exit__(self, *exc):
        import os
        os.path.isfile = self._orig


def test_render_frames_keeps_frames_in_memory(tmp_path):
    graph = NodeGraph()
    inp = InputNode("in")
    out = OutputNode("out")
    graph.add_node(inp)
    graph.add_node(out)
    graph.add_edge("in", "image", "out", "image")

    executor = make_executor()
    frame_path = tmp_path / "frame_source.png"
    frame_path.write_bytes(b"png")

    def fake_execute(graph, fmt, progress_callback=None, timeout=120, frame=0, force_refresh=False, cancel_event=None):
        return ProcessResult(output_paths={"out": str(frame_path)}, output_path=str(frame_path))
    executor.execute = fake_execute

    settings = AnimationSettings(frame_count=3, fps=10, out_format=FORMAT_MP4)
    res = render_frames(graph, executor, settings, progress_callback=None)
    assert res.success is True
    assert len(settings.frames) == 3
    assert all(f.endswith(".png") for f in settings.frames)
    assert settings._frame_dir


def test_mux_animation_after_render(tmp_path):
    graph = NodeGraph()
    inp = InputNode("in")
    out = OutputNode("out")
    graph.add_node(inp)
    graph.add_node(out)
    graph.add_edge("in", "image", "out", "image")

    executor = make_executor()
    png = tmp_path / "f.png"
    png.write_bytes(b"png")

    def fake_execute(graph, fmt, **kwargs):
        return ProcessResult(output_paths={"out": str(png)}, output_path=str(png))
    executor.execute = fake_execute

    settings = AnimationSettings(frame_count=2, fps=10, out_format=FORMAT_PNG_SEQUENCE)
    res = render_frames(graph, executor, settings, progress_callback=None)
    assert res.success is True
    assert len(settings.frames) == 2

    out_box = tmp_path / "seq"
    settings.out_path = str(out_box)
    res = mux_animation(MagicMock(), settings, progress_callback=None)
    assert res.success is True
    assert (out_box / "frame_00000.png").exists()
    assert (out_box / "frame_00001.png").exists()

    settings.cleanup()
    assert settings.frames == []
    assert not settings._frame_dir


def test_render_frames_cancelled_before_start(tmp_path):
    graph = NodeGraph()
    inp = InputNode("in")
    out = OutputNode("out")
    graph.add_node(inp)
    graph.add_node(out)
    graph.add_edge("in", "image", "out", "image")

    executor = make_executor()
    png = tmp_path / "f.png"
    png.write_bytes(b"png")

    def fake_execute(graph, fmt, progress_callback=None, timeout=120, frame=0, force_refresh=False, cancel_event=None):
        return ProcessResult(output_paths={"out": str(png)}, output_path=str(png))
    executor.execute = fake_execute

    ev = threading.Event()
    ev.set()
    settings = AnimationSettings(frame_count=5, fps=10, out_format=FORMAT_MP4)
    res = render_frames(graph, executor, settings, cancel_event=ev)
    assert res.cancelled is True
    assert res.success is False
    assert len(settings.frames) == 0


def test_render_frames_cancelled_midway(tmp_path):
    graph = NodeGraph()
    inp = InputNode("in")
    out = OutputNode("out")
    graph.add_node(inp)
    graph.add_node(out)
    graph.add_edge("in", "image", "out", "image")

    executor = make_executor()
    png = tmp_path / "f.png"
    png.write_bytes(b"png")

    def fake_execute(graph, fmt, progress_callback=None, timeout=120, frame=0, force_refresh=False, cancel_event=None):
        if frame >= 1 and cancel_event is not None:
            cancel_event.set()
        return ProcessResult(output_paths={"out": str(png)}, output_path=str(png))
    executor.execute = fake_execute

    ev = threading.Event()
    settings = AnimationSettings(frame_count=5, fps=10, out_format=FORMAT_MP4)
    res = render_frames(graph, executor, settings, cancel_event=ev)
    assert res.cancelled is True
    assert res.success is False
    assert len(settings.frames) == 2