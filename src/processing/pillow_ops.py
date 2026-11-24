import math
import os
import random
import struct
import tempfile
from typing import Optional

from PIL import Image, ImageChops, ImageOps, ImageMath, ImageFilter

from processing.runner import ProcessResult


def _load(path: str) -> Image.Image:
    return Image.open(path).convert("RGBA")


def _save(img: Image.Image, fmt: str) -> str:
    fd, out_path = tempfile.mkstemp(suffix="." + fmt)
    os.close(fd)
    if fmt == "jpeg":
        img = img.convert("RGB")
    img.save(out_path)
    return out_path


def _match_size(im1: Image.Image, im2: Image.Image) -> tuple[Image.Image, Image.Image]:
    if im1.size == im2.size:
        return im1, im2
    w = max(im1.width, im2.width)
    h = max(im1.height, im2.height)
    c1 = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    c1.paste(im1, (0, 0))
    c2 = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    c2.paste(im2, (0, 0))
    return c1, c2


def _blend_over(base: Image.Image, blend: Image.Image) -> Image.Image:
    return Image.alpha_composite(base, blend)


def _blend_multiply(base: Image.Image, blend: Image.Image) -> Image.Image:
    if base.mode != "RGBA" or blend.mode != "RGBA":
        base = base.convert("RGBA")
        blend = blend.convert("RGBA")
    base_r, base_g, base_b, base_a = base.split()
    blend_r, blend_g, blend_b, blend_a = blend.split()
    r = ImageChops.multiply(base_r, blend_r)
    g = ImageChops.multiply(base_g, blend_g)
    b = ImageChops.multiply(base_b, blend_b)
    a = ImageChops.multiply(base_a, blend_a)
    return Image.merge("RGBA", (r, g, b, a))


def _blend_screen(base: Image.Image, blend: Image.Image) -> Image.Image:
    if base.mode != "RGBA" or blend.mode != "RGBA":
        base = base.convert("RGBA")
        blend = blend.convert("RGBA")
    base_r, base_g, base_b, base_a = base.split()
    blend_r, blend_g, blend_b, blend_a = blend.split()
    r = ImageChops.screen(base_r, blend_r)
    g = ImageChops.screen(base_g, blend_g)
    b = ImageChops.screen(base_b, blend_b)
    a = ImageChops.screen(base_a, blend_a)
    return Image.merge("RGBA", (r, g, b, a))


def _blend_overlay(base: Image.Image, blend: Image.Image) -> Image.Image:
    if base.mode != "RGBA" or blend.mode != "RGBA":
        base = base.convert("RGBA")
        blend = blend.convert("RGBA")
    base_r, base_g, base_b, base_a = base.split()
    blend_r, blend_g, blend_b, blend_a = blend.split()
    r = ImageChops.overlay(base_r, blend_r)
    g = ImageChops.overlay(base_g, blend_g)
    b = ImageChops.overlay(base_b, blend_b)
    a = ImageChops.screen(base_a, blend_a)
    return Image.merge("RGBA", (r, g, b, a))


def _blend_darken(base: Image.Image, blend: Image.Image) -> Image.Image:
    return ImageChops.darker(base, blend)


def _blend_lighten(base: Image.Image, blend: Image.Image) -> Image.Image:
    return ImageChops.lighter(base, blend)


def _blend_color_dodge(base: Image.Image, blend: Image.Image) -> Image.Image:
    base = base.convert("RGBA")
    blend = blend.convert("RGBA")
    base_r, base_g, base_b, base_a = base.split()
    blend_r, blend_g, blend_b, blend_a = blend.split()
    def dodge(a, b):
        return ImageMath.unsafe_eval("convert((a * 256) / (256 - b + 1), 'L')", a=a, b=b)
    r = dodge(base_r, blend_r)
    g = dodge(base_g, blend_g)
    b = dodge(base_b, blend_b)
    a = ImageChops.screen(base_a, blend_a)
    return Image.merge("RGBA", (r, g, b, a))


