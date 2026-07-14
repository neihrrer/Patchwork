import os
import tempfile
import subprocess
from typing import Optional, Callable

from nodes import (
    NodeGraph, InputNode, OutputNode, FilterNode, BlendNode, ColorNode,
    OpacityNode, ColoringNode, MaskNode,
    ConstantNode, AddNode, SubtractNode, MultiplyNode, DivideNode,
)
from models.filter import ENGINE_GMIC, ParamKind
from gmic.cli import GmicCLI
from gmic.pipeline import _serialize_param
from imagemagick.cli import ImageMagickCLI
from processing.runner import ProcessResult


class GraphExecutor:
    def __init__(self, gmic: GmicCLI, imagemagick: ImageMagickCLI):
        self._gmic = gmic
        self._imagemagick = imagemagick
        self._output_paths: dict[str, str] = {}

    def execute(self, graph: NodeGraph, output_format: str = "png",
                progress_callback: Optional[Callable[[str], None]] = None) -> ProcessResult:
        self._output_paths = {}
        order = graph.topological_sort()
        if not order:
            return ProcessResult(error="Graph has no valid execution order (cycle or empty)")

        node_outputs: dict[str, str] = {}
        numeric_outputs: dict[str, float] = {}

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
                    result = self._run_filter(node, inp, output_format, graph, numeric_outputs)
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
                brightness = self._get_numeric_input(node, "brightness", graph, numeric_outputs) or node.brightness
                contrast = self._get_numeric_input(node, "contrast", graph, numeric_outputs) or node.contrast
                saturation = self._get_numeric_input(node, "saturation", graph, numeric_outputs) or node.saturation
                hue = self._get_numeric_input(node, "hue", graph, numeric_outputs) or node.hue
                black_point = self._get_numeric_input(node, "black_point", graph, numeric_outputs) or node.black_point
                white_point = self._get_numeric_input(node, "white_point", graph, numeric_outputs) or node.white_point
                gamma = self._get_numeric_input(node, "gamma", graph, numeric_outputs) or node.gamma
                result = self._run_color_params(inp, node.operation, brightness, contrast, saturation, hue, black_point, white_point, gamma, output_format)
                if not result.success:
                    return result
                node_outputs[node.id] = result.output_path

            elif isinstance(node, OpacityNode):
                inp = self._first_input(node, graph, node_outputs)
                if not inp:
                    return ProcessResult(error=f"Opacity node '{node.label}' has no input")
                opacity = self._get_numeric_input(node, "opacity", graph, numeric_outputs) or node.opacity
                result = self._run_opacity(inp, opacity, output_format)
                if not result.success:
                    return result
                node_outputs[node.id] = result.output_path

            elif isinstance(node, ColoringNode):
                inp = self._first_input(node, graph, node_outputs)
                if not inp:
                    return ProcessResult(error=f"Coloring node '{node.label}' has no input")
                hue = self._get_numeric_input(node, "hue", graph, numeric_outputs) or node.hue
                saturation = self._get_numeric_input(node, "saturation", graph, numeric_outputs) or node.saturation
                lightness = self._get_numeric_input(node, "lightness", graph, numeric_outputs) or node.lightness
                result = self._run_coloring(inp, hue, saturation, lightness, output_format)
                if not result.success:
                    return result
                node_outputs[node.id] = result.output_path

            elif isinstance(node, MaskNode):
                inputs = self._all_inputs(node, graph, node_outputs)
                if len(inputs) < 2:
                    return ProcessResult(error=f"Mask '{node.label}' needs 2 inputs, got {len(inputs)}")
                threshold = self._get_numeric_input(node, "threshold", graph, numeric_outputs) or node.threshold
                result = self._run_mask(inputs[0], inputs[1], node.invert, threshold, output_format)
                if not result.success:
                    return result
                node_outputs[node.id] = result.output_path

            elif isinstance(node, OutputNode):
                inp = self._first_input(node, graph, node_outputs)
                if inp:
                    node_outputs[node.id] = inp
                    self._output_paths[node.id] = inp

            elif isinstance(node, ConstantNode):
                numeric_outputs[node.id] = node.value

            elif isinstance(node, AddNode):
                a = self._get_numeric_input(node, "a", graph, numeric_outputs) or 0.0
                b = self._get_numeric_input(node, "b", graph, numeric_outputs) or 0.0
                numeric_outputs[node.id] = a + b

            elif isinstance(node, SubtractNode):
                a = self._get_numeric_input(node, "a", graph, numeric_outputs) or 0.0
                b = self._get_numeric_input(node, "b", graph, numeric_outputs) or 0.0
                numeric_outputs[node.id] = a - b

            elif isinstance(node, MultiplyNode):
                a = self._get_numeric_input(node, "a", graph, numeric_outputs) or 0.0
                b = self._get_numeric_input(node, "b", graph, numeric_outputs) or 0.0
                numeric_outputs[node.id] = a * b

            elif isinstance(node, DivideNode):
                a = self._get_numeric_input(node, "a", graph, numeric_outputs) or 0.0
                b = self._get_numeric_input(node, "b", graph, numeric_outputs) or 0.0
                if b == 0.0:
                    return ProcessResult(error=f"Divide by zero in node '{node.label}'")
                numeric_outputs[node.id] = a / b

        has_output_nodes = any(isinstance(n, OutputNode) for n in graph.nodes.values())

        if self._output_paths:
            first = list(self._output_paths.values())[0]
            return ProcessResult(output_path=first, output_paths=self._output_paths.copy())

        if has_output_nodes:
            return ProcessResult(error="No output node has a connected input")

        if node_outputs:
            return ProcessResult(error="Graph has no output node")

        return ProcessResult(error="No output produced")

    def _first_input(self, node, graph: NodeGraph, outputs: dict[str, str]) -> Optional[str]:
        for e in graph.edges:
            if e.dst_node == node.id:
                path = outputs.get(e.src_node)
                if path and os.path.isfile(path):
                    return path
        return None

    def _get_numeric_input(self, node, port_name: str, graph: NodeGraph, numeric_outputs: dict[str, float]) -> Optional[float]:
        for e in graph.edges:
            if e.dst_node == node.id and e.dst_port == port_name:
                val = numeric_outputs.get(e.src_node)
                if val is not None:
                    return val
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

    def _run_filter(self, node: FilterNode, input_path: str, output_fmt: str,
                     graph: Optional[NodeGraph] = None,
                     numeric_outputs: Optional[dict[str, float]] = None) -> ProcessResult:
        fd, out_path = tempfile.mkstemp(suffix="." + output_fmt)
        os.close(fd)

        commands = [input_path, node.filter_def.gmic_command]
        for p in node.filter_def.parameters:
            val = node.param_values.get(p.name, p.default)
            if p.kind in (ParamKind.INT, ParamKind.FLOAT) and not p.is_hidden and graph and numeric_outputs:
                num_val = self._get_numeric_input(node, p.name, graph, numeric_outputs)
                if num_val is not None:
                    val = int(num_val) if p.kind == ParamKind.INT else num_val
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

    def _run_color_params(self, input_path: str, operation: str, brightness: float, contrast: float, saturation: float, hue: float, black_point: float, white_point: float, gamma: float, fmt: str) -> ProcessResult:
        if not self._imagemagick.available:
            return ProcessResult(error="ImageMagick required for color adjustments")
        fd, out_path = tempfile.mkstemp(suffix="." + fmt)
        os.close(fd)
        try:
            args = [self._imagemagick.magick_path, input_path]
            if operation == "brightness_contrast":
                args += ["-brightness-contrast", f"{brightness}x{contrast}"]
            elif operation == "hue_saturation":
                hue_val = 100 + hue * 100.0 / 180.0
                args += ["-modulate", f"100,{100 + saturation},{hue_val}"]
            elif operation == "levels":
                args += ["-level", f"{black_point}%,{white_point}%,{gamma}"]
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

    def _run_mask(self, base: str, mask: str, invert: bool, threshold: float, fmt: str) -> ProcessResult:
        if not self._imagemagick.available:
            return ProcessResult(error="ImageMagick required for mask operations")
        fd, out_path = tempfile.mkstemp(suffix="." + fmt)
        os.close(fd)
        try:
            if threshold > 0.0 or invert:
                mfd, mask_path = tempfile.mkstemp(suffix="." + fmt)
                os.close(mfd)
                mask_cmd = [self._imagemagick.magick_path, mask]
                if threshold > 0.0:
                    thresh_pct = threshold * 100.0
                    mask_cmd += ["-threshold", f"{thresh_pct}%"]
                if invert:
                    mask_cmd += ["-negate"]
                mask_cmd += [mask_path]
                r = subprocess.run(mask_cmd, capture_output=True, timeout=60, text=True)
                if r.returncode != 0 or not os.path.isfile(mask_path):
                    return ProcessResult(error="Mask processing failed: " + r.stderr)
                used_mask = mask_path
            else:
                used_mask = mask

            args = [self._imagemagick.magick_path, base, used_mask,
                    "-compose", "CopyOpacity", "-composite", out_path]
            r = subprocess.run(args, capture_output=True, timeout=60, text=True)
            if r.returncode == 0 and os.path.isfile(out_path):
                return ProcessResult(output_path=out_path)
            return ProcessResult(error=r.stderr)
        except Exception as e:
            return ProcessResult(error=str(e))


