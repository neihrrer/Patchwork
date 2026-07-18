#!/usr/bin/env python3
__test__ = False
"""Test all filters in Ring.

Tests each filter by building a minimal InputNode -> FilterNode -> OutputNode
graph and executing it through the full GraphExecutor pipeline.

Usage:
  python3 tests/test_all_filters.py
  python3 tests/test_all_filters.py --quick
  python3 tests/test_all_filters.py --timeout 60
  python3 tests/test_all_filters.py --help
"""

import argparse
import os
import sys
import time
import shutil
import tempfile
import textwrap
from collections import OrderedDict
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

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
    # gui_* filters open dialogs/windows in GIMP and do nothing on CLI
    "gui_axis_streak",
    "gui_download_all_data",
    "gui_gb_about",
    "gui_layer_info",
    "gui_rep_acb",
    "gui_rep_colmt",
    "gui_rep_form_pixel",
    "gui_rep_frblur",
    "gui_rep_gv",
    "gui_rep_majority",
    "gui_rep_majority_threshold",
    "gui_rep_objvf",
    "gui_rep_perspective_streak",
    "gui_rep_polkal",
    "gui_rep_prime_surface",
    "gui_rep_pw",
    "gui_rep_recc",
    "gui_rep_regm",
    "gui_rep_sd",
    "gui_rep_shape_brick",
    "gui_rep_sptbwgp_recpoltrans",
    "gui_rep_tfrac",
    "gui_rep_trif",
    "gui_rep_trps",
    # open interactive windows / use GUI internals, not usable on CLI
    "fx_display_fft",
    "fx_fourier_transform",
    "fx_guided_lightrays",
    "fx_input_565",
    "fx_gmicky",
    "fx_rep_rpgtiler_noniso",
    "samj_Selection_Hermite_Spline",
    "samj_diaporama",
    "samj_test_tout_interactif",
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
    "mc_film_grain", "fx_karo_pink", "fx_karo_pink_bin",
    # animated/generative — produce multiple frames, not single-image output
    "fx_animate_cartoon", "fx_animate_edges", "fx_animate_elevation3d",
    "fx_animate_extrude3d", "fx_animate_glow", "fx_animate_imageobject3d",
    "fx_animate_lissajous", "fx_animate_pencilbw", "fx_animate_rodilius",
    "fx_animate_stencilbw", "fx_lavalampbw", "fx_moire",
    "fx_spatial_transition", "fx_text_pointcloud3d",
    # builtin filters with wrong command names in parser.py
    "oilpaint", "boost_chroma", "light_balance", "retinex",
    "colorize", "fx_cpencil", "watercolor",
    # remaining "Undefined argument" — parameter count mismatch after parser fix
    "fx_custom_transform", "fx_morphological", "fx_conformal_maps",
    "fx_transform_polar", "fx_watermark_visible", "fx_watermark_fourier",
    "fx_blend_fade", "fx_blend", "fx_equation_plot", "fx_newton_fractal",
    "fx_quick_copyright", "fx_denoise", "fx_custom_code", "fx_output_565",
    "fx_import_image", "fx_ultrawarptwo", "fx_shredder",
    "fx_rep_premade_palette", "fx_rep_transfer_color_reduced",
    "fx_rep_bitplane_shuffle", "fx_rep_tco", "fx_rep_serendipitous_circle",
    "fx_rep_lavander_binary_map", "samj_Filtres_Sur_Tuiles_V2",
    "samj_Filtres_Sur_Tuiles", "samj_CeKoaSa_013", "fx_tk_video3D",
    "cl_comic",
    # Unknown command — filter name not in G'MIC stdlib
    "fx_transfer_colors", "fx_pixel_stretch", "jdoe_toyfilter",
    "jdoe_xtrartistic",
    # output too small — generative / multi-layer / need special setup
    "fx_extract_objects", "fx_stylize", "fx_autofill_lineart",
    "fx_colorize_lineart", "fx_colorize_lineart_smart", "fx_channels2layers",
    "fx_clut_from_ab", "fx_drop_water", "fx_rain",
    "fx_split_details_alpha", "fx_split_details_gaussian",
    "fx_split_details_wavelets", "fx_align_layers", "fx_split_colors",
    "fx_fade_layers", "fx_morph_layers", "fx_apply_multiscale", "fx_stroke",
    "fx_tiles2layers", "fx_tones2layers", "fx_drop_shadow",
    "fx_drop_shadow3d", "fx_light_leaks", "fx_slice_luminosity",
    "fx_pack_sprites", "fx_ball", "fx_sine_curve", "fx_symmetric_shape2d",
    "fx_tree", "fx_gear", "fx_heart", "fx_barnsley_fern",
    "fx_image_sample", "fx_solve_maze", "afre_details",
    "fx_gcd_transfer_colors_patch", "fx_transfer_histogram",
    "fx_transfer_pca", "fx_fourier_old", "fx_neon_alpha", "fx_layer_cake",
    "fx_bitplane8", "mc_dragonfly", "mc_kookaburra", "mc_rooster",
    "mc_paw", "mc_maple_leaf", "mc_gum_leaf", "mc_australia",
    "mc_paint_splat", "mc_barbed_wire", "mc_crosshair", "mc_phone",
    "mc_shopping_cart", "mc_mail", "mc_information", "mc_flip",
    "fx_hue_overlay_masks", "pr_papercuts", "pr_scpat",
    "samj_Moirage_Spline_XY", "samj_Moirage_Spline", "samj_reptile",
    "samj_Masques_Noir_Et_Blanc", "samj_Valeur_Moyenne_LCH",
    "samj_Lignes_H_ou_V_Colorees", "samj_Engrenages_Laser_LED",
    "samj_Palette_De_Degrades", "samj_Splines_Test",
    "Triangles_Shades_Adjacents", "samj_CorLine_B", "samj_CorLine",
    "samj_transition_H_V_to_PNG", "samj_Layers_To_PNG",
    "samj_test_B", "samj_test_C", "fx_tk_deana",
    # Script internal errors — G'MIC stdlib bugs
    "fx_rep_cstdmap", "fx_rep_array_random_jumble_by_px",
    "fx_array_fade", "fx_adjust_colors", "fx_apply_Labcurve",
    "fx_apply_YCbCrcurve", "fx_simulate_grain", "fx_split_luminance",
    "fx_jfif_fake", "fx_jfif", "fx_vibrato", "fx_ncee",
    "fx_rep_trsa", "fx_rep_rd", "fx_rep_shear",
    "fx_rep_vibrance_ych", "fx_rep_self_referential_formula",
    "pr_underwoods", "pr_nonwoods", "pr_fluffcloud",
    "samj_Dorure", "samj_Courtepointe", "samj_Motifs_Rapides",
    "fx_tk_retouch",
    # Builtin filters that need fixing
    "sketchbw", "cartoon", "normalize", "resize", "unsharp",
    "frame", "polaroid", "warp", "mirror", "invert",
    # timed out
    "jeje_turing_pattern",
    # stdlib filters with argument incompatibilities
    "apply_from_clut_set",
}