def _blend_color_burn(base: Image.Image, blend: Image.Image) -> Image.Image:
    base = base.convert("RGBA")
    blend = blend.convert("RGBA")
    base_r, base_g, base_b, base_a = base.split()
    blend_r, blend_g, blend_b, blend_a = blend.split()
    def burn(a, b):
        inv_b = ImageMath.unsafe_eval("convert(255 - b, 'L')", b=b)
        return ImageMath.unsafe_eval("convert(255 - (255 - a) * 256 / (b + 1), 'L')", a=a, b=inv_b)
    r = burn(base_r, blend_r)
    g = burn(base_g, blend_g)
    b = burn(base_b, blend_b)
    a = ImageChops.screen(base_a, blend_a)
    return Image.merge("RGBA", (r, g, b, a))


def _blend_hard_light(base: Image.Image, blend: Image.Image) -> Image.Image:
    base = base.convert("RGBA")
    blend = blend.convert("RGBA")
    base_r, base_g, base_b, base_a = base.split()
    blend_r, blend_g, blend_b, blend_a = blend.split()
    def hard(a, b):
        half = ImageMath.unsafe_eval("convert(b * 2, 'L')", b=b)
        double = ImageMath.unsafe_eval("convert(b * 2 - 256, 'L')", b=b)
        mask = ImageMath.unsafe_eval("convert(b < 128 ? 255 : 0, 'L')", b=b)
        mult = ImageChops.multiply(a, half)
        screen = ImageChops.screen(a, double)
        return Image.composite(mult, screen, mask)
    r = hard(base_r, blend_r)
    g = hard(base_g, blend_g)
    b = hard(base_b, blend_b)
    a = ImageChops.screen(base_a, blend_a)
    return Image.merge("RGBA", (r, g, b, a))


def _blend_soft_light(base: Image.Image, blend: Image.Image) -> Image.Image:
    base = base.convert("RGBA")
    blend = blend.convert("RGBA")
    base_r, base_g, base_b, base_a = base.split()
    blend_r, blend_g, blend_b, blend_a = blend.split()
    def soft(a, b):
        return ImageMath.unsafe_eval("convert(a - (1 - 2 * b / 256) * (a - a * a / 256), 'L')", a=a, b=b)
    r = soft(base_r, blend_r)
    g = soft(base_g, blend_g)
    b = soft(base_b, blend_b)
    a = ImageChops.screen(base_a, blend_a)
    return Image.merge("RGBA", (r, g, b, a))


def _blend_difference(base: Image.Image, blend: Image.Image) -> Image.Image:
    return ImageChops.difference(base, blend)


def _blend_exclusion(base: Image.Image, blend: Image.Image) -> Image.Image:
    base = base.convert("RGBA")
    blend = blend.convert("RGBA")
    base_r, base_g, base_b, base_a = base.split()
    blend_r, blend_g, blend_b, blend_a = blend.split()
    def excl(a, b):
        return ImageMath.unsafe_eval("convert(a + b - 2 * a * b / 256, 'L')", a=a, b=b)
    r = excl(base_r, blend_r)
    g = excl(base_g, blend_g)
    b = excl(base_b, blend_b)
    a = ImageChops.screen(base_a, blend_a)
    return Image.merge("RGBA", (r, g, b, a))


_BLEND_FUNCS = {
    "over": _blend_over,
    "multiply": _blend_multiply,
    "screen": _blend_screen,
    "overlay": _blend_overlay,
    "darken": _blend_darken,
    "lighten": _blend_lighten,
    "color-dodge": _blend_color_dodge,
    "color-burn": _blend_color_burn,
    "hard-light": _blend_hard_light,
    "soft-light": _blend_soft_light,
    "difference": _blend_difference,
    "exclusion": _blend_exclusion,
}


def blend_images(inputs: list[str], mode: str, fmt: str) -> ProcessResult:
    try:
        fn = _BLEND_FUNCS.get(mode)
        if fn is None:
            return ProcessResult(error=f"Unknown blend mode: {mode}")
        images = [_load(p) for p in inputs]
        current = images[0]
        for blend in images[1:]:
            current, blend = _match_size(current, blend)
            current = fn(current, blend)
        out_path = _save(current, fmt)
        return ProcessResult(output_path=out_path)
    except Exception as e:
        return ProcessResult(error=str(e))


