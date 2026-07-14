import os
import tempfile
import subprocess
from typing import Optional, Callable

from nodes import NodeGraph, InputNode, OutputNode, FilterNode, BlendNode, ColorNode, OpacityNode, ColoringNode, MaskNode
from models.filter import ENGINE_GMIC
from gmic.cli import GmicCLI
from gmic.pipeline import _serialize_param
from imagemagick.cli import ImageMagickCLI
from processing.runner import ProcessResult


class GraphExecutor:
    def __init__(self, gmic: GmicCLI, imagemagick: ImageMagickCLI):
        self._gmic = gmic
        self._imagemagick = imagemagick
        self._output_path: Optional[str] = None

    def execute(self, graph: NodeGraph, output_format: str = "png",
                progress_callback: Optional[Callable[[str], None]] = None) -> ProcessResult:
        order = graph.topological_sort()
        if not order:
            return ProcessResult(error="Graph has no valid execution order (cycle or empty)")

        node_outputs: dict[str, str] = {}

        for node in order:
            if progress_callback:
                progress_callback(f"Processing: {node.label}")

            if isinstance(node, InputNode):
                if node.file_path and os.path.isfile(node.file_path):
                    node_outputs[node.id] = node.file_path
                    node.cached_output_path = node.file_path
                    node.cache_dirty = False
                else:
                    return ProcessResult(error=f"Input node '{node.label}' has no file set")

            elif isinstance(node, FilterNode):
                if node.cache_dirty or not node.cached_output_path:
                    inp = self._first_input(node, graph, node_outputs)
                    if not inp:
                        return ProcessResult(error=f"Filter '{node.label}' has no input connected")
                    result = self._run_filter(node, inp, output_format)
                    if not result.success:
                        return result
                    node.cached_output_path = result.output_path
                    node.cache_dirty = False
                node_outputs[node.id] = node.cached_output_path

            elif isinstance(node, BlendNode):
                inputs = self._ordered_inputs(node, graph, node_outputs)
                if len(inputs) < 2:
                    return ProcessResult(error=f"Blend '{node.label}' needs 2 inputs, got {len(inputs)}")
                result = self._run_blend(inputs, node.mode, output_format)
                if not result.success:
                    return result
                node_outputs[node.id] = result.output_path

            elif isinstance(node, ColorNode):
                inp = self._first_input(node, graph, node_outputs)
                if not inp:
                    return ProcessResult(error=f"Color node '{node.label}' has no input")
                result = self._run_color(node, inp, output_format)
                if not result.success:
                    return result
                node_outputs[node.id] = result.output_path

            elif isinstance(node, OpacityNode):
                inp = self._first_input(node, graph, node_outputs)
                if not inp:
                    return ProcessResult(error=f"Opacity node '{node.label}' has no input")
                result = self._run_opacity(inp, node.opacity, output_format)
                if not result.success:
                    return result
                node_outputs[node.id] = result.output_path

            elif isinstance(node, ColoringNode):
                inp = self._first_input(node, graph, node_outputs)
                if not inp:
                    return ProcessResult(error=f"Coloring node '{node.label}' has no input")
                result = self._run_coloring(inp, node.hue, node.saturation, node.lightness, output_format)
                if not result.success:
                    return result
                node_outputs[node.id] = result.output_path

            elif isinstance(node, MaskNode):
                inputs = self._all_inputs(node, graph, node_outputs)
                if len(inputs) < 2:
                    return ProcessResult(error=f"Mask '{node.label}' needs 2 inputs, got {len(inputs)}")
                result = self._run_mask(inputs[0], inputs[1], node.invert, output_format)
                if not result.success:
                    return result
                node_outputs[node.id] = result.output_path

            elif isinstance(node, OutputNode):
                inp = self._first_input(node, graph, node_outputs)
                if inp:
                    node_outputs[node.id] = inp
                    self._output_path = inp

        out = self._output_path or (list(node_outputs.values())[-1] if node_outputs else None)
        if out and os.path.isfile(out):
            return ProcessResult(output_path=out)
        return ProcessResult(error="No output produced")

    def _first_input(self, node, graph: NodeGraph, outputs: dict[str, str]) -> Optional[str]:
        for e in graph.edges:
            if e.dst_node == node.id:
                path = outputs.get(e.src_node)
                if path and os.path.isfile(path):
                    return path
        return None

    def _all_inputs(self, node, graph: NodeGraph, outputs: dict[str, str]) -> list[str]:
        result = []
        for e in graph.edges:
            if e.dst_node == node.id:
                path = outputs.get(e.src_node)
                if path and os.path.isfile(path):
                    result.append(path)
        return result

    def _ordered_inputs(self, node, graph: NodeGraph, outputs: dict[str, str]) -> list[str]:
        port_order = {p.name: i for i, p in enumerate(node.inputs)}
        pairs = []
        for e in graph.edges:
            if e.dst_node == node.id:
                path = outputs.get(e.src_node)
                if path and os.path.isfile(path):
                    pairs.append((port_order.get(e.dst_port, 999), path))
        pairs.sort(key=lambda x: x[0])
        return [p for _, p in pairs]

    def _run_filter(self, node: FilterNode, input_path: str, output_fmt: str) -> ProcessResult:
        fd, out_path = tempfile.mkstemp(suffix="." + output_fmt)
        os.close(fd)

        commands = [input_path, node.filter_def.gmic_command]
        for p in node.filter_def.parameters:
            val = node.param_values.get(p.name, p.default)
            commands[-1] += f",{_serialize_param(val, p)}"

        if node.filter_def.engine == ENGINE_GMIC:
            result = self._gmic.run_pipeline(input_path, commands[1:], out_path)
        else:
            result = self._imagemagick.run_pipeline(input_path, commands[1:], out_path)

        if result.success:
            return ProcessResult(output_path=result.output_path)
        return ProcessResult(error=result.error, stdout=result.stdout, stderr=result.stderr)

    def _run_blend(self, inputs: list[str], mode: str, fmt: str) -> ProcessResult:
        if not self._imagemagick.available:
            return ProcessResult(error="ImageMagick required for blend operations")
        if len(inputs) < 2:
            return ProcessResult(error="Need at least 2 inputs to blend")
        current = inputs[0]
        for blend_img in inputs[1:]:
            fd, out_path = tempfile.mkstemp(suffix="." + fmt)
            os.close(fd)
            try:
                args = [self._imagemagick.magick_path, current, blend_img]
                args += ["-compose", mode, "-composite", out_path]
                r = subprocess.run(args, capture_output=True, timeout=60, text=True)
                if r.returncode != 0 or not os.path.isfile(out_path):
                    return ProcessResult(error=r.stderr)
                current = out_path
            except Exception as e:
                return ProcessResult(error=str(e))
        return ProcessResult(output_path=current)

    def _run_color(self, node: ColorNode, input_path: str, fmt: str) -> ProcessResult:
        if not self._imagemagick.available:
            return ProcessResult(error="ImageMagick required for color adjustments")
        fd, out_path = tempfile.mkstemp(suffix="." + fmt)
        os.close(fd)
        try:
            args = [self._imagemagick.magick_path, input_path]
            if node.operation == "brightness_contrast":
                args += ["-brightness-contrast", f"{node.brightness}x{node.contrast}"]
            elif node.operation == "hue_saturation":
                hue_val = 100 + node.hue * 100.0 / 180.0
                args += ["-modulate", f"100,{100 + node.saturation},{hue_val}"]
            elif node.operation == "levels":
                args += ["-level", f"{node.black_point}%,{node.white_point}%,{node.gamma}"]
            else:
                args += ["-level", "0%,100%,1.0"]
            args.append(out_path)
            r = subprocess.run(args, capture_output=True, timeout=60, text=True)
            if r.returncode == 0 and os.path.isfile(out_path):
                return ProcessResult(output_path=out_path)
            return ProcessResult(error=r.stderr)
        except Exception as e:
            return ProcessResult(error=str(e))

    def _run_opacity(self, input_path: str, opacity: float, fmt: str) -> ProcessResult:
        if not self._imagemagick.available:
            return ProcessResult(error="ImageMagick required for opacity")
        fd, out_path = tempfile.mkstemp(suffix="." + fmt)
        os.close(fd)
        try:
            args = [self._imagemagick.magick_path, input_path]
            if opacity < 1.0:
                args += ["-alpha", "on", "-channel", "A", "-evaluate", "multiply", str(opacity), "+channel"]
            args.append(out_path)
            r = subprocess.run(args, capture_output=True, timeout=60, text=True)
            if r.returncode == 0 and os.path.isfile(out_path):
                return ProcessResult(output_path=out_path)
            return ProcessResult(error=r.stderr)
        except Exception as e:
            return ProcessResult(error=str(e))

    def _run_coloring(self, input_path: str, hue: float, saturation: float, lightness: float, fmt: str) -> ProcessResult:
        if not self._imagemagick.available:
            return ProcessResult(error="ImageMagick required for coloring")
        fd, out_path = tempfile.mkstemp(suffix="." + fmt)
        os.close(fd)
        try:
            args = [self._imagemagick.magick_path, input_path]
            hue_val = 100 + hue * 100.0 / 180.0
            args += ["-modulate", f"{100 + lightness},{100 + saturation},{hue_val}"]
            args.append(out_path)
            r = subprocess.run(args, capture_output=True, timeout=60, text=True)
            if r.returncode == 0 and os.path.isfile(out_path):
                return ProcessResult(output_path=out_path)
            return ProcessResult(error=r.stderr)
        except Exception as e:
            return ProcessResult(error=str(e))

    def _run_mask(self, base: str, mask: str, invert: bool, fmt: str) -> ProcessResult:
        if not self._imagemagick.available:
            return ProcessResult(error="ImageMagick required for mask operations")
        fd, out_path = tempfile.mkstemp(suffix="." + fmt)
        os.close(fd)
        try:
            if invert:
                args = [self._imagemagick.magick_path, base, "(", mask, "-negate", ")",
                        "-compose", "CopyOpacity", "-composite", out_path]
            else:
                args = [self._imagemagick.magick_path, base, mask,
                        "-compose", "CopyOpacity", "-composite", out_path]
            r = subprocess.run(args, capture_output=True, timeout=60, text=True)
            if r.returncode == 0 and os.path.isfile(out_path):
                return ProcessResult(output_path=out_path)
            return ProcessResult(error=r.stderr)
        except Exception as e:
            return ProcessResult(error=str(e))

    @property
    def output_path(self) -> Optional[str]:
        return self._output_path
