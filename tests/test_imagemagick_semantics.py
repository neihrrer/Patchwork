"""Integration tests for ImageMagick filter semantics.

These run the real ``magick`` binary through the app's CLI wrapper and check
that the produced image actually matches what the filter parameters promise
(not merely that ImageMagick exited with status 0).
"""

import random
import shutil

import pytest
from PIL import Image, ImageChops, ImageStat


MAGICK = shutil.which("magick")

pytestmark = pytest.mark.skipif(MAGICK is None, reason="magick not installed")


def _gradient_image(path, size=(160, 120)):
    img = Image.new("RGB", size)
    pixels = img.load()
    for y in range(size[1]):
        for x in range(size[0]):
            pixels[x, y] = (x * 255 // (size[0] - 1),
                            y * 255 // (size[1] - 1),
                            (x + y) * 255 // (size[0] + size[1] - 2))
    img.save(path)
    return str(path)


def _noise_image(path, size=(160, 120)):
    rnd = random.Random(1234)
    img = Image.new("RGB", size)
    img.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
                 for _ in range(size[0] * size[1])])
    img.save(path)
    return str(path)


def _run(cli, src, command, dst):
    result = cli.run_pipeline(str(src), [command], str(dst))
    assert result.success, result.error
    return Image.open(dst).convert("RGB")


class TestCharcoalSigma:
    def test_sigma_reaches_image_magick(self, tmp_path):
        from imagemagick.cli import ImageMagickCLI

        src = _gradient_image(tmp_path / "src.png")
        cli = ImageMagickCLI()
        soft = _run(cli, src, "charcoal,2.0,1.0", tmp_path / "soft.png")
        hard = _run(cli, src, "charcoal,2.0,5.0", tmp_path / "hard.png")

        diff = ImageStat.Stat(ImageChops.difference(soft, hard)).mean
        assert sum(diff) > 1.0, "charcoal sigma had no effect on the output"


class TestResizePixels:
    def test_resize_pixels_produces_requested_size(self, tmp_path):
        from gmic.cli import GmicCLI
        from imagemagick.cli import ImageMagickCLI
        from imagemagick.filters import get_builtin_filters
        from nodes import NodeGraph, InputNode, FilterNode, OutputNode
        from processing.graph_executor import GraphExecutor

        src = _gradient_image(tmp_path / "wide.png", size=(500, 100))
        filter_def = next(f for f in get_builtin_filters() if f.name == "resize_px")

        graph = NodeGraph()
        inp = InputNode("in")
        inp.file_path = src
        graph.add_node(inp)
        flt = FilterNode("flt", filter_def)
        flt.set_param("width", 800)
        flt.set_param("height", 600)
        graph.add_node(flt)
        out = OutputNode("out")
        graph.add_node(out)
        graph.add_edge("in", "image", "flt", "image")
        graph.add_edge("flt", "image", "out", "image")

        executor = GraphExecutor(GmicCLI(), ImageMagickCLI())
        result = executor.execute(graph, output_format="png", timeout=60)
        assert result.success, result.error
        assert Image.open(result.output_path).size == (800, 600)


class TestMedianSyntax:
    def test_median_is_applied_without_imagemagick_warning(self, tmp_path):
        from imagemagick.cli import ImageMagickCLI

        src = _noise_image(tmp_path / "src.png")
        out = tmp_path / "out.png"
        result = ImageMagickCLI().run_pipeline(src, ["median,3.0"], str(out))

        assert result.success, result.error
        assert "has been replaced" not in result.stderr
        original = Image.open(src).convert("RGB")
        filtered = Image.open(out).convert("RGB")
        assert ImageStat.Stat(ImageChops.difference(original, filtered)).mean != [0, 0, 0]
