# -*- coding: utf-8 -*-
"""video_validator.py 单元测试"""

import io
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mediacloud_uploader.errors import UploaderValidationError
from mediacloud_uploader.video_validator import (
    VideoMeta,
    _DURATION_LIMIT_SECS,
    _SIZE_LIMIT_BYTES,
    probe_video,
    validate_video_meta,
)


# ── 辅助：生成真实音频文件 ─────────────────────────────────────────────────────────

def _make_mp3_file(tmp_path: Path, duration_secs: float = 10.0) -> str:
    """生成一个真实的 MP3 临时文件（使用 mutagen 写入）"""
    try:
        from mutagen.mp3 import MP3  # noqa: F401
    except ImportError:
        pytest.skip("mutagen not installed")
    pytest.skip("MP3 generation requires real audio frames, use mock instead")


# ── VideoMeta ─────────────────────────────────────────────────────────────────────

class TestVideoMeta:
    def test_fields(self) -> None:
        m = VideoMeta("MP4", 3600.0, 1024 * 1024 * 1024)
        assert m.format        == "MP4"
        assert m.duration_secs == 3600.0
        assert m.size_bytes    == 1024 * 1024 * 1024

    def test_duration_none(self) -> None:
        m = VideoMeta("UNKNOWN", None, 500)
        assert m.duration_secs is None

    def test_repr(self) -> None:
        m = VideoMeta("MP4", 7200.0, 1024 * 1024)
        r = repr(m)
        assert "MP4" in r
        assert "7200" in r


# ── validate_video_meta — 大小校验 ────────────────────────────────────────────────

class TestValidateVideoMetaSize:
    def _meta(self, size_bytes: int, dur: float | None = 60.0) -> VideoMeta:
        return VideoMeta("MP4", dur, size_bytes)

    def test_at_limit_passes(self) -> None:
        validate_video_meta(self._meta(_SIZE_LIMIT_BYTES))  # no error

    def test_over_limit_raises(self) -> None:
        meta = self._meta(_SIZE_LIMIT_BYTES + 1)
        with pytest.raises(UploaderValidationError) as exc_info:
            validate_video_meta(meta)
        assert "20" in exc_info.value.message
        assert "GB" in exc_info.value.message

    def test_well_within_limit(self) -> None:
        validate_video_meta(self._meta(100 * 1024 * 1024))  # 100 MB


# ── validate_video_meta — 时长校验 ───────────────────────────────────────────────

class TestValidateVideoMetaDuration:
    def _meta(self, dur_secs: float | None) -> VideoMeta:
        return VideoMeta("MP4", dur_secs, 1024)

    def test_at_limit_passes(self) -> None:
        validate_video_meta(self._meta(float(_DURATION_LIMIT_SECS)))

    def test_over_limit_raises(self) -> None:
        meta = self._meta(float(_DURATION_LIMIT_SECS + 1))
        with pytest.raises(UploaderValidationError) as exc_info:
            validate_video_meta(meta)
        assert "小时" in exc_info.value.message
        assert "4" in exc_info.value.message

    def test_none_duration_skips_check(self) -> None:
        """格式不支持时长检测时，不报错（仅大小校验）"""
        meta = self._meta(None)
        validate_video_meta(meta)  # no error

    def test_3_hours_passes(self):
        validate_video_meta(self._meta(3 * 3600.0))

    def test_4_hours_1_second_fails(self):
        meta = self._meta(4 * 3600.0 + 1)
        with pytest.raises(UploaderValidationError):
            validate_video_meta(meta)


# ── probe_video — 通过 mock mutagen ──────────────────────────────────────────────

class TestProbeVideo:
    def test_probe_mp4_success(self, tmp_path):
        """probe_video 从文件路径读取元信息（mutagen mock）"""
        f = tmp_path / "clip.mp4"
        f.write_bytes(b"fake mp4 content")

        mock_info = MagicMock()
        mock_info.length = 120.5
        mock_file = MagicMock()
        mock_file.info = mock_info
        type(mock_file).__name__ = "MP4"

        with patch("mediacloud_uploader.video_validator.mutagen") as mock_mutagen:
            mock_mutagen.File.return_value = mock_file
            meta = probe_video(str(f))

        assert meta.duration_secs == pytest.approx(120.5)
        assert meta.size_bytes    == len(b"fake mp4 content")

    def test_probe_unsupported_format_returns_none_duration(self, tmp_path):
        """mutagen 无法解析时，duration_secs 为 None（不报错）"""
        f = tmp_path / "video.avi"
        f.write_bytes(b"avi content")

        with patch("mediacloud_uploader.video_validator.mutagen") as mock_mutagen:
            mock_mutagen.File.side_effect = Exception("unsupported format")
            meta = probe_video(str(f))

        assert meta.duration_secs is None
        assert meta.size_bytes    == len(b"avi content")

    def test_probe_mutagen_returns_none(self, tmp_path):
        """mutagen.File 返回 None（格式不识别）时，duration_secs 也为 None"""
        f = tmp_path / "unknown.bin"
        f.write_bytes(b"x" * 100)

        with patch("mediacloud_uploader.video_validator.mutagen") as mock_mutagen:
            mock_mutagen.File.return_value = None
            meta = probe_video(str(f))

        assert meta.duration_secs is None
        assert meta.size_bytes    == 100

    def test_probe_nonexistent_file_raises(self):
        with pytest.raises(UploaderValidationError, match="不存在"):
            probe_video("/nonexistent/file.mp4")

    def test_probe_size_from_file(self, tmp_path):
        """size_bytes 来自 os.path.getsize，不依赖 mutagen"""
        content = b"x" * 1024
        f = tmp_path / "v.mp4"
        f.write_bytes(content)

        with patch("mediacloud_uploader.video_validator.mutagen") as mock_mutagen:
            mock_mutagen.File.return_value = None
            meta = probe_video(str(f))

        assert meta.size_bytes == 1024
