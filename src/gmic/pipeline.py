from typing import Optional
from models.filter import ParamDef, ParamValue, ParamKind


def _gmic_escape(s: str) -> str:
    """Escape a text parameter value for the G'MIC command line.

    G'MIC keeps each command line argument as a single item, so spaces need no
    escaping, but commas split arguments, double quotes start a quoted string
    and a backslash escapes the following character.  The ``\\,`` escape is
    used for commas rather than ``\\054``: the octal form only survives the
    argument parsing itself, while the backslash form also survives a value
    that a filter re-interprets as a command (e.g. through ``$1``).
    """
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace(",", "\\,")
        .replace("\n", "\\012")
        .replace("\r", "\\015")
        .replace("\t", "\\011")
    )


def _serialize_param(val: ParamValue, param_def: Optional[ParamDef] = None) -> str:
    if val is None or val == "":
        if param_def is not None and param_def.default is not None and param_def.default != "":
            return _serialize_param(param_def.default, param_def)
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
    result = str(val)
    if param_def is not None and param_def.kind == ParamKind.TEXT:
        return _gmic_escape(result)
    return result.strip()
