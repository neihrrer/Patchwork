import math
import os
import tempfile
from typing import Optional, Callable

from nodes import (
    NodeGraph, InputNode, VideoInputNode, TimeNode, RawInputNode, RawDecodeNode, OutputNode, FilterNode, BlendNode,
    OpacityNode, MaskNode,
    BrightnessContrastNode, LevelsNode, HSLNode,
    ColorSourceNode, GradientNode, NoiseNode,
    ColorBalanceNode, ExposureGammaNode, CurvesNode,
    CropNode, ResizeNode, RotateNode, FlipNode, DistortNode,
    BlurNode, SharpenNode, EdgeDetectNode,
    ConstantNode, AddNode, SubtractNode, MultiplyNode, DivideNode,
    CeilNode, FloorNode, RoundNode, SumNode, ProductNode,
    ModuloNode, PowerNode, SquareRootNode, AbsoluteNode, LogNode, ExpNode, RandomNode,
    HistogramNode, WaveformMonitorNode, VectorscopeNode, FrequencyDomainNode,
    NotNode, AndNode, OrNode, NandNode, NorNode, XorNode, XnorNode,
    CompareNode, ClampNode, MapRangeNode,
)
from models.filter import ENGINE_GMIC, ParamKind
from gmic.cli import GmicCLI
from gmic.pipeline import _serialize_param
from imagemagick.cli import ImageMagickCLI
from processing.runner import ProcessResult
from processing.pillow_ops import (
    blend_images, adjust_opacity, adjust_hsl,
    adjust_brightness_contrast, adjust_levels, apply_mask,
    generate_color_source, generate_gradient, generate_noise,
    adjust_color_balance, adjust_exposure_gamma, adjust_curves,
    crop_image, resize_image, rotate_image, flip_image, distort_image,
    blur_image, sharpen_image, edge_detect,
    decode_raw,
)
from processing.analysis import (
    compute_histogram_data, compute_waveform_data, compute_vectorscope_data,
    compute_frequency_data,
)


