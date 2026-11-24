#!/usr/bin/env python3
__test__ = False
"""Test all filters in Patchwork.

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
import re
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
from models.filter import FilterDef
from imagemagick.cli import ImageMagickCLI
from imagemagick.filters import get_builtin_filters as get_im_filters
from nodes import NodeGraph, InputNode, FilterNode, OutputNode
from processing.graph_executor import GraphExecutor


INTERACTIVE_FILTERS = {
    "fx_apply_haldclut", "apply_from_clut_set", "fx_mask_color", "fx_extract_foreground", "fx_morph_interactive",
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

def _quick_sample(filters, n_per_category=2, total_cap=15):
    """Stratified sample: up to n_per_category per category, capped at total_cap."""
    candidates = [f for f in filters
                  if f.name not in INTERACTIVE_FILTERS]
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
                 duration: float, error: str = "", note: str = ""):
        self.name = name
        self.engine = engine
        self.success = success
        self.duration = duration
        self.error = error
        self.note = note


# Filters that need more than one layer without declaring it with ':*'/'+:'
# are retried with two layers so we test the filter itself.
TWO_LAYER_ERRORS = re.compile(
    r"at least (?:two|2) (?:input )?layers?"
    r"|needs? (?:two|2) (?:input )?layers?"
    r"|needs? (?:two|2) images?"
    r"|requires? (?:two|2)"
    r"|not in range -1\.\.\.0",
    re.IGNORECASE,
)


def generate_test_image(path: str, size: int = 200, variant: int = 0):
    """Write a deterministic test image.

    Variant 0 is the original gradient image; variant 1 is a distinct
    picture, so two-layer filters (blend, montage, alignment) get real data
    instead of the same layer twice.
    """
    img = Image.new("RGB", (size, size))
    for x in range(size):
        for y in range(size):
            if variant:
                img.putpixel((x, y), (255 - x * 255 // size,
                                      y * 255 // size // 2,
                                      x * 128 // size + 60))
            else:
                img.putpixel((x, y), (x * 255 // size,
                                      y * 255 // size,
                                      128))
    draw = ImageDraw.Draw(img)
    if variant:
        draw.rectangle([40, 120, 160, 190], fill=(250, 240, 10))
        draw.ellipse([90, 10, 150, 70], fill=(0, 200, 255))
        draw.line([0, size, size, 0], fill=(255, 0, 255), width=4)
    else:
        draw.ellipse([50, 50, 150, 150], outline=(255, 255, 255), width=3)
        draw.rectangle([20, 20, 80, 80], outline=(0, 255, 0), width=2)
        draw.line([0, 0, size, size], fill=(255, 0, 0), width=2)
    img.save(path)


def build_filter_graph(test_images: list[str], filter_def) -> NodeGraph:
    """Build Input(s) -> Filter -> Output, one input per image port."""
    graph = NodeGraph()

    input_nodes = []
    for index in range(filter_def.image_input_count):
        input_node = InputNode(f"in{index}")
        input_node.file_path = test_images[index % len(test_images)]
        graph.add_node(input_node)
        input_nodes.append(input_node)

    filter_node = FilterNode("flt", filter_def)
    graph.add_node(filter_node)

    output_node = OutputNode("out")
    graph.add_node(output_node)

    graph.add_edge(input_nodes[0].id, "image", filter_node.id, "image")
    for index in range(1, filter_def.image_input_count):
        graph.add_edge(input_nodes[index].id, "image", filter_node.id,
                       f"image_{index + 1}")

    graph.add_edge(filter_node.id, "image", output_node.id, "image")
    return graph


def with_input_count(filter_def, count: int):
    """Copy of ``filter_def`` that declares ``count`` image inputs."""
    if filter_def.image_input_count == count:
        return filter_def
    return FilterDef(
        name=filter_def.name,
        display_name=filter_def.display_name,
        category=list(filter_def.category),
        description=filter_def.description,
        parameters=filter_def.parameters,
        gmic_command=filter_def.gmic_command,
        engine=filter_def.engine,
        image_input_count=count,
    )


def _attempt(gmic, imagemagick, test_images: list[str], filter_def, timeout: int):
    """Run one filter, returning (FilterTestResult, error-or-None)."""
    start = time.time()
    graph = build_filter_graph(test_images, filter_def)
    executor = GraphExecutor(gmic, imagemagick)
    result = executor.execute(graph, output_format="png", timeout=timeout)
    duration = time.time() - start

    if result.success and result.output_path and os.path.isfile(result.output_path):
        fsize = os.path.getsize(result.output_path)
        if fsize > 100:
            return FilterTestResult(filter_def.name, filter_def.engine,
                                    True, duration), None
        error = f"output too small ({fsize} bytes)"
        return FilterTestResult(filter_def.name, filter_def.engine, False,
                                duration, error), error
    error = result.error or "no output produced"
    return FilterTestResult(filter_def.name, filter_def.engine, False,
                            duration, error), error


def test_filter(gmic: Optional[GmicCLI], imagemagick: Optional[ImageMagickCLI],
                test_images: list[str], filter_def, timeout: int) -> FilterTestResult:
    try:
        result, error = _attempt(gmic, imagemagick, test_images, filter_def, timeout)
        if (not result.success and filter_def.image_input_count < 2
                and len(test_images) >= 2 and TWO_LAYER_ERRORS.search(error or "")):
            # The filter needs a second layer but does not declare it in
            # '#@gui'; retry with two distinct layers.
            two_layer_def = with_input_count(filter_def, 2)
            retry, _ = _attempt(gmic, imagemagick, test_images[:2],
                                two_layer_def, timeout)
            if retry.success:
                retry.note = "needed two input layers"
                return retry
            result.error = error
        return result
    except Exception as e:
        return FilterTestResult(filter_def.name, filter_def.engine, False,
                                0.0, str(e))


def run_group(label: str, filters: list, gmic: Optional[GmicCLI],
              imagemagick: Optional[ImageMagickCLI],
              test_images: list[str], timeout: int, quick: bool,
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
        r = test_filter(gmic, imagemagick, test_images, fd, timeout)
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
              + (f"  {err}" if err else "")
              + (f"  ({r.note})" if r.note else ""))

    line = "  " + "\u2500" * 60
    print(line)
    pct = passed / total * 100 if total else 0
    print(f"  {passed}/{total} passed ({pct:.1f}%)" +
          (f"  {skipped_count} skipped" if skipped_count else "") +
          f"  in {total_time:.1f}s")

    return passed, total, total_time, skipped_count


def main():
    parser = argparse.ArgumentParser(
        description="Test all Patchwork filters for basic execution",
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

    print("Patchwork Filter Test Suite")
    print("\u2550" * 60)

    gmic_ok = shutil.which("gmic") is not None
    magick_ok = shutil.which("magick") is not None

    print(f"  gmic:   {'found' if gmic_ok else 'NOT FOUND'}")
    print(f"  magick: {'found' if magick_ok else 'NOT FOUND'}")

    if not gmic_ok and not magick_ok:
        print("\nERROR: neither gmic nor magick found on PATH.")
        sys.exit(1)

    img_dir = tempfile.mkdtemp(prefix="patchwork_test_")
    test_images = [os.path.join(img_dir, "input.png"),
                   os.path.join(img_dir, "input_second.png")]
    generate_test_image(test_images[0])
    generate_test_image(test_images[1], variant=1)
    sizes = ", ".join(f"{os.path.getsize(p)} bytes" for p in test_images)
    print(f"\n  Test images: 2 x 200x200 PNG ({sizes})")

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
    error_log.write("Patchwork Filter Test — Error Details\n")
    error_log.write("\u2550" * 60 + "\n\n")

    total_ok = 0
    total_all = 0
    total_secs = 0.0
    total_skipped = 0
    grand_start = time.time()

    for label, filters in groups:
        ok, n, secs, skipped = run_group(label, filters, gmic_cli, im_cli,
                                         test_images, args.timeout, args.quick,
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