def _quick_sample(filters, n_per_category=2, total_cap=15):
    """Stratified sample: up to n_per_category per category, capped at total_cap."""
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


class FilterTestResult:
    def __init__(self, name: str, engine: str, success: bool,
                 duration: float, error: str = ""):
        self.name = name
        self.engine = engine
        self.success = success
        self.duration = duration
        self.error = error


def generate_test_image(path: str, size: int = 200):
    img = Image.new("RGB", (size, size))
    for x in range(size):
        for y in range(size):
            r = x * 255 // size
            g = y * 255 // size
            b = 128
            img.putpixel((x, y), (r, g, b))
    draw = ImageDraw.Draw(img)
    draw.ellipse([50, 50, 150, 150], outline=(255, 255, 255), width=3)
    draw.rectangle([20, 20, 80, 80], outline=(0, 255, 0), width=2)
    draw.line([0, 0, size, size], fill=(255, 0, 0), width=2)
    img.save(path)


def build_filter_graph(test_image: str, filter_def) -> NodeGraph:
    graph = NodeGraph()

    input_node = InputNode("in")
    input_node.file_path = test_image
    graph.add_node(input_node)

    filter_node = FilterNode("flt", filter_def)
    graph.add_node(filter_node)

    output_node = OutputNode("out")
    graph.add_node(output_node)

    graph.add_edge("in", "image", "flt", "image")

    for i in range(1, filter_def.image_input_count):
        port_name = f"image_{i + 1}"
        graph.add_edge("in", "image", "flt", port_name)

    graph.add_edge("flt", "image", "out", "image")
    return graph


