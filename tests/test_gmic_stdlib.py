from unittest.mock import patch, MagicMock


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


class TestStdlibFetchOrGetCached:
    def test_returns_tuple(self, tmp_path):
        from gmic.stdlib import fetch_or_get_cached, CACHE_DIR
        with patch("gmic.stdlib.CACHE_DIR", tmp_path / "stdlib"):
            result = fetch_or_get_cached()
            assert isinstance(result, tuple)
            assert len(result) == 2

    def test_community_returns_none_when_offline(self, tmp_path):
        from urllib.error import URLError
        from gmic.stdlib import fetch_community_files, CACHE_DIR
        with patch("gmic.stdlib.CACHE_DIR", tmp_path / "stdlib"):
            with patch("gmic.stdlib.urlopen", side_effect=URLError("offline")):
                result = fetch_community_files()
                assert result is None
