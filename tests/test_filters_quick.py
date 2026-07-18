"""Quick stratified filter integration test — runs under pytest."""
import os
import shutil
import sys
from collections import OrderedDict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import gi
gi.require_version("GObject", "2.0")

from PIL import Image, ImageDraw

from gmic.cli import GmicCLI
from gmic.parser import GmicFilterParser
from imagemagick.cli import ImageMagickCLI
from imagemagick.filters import get_builtin_filters as get_im_filters
from nodes import NodeGraph, InputNode, FilterNode, OutputNode
from processing.graph_executor import GraphExecutor

INTERACTIVE_FILTERS = {
    "fx_mask_color", "fx_extract_foreground", "fx_morph_interactive",
    "fx_warp_interactive", "fx_colorize_interactive", "fx_gmic_demos",
    "fx_curves_interactive",
    "gui_axis_streak", "gui_download_all_data",
    "gui_gb_about", "gui_layer_info", "gui_rep_acb", "gui_rep_colmt",
    "gui_rep_form_pixel", "gui_rep_frblur", "gui_rep_gv",
    "gui_rep_majority", "gui_rep_majority_threshold", "gui_rep_objvf",
    "gui_rep_perspective_streak", "gui_rep_polkal",
    "gui_rep_prime_surface", "gui_rep_pw", "gui_rep_recc", "gui_rep_regm",
    "gui_rep_sd", "gui_rep_shape_brick", "gui_rep_sptbwgp_recpoltrans",
    "gui_rep_tfrac", "gui_rep_trif", "gui_rep_trps",
    "fx_display_fft", "fx_fourier_transform", "fx_guided_lightrays",
    "fx_input_565", "fx_gmicky", "fx_rep_rpgtiler_noniso",
    "samj_Selection_Hermite_Spline", "samj_diaporama", "samj_test_tout_interactif",
}

STDLIB_BUG_FILTERS = {
    "fx_colorful_blobs", "fx_heightfield_warp", "fx_project_stereographic",
    "fx_speech_bubble", "cl_tangentialCircle", "cl_colorWheel",
    "cl_implicitEqua", "gtutor_abn", "mc_film_grain",
    "fx_karo_cimg_skel", "fx_karo_cimg_nlmeans", "fx_karo_pink_bianca",
    "fx_generate_random_portrait",
    "fx_droste", "fx_spherize", "fx_blur_motion", "fx_distort_rbf",
    "fx_warp_perspective", "fx_twisted_rays", "fx_quadrangle",
    "fx_ultrawarp4plus", "fx_self_glitching_cascade",
    "fx_apply_haldclut", "fx_illuminate_shape2d", "fx_random_pattern",
    "fx_spline_spirograph", "fx_crazy_texture", "fx_jr_deform",
    "fx_buffer_destroyer", "fx_shifter", "fx_jfif_bomb",
    "fx_jr_multi_mosaic_preview", "fx_fourier_picture_watermark",
    "fx_layer_cake_2", "fx_gcd_crmt_tile",
    "fx_euclidean2polar", "fx_for_littbarski", "fx_fire_edges",
    "fx_cupid", "fx_intarsia", "fx_lightning",
    "fx_import_image_16", "fx_ExposureWeightMap", "fx_SmoothSketch",
    "fx_MorphoPaint", "pat_rgb", "gcd_layers", "gcd_stereo_vid",
    "iain_savenoiseprint", "iain_fast_formula", "jeje_render3d",
    "fx_karo_pink", "fx_karo_pink_bin",
    "fx_animate_cartoon", "fx_animate_edges", "fx_animate_elevation3d",
    "fx_animate_extrude3d", "fx_animate_glow", "fx_animate_imageobject3d",
    "fx_animate_lissajous", "fx_animate_pencilbw", "fx_animate_rodilius",
    "fx_animate_stencilbw", "fx_lavalampbw", "fx_moire",
    "fx_spatial_transition", "fx_text_pointcloud3d",
    # builtin filters with wrong command names in parser.py
    "oilpaint", "boost_chroma", "light_balance", "retinex",
    "colorize", "fx_cpencil", "watercolor",
    # stdlib filters with argument incompatibilities
    "apply_from_clut_set",
}


