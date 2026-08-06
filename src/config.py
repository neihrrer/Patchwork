import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "patchwork"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULTS = {
    "processing_timeout": 60,
    "snap_to_grid": False,
    "auto_save_interval": 0,
    "grid_visible": True,
    "extended_zoom": False,
    "minimap_visible": False,
}


class AppConfig:
    def __init__(self, path: str | None = None):
        self._path = Path(path) if path else CONFIG_PATH
        self._data = dict(DEFAULTS)
        self.load()

    def load(self):
        try:
            if self._path.exists():
                with open(self._path) as f:
                    stored = json.load(f)
                self._data = {**DEFAULTS, **stored}
        except (json.JSONDecodeError, OSError):
            self._data = dict(DEFAULTS)

    def save(self):
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w") as f:
                json.dump(self._data, f, indent=2)
        except OSError:
            pass

    def __getattr__(self, name):
        if name.startswith("_"):
            return super().__getattribute__(name)
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        if name.startswith("_"):
            super().__setattr__(name, value)
        else:
            self._data[name] = value
            self.save()
