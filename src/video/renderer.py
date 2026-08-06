import os
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import Callable, Optional

from nodes import NodeGraph, OutputNode
from processing.graph_executor import GraphExecutor
from processing.runner import ProcessResult
from video.ffmpeg import FfmpegCLI

FORMAT_MP4 = "mp4"
FORMAT_GIF = "gif"
FORMAT_PNG_SEQUENCE = "png_sequence"

VALID_ANIMATION_FORMATS = [FORMAT_MP4, FORMAT_GIF, FORMAT_PNG_SEQUENCE]


@dataclass
class AnimationSettings:
    frame_count: int = 24
    fps: int = 12
    out_format: str = FORMAT_MP4
    out_path: str = ""
    _frames: list[str] = field(default_factory=list, repr=False)
    _frame_dir: str = field(default="", repr=False)

    def add_frame(self, path: str):
        self._frames.append(path)

    @property
    def frames(self) -> list[str]:
        return self._frames

    def clear_frames(self):
        self._frames.clear()

    def cleanup(self):
        if self._frame_dir:
            shutil.rmtree(self._frame_dir, ignore_errors=True)
            self._frame_dir = ""
        self._frames.clear()


def _find_output_nodes(graph: NodeGraph) -> list[OutputNode]:
    return [n for n in graph.nodes.values() if isinstance(n, OutputNode)]


def render_frames(
    graph: NodeGraph,
    executor: GraphExecutor,
    settings: AnimationSettings,
    progress_callback: Optional[Callable[[str], None]] = None,
    timeout: int = 120,
    cancel_event=None,
) -> ProcessResult:
    """Render the graph once per frame into temp PNGs (kept in settings.frames)."""
    out_nodes = _find_output_nodes(graph)
    if not out_nodes:
        return ProcessResult(error="Graph has no output node")

    settings.clear_frames()
    frame_dir = tempfile.mkdtemp(prefix="patchwork_anim_")
    settings._frame_dir = frame_dir
    frame_paths: list[str] = []

    for i in range(settings.frame_count):
        if cancel_event is not None and cancel_event.is_set():
            return ProcessResult(error="Rendering cancelled", cancelled=True)
        if progress_callback:
            progress_callback(f"Rendering frame {i + 1}/{settings.frame_count}")
        result = executor.execute(
            graph,
            "png",
            progress_callback=progress_callback,
            timeout=timeout,
            frame=i,
            force_refresh=True,
            cancel_event=cancel_event,
        )
        if result.cancelled:
            return ProcessResult(error="Rendering cancelled", cancelled=True)
        if not result.success:
            return ProcessResult(
                error=f"Frame {i} failed: {result.error}",
                stdout=result.stdout,
                stderr=result.stderr,
            )

        output_path = None
        for node in out_nodes:
            path = result.output_paths.get(node.id)
            if path and os.path.isfile(path):
                output_path = path
                break
        if output_path is None and result.output_path and os.path.isfile(result.output_path):
            output_path = result.output_path
        if output_path is None:
            return ProcessResult(error=f"Frame {i} produced no output image")

        frame_path = os.path.join(frame_dir, f"frame_{i:05d}.png")
        shutil.copy2(output_path, frame_path)
        frame_paths.append(frame_path)
        settings.add_frame(frame_path)

    if not frame_paths:
        return ProcessResult(error="No frames were rendered")
    return ProcessResult(output_path=frame_paths[0], output_paths={"_frames": frame_paths})


def mux_animation(
    ffmpeg: FfmpegCLI,
    settings: AnimationSettings,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> ProcessResult:
    """Encode settings.frames to the file/folder at settings.out_path."""
    frame_paths = settings.frames
    if not frame_paths:
        return ProcessResult(error="No frames were rendered")

    if settings.out_format == FORMAT_PNG_SEQUENCE:
        try:
            out_dir = settings.out_path
            if not out_dir.endswith(os.sep):
                out_dir = out_dir + os.sep
            os.makedirs(out_dir, exist_ok=True)
            for i, path in enumerate(frame_paths):
                shutil.copy2(path, os.path.join(out_dir, f"frame_{i:05d}.png"))
        except OSError as e:
            return ProcessResult(error=str(e))
        return ProcessResult(output_path=os.path.join(out_dir, "frame_00000.png"))

    if settings.out_format == FORMAT_MP4:
        if not ffmpeg.available:
            return ProcessResult(error="ffmpeg not found on system. Install it to export MP4.")
        if progress_callback:
            progress_callback("Encoding video...")
        pattern = os.path.join(settings._frame_dir, "frame_%05d.png")
        result = ffmpeg.mux_mp4(pattern, settings.fps, settings.out_path)
        if not result.success:
            return ProcessResult(error=result.error, stdout=result.stdout, stderr=result.stderr)
        return ProcessResult(output_path=settings.out_path)

    if settings.out_format == FORMAT_GIF:
        from PIL import Image
        if progress_callback:
            progress_callback("Encoding animated GIF...")
        try:
            imgs = []
            for path in frame_paths:
                imgs.append(Image.open(path).convert("RGBA"))
            duration_ms = max(1, int(round(1000.0 / settings.fps)))
            imgs[0].save(
                settings.out_path,
                save_all=True,
                append_images=imgs[1:],
                duration=duration_ms,
                loop=0,
            )
        except Exception as e:
            return ProcessResult(error=str(e))
        return ProcessResult(output_path=settings.out_path)

    return ProcessResult(error=f"Unsupported animation format: {settings.out_format}")


def render_animation(
    graph: NodeGraph,
    executor: GraphExecutor,
    ffmpeg: FfmpegCLI,
    settings: AnimationSettings,
    progress_callback: Optional[Callable[[str], None]] = None,
    timeout: int = 120,
) -> ProcessResult:
    """Render frames and mux them to settings.out_path in one call."""
    if settings.out_format not in VALID_ANIMATION_FORMATS:
        return ProcessResult(error=f"Unsupported animation format: {settings.out_format}")

    result = render_frames(
        graph, executor, settings, progress_callback=progress_callback, timeout=timeout
    )
    if not result.success:
        settings.cleanup()
        return result

    result = mux_animation(ffmpeg, settings, progress_callback=progress_callback)
    settings.cleanup()
    return result
