"""Integration tests for ImageMagick filter semantics.

These run the real ``magick`` binary through the app's CLI wrapper and check
that the produced image actually matches what the filter parameters promise
(not merely that ImageMagick exited with status 0).
"""

import random
import shutil

import pytest
from PIL import Image, ImageChops, ImageDraw, ImageStat


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


def _rgba_shapes(path, size=(160, 120)):
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, 90, 90], fill=(220, 60, 30, 255))
    draw.ellipse([95, 30, 150, 100], fill=(30, 160, 220, 200))
    img.save(path)
    return str(path)


def _mean_diff(a, b):
    return sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3.0


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


class TestAddNoiseAmplitude:
    def test_filter_exposes_amplitude_default(self):
        from imagemagick.filters import get_builtin_filters

        filter_def = next(f for f in get_builtin_filters() if f.name == "add_noise")
        amplitude = next(p for p in filter_def.parameters if p.name == "amplitude")
        assert amplitude.kind == "float"
        assert amplitude.min_val == 0.0
        assert amplitude.max_val == 100.0
        assert amplitude.default == 10.0

    def test_default_amplitude_is_visible(self, tmp_path):
        from imagemagick.cli import ImageMagickCLI

        src = _gradient_image(tmp_path / "src.png")
        out = tmp_path / "out.png"
        result = ImageMagickCLI().run_pipeline(src, ["add_noise,0,10"], str(out))
        assert result.success, result.error

        original = Image.open(src).convert("RGB")
        noisy = Image.open(out).convert("RGB")
        assert _mean_diff(original, noisy) > 0.5

    def test_zero_amplitude_is_a_no_op(self, tmp_path):
        from imagemagick.cli import ImageMagickCLI

        src = _noise_image(tmp_path / "src.png")
        out = tmp_path / "out.png"
        result = ImageMagickCLI().run_pipeline(src, ["add_noise,0,0"], str(out))
        assert result.success, result.error

        original = Image.open(src).convert("RGBA")
        passed = Image.open(out).convert("RGBA")
        assert ImageChops.difference(original, passed).getbbox() is None

    def test_larger_amplitude_adds_more_noise(self, tmp_path):
        from imagemagick.cli import ImageMagickCLI

        src = _gradient_image(tmp_path / "src.png")
        cli = ImageMagickCLI()
        original = Image.open(src).convert("RGB")

        low = _run(cli, src, "add_noise,0,10", tmp_path / "low.png")
        high = _run(cli, src, "add_noise,0,60", tmp_path / "high.png")

        assert _mean_diff(original, high) > 2 * _mean_diff(original, low)

    @pytest.mark.parametrize("noise_index", range(6))
    def test_every_noise_type_renders(self, noise_index, tmp_path):
        from imagemagick.cli import ImageMagickCLI

        src = _gradient_image(tmp_path / "src.png")
        out = tmp_path / f"noise{noise_index}.png"
        result = ImageMagickCLI().run_pipeline(src, [f"add_noise,{noise_index},10"], str(out))
        assert result.success, result.error

        original = Image.open(src).convert("RGB")
        noisy = Image.open(out).convert("RGB")
        assert _mean_diff(original, noisy) > 0.2


class TestAlphaPreservation:
    @pytest.mark.parametrize("command", [
        "charcoal,2.0,1.0",
        "edge,1.0",
        "canny_edge,1.0,1.0,10.0,30.0",
        "vignette,10.0,10.0,3.0,0",
        "add_noise,0,10",
    ])
    def test_transparent_areas_stay_transparent(self, command, tmp_path):
        from imagemagick.cli import ImageMagickCLI

        src = _rgba_shapes(tmp_path / "src.png")
        out = tmp_path / "out.png"
        result = ImageMagickCLI().run_pipeline(src, [command], str(out))
        assert result.success, result.error

        original = Image.open(src).convert("RGBA")
        filtered = Image.open(out).convert("RGBA")
        assert filtered.size == original.size

        alpha_diff = ImageChops.difference(original.getchannel("A"), filtered.getchannel("A"))
        assert alpha_diff.getbbox() is None, f"{command} changed the alpha channel"

        colour_diff = _mean_diff(original.convert("RGB"), filtered.convert("RGB"))
        assert colour_diff > 0.2, f"{command} did not change the colour"

    @pytest.mark.parametrize("source_kind", ["rgba", "rgb"])
    def test_rotate_padding_is_transparent(self, source_kind, tmp_path):
        from imagemagick.cli import ImageMagickCLI

        if source_kind == "rgba":
            src = _rgba_shapes(tmp_path / "src.png")
        else:
            src = _gradient_image(tmp_path / "src.png")
        out = tmp_path / "out.png"
        result = ImageMagickCLI().run_pipeline(src, ["rotate,45.0"], str(out))
        assert result.success, result.error

        rotated = Image.open(out).convert("RGBA")
        assert rotated.getpixel((0, 0))[3] == 0
        assert rotated.getpixel((rotated.width - 1, 0))[3] == 0


class TestDeprecatedOptions:
    def test_contrast_filter_is_gone(self):
        from imagemagick.filters import get_builtin_filters

        names = {f.name for f in get_builtin_filters()}
        assert "contrast" not in names

    def test_no_builtin_emits_a_replaced_imagemagick_option(self, tmp_path):
        from imagemagick.cli import ImageMagickCLI
        from imagemagick.filters import get_builtin_filters
        from gmic.pipeline import _serialize_param

        src = _gradient_image(tmp_path / "src.png")
        cli = ImageMagickCLI()
        for filter_def in get_builtin_filters():
            params = [_serialize_param(p.default, p) for p in filter_def.parameters]
            command = ",".join([filter_def.gmic_command, *params])
            result = cli.run_pipeline(src, [command], str(tmp_path / "out.png"))
            assert result.success, (filter_def.name, result.error)
            assert "has been replaced" not in result.stderr, (filter_def.name, result.stderr)