def adjust_opacity(image_path: str, opacity: float, fmt: str) -> ProcessResult:
    try:
        img = _load(image_path)
        if opacity < 1.0:
            r, g, b, a = img.split()
            a = a.point(lambda x: int(x * opacity))
            img = Image.merge("RGBA", (r, g, b, a))
        out_path = _save(img, fmt)
        return ProcessResult(output_path=out_path)
    except Exception as e:
        return ProcessResult(error=str(e))


def adjust_hsl(image_path: str, hue: float, saturation: float, lightness: float, fmt: str) -> ProcessResult:
    try:
        img = _load(image_path)
        if hue != 0.0 or saturation != 0.0 or lightness != 0.0:
            r, g, b, a = img.split()
            hsv = img.convert("HSV")
            h, s, v = hsv.split()

            if hue != 0.0:
                h = h.point(lambda x: int((x + hue * 255.0 / 360.0)) % 256)
            if saturation != 0.0:
                s = s.point(lambda x: max(0, min(255, int(x * (100 + saturation) / 100.0))))
            if lightness != 0.0:
                v = v.point(lambda x: max(0, min(255, int(x * (100 + lightness) / 100.0))))

            hsv = Image.merge("HSV", (h, s, v))
            img = hsv.convert("RGBA")
            img.putalpha(a)
        out_path = _save(img, fmt)
        return ProcessResult(output_path=out_path)
    except Exception as e:
        return ProcessResult(error=str(e))


def adjust_brightness_contrast(image_path: str, brightness: float, contrast: float, fmt: str) -> ProcessResult:
    try:
        img = _load(image_path)
        if brightness != 0.0 or contrast != 0.0:
            r, g, b, a = img.split()
            factor = (259 * (contrast * 2.55 + 255)) / (255 * (259 - contrast * 2.55)) if contrast != 0 else 1.0
            def apply(x):
                x = int((x - 128) * factor + 128 + brightness * 2.55)
                return max(0, min(255, x))
            r = r.point(apply)
            g = g.point(apply)
            b = b.point(apply)
            img = Image.merge("RGBA", (r, g, b, a))
        out_path = _save(img, fmt)
        return ProcessResult(output_path=out_path)
    except Exception as e:
        return ProcessResult(error=str(e))


def adjust_levels(image_path: str, black_point: float, white_point: float, gamma: float, fmt: str) -> ProcessResult:
    try:
        img = _load(image_path)
        r, g, b, a = img.split()
        if black_point != 0.0 or white_point != 100.0 or gamma != 1.0:
            b_in = black_point / 100.0 * 255.0
            w_in = white_point / 100.0 * 255.0
            inv_gamma = 1.0 / max(gamma, 0.01)
            def apply(x):
                if x <= b_in:
                    return 0
                if x >= w_in:
                    return 255
                norm = (x - b_in) / (w_in - b_in)
                result = (norm ** inv_gamma) * 255.0
                return max(0, min(255, int(result)))
            r = r.point(apply)
            g = g.point(apply)
            b = b.point(apply)
        img = Image.merge("RGBA", (r, g, b, a))
        out_path = _save(img, fmt)
        return ProcessResult(output_path=out_path)
    except Exception as e:
        return ProcessResult(error=str(e))


def apply_mask(base_path: str, mask_path: str, invert: bool, threshold: float, fmt: str) -> ProcessResult:
    try:
        base = _load(base_path)
        mask = _load(mask_path)

        if threshold > 0.0 or invert:
            m = mask.convert("L")
            if threshold > 0.0:
                thresh_val = int(threshold * 255.0)
                m = m.point(lambda x: 255 if x > thresh_val else 0)
            if invert:
                m = ImageOps.invert(m)
            mask = m.convert("RGBA")
        else:
            mask = mask.convert("L").convert("RGBA")

        out = Image.composite(base, Image.new("RGBA", base.size, (0, 0, 0, 0)), mask.convert("L"))
        out_path = _save(out, fmt)
        return ProcessResult(output_path=out_path)
    except Exception as e:
        return ProcessResult(error=str(e))