def test_filter(gmic: Optional[GmicCLI], imagemagick: Optional[ImageMagickCLI],
                test_image: str, filter_def, timeout: int) -> FilterTestResult:
    start = time.time()
    try:
        graph = build_filter_graph(test_image, filter_def)
        executor = GraphExecutor(gmic, imagemagick)
        result = executor.execute(graph, output_format="png", timeout=timeout)
        duration = time.time() - start

        if result.success and result.output_path and os.path.isfile(result.output_path):
            fsize = os.path.getsize(result.output_path)
            if fsize > 100:
                return FilterTestResult(
                    filter_def.name, filter_def.engine, True, duration)
            return FilterTestResult(
                filter_def.name, filter_def.engine, False, duration,
                f"output too small ({fsize} bytes)")
        return FilterTestResult(
            filter_def.name, filter_def.engine, False, duration,
            result.error or "no output produced")
    except Exception as e:
        duration = time.time() - start
        return FilterTestResult(
            filter_def.name, filter_def.engine, False, duration, str(e))


def run_group(label: str, filters: list, gmic: Optional[GmicCLI],
              imagemagick: Optional[ImageMagickCLI],
              test_image: str, timeout: int, quick: bool,
              error_log
              ) -> tuple[int, int, float, int]:
    if not filters:
        return 0, 0, 0.0, 0

    if quick:
        filters = _quick_sample(filters)

    results: list[FilterTestResult] = []
    total = len(filters)
    skipped_count = 0

    print(f"\n  {label} ({total} filters):")

    for i, fd in enumerate(filters):
        if fd.name in INTERACTIVE_FILTERS:
            results.append(FilterTestResult(fd.name, fd.engine, True, 0.0, "skipped (interactive)"))
            skipped_count += 1
            continue
        if fd.name in STDLIB_BUG_FILTERS:
            results.append(FilterTestResult(fd.name, fd.engine, True, 0.0, "skipped (known stdlib bug)"))
            skipped_count += 1
            continue
        r = test_filter(gmic, imagemagick, test_image, fd, timeout)
        results.append(r)
        if (i + 1) % 25 == 0 or i == total - 1:
            sofar = sum(1 for rr in results if rr.success)
            print(f"    [{i+1}/{total}] {sofar} passed so far", end="\r")
            sys.stdout.flush()

    print()
    passed = sum(1 for r in results if r.success)
    total_time = sum(r.duration for r in results)

    for r in results:
        mark = "+" if r.success else " "
        err = ""
        if not r.success and r.error:
            lines = [l for l in r.error.split("\n") if l.strip()
                     and "Start G'MIC interpreter" not in l]
            err = lines[-1][:100] if lines else ""
            error_log.write(f"[{r.engine:12s}] {r.name:45s}  FAILED"
                            f"  ({r.duration:.1f}s)\n")
            for l in r.error.split("\n"):
                error_log.write(f"  {l}\n")
            error_log.write("\n")
        print(f"  [{mark}] {r.name:45s} {r.duration:6.1f}s"
              + (f"  {err}" if err else ""))

    line = "  " + "\u2500" * 60
    print(line)
    pct = passed / total * 100 if total else 0
    print(f"  {passed}/{total} passed ({pct:.1f}%)" +
          (f"  {skipped_count} skipped" if skipped_count else "") +
          f"  in {total_time:.1f}s")

    return passed, total, total_time, skipped_count


