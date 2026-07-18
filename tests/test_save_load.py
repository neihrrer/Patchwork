import json
import zipfile
import io
from pathlib import Path
from unittest.mock import patch

import pytest


class TestSaveRing:
    def test_save_plain_json_no_images(self, tmp_path, empty_graph):
        from window import RingWindow
        path = tmp_path / "project.ring"
        RingWindow._save_ring_to_path(str(path), empty_graph)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["version"] == 1
        assert data["nodes"] == []

    def test_save_zip_with_images(self, tmp_path, test_image):
        from window import RingWindow
        from nodes import NodeGraph, InputNode
        graph = NodeGraph()
        inp = InputNode("in")
        inp.file_path = test_image
        graph.add_node(inp)
        path = tmp_path / "project.ring"
        RingWindow._save_ring_to_path(str(path), graph)
        assert zipfile.is_zipfile(path)
        with zipfile.ZipFile(path, "r") as zf:
            assert "graph.json" in zf.namelist()
            assert "images/in.png" in zf.namelist()
            data = json.loads(zf.read("graph.json"))
            assert data["nodes"][0]["params"]["file_path"] == test_image

    def test_save_no_input_nodes_is_json(self, tmp_path):
        from window import RingWindow
        from nodes import NodeGraph, OutputNode
        graph = NodeGraph()
        graph.add_node(OutputNode("out"))
        path = tmp_path / "project.ring"
        RingWindow._save_ring_to_path(str(path), graph)
        assert not zipfile.is_zipfile(path)
        data = json.loads(path.read_text())
        assert len(data["nodes"]) == 1

    def test_input_node_without_file_skips_packing(self, tmp_path):
        from window import RingWindow
        from nodes import NodeGraph, InputNode
        graph = NodeGraph()
        inp = InputNode("in")
        graph.add_node(inp)
        path = tmp_path / "project.ring"
        RingWindow._save_ring_to_path(str(path), graph)
        assert not zipfile.is_zipfile(path)


class TestLoadRing:
    def test_load_plain_json(self, tmp_path):
        from window import RingWindow
        path = tmp_path / "project.ring"
        data = {"version": 1, "nodes": [], "edges": []}
        path.write_text(json.dumps(data))
        result, pack_dir = RingWindow._load_ring_from_path(str(path))
        assert result["version"] == 1
        assert pack_dir is None

    def test_load_zip_extracts_images(self, tmp_path):
        from window import RingWindow
        path = tmp_path / "project.ring"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("graph.json", json.dumps({
                "version": 1, "nodes": [], "edges": []
            }))
            zf.writestr("images/test.png", b"pretend png data")
        path.write_bytes(buf.getvalue())
        result, pack_dir = RingWindow._load_ring_from_path(str(path))
        assert result["version"] == 1
        assert pack_dir is not None
        assert pack_dir.exists()
        assert (pack_dir / "test.png").exists()
        assert (pack_dir / "test.png").read_bytes() == b"pretend png data"

    def test_load_invalid_json(self, tmp_path):
        from window import RingWindow
        path = tmp_path / "project.ring"
        path.write_text("not json")
        with pytest.raises(json.JSONDecodeError):
            RingWindow._load_ring_from_path(str(path))

    def test_load_old_json_version(self, tmp_path):
        from window import RingWindow
        path = tmp_path / "project.ring"
        data = {"version": 0, "nodes": []}
        path.write_text(json.dumps(data))
        result, pack_dir = RingWindow._load_ring_from_path(str(path))
        assert result["version"] == 0

    def test_load_missing_file(self, tmp_path):
        from window import RingWindow
        path = tmp_path / "nonexistent.ring"
        with pytest.raises(FileNotFoundError):
            RingWindow._load_ring_from_path(str(path))
