import subprocess
import tempfile
import os
import shutil
import gettext
from pathlib import Path
from typing import Optional

from models.filter import FilterDef
from gmic.parser import GmicFilterParser
from gmic.stdlib import fetch_or_get_cached

try:
    _ = gettext.gettext
except Exception:
    _ = lambda s: s


class GmicResult:
    def __init__(self, success: bool, output_path: Optional[str] = None, error: str = "", stdout: str = "", stderr: str = ""):
        self.success = success
        self.output_path = output_path
        self.error = error
        self.stdout = stdout
        self.stderr = stderr


class GmicCLI:
    def __init__(self, gmic_path: str = "gmic"):
        resolved = shutil.which(gmic_path)
        self._gmic_path = resolved or gmic_path
        self._parser = GmicFilterParser()

    @property
    def available(self) -> bool:
        return shutil.which(self._gmic_path) is not None

    def run_pipeline(
        self,
        input_path: str,
        commands: list[str],
        output_path: Optional[str] = None,
        timeout: int = 120,
    ) -> GmicResult:
        if not self.available:
            return GmicResult(False, error=_("gmic not found on system. Install it with your package manager."))

        if not os.path.isfile(input_path):
            return GmicResult(False, error=_("Input file not found: {}").format(input_path))

        if output_path is None:
            fd, output_path = tempfile.mkstemp(suffix=".png")
            os.close(fd)

        args = [self._gmic_path, input_path]
        for cmd in commands:
            if not cmd.strip():
                continue
            if cmd.startswith("-"):
                args.append(cmd)
                continue
            comma_idx = cmd.find(",")
            space_idx = cmd.find(" ")
            comma_first = comma_idx >= 0 and (space_idx < 0 or comma_idx < space_idx)
            if comma_first:
                args.append("-" + cmd[:comma_idx])
                args.append(cmd[comma_idx + 1:])
            elif space_idx >= 0:
                args.append("-" + cmd[:space_idx])
                args.append(cmd[space_idx + 1:])
            else:
                args.append("-" + cmd)
        args.extend(["-o", output_path])

        try:
            result = subprocess.run(
                args,
                capture_output=True,
                timeout=timeout,
                text=True,
            )
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            if result.returncode != 0:
                err_msg = stderr.strip() or _("Unknown error")
                return GmicResult(False, error=err_msg, stdout=stdout, stderr=stderr)

            if not os.path.isfile(output_path):
                return GmicResult(False, error=_("gmic produced no output file"), stdout=stdout, stderr=stderr)

            return GmicResult(True, output_path=output_path, stdout=stdout, stderr=stderr)

        except subprocess.TimeoutExpired:
            return GmicResult(False, error=_("Processing timed out after {} seconds").format(timeout))
        except FileNotFoundError:
            return GmicResult(False, error=_("gmic not found on system"))
        except Exception as e:
            return GmicResult(False, error=str(e))

    def list_filters(self) -> list[FilterDef]:
        main_text, community_text = fetch_or_get_cached()

        all_filters = []
        seen = set()

        for text in (main_text, community_text):
            if text:
                gui_filters = self._parser.parse_gui(text)
                for f in gui_filters:
                    if f.name not in seen:
                        seen.add(f.name)
                        all_filters.append(f)

        if all_filters:
            return all_filters

        try:
            result = subprocess.run(
                [self._gmic_path, "-help"],
                capture_output=True,
                timeout=30,
                text=True,
            )
            if result.returncode == 0:
                filters = self._parser.parse_help(result.stdout)
                if filters:
                    return filters
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        try:
            result = subprocess.run(
                [self._gmic_path, "-h"],
                capture_output=True,
                timeout=30,
                text=True,
            )
            if result.returncode == 0:
                filters = self._parser.parse_help(result.stdout)
                if filters:
                    return filters
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        return self._parser.get_builtin_filters()

    def get_version(self) -> str:
        try:
            result = subprocess.run(
                [self._gmic_path, "--version"],
                capture_output=True,
                timeout=10,
                text=True,
            )
            if result.returncode == 0:
                return result.stdout.strip() or result.stderr.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return _("Unknown")
