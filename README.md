# Patchwork

**Patchwork** is a node-based image editor/patcher for Linux. It uses G'MIC and ImageMagick image processing frameworks. You load an image input, connect processing nodes using wires, and render the output.

## Features

- **Node graph editor:** drag, drop, and connect nodes to build image processing pipelines visually
- **G'MIC filters:** auto-discovered from your local G'MIC installation (Sketch, Oil Painting, Denoise, Retinex, and hundreds more)
- **ImageMagick operations:** blur, sharpen, resize, rotate, color adjustments, edge detection, morphology, and more
- **Built-in node types:** Input, Output, Filter, Blend (12 modes), Color Adjust, Opacity, Coloring (HSL), and Mask
- **Math and logic nodes:** Basic math operators and logic gates
- **Adaptive UI:** responsive layout that works on narrow windows and mobile (thanks to Libadwaita)

## Requirements

| Dependency | Minimum version | Notes |
|---|---|---|
| Python | 3.10+ | |
| GTK | 4.0 | via PyGObject |
| Libadwaita | 1.0 | via PyGObject |
| PyGObject | 3.50 | Python GTK bindings |
| Pillow | 10.0 | Python imaging library |
| G'MIC (`gmic`) | any | CLI — required for G'MIC filters; the filter list is fetched for the installed version (community filters come from a pinned snapshot of `gmic-community`, cached on first use) |
| ImageMagick (`magick`) | any | CLI — required for blends, color ops, masks |
| blueprint-compiler | any | Build-time only |

## Installation

### From source (Meson)

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

This compiles the UI blueprints on the fly and launches Patchwork directly from the source tree.

### Running the tests

```bash
python3 -m pytest tests/ -q
```

The filter suites exercise the installed `gmic` and `magick` CLIs and are skipped when those are unavailable.

## Getting started

1. **Open an image:** click the folder icon in the sidebar (or press Ctrl+O)
2. **Browse filters:** the sidebar lists all available filters and nodes organized by category
3. **Add a filter:** drag a filter from the sidebar onto the canvas, or double-click it
4. **Connect nodes:** click and drag from an output port (right side of a node) to an input port (left side of another node)
   - Wiring an **image** output into a **Width** or **Height** input uses that image's pixel size for the parameter (Resize, Crop, filters, and the Color Source / Gradient / Noise generators all expose such inputs), so a node can follow the size of another image
5. **Tweak parameters:** click a filter node to adjust its parameters
6. **Render:** click the **Render** button in the toolbar to process the graph
7. **Export/Save:** once rendered, click the save icon to export the result and save your project
8. **Projects:** **Ctrl+N** starts a new project, **Ctrl+O** opens one, **Ctrl+S** saves it. Replacing or closing a project with unsaved changes asks Save / Discard / Cancel first
9. **Autosave:** while a project has unsaved changes it is written every 5 minutes to `~/.cache/patchwork/autosave.patch` (interval configurable in Preferences). After a crash, Patchwork offers to restore it on the next start; the file is deleted on save and on a normal exit

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
| Ctrl+N | New project |
| Ctrl+O | Open project |
| Ctrl+S | Save project |
| Ctrl+Q | Quit |
| Ctrl+P | Toggle preview |
| Ctrl+Return | Apply filter |
| Ctrl+R | Reset parameters |
| Ctrl+T | Before / After comparison |
| Ctrl++ | Zoom in |
| Ctrl+- | Zoom out |
| Ctrl+M | Toggle minimap |

## Project structure

```
Patchwork/
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
├── flatpak/            # Flatpak build manifest (Flathub-ready)
├── .github/            # CI workflows
├── meson.build         # Top-level build definition
├── Makefile            # Developer convenience wrappers
├── pyproject.toml      # Python package metadata
└── run.sh              # Quick development launcher
```

## License

Patchwork is distributed under the GNU General Public License v3.0. See the [LICENSE](LICENSE) file for details.
