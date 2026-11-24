import os
import subprocess
import tempfile
import shutil
from typing import Optional

import gettext

try:
    _ = gettext.gettext
except Exception:
    _ = lambda s: s


_NOISE_TYPES = ["Uniform", "Gaussian", "Multiplicative", "Impulse", "Laplacian", "Poisson"]

_GRAYSCALE_METHODS = [
    "Rec709Luminance",
    "Rec601Luminance",
    "Average",
    "Brightness",
]

_MORPHOLOGY_KERNEL = "disk:{radius}"


def _join_params_raw(params: list[str], joiner: str, count: Optional[int] = None) -> str:
    vals = params[:count] if count else params
    return joiner.join(vals)


def _build_args(op: str, raw_params: list[str]) -> list[tuple[str, Optional[str]]]:
    """
    Returns list of (flag, arg) tuples for ImageMagick.
    Flag may start with '+' instead of '-'.
    """
    if op == "blur":
        val = _join_params_raw(raw_params, "x", 2) if raw_params else None
        return [("-blur", val)]
    elif op == "motion_blur":
        val = _join_params_raw(raw_params, "x", 2) if raw_params else None
        if len(raw_params) >= 3:
            val = val + "+" + raw_params[2]
        return [("-motion-blur", val)]
    elif op == "radial_blur":
        val = raw_params[0] if raw_params else None
        return [("-rotational-blur", val)]
    elif op == "median":
        val = raw_params[0] if raw_params else None
        return [("-median", val)]
    elif op == "sharpen":
        val = _join_params_raw(raw_params, "x", 2) if raw_params else None
        return [("-sharpen", val)]
    elif op == "unsharp":
        val = _join_params_raw(raw_params, "x", 2) if raw_params else None
        if len(raw_params) >= 4:
            val = val + "+" + raw_params[2] + "+" + raw_params[3]
        return [("-unsharp", val)]
    elif op == "adaptive_sharpen":
        val = _join_params_raw(raw_params, "x", 2) if raw_params else None
        return [("-adaptive-sharpen", val)]
    elif op == "resize_pct":
        val = raw_params[0] + "%" if raw_params else None
        if raw_params and len(raw_params) > 1:
            val += "x" + raw_params[1] + "%"
        return [("-resize", val)]
    elif op == "resize_px":
        val = _join_params_raw(raw_params, "x", 2) if raw_params else None
        if val:
            val += "!"
        return [("-resize", val)]
    elif op == "rotate":
        val = raw_params[0] if raw_params else None
        return [("-rotate", val)]
    elif op == "grayscale":
        idx = int(raw_params[0]) if raw_params else 0
        idx = max(0, min(idx, len(_GRAYSCALE_METHODS) - 1))
        return [("-grayscale", _GRAYSCALE_METHODS[idx])]
    elif op == "sepia":
        val = (raw_params[0] + "%") if raw_params else None
        return [("-sepia-tone", val)]
    elif op == "modulate":
        val = _join_params_raw(raw_params, ",", 3) if raw_params else None
        return [("-modulate", val)]
    elif op == "level":
        vals = []
        if raw_params:
            vals.append(raw_params[0] + "%")
        if len(raw_params) >= 2:
            vals.append(raw_params[1] + "%")
        if len(raw_params) >= 3:
            vals.append(raw_params[2])
        val = ",".join(vals) if vals else None
        return [("-level", val)]
    elif op == "contrast":
        if raw_params and raw_params[0] == "1":
            return [("-contrast", None)]
        return []
    elif op == "contrast_stretch":
        vals = [raw_params[0] + "%", raw_params[1] + "%"] if len(raw_params) >= 2 else []
        val = ",".join(vals) if vals else None
        return [("-contrast-stretch", val)]
    elif op == "canny_edge":
        val = _join_params_raw(raw_params, "x", 2) if raw_params else None
        if len(raw_params) >= 4:
            val = val + "+" + raw_params[2] + "%+" + raw_params[3] + "%"
        return [("-canny", val)]
    elif op == "edge":
        val = raw_params[0] if raw_params else None
        return [("-edge", val)]
    elif op == "charcoal":
        val = _join_params_raw(raw_params, "x", 2) if raw_params else None
        return [("-charcoal", val)]
    elif op == "oil":
        val = raw_params[0] if raw_params else None
        return [("-paint", val)]
    elif op == "emboss":
        val = raw_params[0] if raw_params else None
        return [("-emboss", val)]
    elif op == "vignette":
        sigma = raw_params[2] if raw_params and len(raw_params) >= 3 else "3"
        shade = int(raw_params[3]) if raw_params and len(raw_params) >= 4 else 0
        bg = "white" if shade else "black"
        val = "0x" + sigma
        if raw_params and len(raw_params) >= 1:
            val += "+" + raw_params[0] + "%"
        if raw_params and len(raw_params) >= 2:
            val += "+" + raw_params[1] + "%"
        return [("-background", bg), ("-vignette", val)]
    elif op == "add_noise":
        idx = int(raw_params[0]) if raw_params else 0
        idx = max(0, min(idx, len(_NOISE_TYPES) - 1))
        return [("+noise", _NOISE_TYPES[idx])]
    elif op == "reduce_noise":
        val = raw_params[0] if raw_params else "3"
        return [("-statistic", ["Median", val])]
    elif op == "dilate":
        radius = raw_params[0] if raw_params else "3"
        return [("-morphology", ["Dilate", _MORPHOLOGY_KERNEL.format(radius=radius)])]
    elif op == "erode":
        radius = raw_params[0] if raw_params else "3"
        return [("-morphology", ["Erode", _MORPHOLOGY_KERNEL.format(radius=radius)])]
    elif op == "opening":
        radius = raw_params[0] if raw_params else "3"
        return [("-morphology", ["Open", _MORPHOLOGY_KERNEL.format(radius=radius)])]
    elif op == "closing":
        radius = raw_params[0] if raw_params else "3"
        return [("-morphology", ["Close", _MORPHOLOGY_KERNEL.format(radius=radius)])]
    return []


