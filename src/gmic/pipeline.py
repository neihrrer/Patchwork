from typing import Optional
from models.filter import ParamDef, ParamValue, ParamKind


def _gmic_escape(s: str) -> str:
    """Escape characters gmic's CLI tokenizer would split or break on.

    gmic splits argument tokens on whitespace even inside double quotes, so
    spaces must be encoded as the octal literal \\040. Embedded double quotes
    (\\042) and backslashes (\\134) are escaped the same way.
    """
    return (
        s.replace("\\", "\\134")
        .replace('"', "\\042")
        .replace(" ", "\\040")
    )


def _serialize_param(val: ParamValue, param_def: Optional[ParamDef] = None) -> str:
    if val is None or val == "":
        if param_def is not None and param_def.default is not None and param_def.default != "":
            return _serialize_param(param_def.default)
        return "0"
    if isinstance(val, bool):
        return "1" if val else "0"
    if isinstance(val, (int, float)):
        if param_def is not None and param_def.min_val is not None:
            val = max(val, param_def.min_val)
        if param_def is not None and param_def.max_val is not None:
            val = min(val, param_def.max_val)
        return str(val)
    if isinstance(val, list):
        return ",".join(str(v) for v in val)
    result = str(val).strip()
    if param_def is not None and param_def.kind == ParamKind.TEXT:
        result = _gmic_escape(result)
        return f'"{result}"'
    return result
