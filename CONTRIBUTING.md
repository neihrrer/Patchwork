# Contributing to Ring

Thank you for your interest in contributing! This document covers the development workflow.

## Prerequisites

- Python 3.10+
- Meson >= 1.0.0
- `blueprint-compiler`
- `gmic` and `magick` (ImageMagick) for running the application
- PyGObject with GTK 4.0 and Libadwaita 1.0 bindings

## Quick start

```bash
# Build and install
meson setup build
meson compile -C build
sudo meson install -C build

# Or run directly from source
./run.sh
```

## Code style

- Follow existing patterns in the codebase
- Use 4-space indentation
- No trailing whitespace
- Keep lines under 100 characters where practical
- Import order: standard library, third-party, local

## Project architecture

```
src/
  main.py              # Entry point
  application.py       # Adw.Application lifecycle
  window.py            # Main window, signal wiring
  models/              # FilterDef, AppState, ParamDef
  nodes/               # Node, NodeGraph, node types
  widgets/             # NodeCanvas, FilterBrowser, ParameterPanel, ComparisonWidget
  processing/          # GraphExecutor, ProcessingRunner
  gmic/                # G'MIC CLI integration, stdlib parser
  imagemagick/         # ImageMagick CLI integration, built-in filters
  resources/           # Blueprint UI files
  style.css            # Application CSS
```

## Making changes

1. Create a branch for your work
2. Make your changes
3. Test by running `./run.sh`
4. Update or add tests if applicable
5. Submit a pull request

## Reporting issues

Report bugs and feature requests at the project's issue tracker.

## License

By contributing, you agree that your contributions will be licensed under the GNU General Public License v3.0.