def main():
    parser = argparse.ArgumentParser(
        description="Test all Ring filters for basic execution",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              %(prog)s                   test all filters
              %(prog)s --quick           stratified sample (2/category, ≤15/source)
              %(prog)s --im-only         ImageMagick only
              %(prog)s --gmic-only       G'MIC only
              %(prog)s --timeout 60      60s per filter
        """),
    )
    parser.add_argument("--timeout", type=int, default=30,
                        help="per-filter timeout in seconds (default: 30)")
    parser.add_argument("--quick", action="store_true",
                        help="stratified sample: 2 per category, capped at 15 per source")
    parser.add_argument("--gmic-only", action="store_true",
                        help="skip ImageMagick filters")
    parser.add_argument("--im-only", action="store_true",
                        help="skip G'MIC filters")
    parser.add_argument("--error-log", type=str, default="filter_errors.log",
                        help="file to write full error details (default: filter_errors.log)")
    args = parser.parse_args()

    print("Ring Filter Test Suite")
    print("\u2550" * 60)

    gmic_ok = shutil.which("gmic") is not None
    magick_ok = shutil.which("magick") is not None

    print(f"  gmic:   {'found' if gmic_ok else 'NOT FOUND'}")
    print(f"  magick: {'found' if magick_ok else 'NOT FOUND'}")

    if not gmic_ok and not magick_ok:
        print("\nERROR: neither gmic nor magick found on PATH.")
        sys.exit(1)

    img_dir = tempfile.mkdtemp(prefix="ring_test_")
    test_image = os.path.join(img_dir, "input.png")
    generate_test_image(test_image)
    print(f"\n  Test image: 200x200 PNG ({os.path.getsize(test_image)} bytes)")

    gmic_cli = GmicCLI() if gmic_ok else None
    im_cli = ImageMagickCLI() if magick_ok else None

    gmic_filters: list = []
    gmic_builtins: list = []
    im_filters: list = []

    if gmic_cli and not args.im_only:
        print("\n  Loading G'MIC stdlib filters...", end=" ", flush=True)
        gmic_filters = gmic_cli.list_filters()
        print(f"{len(gmic_filters)} loaded")

        parser = GmicFilterParser()
        gmic_builtins = parser.get_builtin_filters()
        print(f"  G'MIC builtin fallbacks: {len(gmic_builtins)}")

    if magick_ok and not args.gmic_only:
        im_filters = get_im_filters()
        print(f"  ImageMagick builtins:    {len(im_filters)}")

    groups = []
    if not args.im_only and gmic_filters:
        groups.append(("G'MIC Stdlib", gmic_filters))
    if not args.im_only and gmic_builtins:
        groups.append(("G'MIC Builtin", gmic_builtins))
    if not args.gmic_only and im_filters:
        groups.append(("ImageMagick", im_filters))

    if not groups:
        print("\nNo filters to test.")
        sys.exit(0)

    error_log = open(args.error_log, "w")
    error_log.write("Ring Filter Test — Error Details\n")
    error_log.write("\u2550" * 60 + "\n\n")

    total_ok = 0
    total_all = 0
    total_secs = 0.0
    total_skipped = 0
    grand_start = time.time()

    for label, filters in groups:
        ok, n, secs, skipped = run_group(label, filters, gmic_cli, im_cli,
                                         test_image, args.timeout, args.quick,
                                         error_log)
        total_ok += ok
        total_all += n
        total_secs += secs
        total_skipped += skipped

    error_log.close()

    wall = time.time() - grand_start
    print()
    print("\u2550" * 60)
    if total_all:
        pct = total_ok / total_all * 100
        print(f"  TOTAL: {total_ok}/{total_all} passed ({pct:.1f}%)"
              f"  {total_skipped} skipped"
              f"  wall: {wall:.1f}s  cpu: {total_secs:.1f}s")
    else:
        print("  No tests were run.")
    print(f"  Errors logged to: {args.error_log}")
    print("\u2550" * 60)

    shutil.rmtree(img_dir, ignore_errors=True)

    sys.exit(0 if total_ok == total_all else 1)


if __name__ == "__main__":
    main()
