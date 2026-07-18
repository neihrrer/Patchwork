# Ring — Agent Guide

## Quick start

```bash
./run.sh              # compile blueprints + run from source tree
make dev              # same as above
meson setup build && meson compile -C build && sudo meson install -C build   # full install
```

## Testing

16 test files in `tests/` using **pytest** (249 tests).

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

CI runs in Fedora 40 container.

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
| Graph | `src/nodes/` | `NodeGraph`, `Port`, `Edge`, 8 node types |
| Widgets | `src/widgets/` | `NodeCanvas`, `FilterBrowser`, `ComparisonWidget`, `ParameterPanel` |
| Processing | `src/processing/` | `GraphExecutor` (sync), `ProcessingRunner` (async) |
| G'MIC | `src/gmic/` | CLI wrapper, stdlib parser, pipeline builder |
| ImageMagick | `src/imagemagick/` | CLI wrapper, built-in filter definitions |

Node types: `InputNode`, `OutputNode`, `FilterNode`, `BlendNode`, `ColorNode`, `OpacityNode`, `ColoringNode`, `MaskNode`.

## Key conventions

- **GObject type system** — `FilterDef` is a `GObject.Object` with `@GObject.Property`; `gi.require_version` calls must precede any `gi.repository` import
- **blueprint-compiler** — UI defined in `.blp` (Blueprint), compiled to `.ui` XML. Recompile after editing `.blp` files
- **Project files** — `.ring` JSON format, schema version 1
- **snake_case** for functions/variables, **PascalCase** for classes, **SCREAMING_SNAKE_CASE** for constants
- **Import order**: stdlib, third-party (`gi.repository`, `PIL`), local
- **4-space indent**, no trailing whitespace, ~100 char line limit

## Gotchas

- `./run.sh` requires `blueprint-compiler` on `$PATH`; falls back to existing `build/resources/*.ui`
- Rendering requires `gmic` and/or `magick` CLIs — tests do not
- Only one branch: `master`; tags use `v*` pattern for releases
- Flatpak manifest at `flatpak/io.github.neihrrer.Ring.yml`
