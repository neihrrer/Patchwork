import os
import shutil
import subprocess
from unittest.mock import patch

import pytest
from PIL import Image


def _fake_completed(args, **kwargs):
    return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")


class TestRunPipelineArguments:
    def test_plain_command_with_arguments_is_split(self):
        from gmic.cli import GmicCLI
        with patch("shutil.which", return_value="/usr/bin/gmic"), \
                patch("subprocess.run", side_effect=_fake_completed) as run, \
                patch("os.path.isfile", return_value=True), \
                patch("os.path.getsize", return_value=42):
            GmicCLI().run_pipeline(["/in.png"], ["blur 3"], "/out.png")
        args = run.call_args[0][0]
        assert args == ["/usr/bin/gmic", "/in.png", "-blur", "3", "-o", "/out.png"]

    def test_dash_prefixed_command_with_arguments_is_split(self):
        # "-blur 3" used to be handed to G'MIC as one item, so G'MIC reported
        # "Unknown command or filename '-blur 3'".
        from gmic.cli import GmicCLI
        with patch("shutil.which", return_value="/usr/bin/gmic"), \
                patch("subprocess.run", side_effect=_fake_completed) as run, \
                patch("os.path.isfile", return_value=True), \
                patch("os.path.getsize", return_value=42):
            GmicCLI().run_pipeline(["/in.png"], ["-blur 3"], "/out.png")
        args = run.call_args[0][0]
        assert args == ["/usr/bin/gmic", "/in.png", "-blur", "3", "-o", "/out.png"]

    @pytest.mark.skipif(shutil.which("gmic") is None, reason="gmic not installed")
    def test_dash_prefixed_command_runs(self, tmp_path):
        from gmic.cli import GmicCLI
        source = tmp_path / "in.png"
        Image.new("RGB", (64, 64), (10, 20, 30)).save(str(source))
        target = tmp_path / "out.png"
        result = GmicCLI().run_pipeline([str(source)], ["-blur 3"], str(target))
        assert result.success, result.error
        assert target.stat().st_size > 0


class TestScriptCommandRoute:
    """Commands with space-containing text values run from a command file."""

    def test_uses_a_temporary_command_file(self, tmp_path):
        from gmic.cli import GmicCLI
        source = tmp_path / "in.png"
        Image.new("RGB", (8, 8), (0, 0, 0)).save(str(source))
        target = tmp_path / "out.png"
        target.write_bytes(b"png")
        captured = {}

        def fake_run(args, **kwargs):
            captured["args"] = list(args)
            captured["path"] = args[2]
            with open(args[2], encoding="utf-8") as handle:
                captured["content"] = handle.read()
            return subprocess.CompletedProcess(args, 0, "", "")

        with patch("shutil.which", return_value="/usr/bin/gmic"), \
                patch("subprocess.run", side_effect=fake_run):
            result = GmicCLI().run_pipeline(
                [str(source)], ["unused"], str(target),
                script_command='iain_fast_formula "apply_gamma 2.2"')

        assert result.success, result.error
        assert captured["args"][:2] == ["/usr/bin/gmic", "-m"]
        assert captured["args"][2] == captured["path"]
        assert captured["args"][3:] == [str(source), "-__patchwork_run",
                                        "-o", str(target)]
        assert captured["content"] == ('__patchwork_run :\n'
                                       '  iain_fast_formula "apply_gamma 2.2"\n')
        assert not os.path.exists(captured["path"])

    def test_command_file_is_removed_on_failure(self, tmp_path):
        from gmic.cli import GmicCLI
        source = tmp_path / "in.png"
        Image.new("RGB", (8, 8), (0, 0, 0)).save(str(source))
        captured = {}

        def failing_run(args, **kwargs):
            captured["path"] = args[2]
            return subprocess.CompletedProcess(args, 1, "", "boom")

        with patch("shutil.which", return_value="/usr/bin/gmic"), \
                patch("subprocess.run", side_effect=failing_run):
            result = GmicCLI().run_pipeline(
                [str(source)], [], str(tmp_path / "out.png"),
                script_command="blur 3")

        assert result.success is False
        assert "boom" in result.error
        assert not os.path.exists(captured["path"])


class TestRunPipelineOutput:
    def test_numbered_output_is_promoted_when_output_file_is_empty(self, tmp_path):
        # G'MIC numbers outputs when a filter returns several images; the
        # pre-created output file stays empty and used to be returned as is.
        from gmic.cli import GmicCLI
        source = tmp_path / "in.png"
        Image.new("RGB", (8, 8), (0, 0, 0)).save(str(source))
        target = tmp_path / "out.png"
        target.write_bytes(b"")
        (tmp_path / "out_000000.png").write_bytes(b"first-image")
        (tmp_path / "out_000001.png").write_bytes(b"second-image")

        with patch("shutil.which", return_value="/usr/bin/gmic"), \
                patch("subprocess.run", side_effect=_fake_completed):
            result = GmicCLI().run_pipeline([str(source)], ["blur 3"], str(target))

        assert result.success, result.error
        assert target.read_bytes() == b"first-image"

    def test_missing_output_is_an_error(self, tmp_path):
        from gmic.cli import GmicCLI
        source = tmp_path / "in.png"
        Image.new("RGB", (8, 8), (0, 0, 0)).save(str(source))
        target = tmp_path / "out.png"
        target.write_bytes(b"")

        with patch("shutil.which", return_value="/usr/bin/gmic"), \
                patch("subprocess.run", side_effect=_fake_completed):
            result = GmicCLI().run_pipeline([str(source)], ["blur 3"], str(target))

        assert result.success is False
        assert "no output" in result.error.lower()


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