class ImageMagickResult:
    def __init__(self, success: bool, output_path: Optional[str] = None, error: str = "", stdout: str = "", stderr: str = ""):
        self.success = success
        self.output_path = output_path
        self.error = error
        self.stdout = stdout
        self.stderr = stderr


class ImageMagickCLI:
    def __init__(self, magick_path: str = "magick"):
        resolved = shutil.which(magick_path)
        if resolved is None and magick_path == "magick":
            # ImageMagick 6 ships the CLI as `convert` and has no `magick` driver.
            resolved = shutil.which("convert")
        self._magick_path = resolved or magick_path

    @property
    def available(self) -> bool:
        return shutil.which(self._magick_path) is not None

    @property
    def magick_path(self) -> str:
        return self._magick_path

    def run_pipeline(
        self,
        input_path: str,
        commands: list[str],
        output_path: Optional[str] = None,
        timeout: int = 120,
    ) -> ImageMagickResult:
        if not self.available:
            return ImageMagickResult(False, error=_("magick not found on system. Install ImageMagick."))

        if not os.path.isfile(input_path):
            return ImageMagickResult(False, error=_("Input file not found: {}").format(input_path))

        if output_path is None:
            fd, output_path = tempfile.mkstemp(suffix=".png")
            os.close(fd)

        args = [self._magick_path, input_path]
        for cmd in commands:
            if not cmd.strip():
                continue
            parts = cmd.split(",", 1)
            op = parts[0]
            raw_params = parts[1].split(",") if len(parts) > 1 else []
            flag_parts = _build_args(op, raw_params)
            for flag, arg in flag_parts:
                args.append(flag)
                if arg is not None:
                    if isinstance(arg, list):
                        args.extend(arg)
                    else:
                        args.append(arg)

        args.append(output_path)

        try:
            result = subprocess.run(
                args,
                capture_output=True,
                timeout=timeout,
                text=True,
            )
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            if result.returncode != 0:
                err_msg = stderr.strip() or _("Unknown error")
                return ImageMagickResult(False, error=err_msg, stdout=stdout, stderr=stderr)

            if not os.path.isfile(output_path):
                return ImageMagickResult(False, error=_("magick produced no output file"), stdout=stdout, stderr=stderr)

            return ImageMagickResult(True, output_path=output_path, stdout=stdout, stderr=stderr)

        except subprocess.TimeoutExpired:
            return ImageMagickResult(False, error=_("Processing timed out after {} seconds").format(timeout))
        except FileNotFoundError:
            return ImageMagickResult(False, error=_("magick not found on system"))
        except Exception as e:
            return ImageMagickResult(False, error=str(e))


