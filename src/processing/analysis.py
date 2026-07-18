import math
import os
import tempfile
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from processing.runner import ProcessResult


# ═══════════════════════════════════════════════════════════════════════════════
#  Data computation — Cairo node widget rendering
# ═══════════════════════════════════════════════════════════════════════════════

def compute_histogram_data(image_path: str) -> dict:
    img = Image.open(image_path).convert("RGBA")
    r_hist = img.split()[0].histogram()
    g_hist = img.split()[1].histogram()
    b_hist = img.split()[2].histogram()
    gray = img.convert("L")
    l_hist = gray.histogram()

    max_bin = max(max(r_hist), max(g_hist), max(b_hist), max(l_hist)) or 1

    def norm(h):
        return [v / max_bin for v in h]

    return {
        "r": norm(r_hist),
        "g": norm(g_hist),
        "b": norm(b_hist),
        "l": norm(l_hist),
    }


def compute_waveform_data(image_path: str) -> dict:
    img = Image.open(image_path).convert("RGB")
    iw, ih = img.size
    pixels = list(img.getdata())

    num_cols = min(iw, 512)
    col_samples: list[list[float]] = [[] for _ in range(num_cols)]

    for py in range(ih):
        for px in range(iw):
            sx = int(px * num_cols / iw)
            r, g, b = pixels[py * iw + px]
            luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
            col_samples[min(sx, num_cols - 1)].append(luma / 255.0)

    env_low: list[float] = []
    env_high: list[float] = []
    avg: list[float] = []
    for samples in col_samples:
        if not samples:
            env_low.append(0.0)
            env_high.append(0.0)
            avg.append(0.0)
        else:
            samples.sort()
            env_low.append(samples[max(0, int(len(samples) * 0.01))])
            env_high.append(samples[min(len(samples) - 1, int(len(samples) * 0.99))])
            avg.append(sum(samples) / len(samples))

    return {
        "envelope_low": env_low,
        "envelope_high": env_high,
        "average": avg,
        "num_columns": num_cols,
    }


def compute_vectorscope_data(image_path: str) -> dict:
    img = Image.open(image_path).convert("RGB")
    iw, ih = img.size
    pixels = list(img.getdata())

    density: dict[tuple[int, int], int] = {}
    for r, g, b in pixels:
        y = 0.299 * r + 0.587 * g + 0.114 * b
        cb = (b - y) * 0.564
        cr = (r - y) * 0.713
        cb = max(-128, min(127, cb))
        cr = max(-128, min(127, cr))
        # Quantize to 256x256 grid for density
        qx = int((cb + 128) * 1.0)
        qy = int((cr + 128) * 1.0)
        qx = max(0, min(255, qx))
        qy = max(0, min(255, qy))
        key = (qx, qy)
        density[key] = density.get(key, 0) + 1

    max_den = max(density.values()) if density else 1
    points = [(qx, qy, count / max_den) for (qx, qy), count in density.items()]

    return {"points": points, "max_count": max_den}


def compute_frequency_data(image_path: str) -> dict:
    img = Image.open(image_path).convert("L")
    target = 64
    img.thumbnail((target, target), Image.LANCZOS)
    w, h = img.size

    pixels = [[float(img.getpixel((x, y))) for x in range(w)] for y in range(h)]
    mag = _fft2d(pixels)
    mag = _fft_shift(mag)

    fh = len(mag)
    fw = len(mag[0])

    log_mag = [[0.0] * fw for _ in range(fh)]
    min_log = float("inf")
    max_log = float("-inf")
    for y in range(fh):
        for x in range(fw):
            v = math.log10(mag[y][x] + 1.0)
            log_mag[y][x] = v
            if v < min_log:
                min_log = v
            if v > max_log:
                max_log = v

    scale = max_log - min_log or 1.0
    grid: list[list[float]] = []
    for y in range(fh):
        row: list[float] = []
        for x in range(fw):
            row.append((log_mag[y][x] - min_log) / scale)
        grid.append(row)

    return {"mag_grid": grid, "width": fw, "height": fh}


# ─── GNOME HIG palette ──────────────────────────────────────────────────────
# Source: https://developer.gnome.org/hig/reference/palette.html

