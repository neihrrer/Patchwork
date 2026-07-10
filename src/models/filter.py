from typing import Any, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gio", "2.0")

from gi.repository import GObject, Gio


class ParamKind:
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    CHOICE = "choice"
    COLOR = "color"
    POINT = "point"
    TEXT = "text"
    FILE = "file"
    FOLDER = "folder"


ParamValue = Any


class ParamDef:
    def __init__(
        self,
        name: str,
        label: str,
        kind: str = ParamKind.FLOAT,
        default: ParamValue = None,
        min_val: Optional[float] = None,
        max_val: Optional[float] = None,
        choices: Optional[list[str]] = None,
        no_preview: bool = False,
        randomizable: bool = False,
        is_hidden: bool = False,
        is_disabled: bool = False,
    ):
        self.name = name
        self.label = label
        self.kind = kind
        self.default = default
        self.min_val = min_val
        self.max_val = max_val
        self.choices = choices or []
        self.no_preview = no_preview
        self.randomizable = randomizable
        self.is_hidden = is_hidden
        self.is_disabled = is_disabled

    def __repr__(self):
        return f"ParamDef({self.name}, {self.kind}, default={self.default})"


ENGINE_GMIC = "gmic"
ENGINE_IMAGEMAGICK = "imagemagick"


class FilterDef(GObject.Object):
    __gtype_name__ = "FilterDef"

    def __init__(
        self,
        name: str = "",
        display_name: str = "",
        category: Optional[list[str]] = None,
        description: str = "",
        parameters: Optional[list[ParamDef]] = None,
        gmic_command: str = "",
        engine: str = ENGINE_GMIC,
    ):
        super().__init__()
        self._name = name
        self._display_name = display_name
        self._category = category or []
        self._description = description
        self._parameters = parameters or []
        self._gmic_command = gmic_command or name
        self._engine = engine

    @GObject.Property(type=str)
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str):
        self._name = value

    @GObject.Property(type=str)
    def display_name(self) -> str:
        return self._display_name

    @display_name.setter
    def display_name(self, value: str):
        self._display_name = value

    @GObject.Property(type=str)
    def description(self) -> str:
        return self._description

    @description.setter
    def description(self, value: str):
        self._description = value

    @GObject.Property(type=str)
    def gmic_command(self) -> str:
        return self._gmic_command

    @gmic_command.setter
    def gmic_command(self, value: str):
        self._gmic_command = value

    @property
    def category(self) -> list[str]:
        return self._category

    @category.setter
    def category(self, value: list[str]):
        self._category = value

    @property
    def parameters(self) -> list[ParamDef]:
        return self._parameters

    @parameters.setter
    def parameters(self, value: list[ParamDef]):
        self._parameters = value

    @property
    def engine(self) -> str:
        return self._engine

    @engine.setter
    def engine(self, value: str):
        self._engine = value

    def __repr__(self):
        return f"FilterDef({self._name}, engine={self._engine}, cat={self._category})"