def _parse_color(hex_color: str):
    if hex_color.startswith("#"):
        hex_color = hex_color[1:]
    if len(hex_color) == 6:
        hex_color += "FF"
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4, 6))


def generate_color_source(width: int, height: int, color: str, fmt: str) -> ProcessResult:
    try:
        rgba = _parse_color(color)
        img = Image.new("RGBA", (width, height), rgba)
        out_path = _save(img, fmt)
        return ProcessResult(output_path=out_path)
    except Exception as e:
        return ProcessResult(error=str(e))


def generate_gradient(width: int, height: int, gradient_type: str,
                      start_color: str, end_color: str, angle: float, fmt: str) -> ProcessResult:
    try:
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        sc = _parse_color(start_color)
        ec = _parse_color(end_color)
        pixels = img.load()
        if gradient_type == "linear":
            rad = math.radians(angle)
            gx = math.cos(rad)
            gy = math.sin(rad)
            cx, cy = width / 2.0, height / 2.0
            corners = [(0, 0), (width, 0), (0, height), (width, height)]
            projs = [(x - cx) * gx + (y - cy) * gy for x, y in corners]
            min_p, max_p = min(projs), max(projs)
            span = max_p - min_p
            if span < 1:
                span = 1
            for y in range(height):
                for x in range(width):
                    t = ((x - cx) * gx + (y - cy) * gy - min_p) / span
                    t = max(0.0, min(1.0, t))
                    pixels[x, y] = (
                        int(sc[0] + (ec[0] - sc[0]) * t),
                        int(sc[1] + (ec[1] - sc[1]) * t),
                        int(sc[2] + (ec[2] - sc[2]) * t),
                        int(sc[3] + (ec[3] - sc[3]) * t),
                    )
        else:
            cx, cy = width / 2.0, height / 2.0
            max_r = math.sqrt(cx * cx + cy * cy)
            if max_r < 1:
                max_r = 1
            for y in range(height):
                for x in range(width):
                    dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2) / max_r
                    t = max(0.0, min(1.0, dist))
                    pixels[x, y] = (
                        int(sc[0] + (ec[0] - sc[0]) * t),
                        int(sc[1] + (ec[1] - sc[1]) * t),
                        int(sc[2] + (ec[2] - sc[2]) * t),
                        int(sc[3] + (ec[3] - sc[3]) * t),
                    )
        out_path = _save(img, fmt)
        return ProcessResult(output_path=out_path)
    except Exception as e:
        return ProcessResult(error=str(e))


def generate_noise(width: int, height: int, noise_type: str, scale: float, seed: Optional[int], fmt: str) -> ProcessResult:
    try:
        if seed is not None and seed >= 0:
            random.seed(seed)
        if noise_type == "gaussian":
            img = Image.effect_noise((width, height), scale)
            img = img.convert("RGBA")
        else:
            base = Image.new("L", (width, height), 128)
            img = Image.effect_noise((width, height), scale)
            img = ImageChops.add(base, img, scale=1.0, offset=-128)
            img = img.convert("RGBA")
        out_path = _save(img, fmt)
        return ProcessResult(output_path=out_path)
    except Exception as e:
        return ProcessResult(error=str(e))


def adjust_color_balance(image_path: str, cyan_red: float, magenta_green: float,
                         yellow_blue: float, fmt: str) -> ProcessResult:
    try:
        img = _load(image_path)
        r, g, b, a = img.split()
        rf = 1.0 + cyan_red / 100.0
        gf = 1.0 + magenta_green / 100.0
        bf = 1.0 + yellow_blue / 100.0
        r = r.point(lambda x: max(0, min(255, int(x * rf))))
        g = g.point(lambda x: max(0, min(255, int(x * gf))))
        b = b.point(lambda x: max(0, min(255, int(x * bf))))
        img = Image.merge("RGBA", (r, g, b, a))
        out_path = _save(img, fmt)
        return ProcessResult(output_path=out_path)
    except Exception as e:
        return ProcessResult(error=str(e))


