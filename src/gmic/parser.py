import re
import html as html_mod
import gettext
from typing import Optional

from models.filter import FilterDef, ParamDef, ParamKind, ParamValue

try:
    _ = gettext.gettext
except Exception:
    _ = lambda s: s

_HTML_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return _HTML_RE.sub("", text)


def _strip_name(name: str) -> str:
    return html_mod.unescape(_strip_html(name.strip()))


def _split_args(text: str) -> list[str]:
    parts = []
    depth = 0
    current: list[str] = []
    in_quote: Optional[str] = None
    for ch in text:
        if ch in ("\"", "'"):
            if in_quote is None:
                in_quote = ch
            elif in_quote == ch:
                in_quote = None
            current.append(ch)
        elif ch == "(" and in_quote is None:
            depth += 1
            current.append(ch)
        elif ch == ")" and in_quote is None:
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0 and in_quote is None:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    rest = "".join(current).strip()
    if rest:
        parts.append(rest)
    return parts


def _parse_param_value(value_text: str) -> ParamValue:
    value_text = value_text.strip()
    if value_text in ("None", "none", ""):
        return None
    if value_text.startswith("\"") and value_text.endswith("\""):
        inner = value_text[1:-1]
        if inner in ("None", "none"):
            return None
        return inner
    if value_text.startswith("'") and value_text.endswith("'"):
        inner = value_text[1:-1]
        if inner in ("None", "none"):
            return None
        return inner
    try:
        if "." in value_text:
            return float(value_text)
        return int(value_text)
    except (ValueError, TypeError):
        return value_text


_PARAM_TYPES = {
    "bool": ParamKind.BOOL,
    "int": ParamKind.INT,
    "float": ParamKind.FLOAT,
    "choice": ParamKind.CHOICE,
    "color": ParamKind.COLOR,
    "point": ParamKind.POINT,
    "text": ParamKind.TEXT,
    "file_in": ParamKind.FILE,
    "file_out": ParamKind.FILE,
    "file": ParamKind.FILE,
    "folder": ParamKind.FOLDER,
}


def _parse_param_def(text: str) -> Optional[ParamDef]:
    eq_idx = text.find("=")
    if eq_idx < 0:
        return None

    label = text[:eq_idx].strip()
    rest = text[eq_idx + 1:].strip()

    modifiers = ""
    while rest and rest[0] in ("_", "~"):
        modifiers += rest[0]
        rest = rest[1:]

    no_preview = "_" in modifiers and "~" not in modifiers
    randomizable = "~" in modifiers

    paren_idx = rest.find("(")
    brace_idx = rest.find("{")
    if paren_idx < 0 and brace_idx < 0:
        return None

    if brace_idx >= 0 and (paren_idx < 0 or brace_idx < paren_idx):
        open_char = "{"
        close_char = "}"
        idx = brace_idx
    else:
        open_char = "("
        close_char = ")"
        idx = paren_idx

    type_name = rest[:idx].strip().lower()
    args_text = rest[idx:]

    if not args_text.endswith(close_char):
        return None

    args_text = args_text[1:-1]
    args = _split_args(args_text)

    is_hidden = type_name.endswith("_0")
    is_disabled = type_name.endswith("_1")
    type_name = re.sub(r"_[012]$", "", type_name)

    kind = _PARAM_TYPES.get(type_name)
    if kind is None:
        return None

    default = None
    min_val = None
    max_val = None
    choices = []

    if kind == ParamKind.BOOL:
        if args:
            val = _parse_param_value(args[0])
            if val is None:
                default = False
            elif isinstance(val, str):
                default = val.lower() not in ("0", "false", "none", "")
            else:
                default = bool(int(val))

    elif kind == ParamKind.INT:
        if args:
            val = _parse_param_value(args[0])
            default = int(val) if val is not None else 0
        if len(args) > 1:
            val = _parse_param_value(args[1])
            min_val = float(val) if val is not None else None
        if len(args) > 2:
            val = _parse_param_value(args[2])
            max_val = float(val) if val is not None else None

    elif kind in (ParamKind.FLOAT,):
        if args:
            val = _parse_param_value(args[0])
            default = float(val) if val is not None else 0.0
        if len(args) > 1:
            val = _parse_param_value(args[1])
            min_val = float(val) if val is not None else None
        if len(args) > 2:
            val = _parse_param_value(args[2])
            max_val = float(val) if val is not None else None

    elif kind == ParamKind.CHOICE:
        for a in args[1:]:
            v = _parse_param_value(a)
            choices.append(str(v) if v is not None else "")
        if args:
            val = _parse_param_value(args[0])
            if isinstance(val, str):
                default = choices.index(val) if val in choices else 0
            else:
                default = int(val) if val is not None else 0
        if default is not None and choices:
            default = min(default, len(choices) - 1)

    elif kind == ParamKind.COLOR:
        vals = []
        for a in args:
            v = _parse_param_value(a)
            if v is not None:
                vals.append(v)
        default = vals if vals else [0, 0, 0, 255]

    elif kind == ParamKind.POINT:
        vals = []
        for a in args:
            v = _parse_param_value(a)
            if v is not None:
                vals.append(v)
        default = vals if vals else [0, 0]

    elif kind == ParamKind.TEXT:
        if args:
            v = _parse_param_value(args[-1])
            default = str(v) if v is not None else ""
        else:
            default = ""

    elif kind in (ParamKind.FILE, ParamKind.FOLDER):
        if args:
            v = _parse_param_value(args[0])
            default = str(v) if v is not None else ""

    return ParamDef(
        name=label,
        label=label,
        kind=kind,
        default=default,
        min_val=min_val,
        max_val=max_val,
        choices=choices,
        no_preview=no_preview,
        randomizable=randomizable,
        is_hidden=is_hidden,
        is_disabled=is_disabled,
    )


