import os
import json
import gettext
from pathlib import Path
from typing import Optional
from urllib.request import urlopen
from urllib.error import URLError

try:
    _ = gettext.gettext
except Exception:
    _ = lambda s: s

STDLIB_URL = "https://raw.githubusercontent.com/GreycLab/gmic/master/src/gmic_stdlib.gmic"
COMMUNITY_BASE = "https://raw.githubusercontent.com/GreycLab/gmic-community/master/include"
COMMUNITY_API = "https://api.github.com/repos/GreycLab/gmic-community/contents/include"
CACHE_DIR = Path.home() / ".cache" / "ring" / "stdlib"
CACHE_MAIN = CACHE_DIR / "gmic_stdlib.gmic"
CACHE_COMMUNITY = CACHE_DIR / "gmic_stdlib_community.gmic"


def _ensure_cache_dir():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def download_file(url: str, dest: Path) -> bool:
    try:
        req = urlopen(url, timeout=30)
        data = req.read()
        dest.write_bytes(data)
        return True
    except (URLError, OSError, ValueError):
        return False


def fetch_community_files() -> Optional[str]:
    try:
        req = urlopen(COMMUNITY_API, timeout=15)
        entries = json.loads(req.read().decode())
        parts = []
        for entry in entries:
            if entry["type"] == "file" and entry["name"].endswith(".gmic"):
                file_url = entry["download_url"]
                file_req = urlopen(file_url, timeout=30)
                parts.append(file_req.read().decode("utf-8", errors="replace"))
        result = "\n".join(parts)
        CACHE_COMMUNITY.write_text(result, encoding="utf-8")
        return result
    except (URLError, OSError, ValueError, json.JSONDecodeError):
        return None


def fetch_or_get_cached() -> tuple[Optional[str], Optional[str]]:
    _ensure_cache_dir()

    main_text = None
    community_text = None

    if CACHE_MAIN.exists():
        main_text = CACHE_MAIN.read_text(encoding="utf-8", errors="replace")
    else:
        if download_file(STDLIB_URL, CACHE_MAIN):
            main_text = CACHE_MAIN.read_text(encoding="utf-8", errors="replace")

    if CACHE_COMMUNITY.exists():
        community_text = CACHE_COMMUNITY.read_text(encoding="utf-8", errors="replace")
    else:
        community_text = fetch_community_files()

    return main_text, community_text
