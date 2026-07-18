from processing.runner import ProcessResult


class TestProcessResult:
    def test_success_from_output_path(self):
        r = ProcessResult(output_path="/tmp/out.png", error="", stdout="", stderr="")
        assert r.success is True
        assert r.output_path == "/tmp/out.png"

    def test_success_from_output_paths(self):
        r = ProcessResult(output_path=None, error="", stdout="", stderr="",
                          output_paths={"n1": "/tmp/n1.png"})
        assert r.success is True

    def test_failure_no_output(self):
        r = ProcessResult(output_path=None, error="failed", stdout="", stderr="")
        assert r.success is False

    def test_failure_empty_paths(self):
        r = ProcessResult(output_path=None, error="", stdout="", stderr="",
                          output_paths={})
        assert r.success is False

    def test_verbose_output(self):
        r = ProcessResult(output_path="/tmp/o.png", error="", stdout="hello\n",
                          stderr="world\n")
        assert "hello" in r.verbose_output
        assert "world" in r.verbose_output

    def test_default_output_paths(self):
        r = ProcessResult(output_path="/tmp/o.png", error="", stdout="", stderr="")
        assert r.output_paths == {}

    def test_defaults_none(self):
        r = ProcessResult(output_path="/tmp/o.png", error="", stdout="", stderr="")
        assert r.error == ""
        assert r.stdout == ""
        assert r.stderr == ""