class GraphExecutor:
    def __init__(self, gmic: GmicCLI, imagemagick: ImageMagickCLI):
        self._gmic = gmic
        self._imagemagick = imagemagick
        self._output_paths: dict[str, str] = {}
        self._ffmpeg: Optional[object] = None

    def set_ffmpeg(self, ffmpeg):
        self._ffmpeg = ffmpeg

    def execute(self, graph: NodeGraph, output_format: str = "png",
                progress_callback: Optional[Callable[[str], None]] = None,
                timeout: int = 120, frame: int = 0,
                force_refresh: bool = False,
                cancel_event=None) -> ProcessResult:
        self._timeout = timeout
        self._cancel_event = cancel_event
        self._output_paths = {}
        order = graph.topological_sort()
        if not order:
            return ProcessResult(error="Graph has no valid execution order (cycle or empty)")

        def cancelled():
            return self._cancel_event is not None and self._cancel_event.is_set()

        if force_refresh:
            for n in graph.nodes.values():
                n.cache_dirty = True

        node_outputs: dict[str, str] = {}
        numeric_outputs: dict[str, float] = {}

        for node in order:
            if cancelled():
                return ProcessResult(error="Rendering cancelled", cancelled=True)

            if progress_callback:
                progress_callback(f"Processing: {node.label}")

            was_processed = True

            if isinstance(node, InputNode):
                if node.file_path and os.path.isfile(node.file_path):
                    node_outputs[node.id] = node.file_path
                    node.cached_output_path = node.file_path
                    node.cache_dirty = False
                else:
                    return ProcessResult(error=f"Input node '{node.label}' has no file set")

            elif isinstance(node, TimeNode):
                node._last_frame = frame
                numeric_outputs[node.id] = node.value_for(frame)

            elif isinstance(node, VideoInputNode):
                if not node.file_path:
                    return ProcessResult(error=f"Video Input node '{node.label}' has no file set")
                if not os.path.isfile(node.file_path):
                    return ProcessResult(error=f"Video file not found: {node.file_path}")
                if not self._ffmpeg:
                    return ProcessResult(error="Video input requires ffmpeg, which is not available")
                fd, frame_path = tempfile.mkstemp(suffix=".png")
                os.close(fd)
                result = self._ffmpeg.extract_frame(node.file_path, frame, frame_path, timeout=timeout)
                if not result.success:
                    return ProcessResult(error=result.error, stdout=result.stdout, stderr=result.stderr)
                node.cached_output_path = frame_path
                node.cache_dirty = False
                node_outputs[node.id] = frame_path

            elif isinstance(node, RawInputNode):
                if node.file_path and os.path.isfile(node.file_path):
                    node_outputs[node.id] = node.file_path
                    node.cached_output_path = node.file_path
                    node.cache_dirty = False
                else:
                    return ProcessResult(error=f"Raw Input node '{node.label}' has no file set")

            elif isinstance(node, RawDecodeNode):
                was_processed = node.cache_dirty or not node.cached_output_path
                if was_processed:
                    inp = self._first_raw_input(node, graph, node_outputs)
                    if not inp:
                        return ProcessResult(error=f"Raw Decode '{node.label}' has no input")
                    result = decode_raw(inp, node.decode_method,
                                        node.decode_width, node.decode_height,
                                        node.byte_offset, output_format)
                    if not result.success:
                        return result
                    node.cached_output_path = result.output_path
                    node.cache_dirty = False
                node_outputs[node.id] = node.cached_output_path

            elif isinstance(node, FilterNode):
                was_processed = node.cache_dirty or not node.cached_output_path
                if was_processed:
                    inputs = self._ordered_inputs(node, graph, node_outputs)
                    if not inputs:
                        return ProcessResult(error=f"Filter '{node.label}' has no input connected")
                    if len(inputs) < node.filter_def.image_input_count:
                        return ProcessResult(error=f"Filter '{node.label}' needs {node.filter_def.image_input_count} images, got {len(inputs)}")
                    result = self._run_filter(node, inputs, output_format, graph, numeric_outputs, self._timeout)
                    if not result.success:
                        return result
                    node.cached_output_path = result.output_path
                    node.cache_dirty = False
                node_outputs[node.id] = node.cached_output_path

            elif isinstance(node, BlendNode):
                inputs = self._ordered_inputs(node, graph, node_outputs)
                if len(inputs) < 2:
                    return ProcessResult(error=f"Blend '{node.label}' needs 2 inputs, got {len(inputs)}")
                result = blend_images(inputs, node.mode, output_format)
                if not result.success:
                    return result
                node_outputs[node.id] = result.output_path

            elif isinstance(node, BrightnessContrastNode):
                inp = self._first_input(node, graph, node_outputs)
                if not inp:
                    return ProcessResult(error=f"Brightness/Contrast '{node.label}' has no input")
                brightness = self._get_numeric_input(node, "brightness", graph, numeric_outputs) or node.brightness
                contrast = self._get_numeric_input(node, "contrast", graph, numeric_outputs) or node.contrast
                result = adjust_brightness_contrast(inp, brightness, contrast, output_format)
                if not result.success:
                    return result
                node_outputs[node.id] = result.output_path

            elif isinstance(node, LevelsNode):
                inp = self._first_input(node, graph, node_outputs)
                if not inp:
                    return ProcessResult(error=f"Levels '{node.label}' has no input")
                black_point = self._get_numeric_input(node, "black_point", graph, numeric_outputs) or node.black_point
                white_point = self._get_numeric_input(node, "white_point", graph, numeric_outputs) or node.white_point
                gamma = self._get_numeric_input(node, "gamma", graph, numeric_outputs) or node.gamma
                result = adjust_levels(inp, black_point, white_point, gamma, output_format)
                if not result.success:
                    return result
                node_outputs[node.id] = result.output_path

            elif isinstance(node, HSLNode):
                inp = self._first_input(node, graph, node_outputs)
                if not inp:
                    return ProcessResult(error=f"HSL '{node.label}' has no input")
                hue = self._get_numeric_input(node, "hue", graph, numeric_outputs) or node.hue
                saturation = self._get_numeric_input(node, "saturation", graph, numeric_outputs) or node.saturation
                lightness = self._get_numeric_input(node, "lightness", graph, numeric_outputs) or node.lightness
                result = adjust_hsl(inp, hue, saturation, lightness, output_format)
                if not result.success:
                    return result
                node_outputs[node.id] = result.output_path

            elif isinstance(node, OpacityNode):
                inp = self._first_input(node, graph, node_outputs)
                if not inp:
                    return ProcessResult(error=f"Opacity '{node.label}' has no input")
                opacity = self._get_numeric_input(node, "opacity", graph, numeric_outputs) or node.opacity
                result = adjust_opacity(inp, opacity, output_format)
                if not result.success:
                    return result
                node_outputs[node.id] = result.output_path

            elif isinstance(node, MaskNode):
                inputs = self._all_inputs(node, graph, node_outputs)
                if len(inputs) < 2:
                    return ProcessResult(error=f"Mask '{node.label}' needs 2 inputs, got {len(inputs)}")
                threshold = self._get_numeric_input(node, "threshold", graph, numeric_outputs) or node.threshold
                result = apply_mask(inputs[0], inputs[1], node.invert, threshold, output_format)
                if not result.success:
                    return result
                node_outputs[node.id] = result.output_path

            elif isinstance(node, ColorSourceNode):
                result = generate_color_source(node.source_width, node.source_height, node.color, output_format)
                if not result.success:
                    return result
                node_outputs[node.id] = result.output_path

            elif isinstance(node, GradientNode):
                result = generate_gradient(node.source_width, node.source_height, node.gradient_type,
                                           node.start_color, node.end_color, node.angle, output_format)
                if not result.success:
                    return result
                node_outputs[node.id] = result.output_path

            elif isinstance(node, NoiseNode):
                result = generate_noise(node.source_width, node.source_height, node.noise_type,
                                        node.scale, node.seed if node.seed else None, output_format)
                if not result.success:
                    return result
                node_outputs[node.id] = result.output_path

            elif isinstance(node, ColorBalanceNode):
                inp = self._first_input(node, graph, node_outputs)
                if not inp:
                    return ProcessResult(error=f"Color Balance '{node.label}' has no input")
                cr = self._get_numeric_input(node, "cyan_red", graph, numeric_outputs) or node.cyan_red
                mg = self._get_numeric_input(node, "magenta_green", graph, numeric_outputs) or node.magenta_green
                yb = self._get_numeric_input(node, "yellow_blue", graph, numeric_outputs) or node.yellow_blue
                result = adjust_color_balance(inp, cr, mg, yb, output_format)
                if not result.success:
                    return result
                node_outputs[node.id] = result.output_path

            elif isinstance(node, ExposureGammaNode):
                inp = self._first_input(node, graph, node_outputs)
                if not inp:
                    return ProcessResult(error=f"Exposure/Gamma '{node.label}' has no input")
                exposure = self._get_numeric_input(node, "exposure", graph, numeric_outputs) or node.exposure
                gamma = self._get_numeric_input(node, "gamma", graph, numeric_outputs) or node.gamma
                result = adjust_exposure_gamma(inp, exposure, gamma, output_format)
                if not result.success:
                    return result
                node_outputs[node.id] = result.output_path

            elif isinstance(node, CurvesNode):
                inp = self._first_input(node, graph, node_outputs)
                if not inp:
                    return ProcessResult(error=f"Curves '{node.label}' has no input")
                shadows = self._get_numeric_input(node, "shadows", graph, numeric_outputs) or node.shadows
                dark_mid = self._get_numeric_input(node, "dark_midtones", graph, numeric_outputs) or node.dark_midtones
                midtones = self._get_numeric_input(node, "midtones", graph, numeric_outputs) or node.midtones
                light_mid = self._get_numeric_input(node, "light_midtones", graph, numeric_outputs) or node.light_midtones
                highlights = self._get_numeric_input(node, "highlights", graph, numeric_outputs) or node.highlights
                result = adjust_curves(inp, shadows, dark_mid, midtones, light_mid, highlights, output_format)
                if not result.success:
                    return result
                node_outputs[node.id] = result.output_path

            elif isinstance(node, CropNode):
                inp = self._first_input(node, graph, node_outputs)
                if not inp:
                    return ProcessResult(error=f"Crop '{node.label}' has no input")
                cx = self._get_numeric_input(node, "x", graph, numeric_outputs) or node.crop_x
                cy = self._get_numeric_input(node, "y", graph, numeric_outputs) or node.crop_y
                cw = self._get_numeric_input(node, "width", graph, numeric_outputs) or node.crop_width
                ch = self._get_numeric_input(node, "height", graph, numeric_outputs) or node.crop_height
                result = crop_image(inp, cx, cy, cw, ch, output_format)
                if not result.success:
                    return result
                node_outputs[node.id] = result.output_path

            elif isinstance(node, ResizeNode):
                inp = self._first_input(node, graph, node_outputs)
                if not inp:
                    return ProcessResult(error=f"Resize '{node.label}' has no input")
                rw = self._get_numeric_input(node, "width", graph, numeric_outputs) or node.resize_width
                rh = self._get_numeric_input(node, "height", graph, numeric_outputs) or node.resize_height
                result = resize_image(inp, rw, rh, node.resize_mode, output_format)
                if not result.success:
                    return result
                node_outputs[node.id] = result.output_path

            elif isinstance(node, RotateNode):
                inp = self._first_input(node, graph, node_outputs)
                if not inp:
                    return ProcessResult(error=f"Rotate '{node.label}' has no input")
                angle = self._get_numeric_input(node, "angle", graph, numeric_outputs) or node.angle
                result = rotate_image(inp, angle, output_format)
                if not result.success:
                    return result
                node_outputs[node.id] = result.output_path

            elif isinstance(node, FlipNode):
                inp = self._first_input(node, graph, node_outputs)
                if not inp:
                    return ProcessResult(error=f"Flip '{node.label}' has no input")
                result = flip_image(inp, node.direction, output_format)
                if not result.success:
                    return result
                node_outputs[node.id] = result.output_path

            elif isinstance(node, DistortNode):
                inp = self._first_input(node, graph, node_outputs)
                if not inp:
                    return ProcessResult(error=f"Distort '{node.label}' has no input")
                x0 = self._get_numeric_input(node, "x0", graph, numeric_outputs) or node.dist_x0
                y0 = self._get_numeric_input(node, "y0", graph, numeric_outputs) or node.dist_y0
                x1 = self._get_numeric_input(node, "x1", graph, numeric_outputs) or node.dist_x1
                y1 = self._get_numeric_input(node, "y1", graph, numeric_outputs) or node.dist_y1
                x2 = self._get_numeric_input(node, "x2", graph, numeric_outputs) or node.dist_x2
                y2 = self._get_numeric_input(node, "y2", graph, numeric_outputs) or node.dist_y2
                x3 = self._get_numeric_input(node, "x3", graph, numeric_outputs) or node.dist_x3
                y3 = self._get_numeric_input(node, "y3", graph, numeric_outputs) or node.dist_y3
                result = distort_image(inp, x0, y0, x1, y1, x2, y2, x3, y3, output_format)
                if not result.success:
                    return result
                node_outputs[node.id] = result.output_path

            elif isinstance(node, BlurNode):
                inp = self._first_input(node, graph, node_outputs)
                if not inp:
                    return ProcessResult(error=f"Blur '{node.label}' has no input")
                radius = self._get_numeric_input(node, "radius", graph, numeric_outputs) or node.radius
                result = blur_image(inp, radius, output_format)
                if not result.success:
                    return result
                node_outputs[node.id] = result.output_path

            elif isinstance(node, SharpenNode):
                inp = self._first_input(node, graph, node_outputs)
                if not inp:
                    return ProcessResult(error=f"Sharpen '{node.label}' has no input")
                amount = self._get_numeric_input(node, "amount", graph, numeric_outputs) or node.amount
                radius = self._get_numeric_input(node, "radius", graph, numeric_outputs) or node.radius
                result = sharpen_image(inp, amount, radius, output_format)
                if not result.success:
                    return result
                node_outputs[node.id] = result.output_path

            elif isinstance(node, EdgeDetectNode):
                inp = self._first_input(node, graph, node_outputs)
                if not inp:
                    return ProcessResult(error=f"Edge Detect '{node.label}' has no input")
                threshold = self._get_numeric_input(node, "threshold", graph, numeric_outputs) or node.threshold
                result = edge_detect(inp, threshold, output_format)
                if not result.success:
                    return result
                node_outputs[node.id] = result.output_path

            elif isinstance(node, OutputNode):
                inp = self._first_input(node, graph, node_outputs)
                if inp:
                    node_outputs[node.id] = inp
                    self._output_paths[node.id] = inp

            elif isinstance(node, HistogramNode):
                inp = self._first_input(node, graph, node_outputs)
                if not inp:
                    return ProcessResult(error=f"Histogram '{node.label}' has no input")
                node.analysis_data = compute_histogram_data(inp)
                node.cache_dirty = False

            elif isinstance(node, WaveformMonitorNode):
                inp = self._first_input(node, graph, node_outputs)
                if not inp:
                    return ProcessResult(error=f"Waveform Monitor '{node.label}' has no input")
                node.analysis_data = compute_waveform_data(inp)
                node.cache_dirty = False

            elif isinstance(node, VectorscopeNode):
                inp = self._first_input(node, graph, node_outputs)
                if not inp:
                    return ProcessResult(error=f"Vectorscope '{node.label}' has no input")
                node.analysis_data = compute_vectorscope_data(inp)
                node.cache_dirty = False

            elif isinstance(node, FrequencyDomainNode):
                inp = self._first_input(node, graph, node_outputs)
                if not inp:
                    return ProcessResult(error=f"Frequency Domain '{node.label}' has no input")
                node.analysis_data = compute_frequency_data(inp)
                node.cache_dirty = False

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

            elif isinstance(node, CeilNode):
                a = self._get_numeric_input(node, "a", graph, numeric_outputs) or 0.0
                numeric_outputs[node.id] = math.ceil(a)

            elif isinstance(node, FloorNode):
                a = self._get_numeric_input(node, "a", graph, numeric_outputs) or 0.0
                numeric_outputs[node.id] = math.floor(a)

            elif isinstance(node, RoundNode):
                a = self._get_numeric_input(node, "a", graph, numeric_outputs) or 0.0
                numeric_outputs[node.id] = round(a)

            elif isinstance(node, SumNode):
                a = self._get_numeric_input(node, "a", graph, numeric_outputs) or 0.0
                b = self._get_numeric_input(node, "b", graph, numeric_outputs) or 0.0
                numeric_outputs[node.id] = a + b

            elif isinstance(node, ProductNode):
                a = self._get_numeric_input(node, "a", graph, numeric_outputs) or 0.0
                b = self._get_numeric_input(node, "b", graph, numeric_outputs) or 0.0
                numeric_outputs[node.id] = a * b

            elif isinstance(node, NotNode):
                a = self._get_numeric_input(node, "a", graph, numeric_outputs) or 0.0
                numeric_outputs[node.id] = 1.0 if a == 0.0 else 0.0

            elif isinstance(node, AndNode):
                a = self._get_numeric_input(node, "a", graph, numeric_outputs) or 0.0
                b = self._get_numeric_input(node, "b", graph, numeric_outputs) or 0.0
                numeric_outputs[node.id] = 1.0 if a != 0.0 and b != 0.0 else 0.0

            elif isinstance(node, OrNode):
                a = self._get_numeric_input(node, "a", graph, numeric_outputs) or 0.0
                b = self._get_numeric_input(node, "b", graph, numeric_outputs) or 0.0
                numeric_outputs[node.id] = 1.0 if a != 0.0 or b != 0.0 else 0.0

            elif isinstance(node, NandNode):
                a = self._get_numeric_input(node, "a", graph, numeric_outputs) or 0.0
                b = self._get_numeric_input(node, "b", graph, numeric_outputs) or 0.0
                numeric_outputs[node.id] = 0.0 if a != 0.0 and b != 0.0 else 1.0

            elif isinstance(node, NorNode):
                a = self._get_numeric_input(node, "a", graph, numeric_outputs) or 0.0
                b = self._get_numeric_input(node, "b", graph, numeric_outputs) or 0.0
                numeric_outputs[node.id] = 0.0 if a != 0.0 or b != 0.0 else 1.0

            elif isinstance(node, XorNode):
                a = self._get_numeric_input(node, "a", graph, numeric_outputs) or 0.0
                b = self._get_numeric_input(node, "b", graph, numeric_outputs) or 0.0
                numeric_outputs[node.id] = 1.0 if (a != 0.0) != (b != 0.0) else 0.0

            elif isinstance(node, XnorNode):
                a = self._get_numeric_input(node, "a", graph, numeric_outputs) or 0.0
                b = self._get_numeric_input(node, "b", graph, numeric_outputs) or 0.0
                numeric_outputs[node.id] = 1.0 if (a != 0.0) == (b != 0.0) else 0.0

            elif isinstance(node, CompareNode):
                a = self._get_numeric_input(node, "a", graph, numeric_outputs) or 0.0
                b = self._get_numeric_input(node, "b", graph, numeric_outputs) or 0.0
                op = node.operator
                result = False
                if op == "==":
                    result = a == b
                elif op == "!=":
                    result = a != b
                elif op == "<":
                    result = a < b
                elif op == ">":
                    result = a > b
                elif op == "<=":
                    result = a <= b
                elif op == ">=":
                    result = a >= b
                numeric_outputs[node.id] = 1.0 if result else 0.0

            elif isinstance(node, ClampNode):
                a = self._get_numeric_input(node, "a", graph, numeric_outputs) or 0.0
                numeric_outputs[node.id] = max(node.min_val, min(node.max_val, a))

            elif isinstance(node, MapRangeNode):
                a = self._get_numeric_input(node, "a", graph, numeric_outputs) or 0.0
                in_range = node.in_max - node.in_min
                if in_range == 0.0:
                    numeric_outputs[node.id] = node.out_min
                else:
                    t = (a - node.in_min) / in_range
                    numeric_outputs[node.id] = node.out_min + t * (node.out_max - node.out_min)

            elif isinstance(node, ModuloNode):
                a = self._get_numeric_input(node, "a", graph, numeric_outputs) or 0.0
                b = self._get_numeric_input(node, "b", graph, numeric_outputs) or 1.0
                if b == 0.0:
                    return ProcessResult(error=f"Modulo by zero in node '{node.label}'")
                numeric_outputs[node.id] = a % b

            elif isinstance(node, PowerNode):
                a = self._get_numeric_input(node, "a", graph, numeric_outputs) or 0.0
                b = self._get_numeric_input(node, "b", graph, numeric_outputs) or 1.0
                numeric_outputs[node.id] = a ** b

            elif isinstance(node, SquareRootNode):
                a = self._get_numeric_input(node, "a", graph, numeric_outputs) or 0.0
                if a < 0.0:
                    return ProcessResult(error=f"Square root of negative number in node '{node.label}'")
                numeric_outputs[node.id] = math.sqrt(a)

            elif isinstance(node, AbsoluteNode):
                a = self._get_numeric_input(node, "a", graph, numeric_outputs) or 0.0
                numeric_outputs[node.id] = abs(a)

            elif isinstance(node, LogNode):
                a = self._get_numeric_input(node, "a", graph, numeric_outputs) or 1.0
                if a <= 0.0:
                    return ProcessResult(error=f"Log of non-positive number in node '{node.label}'")
                numeric_outputs[node.id] = math.log(a)

            elif isinstance(node, ExpNode):
                a = self._get_numeric_input(node, "a", graph, numeric_outputs) or 0.0
                numeric_outputs[node.id] = math.exp(a)

            elif isinstance(node, RandomNode):
                node.randomize()
                numeric_outputs[node.id] = node.value

            if was_processed:
                for e in graph.edges:
                    if e.src_node == node.id:
                        dst = graph.nodes.get(e.dst_node)
                        if dst:
                            dst.cache_dirty = True

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

    def _first_raw_input(self, node, graph: NodeGraph, outputs: dict[str, str]) -> Optional[str]:
        for e in graph.edges:
            if e.dst_node == node.id:
                path = outputs.get(e.src_node)
                if path:
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

    def _run_filter(self, node: FilterNode, input_paths: list[str], output_fmt: str,
                     graph: Optional[NodeGraph] = None,
                     numeric_outputs: Optional[dict[str, float]] = None,
                     timeout: int = 120) -> ProcessResult:
        fd, out_path = tempfile.mkstemp(suffix="." + output_fmt)
        os.close(fd)

        raw_cmd = node.filter_def.gmic_command
        space_idx = raw_cmd.find(" ")
        cmd_name = raw_cmd[:space_idx] if space_idx >= 0 else raw_cmd
        params = node.filter_def.parameters
        values = [node.param_values.get(p.name, p.default) for p in params]
        for i, p in enumerate(params):
            if p.kind in (ParamKind.INT, ParamKind.FLOAT) and not p.is_hidden and graph and numeric_outputs:
                num_val = self._get_numeric_input(node, p.name, graph, numeric_outputs)
                if num_val is not None:
                    values[i] = int(num_val) if p.kind == ParamKind.INT else num_val
        serialized = [_serialize_param(value, p) for value, p in zip(values, params)]
        if serialized:
            full_cmd = cmd_name + "," + ",".join(serialized)
        elif space_idx >= 0:
            full_cmd = raw_cmd
        else:
            full_cmd = cmd_name
        commands = [input_paths[0], full_cmd]

        # The CLI cannot carry a text value with a space (it quotes the whole
        # argument list and the commas stop splitting), so such commands run
        # from a temporary command file instead.
        script_cmd = None
        needs_script = any(
            p.kind == ParamKind.TEXT and (
                (isinstance(value, str) and " " in value)
                or (value in (None, "") and isinstance(p.default, str) and " " in p.default))
            for value, p in zip(values, params))
        if needs_script:
            script_values = [_serialize_param(value, p, style="script")
                             for value, p in zip(values, params)]
            script_cmd = cmd_name + ((" " + ",".join(script_values)) if script_values else "")

        if node.filter_def.engine == ENGINE_GMIC:
            result = self._gmic.run_pipeline(input_paths, commands[1:], out_path, timeout=timeout,
                                             script_command=script_cmd)
        else:
            result = self._imagemagick.run_pipeline(input_paths[0], commands[1:], out_path, timeout=timeout)

        if result.success:
            return ProcessResult(output_path=result.output_path)
        return ProcessResult(error=result.error, stdout=result.stdout, stderr=result.stderr)