_HIG_BG = (36, 31, 49)
_HIG_BG_LIGHTER = (50, 45, 63)
_HIG_GRID = (94, 92, 100)
_HIG_AXIS = (192, 191, 188)
_HIG_RED = (224, 27, 36)
_HIG_GREEN = (46, 194, 126)
_HIG_BLUE = (28, 113, 216)
_HIG_YELLOW = (246, 211, 45)
_HIG_WHITE = (255, 255, 255)
_HIG_ORANGE = (255, 163, 72)
_HIG_PURPLE = (192, 97, 203)


def _save(img: Image.Image, fmt: str) -> str:
    fd, out_path = tempfile.mkstemp(suffix="." + fmt)
    os.close(fd)
    if fmt == "jpeg":
        img = img.convert("RGB")
    img.save(out_path)
    return out_path


# ─── Iterative in‑place radix‑2 FFT ──────────────────────────────────────────

def _fft_1d(data: list[complex]) -> list[complex]:
    n = len(data)
    if n <= 1:
        return data

    # Bit-reversal permutation
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            data[i], data[j] = data[j], data[i]

    # Butterfly iterations
    length = 2
    while length <= n:
        half = length >> 1
        wlen = complex(math.cos(math.pi / half), -math.sin(math.pi / half))
        for i in range(0, n, length):
            w = 1 + 0j
            for k in range(half):
                u = data[i + k]
                v = data[i + k + half] * w
                data[i + k] = u + v
                data[i + k + half] = u - v
                w *= wlen
        length <<= 1
    return data


def _fft2d(pixels: list[list[float]]) -> list[list[float]]:
    h = len(pixels)
    w = len(pixels[0])
    next_pow2 = lambda n: 1 << (n - 1).bit_length()
    fw = next_pow2(w)
    fh = next_pow2(h)

    rows: list[list[complex]] = []
    for y in range(h):
        row = [complex(pixels[y][x], 0) for x in range(w)]
        row.extend([0j] * (fw - w))
        rows.append(_fft_1d(row))
    for _ in range(fh - h):
        rows.append([0j] * fw)

    cols: list[list[complex]] = []
    for x in range(fw):
        col = [rows[y][x] for y in range(fh)]
        cols.append(_fft_1d(col))

    mag: list[list[float]] = []
    for y in range(fh):
        mag_row: list[float] = []
        for x in range(fw):
            mag_row.append(abs(cols[x][y]))
        mag.append(mag_row)
    return mag


