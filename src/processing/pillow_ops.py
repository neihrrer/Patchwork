import os
import tempfile
from typing import Optional

from PIL import Image, ImageChops, ImageOps, ImageMath

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


def _blend_channel(base_ch, blend_ch, op):
    return op(base_ch, blend_ch)


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
        return ImageMath.eval("convert((a * 256) / (256 - b + 1), 'L')", a=a, b=b)
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
        inv_b = ImageMath.eval("convert(255 - b, 'L')", b=b)
        return ImageMath.eval("convert(255 - (255 - a) * 256 / (b + 1), 'L')", a=a, b=inv_b)
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
        half = ImageMath.eval("convert(b * 2, 'L')", b=b)
        double = ImageMath.eval("convert(b * 2 - 256, 'L')", b=b)
        mask = ImageMath.eval("convert(b < 128 ? 255 : 0, 'L')", b=b)
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
        b2 = ImageMath.eval("convert(b * 2, 'L')", b=b)
        b2m256 = ImageMath.eval("convert(b * 2 - 256, 'L')", b=b)
        mask = ImageMath.eval("convert(b < 128 ? 255 : 0, 'L')", b=b)
        term1 = ImageChops.multiply(a, b2)
        term2 = ImageChops.screen(a, b2m256)
        raw = Image.composite(term1, term2, mask)
        return ImageMath.eval("convert(a - (1 - 2 * b / 256) * (a - a * a / 256), 'L')", a=base_r, b=blend_r)
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
        return ImageMath.eval("convert(a + b - 2 * a * b / 256, 'L')", a=a, b=b)
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
        current = _load(inputs[0])
        for path in inputs[1:]:
            blend = _load(path)
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
