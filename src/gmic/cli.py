import subprocess
import tempfile
import os
import shutil
import gettext
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
        input_paths: list[str],
        commands: list[str],
        output_path: Optional[str] = None,
        timeout: int = 120,
        script_command: Optional[str] = None,
        custom_commands: Optional[str] = None,
    ) -> GmicResult:
        """Run ``commands`` on ``input_paths`` and write ``output_path``.

        ``script_command`` is an alternative command line (one line, ``name
        arg,arg``) that is executed from a temporary G'MIC command file.  The
        CLI cannot represent an argument list where a text value contains a
        space (its argv parser quotes such items and swallows the commas), but
        a command file is parsed by G'MIC itself, so filters that re-interpret
        their text parameter get the value verbatim.

        ``custom_commands`` is a command file imported with ``-m`` before the
        inputs.  Community filters need it: their definitions are not part of
        the interpreter's own standard library.
        """
        if not self.available:
            return GmicResult(False, error=_("gmic not found on system. Install it with your package manager."))

        for path in input_paths:
            if not os.path.isfile(path):
                return GmicResult(False, error=_("Input file not found: {}").format(path))

        if output_path is None:
            fd, output_path = tempfile.mkstemp(suffix=".png")
            os.close(fd)

        command_file = None
        imports = ["-m", custom_commands] if custom_commands else []
        if script_command is not None:
            fd, command_file = tempfile.mkstemp(suffix=".gmic")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write("__patchwork_run :\n")
                for line in script_command.splitlines() or [script_command]:
                    handle.write("  " + line + "\n")
            args = ([self._gmic_path] + imports + ["-m", command_file] + input_paths
                    + ["-__patchwork_run", "-o", output_path])
        else:
            args = [self._gmic_path] + imports + input_paths
            for cmd in commands:
                if not cmd.strip():
                    continue
                if cmd.startswith("-"):
                    # Already an option: split it like a bare command, otherwise
                    # "-blur 3" reaches G'MIC as a single (unknown) item.
                    cmd = cmd[1:]
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

            if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
                # G'MIC appends an index when a filter returns several
                # images ('out_000000.png', ...) and the pre-created output
                # file stays empty: keep the first image.
                stem, suffix = os.path.splitext(output_path)
                first = f"{stem}_000000{suffix}"
                if os.path.isfile(first) and os.path.getsize(first) > 0:
                    os.replace(first, output_path)
                else:
                    return GmicResult(False, error=_("gmic produced no output file"), stdout=stdout, stderr=stderr)

            return GmicResult(True, output_path=output_path, stdout=stdout, stderr=stderr)

        except subprocess.TimeoutExpired:
            return GmicResult(False, error=_("Processing timed out after {} seconds").format(timeout))
        except FileNotFoundError:
            return GmicResult(False, error=_("gmic not found on system"))
        except Exception as e:
            return GmicResult(False, error=str(e))
        finally:
            if command_file is not None:
                try:
                    os.unlink(command_file)
                except OSError:
                    pass

    def list_filters(self) -> list[FilterDef]:
        main_text, community_text = fetch_or_get_cached()

        all_filters = []
        seen = set()

        for text, source in ((main_text, "main"), (community_text, "community")):
            if not text:
                continue
            for f in self._parser.parse_gui(text):
                if f.name not in seen:
                    seen.add(f.name)
                    f.source = source
                    all_filters.append(f)

        if all_filters:
            return all_filters
        builtins = self._parser.get_builtin_filters()
        for f in builtins:
            f.source = "main"
        return builtins