def _join_continuations(lines: list[str]) -> list[str]:
    joined = []
    buf: list[str] = []
    for line in lines:
        is_cont = line.startswith("# ") and bool(buf)
        raw = line[2:] if is_cont else line
        if raw.endswith("\\"):
            buf.append(raw[:-1])
        else:
            buf.append(raw)
            joined.append("".join(buf))
            buf = []
    if buf:
        joined.append("".join(buf))

    # Merge #@gui continuation lines (a param def spanning multiple
    # lines without backslash, e.g. long choice lists)
    merged = []
    gui_buf = ""
    for line in joined:
        stripped = line.strip()
        if stripped.startswith("#@gui"):
            content = stripped[5:].strip()
            if ":" in content:
                lhs, rhs = content.split(":", 1)
                if not lhs.strip() and "=" not in rhs and "=" in gui_buf:
                    gui_buf += " " + rhs.strip()
                    continue
            if gui_buf:
                merged.append(gui_buf)
            gui_buf = stripped
        else:
            if gui_buf:
                merged.append(gui_buf)
                gui_buf = ""
            merged.append(line)
    if gui_buf:
        merged.append(gui_buf)
    return merged


def _munge_gui_command(command: str) -> str:
    command = command.strip()
    # Find the part with parentheses — that is the filter command with defaults
    main_part = None
    for p in command.split(","):
        if "(" in p:
            main_part = p.strip()
            break
    if main_part is not None:
        command = main_part.split("(")[0].strip()
    else:
        if "," in command:
            command = command.split(",")[0]
        command = command.split("(")[0].strip()
    if command.endswith(":*"):
        command = command[:-2]
    return command


def _is_testing_category(category: list[str]) -> bool:
    return any("testing" in c.lower() for c in category)


