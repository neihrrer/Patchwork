"""Integration tests for ImageMagick filter semantics.

These run the real ``magick`` binary through the app's CLI wrapper and check
that the produced image actually matches what the filter parameters promise
(not merely that ImageMagick exited with status 0).
"""

import shutil
from unittest.mock import patch

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
