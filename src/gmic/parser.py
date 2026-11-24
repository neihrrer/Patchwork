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
        # Quoted arguments are literals: a quoted "None" is the text 'None'
        # (e.g. a choice label), not the G'MIC 'None' keyword.
        return value_text[1:-1]
    if value_text.startswith("'") and value_text.endswith("'"):
        return value_text[1:-1]
    try:
        if "." in value_text:
            return float(value_text)
        return int(value_text)
    except (ValueError, TypeError):
        return value_text


_PARAM_TYPE_PREFIXES = (
    ("int", ParamKind.INT),
    ("float", ParamKind.FLOAT),
    ("bool", ParamKind.BOOL),
    ("button", ParamKind.BOOL),
    ("choice", ParamKind.CHOICE),
    ("color", ParamKind.COLOR),
    ("point", ParamKind.POINT),
    ("text", ParamKind.TEXT),
    ("value", ParamKind.TEXT),
    # Also matches the 'filein' and 'fileout' spellings.
    ("file", ParamKind.FILE),
    ("folder", ParamKind.FOLDER),
)

_NON_PARAM_TYPES = ("sep", "separator", "note", "link")


def _param_kind(type_name: str) -> Optional[str]:
    """Map a 'typedef' name to a parameter kind (G'MIC-Qt matches prefixes)."""
    for prefix, kind in _PARAM_TYPE_PREFIXES:
        if type_name.startswith(prefix):
            return kind
    return None


_TEXT_ESCAPES = {
    "a": "\a", "b": "\b", "e": "\x1b", "f": "\f", "n": "\n",
    "r": "\r", "t": "\t", "v": "\v",
    "\\": "\\", "'": "'", '"': '"', "?": "?",
}

_OCTAL_DIGITS = "01234567"
_HEX_DIGITS = "0123456789abcdefABCDEF"


def _unescape_text(text: str) -> str:
    """Decode escape sequences in a text parameter default.

    Mirrors ``cimg::strunescape``, which G'MIC-Qt applies to text, value, file
    and folder parameters: a default written as ``line1\\nline2`` holds two
    lines, and ``\\\\`` is a single backslash.
    """
    result = []
    index = 0
    while index < len(text):
        char = text[index]
        if char != "\\" or index + 1 >= len(text):
            result.append(char)
            index += 1
            continue
        nxt = text[index + 1]
        if nxt in _TEXT_ESCAPES:
            result.append(_TEXT_ESCAPES[nxt])
            index += 2
        elif nxt in _OCTAL_DIGITS:
            end = index + 1
            while end < len(text) and end - (index + 1) < 3 and text[end] in _OCTAL_DIGITS:
                end += 1
            result.append(chr(int(text[index + 1:end], 8) & 0xFF))
            index = end
        elif nxt == "x" and index + 2 < len(text) and text[index + 2] in _HEX_DIGITS:
            end = index + 2
            while end < len(text) and end - (index + 2) < 2 and text[end] in _HEX_DIGITS:
                end += 1
            result.append(chr(int(text[index + 2:end], 16)))
            index = end
        else:
            result.append(nxt)
            index += 2
    return "".join(result)


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
    if type_name in _NON_PARAM_TYPES:
        return None, after_close

    args = _split_args(args_text)

    is_hidden = type_name.endswith("_0")
    is_disabled = type_name.endswith("_1")
    type_name = re.sub(r"_[012]$", "", type_name)

    # Also check for suffix after closing brace (e.g. choice{...}_0)
    _sm = re.match(r"^_([012])\b", after_close)
    if _sm:
        is_hidden = is_hidden or _sm.group(1) == "0"
        is_disabled = is_disabled or _sm.group(1) == "1"
        after_close = after_close[_sm.end():].strip()

    kind = _param_kind(type_name)
    if kind is None:
        return None, after_close

    if type_name == "value":
        is_hidden = True

    default = None
    min_val = None
    max_val = None
    choices = []

    if kind == ParamKind.BOOL:
        if type_name == "button":
            # A button passes 0 until it is pressed; its argument is only
            # the widget alignment.
            default = False
        elif args:
            val = _parse_param_value(args[0])
            if val is None:
                default = False
            elif isinstance(val, str):
                default = val.lower() not in ("0", "false", "none", "")
            else:
                default = bool(int(val))
        else:
            default = False

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
        if args:
            first = _parse_param_value(args[0])
            if isinstance(first, str):
                # A quoted first argument is the default choice *label* and is
                # also listed as the first choice (see 'choice("X","Y","XY")'
                # in the G'MIC plug-in documentation).
                choices.append(first)
                for a in args[1:]:
                    v = _parse_param_value(a)
                    choices.append(str(v) if v is not None else "")
                default = choices.index(first)
            else:
                for a in args[1:]:
                    v = _parse_param_value(a)
                    choices.append(str(v) if v is not None else "")
                default = int(first) if first is not None else 0
        if default is not None and choices:
            default = max(0, min(default, len(choices) - 1))

    elif kind == ParamKind.COLOR:
        vals = []
        for a in args:
            v = _parse_param_value(a)
            if v is not None:
                vals.append(v)
        default = vals if vals else [0, 0, 0, 255]

    elif kind == ParamKind.POINT:
        # Only the first two arguments are the point value; the optional
        # removable/burst/color/radius arguments configure the widget.
        vals = []
        for a in args[:2]:
            v = _parse_param_value(a)
            if v is not None:
                vals.append(v)
        default = vals if vals else [0, 0]

    elif kind == ParamKind.TEXT:
        if type_name == "value" and args_text.strip():
            # 'value(25,25)' is passed as a single (quoted) argument; G'MIC
            # commands commonly bind it to several variables at once.
            v = _parse_param_value(args_text.strip())
            if isinstance(v, str):
                default = _unescape_text(v)
            else:
                default = str(v) if v is not None else ""
        elif args:
            v = _parse_param_value(args[-1])
            default = _unescape_text(str(v)) if v is not None else ""
        else:
            default = ""

    elif kind in (ParamKind.FILE, ParamKind.FOLDER):
        if args:
            v = _parse_param_value(args[0])
            default = _unescape_text(str(v)) if v is not None else ""

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


