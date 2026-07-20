import subprocess
from unittest.mock import patch

import pytest


class TestGmicResult:
    def test_construction(self):
        from gmic.cli import GmicResult
        r = GmicResult(success=True, output_path="/tmp/out.png", error="",
                        stdout="done", stderr="")
        assert r.success is True
        assert r.output_path == "/tmp/out.png"
        assert r.error == ""
        assert r.stdout == "done"

    def test_error_result(self):
        from gmic.cli import GmicResult
        r = GmicResult(success=False, output_path=None, error="gmic not found")
        assert r.success is False
        assert r.output_path is None


class TestGmicCLI:
    def test_available_when_gmic_on_path(self):
        from gmic.cli import GmicCLI
        with patch("shutil.which", return_value="/usr/bin/gmic"):
            cli = GmicCLI()
            assert cli.available is True

    def test_not_available_when_gmic_missing(self):
        from gmic.cli import GmicCLI
        with patch("shutil.which", return_value=None):
            cli = GmicCLI()
            assert cli.available is False

    def test_run_pipeline_raises_when_not_available(self):
        from gmic.cli import GmicCLI
        with patch("shutil.which", return_value=None):
            cli = GmicCLI()
            result = cli.run_pipeline(["/in.png"], [""], "/out.png")
            assert result.success is False
            assert "not found" in (result.error or "").lower()

    def test_run_pipeline_input_not_found(self):
        from gmic.cli import GmicCLI
        with patch("shutil.which", return_value="/usr/bin/gmic"):
            cli = GmicCLI()
            result = cli.run_pipeline(["/nonexistent.png"], [""], "/out.png")
            assert result.success is False

    def test_subprocess_timeout(self):
        from gmic.cli import GmicCLI
        with patch("shutil.which", return_value="/usr/bin/gmic"):
            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 10)):
                with patch("os.path.isfile", return_value=True):
                    cli = GmicCLI()
                    result = cli.run_pipeline(["/in.png"], [""], "/out.png")
                    assert result.success is False

    def test_subprocess_file_not_found(self):
        from gmic.cli import GmicCLI
        with patch("shutil.which", return_value="/usr/bin/gmic"):
            with patch("subprocess.run", side_effect=FileNotFoundError):
                with patch("os.path.isfile", return_value=True):
                    cli = GmicCLI()
                    result = cli.run_pipeline(["/in.png"], [""], "/out.png")
                    assert result.success is False

    def test_list_filters_without_gmic(self):
        from gmic.cli import GmicCLI
        with patch("shutil.which", return_value=None):
            cli = GmicCLI()
            with patch("gmic.cli.fetch_or_get_cached", return_value=("", "")):
                with patch.object(cli._parser, "get_builtin_filters", return_value=[]):
                    filters = cli.list_filters()
                    assert filters == []
