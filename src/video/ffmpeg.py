import json
import os
import shutil
import subprocess
import tempfile
import gettext
from typing import Optional

try:
    _ = gettext.gettext
except Exception:
    _ = lambda s: s


class FfmpegResult:
    def __init__(self, success: bool, error: str = "", stdout: str = "", stderr: str = ""):
        self.success = success
        self.error = error
        self.stdout = stdout
        self.stderr = stderr


class FfmpegCLI:
    def __init__(self, ffmpeg_path: str = "ffmpeg", ffprobe_path: str = "ffprobe"):
        self._ffmpeg_path = shutil.which(ffmpeg_path) or ffmpeg_path
        self._ffprobe_path = shutil.which(ffprobe_path) or ffprobe_path

    @property
    def available(self) -> bool:
        return shutil.which(self._ffmpeg_path) is not None

    def probe(self, path: str) -> Optional[dict]:
        if not self.available:
            return None
        if not os.path.isfile(path):
            return None
        args = [
            self._ffprobe_path, "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,nb_frames,r_frame_rate",
            "-show_entries", "format=duration",
            "-of", "json",
            path,
        ]
        try:
            result = subprocess.run(args, capture_output=True, timeout=30, text=True)
        except (subprocess.TimeoutExpired, OSError):
            return None
        if result.returncode != 0:
            return None
        try:
            data = json.loads(result.stdout or "{}")
        except (ValueError, TypeError):
            return None

        stream = (data.get("streams") or [{}])[0]
        fmt = data.get("format") or {}
        width = stream.get("width")
        height = stream.get("height")
        try:
            duration = float(fmt.get("duration", 0.0))
        except (TypeError, ValueError):
            duration = 0.0
        fps = self._parse_fps(stream.get("r_frame_rate"))
        nb_frames = stream.get("nb_frames")
        frame_count = None
        if nb_frames not in (None, "", "N/A"):
            try:
                frame_count = int(nb_frames)
            except (TypeError, ValueError):
                frame_count = None
        if frame_count is None and fps and duration:
            frame_count = int(round(duration * fps))
        return {
            "width": width,
            "height": height,
            "fps": fps,
            "frame_count": frame_count,
        }

    @staticmethod
    def _parse_fps(r_frame_rate) -> Optional[float]:
        if not r_frame_rate or r_frame_rate == "N/A":
            return None
        if "/" in r_frame_rate:
            num, _, den = r_frame_rate.partition("/")
            try:
                num, den = float(num), float(den)
                if den == 0:
                    return None
                return num / den
            except (TypeError, ValueError):
                return None
        try:
            return float(r_frame_rate)
        except (TypeError, ValueError):
            return None

    def extract_frame(self, path: str, frame_index: int, out_path: Optional[str] = None,
                      timeout: int = 60) -> FfmpegResult:
        if not os.path.isfile(path):
            return FfmpegResult(False, error=_("Video file not found: {}").format(path))
        if out_path is None:
            fd, out_path = tempfile.mkstemp(suffix=".png")
            os.close(fd)
        args = [
            self._ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
            "-i", path,
            "-vf", f"select='eq(n\\,{frame_index})'",
            "-vsync", "vfr",
            "-frames:v", "1",
            out_path,
        ]
        try:
            result = subprocess.run(args, capture_output=True, timeout=timeout, text=True)
        except subprocess.TimeoutExpired:
            return FfmpegResult(False, error=_("Frame extraction timed out"))
        except OSError as e:
            return FfmpegResult(False, error=str(e))
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            return FfmpegResult(False, error=err or _("ffmpeg failed to extract frame"),
                                stdout=result.stdout or "", stderr=result.stderr or "")
        if not os.path.isfile(out_path):
            return FfmpegResult(False, error=_("ffmpeg produced no frame image: frame out of range"))
        return FfmpegResult(True, stdout=result.stdout or "")

    def mux_mp4(self, frames_pattern: str, fps: int, out_path: str, timeout: int = 300) -> FfmpegResult:
        if os.path.isfile(out_path):
            os.remove(out_path)
        args = [
            self._ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
            "-framerate", str(fps),
            "-i", frames_pattern,
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            out_path,
        ]
        try:
            result = subprocess.run(args, capture_output=True, timeout=timeout, text=True)
        except subprocess.TimeoutExpired:
            return FfmpegResult(False, error=_("Video encoding timed out"))
        except OSError as e:
            return FfmpegResult(False, error=str(e))
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            return FfmpegResult(False, error=err or _("ffmpeg failed to encode video"),
                                stdout=result.stdout or "", stderr=result.stderr or "")
        if not os.path.isfile(out_path):
            return FfmpegResult(False, error=_("ffmpeg produced no output file"))
        return FfmpegResult(True, stdout=result.stdout or "")