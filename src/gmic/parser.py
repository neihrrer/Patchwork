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


def _find_matching_close(text: str, open_idx: int,
                        open_ch: str = "(", close_ch: str = ")") -> int:
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == open_ch:
            depth += 1
        elif text[i] == close_ch:
            depth -= 1
            if depth == 0:
                return i
    return -1


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
        elif ch in ("{", "[") and in_quote is None:
            depth += 1
            current.append(ch)
        elif ch in ("}", "]") and in_quote is None:
            depth -= 1
            current.append(ch)
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
    "value": ParamKind.TEXT,
    "file_in": ParamKind.FILE,
    "file_out": ParamKind.FILE,
    "file": ParamKind.FILE,
    "folder": ParamKind.FOLDER,
}


def _parse_param_def(text: str) -> Optional[tuple[Optional[ParamDef], str]]:
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
    close_idx = _find_matching_close(rest, idx, open_char, close_char)
    if close_idx < 0:
        return None

    args_text = rest[idx + 1:close_idx]
    after_close = rest[close_idx + 1:].strip()

    # Skip non-param markers but let caller continue parsing
    if type_name in ("sep", "separator", "note"):
        return None, after_close

    args = _split_args(args_text)

    is_hidden = type_name.endswith("_0")
    is_disabled = type_name.endswith("_1")
    type_name = re.sub(r"_[012]$", "", type_name)

    kind = _PARAM_TYPES.get(type_name)
    if kind is None:
        return None, after_close

    if type_name == "value":
        is_hidden = True

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
        is_hidden=is_hidden,
    ), after_close


def _parse_params(text: str) -> list[ParamDef]:
    results = []
    remaining = text
    while remaining:
        result = _parse_param_def(remaining)
        if result is None:
            break
        param, after_close = result
        if param is None:
            remaining = after_close
            continue
        results.append(param)
        # Check if there's another param after this one, separated by comma
        # Format: ..., param_name = type(...)
        while after_close.startswith(","):
            after_close = after_close[1:].strip()
            # Look for another "= type(" pattern
            next_eq = after_close.find("=")
            if next_eq < 0:
                remaining = after_close
                break
            # Check the next part has a type with parentheses
            next_rest = after_close[next_eq + 1:].strip()
            next_paren = next_rest.find("(")
            next_brace = next_rest.find("{")
            has_type = (next_paren >= 0 and (next_brace < 0 or next_paren < next_brace))
            if not has_type:
                remaining = after_close
                break
            remaining = after_close
            result = _parse_param_def(remaining)
            if result is None:
                break
            sub_param, after_close = result
            if sub_param is None:
                remaining = after_close
                break
            results.append(sub_param)
        else:
            remaining = after_close
    return results


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
                if not lhs.strip() and "=" in gui_buf:
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
    # Strip preview suffix: ..., preview_command(zoom)[*|+]
    m = re.search(r',\s*[a-zA-Z_]\w*(?:\([^)]*\))?\s*[*+]?\s*$', command)
    if m:
        command = command[:m.start()]
    return command.strip()


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
                        params = _parse_params(rhs)
                        for p in params:
                            current_filter.parameters.append(p)
                    except Exception:
                        pass
                continue

            # Extract multi-input flags (*, +) from the right-hand side
            image_input_count = 1
            # Format: "command, preview_command(zoom_factor) [: *|+]"
            m = re.match(r'^(.*?)\s*:\s*([*+])$', rhs)
            if m:
                rhs = m.group(1).strip()
                image_input_count = 2
            # Also handle :* or :+ without space before the flag
            elif rhs.endswith(":*") or rhs.endswith(":+") or rhs.endswith(": *") or rhs.endswith(": +"):
                for sep in [":*", ":+", ": *", ": +"]:
                    if rhs.endswith(sep):
                        rhs = rhs[:-len(sep)].strip()
                        image_input_count = 2
                        break

            display_name = _strip_name(lhs)
            if display_name in ("note", "sep", "separator"):
                continue

            command = _munge_gui_command(rhs)

            if not command or command.startswith("_"):
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
                image_input_count=image_input_count,
            )
            filters.append(current_filter)

        return filters if filters else self._builtin_filters

    def get_builtin_filters(self) -> list[FilterDef]:
        return self._builtin_filters

    def _create_builtin_filters(self) -> list[FilterDef]:
        categories = {
            _("Artistic"): [
                ("sketchbw", _("Sketch (B&W)"), "sketchbw 50,0,0,0"),
                ("fx_cpencil", _("Pencil Drawing"), "fx_cpencil 30,60,0,0,50,0,2,25"),
                ("cartoon", _("Cartoon"), "cartoon 3,10,10,1"),
                ("cl_comic", _("Comic Book"), "cl_comic"),
            ],
            _("Colors"): [
                ("sepia", _("Sepia"), "sepia"),
                ("normalize", _("Auto Levels"), "normalize 0,255"),
                ("equalize", _("Histogram Equalization"), "equalize 256"),
            ],
            _("Details"): [
                ("sharpen", _("Sharpen"), "sharpen 500"),
                ("unsharp", _("Unsharp Mask"), "unsharp 2,50,0,0,0.5,0"),
                ("blur", _("Blur"), "blur 3"),
                ("denoise", _("Denoise"), "denoise 3,10,0,6"),
            ],
            _("Deformations"): [
                ("rotate", _("Rotate"), "rotate 90"),
                ("resize", _("Resize"), "resize 50%,50%"),
                ("warp", _("Warp"), "warp 10"),
                ("mirror", _("Mirror"), "mirror x"),
            ],
            _("Light & Shadows"): [
                ("retinex", _("Retinex"), "retinex 100,2,0,200,1,5,15,80,250"),
                ("normalize_local", _("Local Normalization"), "normalize_local 10"),
            ],
            _("B&W"): [
                ("to_gray", _("Grayscale"), "to_gray"),
                ("threshold", _("Threshold"), "threshold 128"),
                ("invert", _("Invert"), "invert"),
            ],
            _("Frames"): [
                ("frame", _("Add Frame"), "frame 5,255,255,255"),
                ("polaroid", _("Polaroid"), "polaroid 10,5,0,0"),
                ("vignette", _("Vignette"), "vignette 20"),
            ],
            _("Repair"): [
                ("remove_hotpixels", _("Remove Hot Pixels"), "remove_hotpixels 3"),
            ],
            _("Rendering"): [
                ("plasma", _("Plasma"), "plasma 50"),
                ("clouds", _("Cloud"), "clouds 50"),
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
