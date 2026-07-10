# Ring

**Ring** is a modern, node-based image editor for Linux. Think of it as a visual patcher for the [G'MIC](https://gmic.eu) image processing framework — you load an image, connect processing nodes, and render the result. No coding required.

## Features

- **Node graph editor** — drag, drop, and connect nodes to build image processing pipelines visually
- **600+ G'MIC filters** — auto-discovered from your local G'MIC installation (Sketch, Oil Painting, Denoise, Retinex, and hundreds more)
- **ImageMagick operations** — blur, sharpen, resize, rotate, color adjustments, edge detection, morphology, and more
- **Built-in node types** — Input, Output, Filter, Blend (12 modes), Color Adjust, Opacity, Coloring (HSL), and Mask
- **Live preview** — compare original vs. result with split-view before/after
- **Project save/load** — save your node graphs as `.ring` files and reopen them later
- **Export** — PNG, JPEG, TIFF, BMP, WebP
- **Keyboard shortcuts** — quick access to all common operations
- **Adaptive UI** — responsive layout that works on narrow windows (thanks to Libadwaita)
- **Dark & light themes** — follows your system preference
- **No cloud, no accounts** — everything runs locally on your machine

## Requirements

| Dependency | Minimum version | Notes |
|---|---|---|
| Python | 3.10+ | |
| GTK | 4.0 | via PyGObject |
| Libadwaita | 1.0 | via PyGObject |
| PyGObject | 3.50 | Python GTK bindings |
| Pillow | 10.0 | Python imaging library |
| G'MIC (`gmic`) | any | CLI — required for G'MIC filters |
| ImageMagick (`magick`) | any | CLI — required for blends, color ops, masks |
| blueprint-compiler | any | Build-time only |

## Installation

### From source (Meson — recommended)

```bash
# Install system dependencies
# Debian/Ubuntu:
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 \
  meson blueprint-compiler gmic imagemagick

# Fedora:
sudo dnf install python3-gobject gtk4 libadwaita meson blueprint-compiler \
  gmic ImageMagick

# Arch:
sudo pacman -S python-gobject gtk4 libadwaita meson blueprint-compiler \
  gmic imagemagick

# Build and install
meson setup build
meson compile -C build
sudo meson install -C build
```

### Quick development run (no install)

```bash
./run.sh
```

This compiles the UI blueprints on the fly and launches Ring directly from the source tree.

## Getting started

1. **Open an image** — click the folder icon in the sidebar (or press Ctrl+O)
2. **Browse filters** — the sidebar lists all available G'MIC filters organized by category
3. **Add a filter** — drag a filter from the sidebar onto the canvas, or double-click it
4. **Connect nodes** — click and drag from an output port (right side of a node) to an input port (left side of another node)
5. **Tweak parameters** — click a filter node to adjust its parameters
6. **Render** — click the **Render** button in the toolbar to process the graph
7. **Export** — once rendered, click the save icon to export the result

### Node types

| Node | Color | Purpose |
|---|---|---|
| Input | Green | Loads an image from disk |
| Output | Red | Marks the final result |
| Filter | Blue | Applies a G'MIC or ImageMagick filter |
| Blend | Brown | Combines two or more images (12 blend modes) |
| Color Adjust | Teal | Brightness, contrast, hue, saturation |
| Opacity | Purple | Adjusts transparency |
| Coloring | Cyan | HSL color adjustments |
| Mask | Dark Teal | Mask-based compositing |

### Keyboard shortcuts

| Shortcut | Action |
|---|---|
| Ctrl+O | Open image |
| Ctrl+S | Export result |
| Ctrl+Q | Quit |
| Ctrl+P | Toggle preview |
| Ctrl+Return | Apply filter |
| Ctrl+R | Reset parameters |
| Ctrl+T | Before / After comparison |
| Ctrl++ | Zoom in |
| Ctrl+- | Zoom out |

## Project structure

```
Ring/
├── data/               # Desktop file, AppStream metadata, icons
├── src/
│   ├── main.py         # Entry point
│   ├── application.py  # App lifecycle, actions
│   ├── window.py       # Main window, signal wiring
│   ├── models/         # Filter definitions, app state
│   ├── nodes/          # Graph data structure, node types
│   ├── widgets/        # Node canvas, filter browser, comparison, parameters
│   ├── processing/     # Graph executor, threaded runner
│   ├── gmic/           # G'MIC CLI integration, stdlib parser
│   ├── imagemagick/    # ImageMagick CLI integration, built-in filters
│   ├── resources/      # Blueprint UI files
│   └── style.css       # Application stylesheet
├── meson.build         # Top-level build definition
├── pyproject.toml      # Python package metadata
└── run.sh              # Quick development launcher
```

## License

Ring is distributed under the MIT License. See the [LICENSE](LICENSE) file for details.
