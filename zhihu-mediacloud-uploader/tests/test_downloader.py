# -*- coding: utf-8 -*-
"""downloader.py 单元测试"""

import os
from unittest.mock import MagicMock, patch

import pytest
import requests

from mediacloud_uploader.downloader import (
    download_url_to_file,
    filename_from_url,
    is_url,
    _extract_content_type,
)
from mediacloud_uploader.errors import UploaderDownloadError


# ── is_url ────────────────────────────────────────────────────────────────────────

class TestIsUrl:
    def test_http(self) -> None:
        assert is_url("http://example.com/file.jpg") is True

    def test_https(self) -> None:
        assert is_url("https://example.com/file.jpg") is True

    def test_local_path(self) -> None:
        assert is_url("/Users/alice/file.jpg") is False

    def test_relative_path(self) -> None:
        assert is_url("./file.jpg") is False

    def test_empty(self) -> None:
        assert is_url("") is False

    def test_case_insensitive(self) -> None:
        assert is_url("HTTP://example.com/f") is True
        assert is_url("HTTPS://example.com/f") is True


# ── filename_from_url ─────────────────────────────────────────────────────────────

class TestFilenameFromUrl:
    def test_simple_filename(self) -> None:
        assert filename_from_url("https://example.com/photo.jpg") == "photo.jpg"

    def test_path_with_dir(self) -> None:
        assert filename_from_url("https://cdn.example.com/images/2024/banner.png") == "banner.png"

    def test_no_filename(self) -> None:
        assert filename_from_url("https://example.com/") == ""

    def test_query_string_ignored(self) -> None:
        result = filename_from_url("https://example.com/file.mp4?token=abc")
        assert result == "file.mp4"


# ── download_url_to_file ──────────────────────────────────────────────────────────

class TestDownloadUrlToFile:
    def _make_mock_response(self, content: bytes, status_code: int = 200, content_type: str = "video/mp4") -> MagicMock:
        resp = MagicMock()
        resp.ok = (status_code < 400)
        resp.status_code = status_code
        resp.headers = {"Content-Type": content_type}
        resp.iter_content = MagicMock(return_value=[content])
        return resp

    def test_downloads_to_file(self, tmp_path) -> None:
        content   = b"fake video data" * 100
        mock_resp = self._make_mock_response(content)

        with patch("mediacloud_uploader.downloader.requests.get", return_value=mock_resp):
            path, size, ct = download_url_to_file("https://example.com/video.mp4")

        try:
            assert size == len(content)
            assert ct   == "video/mp4"
            assert os.path.isfile(path)
            with open(path, "rb") as f:
                assert f.read() == content
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_returns_file_path_not_bytesio(self, tmp_path) -> None:
        mock_resp = self._make_mock_response(b"data")
        with patch("mediacloud_uploader.downloader.requests.get", return_value=mock_resp):
            path, _, _ = download_url_to_file("https://example.com/file.zip")
        try:
            assert isinstance(path, str)
            assert os.path.isfile(path)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_404_raises_download_error(self) -> None:
        mock_resp = self._make_mock_response(b"not found", status_code=404)
        with patch("mediacloud_uploader.downloader.requests.get", return_value=mock_resp):
            with pytest.raises(UploaderDownloadError) as exc_info:
                download_url_to_file("https://example.com/missing.mp4")
        assert exc_info.value.http_status == 404

    def test_content_type_extracted(self) -> None:
        mock_resp = self._make_mock_response(b"audio data", content_type="audio/mpeg")
        with patch("mediacloud_uploader.downloader.requests.get", return_value=mock_resp):
            path, _, ct = download_url_to_file("https://example.com/song.mp3")
        try:
            assert ct == "audio/mpeg"
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_unsupported_scheme_raises(self) -> None:
        with pytest.raises(UploaderDownloadError):
            download_url_to_file("ftp://example.com/file.mp4")
