import gettext
import threading
import os
import tempfile
from typing import Optional, Callable

from gmic.cli import GmicCLI, GmicResult
from imagemagick.cli import ImageMagickCLI, ImageMagickResult
from models.filter import FilterDef, ENGINE_GMIC, ENGINE_IMAGEMAGICK

try:
    _ = gettext.gettext
except Exception:
    _ = lambda s: s


class ProcessResult:
    def __init__(self, output_path: Optional[str] = None, error: str = "", stdout: str = "", stderr: str = ""):
        self.output_path = output_path
        self.error = error
        self.stdout = stdout
        self.stderr = stderr

    @property
    def success(self) -> bool:
        return self.output_path is not None

    @property
    def verbose_output(self) -> str:
        parts = []
        if self.stdout:
            parts.append(self.stdout)
        if self.stderr:
            parts.append(self.stderr)
        return "\n".join(parts)


class ProcessingRunner:
    def __init__(self, gmic: GmicCLI, imagemagick: ImageMagickCLI):
        self._gmic = gmic
        self._imagemagick = imagemagick
        self._thread: Optional[threading.Thread] = None
        self._cancel_flag = False

    def run(self, commands: list[str], filter_def: FilterDef, output_format: str, callback: Callable[[ProcessResult], None]):
        if self._thread and self._thread.is_alive():
            self._cancel_flag = True
            self._thread.join(timeout=1)

        self._cancel_flag = False

        if not commands or len(commands) < 1:
            callback(ProcessResult(error="No input or filter selected"))
            return

        suffix = "." + output_format if output_format else ".png"
        fd, out_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)

        engine = filter_def.engine if filter_def else ENGINE_GMIC

        if engine == ENGINE_IMAGEMAGICK:
            if not self._imagemagick.available:
                callback(ProcessResult(
                    error=_("ImageMagick is not installed. Install it with your package manager.")
                ))
                return

            def worker():
                if self._cancel_flag:
                    callback(ProcessResult(error=_("Cancelled")))
                    return

                im_result = self._imagemagick.run_pipeline(
                    input_path=commands[0],
                    commands=commands[1:],
                    output_path=out_path,
                )

                if im_result.success:
                    callback(ProcessResult(output_path=im_result.output_path, stdout=im_result.stdout, stderr=im_result.stderr))
                else:
                    callback(ProcessResult(error=im_result.error, stdout=im_result.stdout, stderr=im_result.stderr))
        elif engine == ENGINE_GMIC:
            if not self._gmic.available:
                callback(ProcessResult(
                    error=_("G'MIC is not installed. Install it with your package manager.")
                ))
                return

            def worker():
                if self._cancel_flag:
                    callback(ProcessResult(error=_("Cancelled")))
                    return

                gmic_result = self._gmic.run_pipeline(
                    input_path=commands[0],
                    commands=commands[1:],
                    output_path=out_path,
                )

                if gmic_result.success:
                    callback(ProcessResult(output_path=gmic_result.output_path, stdout=gmic_result.stdout, stderr=gmic_result.stderr))
                else:
                    callback(ProcessResult(error=gmic_result.error, stdout=gmic_result.stdout, stderr=gmic_result.stderr))
        else:
            callback(ProcessResult(error=_("Unknown engine: {}").format(engine)))
            return

        self._thread = threading.Thread(target=worker, daemon=True)
        self._thread.start()

    def cancel(self):
        self._cancel_flag = True