def _fft_shift(mag: list[list[float]]) -> list[list[float]]:
    h = len(mag)
    w = len(mag[0])
    h2 = h // 2
    w2 = w // 2
    result = [[0.0] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            result[(y + h2) % h][(x + w2) % w] = mag[y][x]
    return result


# ─── Drawing helpers ─────────────────────────────────────────────────────────

def _draw_axis_labels(draw: ImageDraw.Draw, labels: list[str],
                      y: int, color, font_size: int = 10):
    for i, lbl in enumerate(labels):
        draw.text((10 + i * 42, y), lbl, fill=color)


# ═══════════════════════════════════════════════════════════════════════════════
#  Histogram
# ═══════════════════════════════════════════════════════════════════════════════

_CHART_W = 1024
_CHART_H = 480
_MARGIN_L = 55
_MARGIN_R = 20
_MARGIN_T = 30
_MARGIN_B = 40
_PLOT_W = _CHART_W - _MARGIN_L - _MARGIN_R
_PLOT_H = _CHART_H - _MARGIN_T - _MARGIN_B


def render_histogram(image_path: str, fmt: str = "png") -> ProcessResult:
    try:
        img = Image.open(image_path).convert("RGBA")
        img.thumbnail((512, 512), Image.LANCZOS)

        r_hist = img.split()[0].histogram()
        g_hist = img.split()[1].histogram()
        b_hist = img.split()[2].histogram()
        gray = img.convert("L")
        l_hist = gray.histogram()

        chart = Image.new("RGBA", (_CHART_W, _CHART_H), _HIG_BG + (255,))
        draw = ImageDraw.Draw(chart)

        # Grid
        for i in range(5):
            y = _MARGIN_T + int(_PLOT_H * i / 4)
            draw.line([(_MARGIN_L, y), (_CHART_W - _MARGIN_R, y)],
                      _HIG_GRID + (60,), 1)
            pct = int(100 * (1 - i / 4))
            draw.text((5, y - 6), f"{pct}%", fill=_HIG_GRID + (180,))

        # Axis line
        draw.line([(_MARGIN_L, _CHART_H - _MARGIN_B),
                   (_CHART_W - _MARGIN_R, _CHART_H - _MARGIN_B)],
                  _HIG_AXIS + (220,), 1)
        draw.line([(_MARGIN_L, _MARGIN_T),
                   (_MARGIN_L, _CHART_H - _MARGIN_B)],
                  _HIG_AXIS + (220,), 1)

        # Tick labels
        for i in range(9):
            x = _MARGIN_L + int(_PLOT_W * i / 8)
            draw.text((x - 8, _CHART_H - _MARGIN_B + 5),
                      str(i * 32), fill=_HIG_GRID + (180,))

        draw.text((_CHART_W // 2 - 40, _CHART_H - 18),
                  "Pixel value (0-255)", fill=_HIG_AXIS + (200,))

        # Draw filled area under each curve
        def draw_channel(hist, color, label, label_color):
            bins = 256
            max_val = max(hist) or 1
            points: list[tuple[float, float]] = []
            for i in range(bins):
                x = _MARGIN_L + (i / bins) * _PLOT_W
                y = _CHART_H - _MARGIN_B - (hist[i] / max_val) * _PLOT_H
                points.append((x, y))

            # Filled area
            fill_poly = [(_MARGIN_L, _CHART_H - _MARGIN_B)] + points + [
                (_MARGIN_L + _PLOT_W, _CHART_H - _MARGIN_B)]
            draw.polygon(fill_poly, fill=color + (40,))

            # Curve line
            for i in range(1, len(points)):
                draw.line([points[i - 1], points[i]], color + (200,), 2)

        draw_channel(r_hist, _HIG_RED, "R", _HIG_RED)
        draw_channel(g_hist, _HIG_GREEN, "G", _HIG_GREEN)
        draw_channel(b_hist, _HIG_BLUE, "B", _HIG_BLUE)
        draw_channel(l_hist, _HIG_YELLOW, "L", _HIG_YELLOW)

        # Legend
        legend_items = [
            ("R", _HIG_RED), ("G", _HIG_GREEN),
            ("B", _HIG_BLUE), ("Luma", _HIG_YELLOW)]
        for i, (txt, clr) in enumerate(legend_items):
            lx = _MARGIN_L + 10 + i * 120
            draw.rectangle([lx, 8, lx + 16, 24], fill=clr + (200,))
            draw.text((lx + 22, 6), txt, fill=_HIG_AXIS + (200,))

        out_path = _save(chart, fmt)
        return ProcessResult(output_path=out_path)
    except Exception as e:
        return ProcessResult(error=str(e))


# ═══════════════════════════════════════════════════════════════════════════════
#  Waveform Monitor  —  classic green CRT, X = pixel column, Y = luma
# ═══════════════════════════════════════════════════════════════════════════════

_WF_W = 1024
_WF_H = 512


def render_waveform(image_path: str, fmt: str = "png") -> ProcessResult:
    try:
        img = Image.open(image_path).convert("RGB")
        img.thumbnail((_WF_W, 1024), Image.LANCZOS)
        iw, ih = img.size
        pixels = list(img.getdata())

        chart = Image.new("RGBA", (_WF_W, _WF_H), _HIG_BG + (255,))
        draw = ImageDraw.Draw(chart)

        # Graticule
        for i in range(5):
            y = int(_WF_H * i / 4)
            draw.line([(0, y), (_WF_W, y)], _HIG_GRID + (80,), 1)
            ire_val = int(100 * (1 - i / 4))
            draw.text((3, y - 6), f"{ire_val}%", fill=_HIG_GRID + (180,))

        for i in range(9):
            x = int(_WF_W * i / 8)
            draw.line([(x, 0), (x, _WF_H)], _HIG_GRID + (50,), 1)

        # Sample luma per column
        col_samples: list[list[float]] = [[] for _ in range(_WF_W)]
        for py in range(ih):
            for px in range(iw):
                sx = int(px * _WF_W / iw)
                r, g, b = pixels[py * iw + px]
                luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
                col_samples[min(sx, _WF_W - 1)].append(luma)

        # Render waveform: max/min envelope + average trace
        trace = Image.new("RGBA", (_WF_W, _WF_H), (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(trace)

        for x in range(_WF_W):
            samples = col_samples[x]
            if not samples:
                continue
            samples.sort()
            low = samples[max(0, int(len(samples) * 0.01))]
            high = samples[min(len(samples) - 1, int(len(samples) * 0.99))]
            avg = sum(samples) / len(samples)

            ly = int(_WF_H - 1 - (low / 255.0) * (_WF_H - 1))
            hy = int(_WF_H - 1 - (high / 255.0) * (_WF_H - 1))
            ay = int(_WF_H - 1 - (avg / 255.0) * (_WF_H - 1))

            # Envelope (dim green)
            t_draw.line([(x, ly), (x, hy)], (30, 140, 80, 80), 1)
            # Average trace (bright green)
            if x > 0:
                prev_ay = int(_WF_H - 1 - (
                    (sum(col_samples[x - 1]) / max(len(col_samples[x - 1]), 1)) / 255.0
                ) * (_WF_H - 1)) if col_samples[x - 1] else ay
                t_draw.line([(x - 1, prev_ay), (x, ay)],
                            (51, 209, 122, 220), 2)

        chart = Image.alpha_composite(chart, trace)

        out_path = _save(chart, fmt)
        return ProcessResult(output_path=out_path)
    except Exception as e:
        return ProcessResult(error=str(e))


# ═══════════════════════════════════════════════════════════════════════════════
#  Vectorscope  —  Cb/Cr chrominance scatter with density
# ═══════════════════════════════════════════════════════════════════════════════

_VS_W = 1024
_VS_H = 1024


def render_vectorscope(image_path: str, fmt: str = "png") -> ProcessResult:
    try:
        img = Image.open(image_path).convert("RGB")
        img.thumbnail((512, 512), Image.LANCZOS)
        iw, ih = img.size
        pixels = list(img.getdata())

        chart = Image.new("RGBA", (_VS_W, _VS_H), _HIG_BG + (255,))
        draw = ImageDraw.Draw(chart)

        cx, cy = _VS_W // 2, _VS_H // 2
        radius = min(_VS_W, _VS_H) // 2 - 30

        # Graticule
        _draw_vs_graticule(draw, cx, cy, radius)

        # Accumulate chrominance points
        density: dict[tuple[int, int], float] = {}
        scale = radius / 128.0
        for r, g, b in pixels:
            y = 0.299 * r + 0.587 * g + 0.114 * b
            cb = (b - y) * 0.564
            cr = (r - y) * 0.713
            cb = max(-128, min(127, cb))
            cr = max(-128, min(127, cr))
            px = int(cx + cb * scale)
            py = int(cy - cr * scale)
            if 0 <= px < _VS_W and 0 <= py < _VS_H:
                key = (px, py)
                density[key] = density.get(key, 0) + 1

        # Render density as colored dots
        max_den = max(density.values()) if density else 1
        dot_layer = Image.new("RGBA", (_VS_W, _VS_H), (0, 0, 0, 0))
        d_draw = ImageDraw.Draw(dot_layer)

        # Fallback: white dots for neutral, hue-colored for saturated
        for (px, py), count in density.items():
            intensity = min(255, int(200 * (count / max_den) ** 0.4))
            d_draw.point((px, py), (intensity, intensity, intensity, min(220, intensity + 20)))

        chart = Image.alpha_composite(chart, dot_layer)

        # Graticule lines on top
        _draw_vs_graticule(ImageDraw.Draw(chart), cx, cy, radius)

        out_path = _save(chart, fmt)
        return ProcessResult(output_path=out_path)
    except Exception as e:
        return ProcessResult(error=str(e))


def _draw_vs_graticule(draw: ImageDraw.Draw, cx: int, cy: int, r: int):
    g = _HIG_GRID
    g_dim = g + (120,)

    # Outer circle
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=g_dim, width=1)
    # 50% circle
    r2 = r // 2
    draw.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], outline=g_dim, width=1)
    # 25% circle
    r4 = r // 4
    draw.ellipse([cx - r4, cy - r4, cx + r4, cy + r4], outline=g_dim, width=1)

    # Radial lines every 30°
    for deg in range(0, 360, 30):
        a = math.radians(deg)
        draw.line([
            (cx + int(r2 * math.cos(a)), cy + int(r2 * math.sin(a))),
            (cx + int(r * math.cos(a)), cy + int(r * math.sin(a))),
        ], g_dim, 1)

    # Crosshairs
    draw.line([(cx - r, cy), (cx + r, cy)], g_dim, 1)
    draw.line([(cx, cy - r), (cx, cy + r)], g_dim, 1)

    # Center dot
    draw.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=g_dim)

    # Color labels at edge
    labels = [("R", 0), ("M", 60), ("B", 120), ("C", 180),
              ("G", 240), ("Y", 300)]
    for txt, deg in labels:
        a = math.radians(deg)
        lx = cx + int((r + 18) * math.cos(a))
        ly = cy + int((r + 18) * math.sin(a))
        draw.text((lx - 4, ly - 6), txt, fill=_HIG_AXIS)




