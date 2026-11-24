from unittest.mock import MagicMock

from video.ffmpeg import FfmpegCLI


def make_cli():
    cli = FfmpegCLI()
    cli._ffmpeg_path = "ffmpeg"
    cli._ffprobe_path = "ffprobe"
    return cli


def make_run(returncode=0, stdout="", stderr=""):
    proc = MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)
    return MagicMock(return_value=proc), proc


def test_available_true(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda p: "/usr/bin/ffmpeg")
    assert FfmpegCLI().available is True


def test_available_false(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda p: None)
    assert FfmpegCLI().available is False


def test_probe_parses_json(monkeypatch):
    cli = make_cli()
    fake, _ = make_run(returncode=0, stdout='''{
        "streams": [{"width": 640, "height": 480, "r_frame_rate": "24/1", "nb_frames": "100"}],
        "format": {"duration": "4.166666"}
    }''')
    monkeypatch.setattr("video.ffmpeg.subprocess.run", fake)
    monkeypatch.setattr("video.ffmpeg.os.path.isfile", lambda p: True)
    monkeypatch.setattr("shutil.which", lambda p: "/usr/bin/" + p)
    info = cli.probe("/tmp/a.mp4")
    assert info["width"] == 640
    assert info["height"] == 480
    assert info["fps"] == 24.0
    assert info["frame_count"] == 100


def test_probe_frame_count_falls_back_to_duration(monkeypatch):
    cli = make_cli()
    fake, _ = make_run(returncode=0, stdout=(
        '{"streams": [{"width": 640, "height": 480, "r_frame_rate": "30/1", "nb_frames": "N/A"}],'
        ' "format": {"duration": "2.0"}}'
    ))
    monkeypatch.setattr("video.ffmpeg.subprocess.run", fake)
    monkeypatch.setattr("video.ffmpeg.os.path.isfile", lambda p: True)
    monkeypatch.setattr("shutil.which", lambda p: "/usr/bin/" + p)
    info = cli.probe("/tmp/a.mp4")
    assert info["fps"] == 30.0
    assert info["frame_count"] == 60


def test_probe_missing_file_returns_none(monkeypatch):
    cli = make_cli()
    monkeypatch.setattr("video.ffmpeg.os.path.isfile", lambda p: False)
    assert cli.probe("/tmp/nope.mp4") is None


def test_extract_frame_uses_select(monkeypatch):
    cli = make_cli()
    fake, _ = make_run(returncode=0)
    monkeypatch.setattr("video.ffmpeg.subprocess.run", fake)
    monkeypatch.setattr("video.ffmpeg.os.path.isfile", lambda p: True)
    res = cli.extract_frame("/tmp/in.mp4", 5, "/tmp/out.png")
    assert res.success is True
    args = fake.call_args.args[0]
    assert "ffmpeg" in args
    assert "select='eq(n\\,5)'" in args
    assert args[-1] == "/tmp/out.png"


def test_extract_frame_failure(monkeypatch):
    cli = make_cli()
    fake, _ = make_run(returncode=1, stderr="boom")
    monkeypatch.setattr("video.ffmpeg.subprocess.run", fake)
    monkeypatch.setattr("video.ffmpeg.os.path.isfile", lambda p: True)
    res = cli.extract_frame("/tmp/in.mp4", 0, "/tmp/out.png")
    assert res.success is False
    assert "boom" in res.error


def test_mux_mp4(monkeypatch, tmp_path):
    cli = make_cli()
    out = tmp_path / "out.mp4"
    out.write_bytes(b"fake")
    fake, _ = make_run(returncode=0)
    monkeypatch.setattr("video.ffmpeg.subprocess.run", fake)
    monkeypatch.setattr("video.ffmpeg.os.path.isfile", lambda p: p == str(out))
    res = cli.mux_mp4(str(tmp_path / "frame_%05d.png"), 12, str(out))
    assert res.success is True
    args = fake.call_args.args[0]
    assert "libx264" in args