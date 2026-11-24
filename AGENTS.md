# Patchwork — Agent Guide

## Quick start

```bash
./run.sh              # compile blueprints + run from source tree
make dev              # same as above
meson setup build && meson compile -C build && sudo meson install -C build   # full install
```

## Testing

17 test files in `tests/` using **pytest** (302 tests, including the filter suite once `gmic` and `magick` are installed).

```bash
python3 -m pytest tests/ -q                  # all tests (fast, no CLI needed)
python3 -m pytest tests/foo.py -q            # single file
```

Two integration tests require `gmic` + `magick` CLIs and are run separately:
- `tests/test_filters_quick.py` — `python3 -m pytest tests/test_filters_quick.py`
- `tests/test_all_filters.py` — `python3 tests/test_all_filters.py`

`conftest.py` handles `sys.path.insert(0, "src")` and GTK introspection setup.

## Lint & CI

CI uses `python3 -m py_compile` on 3 files (no formatter, no type checker, no linter).

```bash
python3 -m py_compile src/main.py src/application.py src/window.py
```

CI runs in a Fedora 45 container: `meson` build, `py_compile` lint, then `pytest`.

## Build system

- **Meson** with `blueprint-compiler` compiles `src/resources/*.blp` → `build/resources/*.ui`
- `meson.build` at root, `src/meson.build` installs Python sources + UI files
- Python dependencies: `PyGObject>=3.50`, `Pillow>=10.0` (declared in `pyproject.toml`)
- Runtime system deps: `gmic` CLI, `magick` (ImageMagick), GTK4, Libadwaita

## Architecture

| Layer | Directory | Role |
|-------|-----------|------|
| Entry | `src/main.py` → `application.py` → `window.py` | App lifecycle, main window |
| Models | `src/models/` | `FilterDef` (GObject), `ParamDef`, `AppState` |
| Graph | `src/nodes/` | `NodeGraph`, `Port`, `Edge`, 60 node type classes |
| Widgets | `src/widgets/` | `FilterBrowser`, `NodeCanvas`, `NodeWidget`, `PortWidget`, `Minimap` |
| Processing | `src/processing/` | `GraphExecutor`, `ProcessResult`; PIL image ops, analysis utils |
| G'MIC | `src/gmic/` | CLI wrapper, stdlib parser, pipeline builder |
| ImageMagick | `src/imagemagick/` | CLI wrapper, built-in filter definitions |

Node types (58 classes): Input/Output, Filter, Blend, Opacity, Mask, Color Adjust (BrightnessContrast, Levels, HSL, ColorBalance, ExposureGamma, Curves), Color Source/Gradient/Noise, Transform (Crop, Resize, Rotate, Flip, Distort), Blur/Sharpen/EdgeDetect, Math/Logic (~20 operators), Raw I/O, Label/Comment, Analysis (Histogram, Waveform, Vectorscope, FrequencyDomain).

## Key conventions

- **GObject type system** — `FilterDef` is a `GObject.Object` with `@GObject.Property`; `gi.require_version` calls must precede any `gi.repository` import
- **blueprint-compiler** — UI defined in `.blp` (Blueprint), compiled to `.ui` XML. Recompile after editing `.blp` files
- **Project files** — `.patch` JSON format, schema version 1
- **snake_case** for functions/variables, **PascalCase** for classes, **SCREAMING_SNAKE_CASE** for constants
- **Import order**: stdlib, third-party (`gi.repository`, `PIL`), local
- **Image-driven size ports** — an image output may be wired into an input port whose name describes a width or height (`resize_width`, `Width (px)`, `source_height`, ...; see `nodes.graph.size_port_kind`); `GraphExecutor._image_dimension` then supplies that pixel size instead of a numeric input. `NodeGraph.add_edge` allows exactly this cross-type case and nothing else
- **4-space indent**, no trailing whitespace, ~100 char line limit

## Gotchas

- `./run.sh` requires `blueprint-compiler` on `$PATH`; falls back to existing `build/resources/*.ui`
- Rendering requires `gmic` and/or `magick` CLIs; the filter tests skip when they are missing
- The G'MIC filter list is downloaded from the tag matching the installed `gmic` version (`master` when undetectable) and cached in `~/.cache/patchwork/stdlib` — see `src/gmic/stdlib.py`
- The community filter list is pinned in `src/gmic/stdlib.py` (`COMMUNITY_REF`, the snapshot for G'MIC 4.0.3) and cached under a ref-keyed name; it is deliberately not fetched from `master`, whose newer filters need commands the installed interpreter does not have. Community filters are imported with `gmic -m <pinned file>` before they run, so that file must stay in the cache for them to work
- Projects with unsaved changes are autosaved to `~/.cache/patchwork/autosave.patch` (default every 5 min); the file is offered for restore on the next start and deleted on save and on a clean exit
- Only one branch: `master`; tags use `v*` pattern for releases
- Flatpak manifest at `flatpak/org.patchwork.Patchwork.yml`