# ═══════════════════════════════════════════════════════════════════════════════
#  Frequency Domain  —  FFT magnitude with Turbo-like colormap
# ═══════════════════════════════════════════════════════════════════════════════

_FD_W = 1024
_FD_H = 1024


_TURBO_LUT: Optional[list[tuple[int, int, int]]] = None


def _build_turbo_lut() -> list[tuple[int, int, int]]:
    lut: list[tuple[int, int, int]] = []
    for i in range(256):
        v = i / 255.0
        r = int(255 * (0.5 + 0.5 * math.sin(2.0 * math.pi * (v * 0.85 - 0.5)) ** 8))
        g = int(255 * (0.3 + 0.7 * math.sin(2.0 * math.pi * (v * 0.70 + 0.1))))
        b = int(255 * (0.8 - 0.6 * math.sin(2.0 * math.pi * (v * 0.60 + 0.3))))
        lut.append((
            max(0, min(255, r)),
            max(0, min(255, g)),
            max(0, min(255, b)),
        ))
    return lut


def render_frequency_domain(image_path: str, fmt: str = "png") -> ProcessResult:
    global _TURBO_LUT
    try:
        if _TURBO_LUT is None:
            _TURBO_LUT = _build_turbo_lut()
        lut = _TURBO_LUT

        img = Image.open(image_path).convert("L")
        target = 64
        img.thumbnail((target, target), Image.LANCZOS)
        w, h = img.size

        pixels = [[float(img.getpixel((x, y))) for x in range(w)] for y in range(h)]
        mag = _fft2d(pixels)
        mag = _fft_shift(mag)

        fh = len(mag)
        fw = len(mag[0])

        log_mag = [[0.0] * fw for _ in range(fh)]
        min_log = float("inf")
        max_log = float("-inf")
        for y in range(fh):
            for x in range(fw):
                v = math.log10(mag[y][x] + 1.0)
                log_mag[y][x] = v
                if v < min_log:
                    min_log = v
                if v > max_log:
                    max_log = v

        scale = max_log - min_log or 1.0

        spectrum = Image.new("RGBA", (_FD_W, _FD_H), _HIG_BG + (255,))
        sp_pixels = spectrum.load()

        # Precompute source indices
        src_x = [int(x * fw / _FD_W) for x in range(_FD_W)]
        for y in range(_FD_H):
            fy = int(y * fh / _FD_H)
            log_row = log_mag[fy]
            for x in range(_FD_W):
                n = (log_row[src_x[x]] - min_log) / scale
                idx = int(n * 255.0)
                idx = max(0, min(255, idx))
                r, g, b = lut[idx]
                sp_pixels[x, y] = (r, g, b, 255)

        out_path = _save(spectrum, fmt)
        return ProcessResult(output_path=out_path)
    except Exception as e:
        return ProcessResult(error=str(e))
