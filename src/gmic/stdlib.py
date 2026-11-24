import json
import gettext
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional
from urllib.request import urlopen
from urllib.error import URLError

try:
    _ = gettext.gettext
except Exception:
    _ = lambda s: s

_STDLIB_RAW = "https://raw.githubusercontent.com/GreycLab/gmic"
_REPO_STDLIB_PATH = "src/gmic_stdlib.gmic"
# Fallback used when the local G'MIC version cannot be detected.
STDLIB_URL = f"{_STDLIB_RAW}/master/{_REPO_STDLIB_PATH}"

_COMMUNITY_REPO = "GreycLab/gmic-community"
_COMMUNITY_RAW = f"https://raw.githubusercontent.com/{_COMMUNITY_REPO}"
COMMUNITY_API = f"https://api.github.com/repos/{_COMMUNITY_REPO}/contents/include"
# Community filter sources pinned to the last commit before the G'MIC v.4.0.3
# tag (released 2026-07-20), i.e. the snapshot matching the interpreter Fedora
# 45 ships (gmic-4.0.3-6.fc45).  The community repository moves faster than
# G'MIC releases: filters added later declare commands the installed binary
# does not know, so this list deliberately does not track 'master'.
COMMUNITY_REF = "ea527ed510fcba0e578d33fcf884f67290810646"

CACHE_DIR = Path.home() / ".cache" / "patchwork" / "stdlib"

_VERSION_RE = re.compile(r"Version\s+(\d+\.\d+\.\d+)")


def gmic_version(gmic_path: str = "gmic") -> Optional[str]:
    """Return the version of the local G'MIC binary, e.g. ``"4.0.3"``.

    The filter list is downloaded from the G'MIC sources, so it has to come
    from the tag matching the installed binary: the ``master`` stdlib declares
    filters that only newer interpreters understand, and running those ends in
    ``Unknown command or filename``.
    """
    exe = shutil.which(gmic_path)
    if not exe:
        return None
    try:
        result = subprocess.run(
            [exe, "version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = _VERSION_RE.search((result.stdout or "") + (result.stderr or ""))
    if match:
        return match.group(1)
    return None


def stdlib_url(version: Optional[str]) -> str:
    """URL of the stdlib source matching ``version`` (``master`` if unknown)."""
    ref = f"v.{version}" if version else "master"
    return f"{_STDLIB_RAW}/{ref}/{_REPO_STDLIB_PATH}"


def stdlib_cache_path(version: Optional[str]) -> Path:
    """Cache file for the stdlib of ``version``.

    Versioned names keep a previously cached ``master`` stdlib from leaking
    into a run against an older G'MIC binary.
    """
    if version:
        return CACHE_DIR / f"gmic_stdlib_{version}.gmic"
    return CACHE_DIR / "gmic_stdlib.gmic"


def community_cache_path(ref: str = COMMUNITY_REF) -> Path:
    """Cache file for the community filter list pinned at ``ref``.

    The ref is part of the filename so the unpinned list cached by older
    versions of the app (``gmic_stdlib_community.gmic``) is never reused.
    """
    return CACHE_DIR / f"gmic_stdlib_community_{ref[:8]}.gmic"


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


def fetch_community_files(ref: str = COMMUNITY_REF) -> Optional[str]:
    """Download the community filter sources pinned at ``ref``.

    The include directory is listed for that commit and every ``.gmic`` file
    is fetched from its raw URL at the same commit, then cached under a
    ref-keyed name.  Returns ``None`` when the download fails; the caller then
    keeps an existing cache or runs with the main stdlib only.
    """
    try:
        req = urlopen(f"{COMMUNITY_API}?ref={ref}", timeout=20)
        entries = json.loads(req.read().decode())
        parts = []
        for entry in entries:
            if entry.get("type") != "file" or not entry.get("name", "").endswith(".gmic"):
                continue
            file_url = f"{_COMMUNITY_RAW}/{ref}/include/{entry['name']}"
            try:
                file_req = urlopen(file_url, timeout=20)
                parts.append(file_req.read().decode("utf-8", errors="replace"))
            except (URLError, OSError, ValueError):
                continue
        if not parts:
            return None
        result = "\n#@gui _\n".join(parts)
        _ensure_cache_dir()
        community_cache_path(ref).write_text(result, encoding="utf-8")
        return result
    except (URLError, OSError, ValueError, json.JSONDecodeError, KeyError):
        return None


def _fetch_stdlib(version: Optional[str]) -> tuple[Optional[str], Optional[Path]]:
    """Return (stdlib text, cache file) for the given G'MIC version."""
    cache_path = stdlib_cache_path(version)
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8", errors="replace"), cache_path

    attempts = [(stdlib_url(version), cache_path)]
    if version:
        # Network hiccup on the tag? The master copy still beats no filters.
        attempts.append((stdlib_url(None), stdlib_cache_path(None)))

    for url, target in attempts:
        if download_file(url, target):
            return target.read_text(encoding="utf-8", errors="replace"), target
    return None, None


def fetch_community_pinned(ref: str = COMMUNITY_REF) -> Optional[str]:
    """Return the community list for ``ref``, from cache or network.

    There is deliberately no fallback to ``master``: a newer list is exactly
    what declares filters the installed interpreter cannot run.  When the
    pinned ref cannot be downloaded and nothing is cached yet, community
    filters are simply absent and the main stdlib still works.
    """
    cache_path = community_cache_path(ref)
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8", errors="replace")
    return fetch_community_files(ref)


def fetch_or_get_cached() -> tuple[Optional[str], Optional[str]]:
    _ensure_cache_dir()

    main_text, _ = _fetch_stdlib(gmic_version())
    community_text = fetch_community_pinned()

    return main_text, community_text