def _skip_separator(text: str) -> str:
    """Drop a leading parameter separator (', ' between definitions)."""
    text = text.lstrip()
    if text.startswith(","):
        text = text[1:].lstrip()
    return text


def _parse_params(text: str) -> list[ParamDef]:
    results = []
    remaining = text
    while remaining:
        result = _parse_param_def(remaining)
        if result is None:
            break
        param, after_close = result
        if param is None:
            # A separator/note/link widget: continue with the next parameter
            # on the same line, without its leading comma.
            remaining = _skip_separator(after_close)
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


def _gui_param_incomplete(line: str) -> bool:
    """Tell whether a ``#@gui :`` parameter line ends inside brackets/quotes.

    Such a line is continued on the following ``#@gui`` line (long choice
    lists, multi-line text defaults) without a trailing backslash.
    """
    content = line.strip()[5:].strip()
    if not content.startswith(":"):
        return False
    text = content[1:]
    eq_idx = text.find("=")
    if eq_idx < 0:
        return False
    depth = 0
    in_quote = False
    escaped = False
    for ch in text[eq_idx + 1:]:
        if escaped:
            escaped = False
        elif ch == "\\":
            escaped = True
        elif in_quote:
            if ch == '"':
                in_quote = False
        elif ch == '"':
            in_quote = True
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
    return depth > 0 or in_quote


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
            is_param = content.startswith(":")
            if gui_buf and is_param and _gui_param_incomplete(gui_buf):
                gui_buf += " " + content[1:].strip()
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
    m = re.search(r',\s*[a-zA-Z_]\w*\s*(?:\([^)]*\))?\s*[*+]?\s*$', command)
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

            if not content:
                current_filter = None
                continue

            if ":" not in content:
                # A folder name may be prefixed by N underscores, meaning
                # "go up N levels" before entering the folder itself.
                levelup = len(content) - len(content.lstrip("_"))
                folder_name = _strip_name(content[levelup:])
                for _ in range(levelup):
                    if folder_stack:
                        folder_stack.pop()
                if folder_name:
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

            # Extract the input mode from the right-hand side.  The mode is one
            # of {x: none, .: active, *: all, +: active & below, -: active &
            # above, v: all visible, i: all invisible}; '*' and '+' mean the
            # filter wants every layer.
            image_input_count = 1
            # Format: "command, preview_command(zoom_factor) [: <mode>]"
            m = re.match(r"^(.*?)\s*:\s*([x.*+\-vi])$", rhs)
            if m:
                rhs = m.group(1).strip()
                if m.group(2) in "*+":
                    image_input_count = 2

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
                ("fx_cpencil", _("Pencil Drawing"), "fx_cpencil 1.3,50,20,2,2,1,0"),
                ("cartoon", _("Cartoon"), "cartoon 3,10,10,1"),
                ("cl_comic", _("Comic Book"), "cl_comic 0,2,0,1,1,15,15,1,10,20,6,2,0,0,0,0,0"),
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
                ("deform", _("Deform"), "deform 10"),
                ("mirror", _("Mirror"), "mirror x"),
            ],
            _("Light & Shadows"): [
                ("retinex", _("Retinex"), "retinex 100,hsv,0,1,15,80,250"),
                ("normalize_local", _("Local Normalization"), "normalize_local 10"),
            ],
            _("B&W"): [
                ("to_gray", _("Grayscale"), "to_gray"),
                ("threshold", _("Threshold"), "threshold 128"),
                ("negate", _("Invert"), "negate"),
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
