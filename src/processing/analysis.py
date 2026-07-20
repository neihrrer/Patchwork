import math

from PIL import Image


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



