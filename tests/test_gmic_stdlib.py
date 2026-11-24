from unittest.mock import patch, MagicMock
from urllib.error import URLError


class TestStdlibEnsureCacheDir:
    def test_creates_directory(self, tmp_path):
        from gmic.stdlib import _ensure_cache_dir
        test_dir = tmp_path / "stdlib"
        with patch("gmic.stdlib.CACHE_DIR", test_dir):
            _ensure_cache_dir()
            assert test_dir.exists()


class TestStdlibDownloadFile:
    def test_download_success(self, tmp_path):
        from gmic.stdlib import download_file
        dest = tmp_path / "test.txt"
        mock_response = MagicMock()
        mock_response.read.return_value = b"test content"
        mock_response.__enter__.return_value = mock_response
        with patch("gmic.stdlib.urlopen", return_value=mock_response):
            result = download_file("http://example.com/test.txt", dest)
            assert result is True
            assert dest.read_text() == "test content"

    def test_download_failure(self, tmp_path):
        from urllib.error import URLError
        from gmic.stdlib import download_file
        dest = tmp_path / "test.txt"
        with patch("gmic.stdlib.urlopen", side_effect=URLError("network error")):
            result = download_file("http://example.com/test.txt", dest)
            assert result is False


class TestGmicVersion:
    def test_parses_version_from_output(self):
        from gmic.stdlib import gmic_version
        completed = MagicMock()
        completed.stdout = "gmic: GREYC's Magic for Image Computing\n  Version 4.0.3\n"
        completed.stderr = ""
        with patch("gmic.stdlib.shutil.which", return_value="/usr/bin/gmic"):
            with patch("gmic.stdlib.subprocess.run", return_value=completed):
                assert gmic_version() == "4.0.3"

    def test_returns_none_without_binary(self):
        from gmic.stdlib import gmic_version
        with patch("gmic.stdlib.shutil.which", return_value=None):
            assert gmic_version() is None

    def test_returns_none_on_failure(self):
        from gmic.stdlib import gmic_version
        with patch("gmic.stdlib.shutil.which", return_value="/usr/bin/gmic"):
            with patch("gmic.stdlib.subprocess.run", side_effect=OSError("boom")):
                assert gmic_version() is None


class TestStdlibSource:
    def test_url_uses_matching_tag(self):
        from gmic.stdlib import stdlib_url
        assert stdlib_url("4.0.3") == (
            "https://raw.githubusercontent.com/GreycLab/gmic/v.4.0.3/src/gmic_stdlib.gmic"
        )

    def test_url_falls_back_to_master(self):
        from gmic.stdlib import stdlib_url
        assert "/master/" in stdlib_url(None)

    def test_cache_path_is_versioned(self, tmp_path):
        from gmic.stdlib import stdlib_cache_path
        with patch("gmic.stdlib.CACHE_DIR", tmp_path):
            assert stdlib_cache_path("4.0.3").name == "gmic_stdlib_4.0.3.gmic"

    def test_cache_path_unversioned_uses_legacy_name(self, tmp_path):
        from gmic.stdlib import stdlib_cache_path
        with patch("gmic.stdlib.CACHE_DIR", tmp_path):
            assert stdlib_cache_path(None).name == "gmic_stdlib.gmic"


class TestStdlibFetchOrGetCached:
    def test_returns_tuple(self, tmp_path):
        from gmic.stdlib import fetch_or_get_cached, CACHE_DIR
        with patch("gmic.stdlib.CACHE_DIR", tmp_path / "stdlib"):
            with patch("gmic.stdlib.gmic_version", return_value=None):
                with patch("gmic.stdlib.urlopen", side_effect=URLError("offline")):
                    result = fetch_or_get_cached()
                    assert isinstance(result, tuple)
                    assert len(result) == 2

    def test_uses_version_matched_stdlib(self, tmp_path):
        from gmic.stdlib import fetch_or_get_cached
        cache_dir = tmp_path / "stdlib"
        cache_dir.mkdir()
        (cache_dir / "gmic_stdlib_4.0.3.gmic").write_text("#@gui Filter:fx_test\n")
        with patch("gmic.stdlib.CACHE_DIR", cache_dir):
            with patch("gmic.stdlib.gmic_version", return_value="4.0.3"):
                main_text, _community = fetch_or_get_cached()
                assert "fx_test" in main_text

    def test_community_returns_none_when_offline(self, tmp_path):
        from urllib.error import URLError
        from gmic.stdlib import fetch_community_files, CACHE_DIR
        with patch("gmic.stdlib.CACHE_DIR", tmp_path / "stdlib"):
            with patch("gmic.stdlib.urlopen", side_effect=URLError("offline")):
                result = fetch_community_files()
                assert result is None
