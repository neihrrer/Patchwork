from typing import Optional
from models.filter import ParamDef, ParamValue, ParamKind


def _gmic_escape(s: str) -> str:
    """Escape a text parameter value for the G'MIC command line.

    The CLI wraps every argument containing a space in double quotes, which
    turns the whole comma-separated argument list into a single value, so
    spaces are encoded as the octal literal \\040.  Commas are escaped with a
    backslash: inside one argument list they separate values, so a comma that
    belongs to a text value must be protected.  Double quotes and backslashes
    escape the same way.
    """
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace(" ", "\\040")
        .replace(",", "\\,")
        .replace("\n", "\\012")
        .replace("\r", "\\015")
        .replace("\t", "\\011")
    )


def _gmic_script_escape(s: str) -> str:
    """Escape a text parameter value for a line of a G'MIC command file.

    Command files are parsed by G'MIC itself instead of the shell CLI, so
    double quotes protect ``$``, ``{``, commas and spaces and the value reads
    back verbatim (this is what filters that re-interpret a parameter, such as
    "run this code", need).  Only backslashes, quotes, line breaks and ``#``
    need an escape: a comment marker after a blank would otherwise end the
    line even inside the quotes.
    """
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\012")
        .replace("\r", "\\015")
        .replace("\t", "\\011")
        .replace("#", "\\#")
    )


def _serialize_param(val: ParamValue, param_def: Optional[ParamDef] = None,
                     style: str = "cli") -> str:
    if val is None or val == "":
        if param_def is not None and param_def.default is not None and param_def.default != "":
            return _serialize_param(param_def.default, param_def, style)
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
        if style == "script":
            return '"' + _gmic_script_escape(result) + '"'
        # Quotes keep '$', ',' and spaces literal; the octals keep the whole
        # argument list free of raw spaces so G'MIC still splits it.
        return '"' + _gmic_escape(result) + '"'
    return result.strip()
