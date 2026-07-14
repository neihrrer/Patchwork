from typing import Optional

from models.filter import FilterDef, ParamValue
from gmic.pipeline import _serialize_param


VALID_OUTPUT_FORMATS = ["png", "jpeg", "tiff", "bmp", "webp"]


class AppState:
    def __init__(self):
        self.input_path: Optional[str] = None
        self.current_image_path: Optional[str] = None
        self.original_pixbuf = None
        self.selected_filter: Optional[FilterDef] = None
        self.filter_params: dict[str, ParamValue] = {}
        self.output_format: str = "png"

    def build_pipeline(self) -> list[str]:
        if not self.current_image_path or not self.selected_filter:
            return []

        cmd = [self.current_image_path, self.selected_filter.gmic_command]
        for p in self.selected_filter.parameters:
            val = self.filter_params.get(p.name, p.default)
            cmd[-1] += f",{_serialize_param(val, p)}"

        return cmd