def adjust_exposure_gamma(image_path: str, exposure: float, gamma: float, fmt: str) -> ProcessResult:
    try:
        img = _load(image_path)
        r, g, b, a = img.split()
        exp_factor = pow(2.0, exposure)
        inv_gamma = 1.0 / max(gamma, 0.01)
        def apply(x):
            val = (x / 255.0) * exp_factor
            val = pow(max(val, 0.0), inv_gamma)
            return max(0, min(255, int(val * 255.0)))
        r = r.point(apply)
        g = g.point(apply)
        b = b.point(apply)
        img = Image.merge("RGBA", (r, g, b, a))
        out_path = _save(img, fmt)
        return ProcessResult(output_path=out_path)
    except Exception as e:
        return ProcessResult(error=str(e))


def adjust_curves(image_path: str, p0: float, p1: float, p2: float,
                  p3: float, p4: float, fmt: str) -> ProcessResult:
    try:
        img = _load(image_path)
        r, g, b, a = img.split()
        anchors = [(0, max(0, min(255, int(p0)))),
                    (64, max(0, min(255, int(p1)))),
                    (128, max(0, min(255, int(p2)))),
                    (192, max(0, min(255, int(p3)))),
                    (255, max(0, min(255, int(p4))))]
        lut = []
        for x in range(256):
            for i in range(len(anchors) - 1):
                if anchors[i][0] <= x <= anchors[i + 1][0]:
                    x1, y1 = anchors[i]
                    x2, y2 = anchors[i + 1]
                    t = (x - x1) / max(x2 - x1, 1)
                    y = y1 + (y2 - y1) * t
                    lut.append(max(0, min(255, int(y))))
                    break
            else:
                lut.append(x)
        r = r.point(lut)
        g = g.point(lut)
        b = b.point(lut)
        img = Image.merge("RGBA", (r, g, b, a))
        out_path = _save(img, fmt)
        return ProcessResult(output_path=out_path)
    except Exception as e:
        return ProcessResult(error=str(e))


def crop_image(image_path: str, x: float, y: float, w: float, h: float, fmt: str) -> ProcessResult:
    try:
        img = Image.open(image_path)
        xi, yi, wi, hi = int(x), int(y), int(w), int(h)
        cropped = img.crop((xi, yi, xi + wi, yi + hi))
        out_path = _save(cropped, fmt)
        return ProcessResult(output_path=out_path)
    except Exception as e:
        return ProcessResult(error=str(e))


