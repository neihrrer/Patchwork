from typing import Optional
from models.filter import ParamDef, ParamValue, ParamKind


def _serialize_param(val: ParamValue, param_def: Optional[ParamDef] = None) -> str:
    if val is None or val == "":
        if param_def is not None and param_def.default is not None and param_def.default != "":
            return _serialize_param(param_def.default)
        return "0"
    if isinstance(val, bool):
        return "1" if val else "0"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, list):
        return ",".join(str(v) for v in val)
    result = str(val).strip()
    if param_def is not None and param_def.kind == ParamKind.TEXT:
        result = f'"{result}"'
    return result
