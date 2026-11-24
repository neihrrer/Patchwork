from unittest.mock import patch

import pytest


class TestJoinParamsRaw:
    def test_join_with_colon(self):
        from imagemagick.cli import _join_params_raw
        result = _join_params_raw(["1", "2", "3"], ":")
        assert result == "1:2:3"

    def test_join_with_comma(self):
        from imagemagick.cli import _join_params_raw
        result = _join_params_raw(["10", "20"], ",")
        assert result == "10,20"

    def test_single_value(self):
        from imagemagick.cli import _join_params_raw
        result = _join_params_raw(["42"], ",")
        assert result == "42"

    def test_with_count(self):
        from imagemagick.cli import _join_params_raw
        result = _join_params_raw(["1", "2", "3", "4"], "x", 2)
        assert result == "1x2"


class TestBuildArgs:
    @pytest.mark.parametrize("op,raw_params,expected", [
        ("blur", ["5.0"], [("-blur", "5.0")]),
        ("motion_blur", ["10", "45"], [("-motion-blur", "10x45")]),
        ("radial_blur", ["30"], [("-rotational-blur", "30")]),
        ("sharpen", ["3.0", "1.5"], [("-sharpen", "3.0x1.5")]),
        ("unsharp", ["2.0", "1.0", "1.5", "0.1"], [("-unsharp", "2.0x1.0+1.5+0.1")]),
        ("adaptive_sharpen", ["3.0", "1.0"], [("-adaptive-sharpen", "3.0x1.0")]),
        ("median", ["3"], [("-statistic", ["Median", "3"])]),
        ("resize_pct", ["50"], [("-resize", "50%")]),
        ("resize_px", ["800", "600"], [("-resize", "800x600!")]),
        ("rotate", ["90"], [("-rotate", "90")]),
        ("grayscale", ["0"], [("-grayscale", "Rec709Luminance")]),
        ("sepia", ["80"], [("-sepia-tone", "80%")]),
        ("modulate", ["100", "150", "0"], [("-modulate", "100,150,0")]),
        ("level", ["10", "240", "1.2"], [("-level", "10%,240%,1.2")]),
        ("contrast", ["1"], [("-contrast", None)]),
        ("contrast", ["0"], []),
        ("contrast_stretch", ["5", "245"], [("-contrast-stretch", "5%,245%")]),
        ("canny_edge", ["1", "1.0", "10", "30"], [("-canny", "1x1.0+10%+30%")]),
        ("charcoal", ["2"], [("-charcoal", "2")]),
        ("charcoal", ["2.0", "1.0"], [("-charcoal", "2.0x1.0")]),
        ("oil", ["3"], [("-paint", "3")]),
        ("emboss", ["1"], [("-emboss", "1")]),
        ("edge", ["1"], [("-edge", "1")]),
        ("vignette", ["50", "30"], [("-background", "black"), ("-vignette", "0x3+50%+30%")]),
        ("vignette", ["10", "10", "5"], [("-background", "black"), ("-vignette", "0x5+10%+10%")]),
        ("vignette", ["10", "10", "3", "1"], [("-background", "white"), ("-vignette", "0x3+10%+10%")]),
        ("add_noise", ["2", "0.1"], [("-attenuate", "0.065"), ("+noise", "Multiplicative")]),
        ("add_noise", ["0", "0.1"], [("-attenuate", "1.5"), ("+noise", "Uniform")]),
        ("add_noise", ["5", "0.1"], [("-attenuate", "10"), ("+noise", "Poisson")]),
        ("add_noise", ["0", "0"], []),
        ("add_noise", ["3"], [("-attenuate", "0.117"), ("+noise", "Impulse")]),
        ("reduce_noise", ["5"], [("-statistic", ["Median", "5"])]),
        ("dilate", ["2"], [("-morphology", ["Dilate", "disk:2"])]),
        ("erode", ["2"], [("-morphology", ["Erode", "disk:2"])]),
        ("opening", ["3"], [("-morphology", ["Open", "disk:3"])]),
        ("closing", ["3"], [("-morphology", ["Close", "disk:3"])]),
    ])
    def test_build_args(self, op, raw_params, expected):
        from imagemagick.cli import _build_args
        result = _build_args(op, raw_params)
        assert result == expected, f"Failed for {op}: got {result}"

    def test_unknown_operation(self):
        from imagemagick.cli import _build_args
        result = _build_args("nonexistent", [])
        assert result == []


class TestImageMagickCLI:
    def test_available_when_magick_on_path(self):
        from imagemagick.cli import ImageMagickCLI
        with patch("shutil.which", return_value="/usr/bin/magick"):
            cli = ImageMagickCLI()
            assert cli.available is True

    def test_not_available_when_missing(self):
        from imagemagick.cli import ImageMagickCLI
        with patch("shutil.which", return_value=None):
            cli = ImageMagickCLI()
            assert cli.available is False

    def test_run_pipeline_not_available(self):
        from imagemagick.cli import ImageMagickCLI
        with patch("shutil.which", return_value=None):
            cli = ImageMagickCLI()
            result = cli.run_pipeline("/in.png", ["blur", "5"], "/out.png")
            assert result.success is False
            assert "not found" in (result.error or "").lower()

    def test_run_pipeline_input_not_found(self):
        from imagemagick.cli import ImageMagickCLI
        with patch("shutil.which", return_value="/usr/bin/magick"):
            cli = ImageMagickCLI()
            result = cli.run_pipeline("/nonexistent.png", ["blur", "5"], "/out.png")
            assert result.success is False

    def test_run_pipeline_subprocess_error(self):
        from imagemagick.cli import ImageMagickCLI
        with patch("shutil.which", return_value="/usr/bin/magick"):
            with patch("subprocess.run", side_effect=FileNotFoundError):
                cli = ImageMagickCLI()
                result = cli.run_pipeline("/in.png", ["blur", "5"], "/out.png")
                assert result.success is False

    def test_image_magick_result(self):
        from imagemagick.cli import ImageMagickResult
        r = ImageMagickResult(success=True, output_path="/tmp/out.png",
                               error="", stdout="", stderr="")
        assert r.success is True
        assert r.output_path == "/tmp/out.png"


class TestImageMagick6Fallback:
    @staticmethod
    def _im6_which(name):
        return "/usr/bin/convert" if name in ("convert", "/usr/bin/convert") else None

    def test_detects_convert_when_magick_is_missing(self):
        from imagemagick.cli import ImageMagickCLI
        with patch("shutil.which", side_effect=self._im6_which):
            cli = ImageMagickCLI()
            assert cli.available is True
            assert cli.magick_path == "/usr/bin/convert"

    def test_run_pipeline_invokes_convert(self, tmp_path):
        from imagemagick.cli import ImageMagickCLI
        src = tmp_path / "in.png"
        src.write_bytes(b"not really a png")
        out = tmp_path / "out.png"
        with patch("shutil.which", side_effect=self._im6_which):
            with patch("subprocess.run") as run:
                run.return_value.returncode = 0
                run.return_value.stdout = ""
                run.return_value.stderr = ""
                out.write_bytes(b"out")
                cli = ImageMagickCLI()
                result = cli.run_pipeline(str(src), ["blur,3.0,1.0"], str(out))
        assert result.success is True
        assert run.call_args.args[0][0] == "/usr/bin/convert"

    def test_explicit_path_is_not_overridden(self):
        from imagemagick.cli import ImageMagickCLI
        with patch("shutil.which", return_value=None):
            cli = ImageMagickCLI("/opt/ima/magick")
            assert cli.magick_path == "/opt/ima/magick"