def _quick_sample(filters, n_per_category=2, total_cap=15):
    candidates = [f for f in filters
                  if f.name not in INTERACTIVE_FILTERS
                  and f.name not in STDLIB_BUG_FILTERS]
    groups = OrderedDict()
    for f in candidates:
        cat = f.category[0] if f.category else "Other"
        groups.setdefault(cat, []).append(f)
    result = []
    for cat in sorted(groups):
        result.extend(groups[cat][:n_per_category])
        if len(result) >= total_cap:
            break
    return result[:total_cap]


def _build_filter_graph(test_image: str, filter_def):
    graph = NodeGraph()
    inp = InputNode("in")
    inp.file_path = test_image
    graph.add_node(inp)
    flt = FilterNode("flt", filter_def)
    graph.add_node(flt)
    out = OutputNode("out")
    graph.add_node(out)
    graph.add_edge("in", "image", "flt", "image")
    for i in range(1, filter_def.image_input_count):
        port_name = f"image_{i + 1}"
        graph.add_edge("in", "image", "flt", port_name)
    graph.add_edge("flt", "image", "out", "image")
    return graph


@pytest.fixture(scope="module")
def test_image(tmp_path_factory):
    img_dir = tmp_path_factory.mktemp("ring_test")
    path = str(img_dir / "input.png")
    img = Image.new("RGB", (200, 200))
    for x in range(200):
        for y in range(200):
            r = x * 255 // 200
            g = y * 255 // 200
            b = 128
            img.putpixel((x, y), (r, g, b))
    draw = ImageDraw.Draw(img)
    draw.ellipse([50, 50, 150, 150], outline=(255, 255, 255), width=3)
    draw.rectangle([20, 20, 80, 80], outline=(0, 255, 0), width=2)
    draw.line([0, 0, 200, 200], fill=(255, 0, 0), width=2)
    img.save(path)
    return path


def _collect_filter_defs():
    """Return list of (label, FilterDef) for quick stratified testing."""
    gmic_ok = shutil.which("gmic") is not None
    magick_ok = shutil.which("magick") is not None

    filter_defs = []

    if gmic_ok:
        cli = GmicCLI()
        gmic_filters = cli.list_filters()
        if gmic_filters:
            for fd in _quick_sample(gmic_filters):
                filter_defs.append(("G'MIC Stdlib", fd))

        builtins = GmicFilterParser().get_builtin_filters()
        if builtins:
            for fd in _quick_sample(builtins):
                filter_defs.append(("G'MIC Builtin", fd))

    if magick_ok:
        im_filters = get_im_filters()
        if im_filters:
            for fd in _quick_sample(im_filters):
                filter_defs.append(("ImageMagick", fd))

    return filter_defs


def test_filters_quick(test_image):
    gmic_ok = shutil.which("gmic") is not None
    magick_ok = shutil.which("magick") is not None

    if not gmic_ok and not magick_ok:
        pytest.skip("Neither gmic nor magick found on PATH")

    gmic_cli = GmicCLI() if gmic_ok else GmicCLI()
    im_cli = ImageMagickCLI() if magick_ok else ImageMagickCLI()
    executor = GraphExecutor(gmic_cli, im_cli)

    filter_defs = _collect_filter_defs()

    if not filter_defs:
        pytest.skip("No filter definitions found")

    failures = []
    for label, fd in filter_defs:
        graph = _build_filter_graph(test_image, fd)
        result = executor.execute(graph, "png", timeout=30)
        ok = result.success and result.output_path and os.path.getsize(result.output_path) > 100
        if not ok:
            failures.append((label, fd.name, result.error or "no output"))

    if failures:
        lines = "\n".join(f"  [{e}] {n}: {err}" for e, n, err in failures)
        pytest.fail(f"{len(failures)}/{len(filter_defs)} filters failed:\n{lines}")
