from typing import Optional
from models.filter import FilterDef, ParamDef, ParamValue


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
    return str(val)


class PipelineBuilder:
    def __init__(self):
        self.input_path: Optional[str] = None
        self.filter: Optional[FilterDef] = None
        self.params: dict[str, ParamValue] = {}
        self.output_path: Optional[str] = None

    def build_command(self) -> list[str]:
        if not self.input_path or not self.filter:
            return []

        command_parts = [self.filter.gmic_command]
        for p in self.filter.parameters:
            val = self.params.get(p.name, p.default)
            command_parts[-1] += f",{_serialize_param(val, p)}"

        return command_parts

    def build_args(self) -> list[str]:
        args = [self.input_path]
        args.extend(self.build_command())
        if self.output_path:
            args.extend(["-o", self.output_path])
        return args