class GmicFilterParser:
    def __init__(self):
        self._builtin_filters = self._create_builtin_filters()

    def parse_gui(self, text: str) -> list[FilterDef]:
        filters: list[FilterDef] = []
        seen: set[str] = set()
        folder_stack: list[str] = []
        current_filter: Optional[FilterDef] = None

        lines = _join_continuations(text.splitlines())

        for raw_line in lines:
            line = raw_line.strip()
            if not line.startswith("#@gui"):
                continue

            content = line[5:].strip()

            if not content or content == "_":
                if content == "_":
                    folder_stack.clear()
                current_filter = None
                continue

            if ":" not in content:
                was_pop = content.startswith("_")
                folder_name = _strip_name(content.lstrip("_"))
                if not folder_name:
                    continue
                if was_pop and folder_stack:
                    folder_stack.pop()
                folder_stack.append(folder_name)
                current_filter = None
                continue

            lhs, rhs = content.split(":", 1)
            lhs = lhs.strip()
            rhs = rhs.strip()

            if not lhs:
                if current_filter is not None:
                    try:
                        param = _parse_param_def(rhs)
                        if param is not None:
                            current_filter.parameters.append(param)
                    except Exception:
                        pass
                continue

            display_name = _strip_name(lhs)
            command = _munge_gui_command(rhs)

            if not command or command.startswith("_"):
                continue

            if _is_testing_category(folder_stack):
                current_filter = None
                continue

            filter_name = command.split()[0].split(",")[0].strip()

            if filter_name in seen:
                current_filter = None
                continue
            seen.add(filter_name)

            current_filter = FilterDef(
                name=filter_name,
                display_name=display_name,
                category=list(folder_stack),
                description="",
                parameters=[],
                gmic_command=command,
            )
            filters.append(current_filter)

        return filters if filters else self._builtin_filters

    def get_builtin_filters(self) -> list[FilterDef]:
        return self._builtin_filters

    def _create_builtin_filters(self) -> list[FilterDef]:
        categories = {
            _("Artistic"): [
                ("fx_sketchbw", _("Sketch (B&W)"), "fx_sketchbw"),
                ("fx_oilpaint", _("Oil Painting"), "fx_oilpaint"),
                ("fx_pencil", _("Pencil Drawing"), "fx_pencil"),
                ("fx_watercolor", _("Watercolor"), "fx_watercolor"),
                ("fx_cartoon", _("Cartoon"), "fx_cartoon"),
                ("fx_comic", _("Comic Book"), "fx_comic"),
            ],
            _("Colors"): [
                ("fx_boost_chroma", _("Boost Chroma"), "fx_boost_chroma"),
                ("sepia", _("Sepia"), "sepia"),
                ("fx_colorize", _("Colorize"), "fx_colorize"),
                ("normalize", _("Auto Levels"), "normalize 0,255"),
                ("equalize", _("Histogram Equalization"), "equalize 256"),
                ("fx_balance_gray", _("Gray Balance"), "fx_balance_gray"),
            ],
            _("Details"): [
                ("sharpen", _("Sharpen"), "sharpen 500"),
                ("fx_unsharp", _("Unsharp Mask"), "fx_unsharp"),
                ("fx_details", _("Extract Details"), "fx_details"),
                ("blur", _("Blur"), "blur 3"),
                ("fx_denoise", _("Denoise"), "fx_denoise"),
            ],
            _("Deformations"): [
                ("rotate", _("Rotate"), "rotate 90"),
                ("resize", _("Resize"), "resize 50%,50%"),
                ("warp", _("Warp"), "warp 10,10"),
                ("flip", _("Flip"), "flip"),
                ("mirror", _("Mirror"), "mirror"),
            ],
            _("Light & Shadows"): [
                ("fx_light_balance", _("Light Balance"), "fx_light_balance"),
                ("fx_retinex", _("Retinex"), "fx_retinex"),
                ("normalize_local", _("Local Normalization"), "normalize_local 10"),
            ],
            _("B&W"): [
                ("to_gray", _("Grayscale"), "to_gray"),
                ("threshold", _("Threshold"), "threshold 128"),
                ("invert", _("Invert"), "invert"),
            ],
            _("Frames"): [
                ("frame", _("Add Frame"), "frame 5,white"),
                ("fx_polaroid", _("Polaroid"), "fx_polaroid"),
                ("vignette", _("Vignette"), "vignette 20"),
            ],
            _("Repair"): [
                ("fx_hotpixels", _("Remove Hot Pixels"), "fx_hotpixels"),
                ("fx_banding", _("Remove Banding"), "fx_banding"),
                ("fx_antialias", _("Anti-alias"), "fx_antialias"),
            ],
            _("Rendering"): [
                ("plasma", _("Plasma"), "plasma 50"),
                ("cloud", _("Cloud"), "cloud 50"),
                ("fractal", _("Fractal"), "fractal"),
            ],
        }

        filters = []
        for category_name, items in categories.items():
            for name, display_name, command in items:
                filters.append(FilterDef(
                    name=name,
                    display_name=display_name,
                    category=[category_name],
                    description="",
                    parameters=[],
                    gmic_command=command,
                ))
        return filters