def resize_image(image_path: str, width: float, height: float, mode: str, fmt: str) -> ProcessResult:
    try:
        img = Image.open(image_path)
        wi, hi = int(width), int(height)
        if mode == "stretch":
            resized = img.resize((wi, hi), Image.LANCZOS)
        elif mode == "fit":
            img.thumbnail((wi, hi), Image.LANCZOS)
            resized = Image.new(img.mode, (wi, hi), (0, 0, 0, 0))
            ox = (wi - img.width) // 2
            oy = (hi - img.height) // 2
            resized.paste(img, (ox, oy))
        else:
            img.thumbnail((wi, hi), Image.LANCZOS)
            resized = Image.new(img.mode, (wi, hi), (0, 0, 0, 0))
            ox = max(0, (wi - img.width) // 2)
            oy = max(0, (hi - img.height) // 2)
            sx = max(0, (img.width - wi) // 2)
            sy = max(0, (img.height - hi) // 2)
            resized.paste(img.crop((sx, sy, sx + min(wi, img.width), sy + min(hi, img.height))), (ox, oy))
        out_path = _save(resized, fmt)
        return ProcessResult(output_path=out_path)
    except Exception as e:
        return ProcessResult(error=str(e))


def rotate_image(image_path: str, angle: float, fmt: str) -> ProcessResult:
    try:
        img = Image.open(image_path)
        rotated = img.rotate(angle, expand=True, resample=Image.BICUBIC)
        out_path = _save(rotated, fmt)
        return ProcessResult(output_path=out_path)
    except Exception as e:
        return ProcessResult(error=str(e))


def flip_image(image_path: str, direction: str, fmt: str) -> ProcessResult:
    try:
        img = Image.open(image_path)
        if direction == "horizontal":
            flipped = ImageOps.mirror(img)
        else:
            flipped = ImageOps.flip(img)
        out_path = _save(flipped, fmt)
        return ProcessResult(output_path=out_path)
    except Exception as e:
        return ProcessResult(error=str(e))


def distort_image(image_path: str, x0: float, y0: float, x1: float, y1: float,
                  x2: float, y2: float, x3: float, y3: float, fmt: str) -> ProcessResult:
    try:
        img = Image.open(image_path)
        w, h = img.size
        src = [(0, 0), (w, 0), (w, h), (0, h)]
        dst = [(x0, y0), (x1, y1), (x2, y2), (x3, y3)]
        matrix = []
        for (x, y), (xp, yp) in zip(src, dst):
            matrix.append([x, y, 1, 0, 0, 0, -x * xp, -y * xp, xp])
            matrix.append([0, 0, 0, x, y, 1, -x * yp, -y * yp, yp])
        flat = [item for row in matrix for item in row]
        A = [flat[i * 9:(i + 1) * 9] for i in range(8)]
        for col in range(8):
            pivot = None
            for row in range(col, 8):
                if abs(A[row][col]) > 1e-12:
                    pivot = row
                    break
            if pivot is None:
                continue
            A[col], A[pivot] = A[pivot], A[col]
            piv_val = A[col][col]
            for j in range(9):
                A[col][j] /= piv_val
            for row in range(8):
                if row != col:
                    factor = A[row][col]
                    for j in range(9):
                        A[row][j] -= factor * A[col][j]
        coeffs = tuple(A[i][8] for i in range(8))
        distorted = img.transform(img.size, Image.PERSPECTIVE, coeffs, Image.BICUBIC)
        out_path = _save(distorted, fmt)
        return ProcessResult(output_path=out_path)
    except Exception as e:
        return ProcessResult(error=str(e))


def blur_image(image_path: str, radius: float, fmt: str) -> ProcessResult:
    try:
        img = Image.open(image_path)
        blurred = img.filter(ImageFilter.GaussianBlur(radius=radius))
        out_path = _save(blurred, fmt)
        return ProcessResult(output_path=out_path)
    except Exception as e:
        return ProcessResult(error=str(e))


def sharpen_image(image_path: str, amount: float, radius: float, fmt: str) -> ProcessResult:
    try:
        img = Image.open(image_path)
        sharpened = img.filter(ImageFilter.UnsharpMask(radius=radius, percent=int(amount * 100), threshold=0))
        out_path = _save(sharpened, fmt)
        return ProcessResult(output_path=out_path)
    except Exception as e:
        return ProcessResult(error=str(e))


def edge_detect(image_path: str, threshold: float, fmt: str) -> ProcessResult:
    try:
        img = Image.open(image_path).convert("L")
        edges = img.filter(ImageFilter.FIND_EDGES)
        if threshold > 0.0:
            thresh_val = int(threshold * 255.0)
            edges = edges.point(lambda x: 255 if x > thresh_val else 0)
        edges = edges.convert("RGBA")
        out_path = _save(edges, fmt)
        return ProcessResult(output_path=out_path)
    except Exception as e:
        return ProcessResult(error=str(e))


_DECODE_FORMATS = {
    "1-bit (monochrome)":     {"bpp": 0.125, "mode": "1"},
    "8-bit grayscale":        {"bpp": 1,     "mode": "L"},
    "8-bit RGB (24-bit)":     {"bpp": 3,     "mode": "RGB"},
    "8-bit RGBA (32-bit)":    {"bpp": 4,     "mode": "RGBA"},
    "16-bit grayscale LE":    {"bpp": 2,     "mode": "I;16"},
    "16-bit grayscale BE":    {"bpp": 2,     "mode": "I;16B"},
    "16-bit RGB (48-bit) LE": {"bpp": 6,     "mode": "RGB",   "bit16": True, "little": True},
    "16-bit RGB (48-bit) BE": {"bpp": 6,     "mode": "RGB",   "bit16": True, "little": False},
    "16-bit RGBA (64-bit) LE":{"bpp": 8,     "mode": "RGBA",  "bit16": True, "little": True},
    "16-bit RGBA (64-bit) BE":{"bpp": 8,     "mode": "RGBA",  "bit16": True, "little": False},
    "32-bit float grayscale": {"bpp": 4,     "mode": "F"},
    "32-bit float RGB":       {"bpp": 12,    "mode": "RGB",   "float32": True},
    "32-bit float RGBA":      {"bpp": 16,    "mode": "RGBA",  "float32": True},
}


def decode_raw(raw_path: str, method: str, width: int, height: int, offset: int, fmt: str) -> ProcessResult:
    try:
        finfo = _DECODE_FORMATS.get(method)
        if not finfo:
            return ProcessResult(error=f"Unknown decode method: {method}")

        total_pixels = width * height
        if total_pixels == 0:
            return ProcessResult(error="Width and height must be greater than 0")

        with open(raw_path, "rb") as f:
            if offset > 0:
                f.seek(offset)

            if method == "1-bit (monochrome)":
                byte_count = (total_pixels + 7) // 8
                data = f.read(byte_count)
                if len(data) < byte_count:
                    return ProcessResult(error=f"File too small: need {byte_count} bytes, got {len(data)}")
                pixels = bytearray()
                for byte in data:
                    for b in range(8):
                        pixels.append(0xFF if (byte >> (7 - b)) & 1 else 0x00)
                pixels = bytes(pixels[:total_pixels])
                img = Image.frombytes("1", (width, height), pixels)
            elif finfo.get("bit16"):
                bpp = int(finfo["bpp"])
                byte_count = total_pixels * bpp
                data = f.read(byte_count)
                if len(data) < byte_count:
                    return ProcessResult(error=f"File too small: need {byte_count} bytes, got {len(data)}")
                channels = 3 if finfo["mode"] == "RGB" else 4
                pix_per_channel = total_pixels
                ch_data = []
                for c in range(channels):
                    ch_bytes = bytearray()
                    for i in range(pix_per_channel):
                        lo = data[(i * channels + c) * 2]
                        hi = data[(i * channels + c) * 2 + 1]
                        if finfo["little"]:
                            val = lo | (hi << 8)
                        else:
                            val = hi | (lo << 8)
                        ch_bytes.append(val >> 8)
                    ch_data.append(bytes(ch_bytes))
                raw = b"".join(
                    bytes([ch_data[c][i] for c in range(channels)])
                    for i in range(pix_per_channel)
                )
                img = Image.frombytes(finfo["mode"], (width, height), raw)
            elif finfo.get("float32"):
                bpp = int(finfo["bpp"])
                channels = width * height
                total_floats = channels if finfo["mode"] == "F" else channels * (3 if finfo["mode"] == "RGB" else 4)
                data = f.read(total_floats * 4)
                if len(data) < total_floats * 4:
                    return ProcessResult(error="File too small")
                vals = struct.unpack(f"<{total_floats}f", data[:total_floats * 4])
                clamped = bytes(max(0, min(255, int(v * 255.0))) for v in vals)
                img = Image.frombytes(finfo["mode"], (width, height), clamped)
            else:
                bpp = int(finfo["bpp"])
                byte_count = total_pixels * bpp
                data = f.read(byte_count)
                if len(data) < byte_count:
                    return ProcessResult(error=f"File too small: need {byte_count} bytes, got {len(data)}")
                img = Image.frombytes(finfo["mode"], (width, height), data)

        if img.mode != "RGBA":
            img = img.convert("RGBA")
        out_path = _save(img, fmt)
        return ProcessResult(output_path=out_path)
    except Exception as e:
        return ProcessResult(error=str(e))
