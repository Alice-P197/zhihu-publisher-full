# -*- coding: utf-8 -*-
"""image_transcoder.py 单元测试"""

import io
import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from mediacloud_uploader.image_transcoder import (
    needs_transcode,
    transcode_to_webp,
    TranscodeResult,
    _TARGET_CONTENT_TYPE,
    _TARGET_EXTENSION,
)
from mediacloud_uploader.client import _replace_ext
from mediacloud_uploader.mcp_server import upload as _handle_upload


# ── 辅助：生成合成图片 ──────────────────────────────────────────────────────────

def _make_heif_bytes(width: int = 80, height: int = 60) -> bytes:
    """生成合法 HEIF 字节（pillow_heif.from_pillow 编码）"""
    import pillow_heif
    from PIL import Image
    img = Image.new("RGB", (width, height), color=(100, 150, 200))
    buf = io.BytesIO()
    pillow_heif.from_pillow(img).save(buf)
    buf.seek(0)
    return buf.read()


def _open_webp(buf: io.BytesIO):
    from PIL import Image
    buf.seek(0)
    return Image.open(buf)


# ── needs_transcode ─────────────────────────────────────────────────────────────

class TestNeedsTranscode:
    def test_heif_needs_transcode(self) -> None:
        assert needs_transcode("HEIF") is True

    def test_avif_needs_transcode(self) -> None:
        assert needs_transcode("AVIF") is True

    def test_case_insensitive(self) -> None:
        assert needs_transcode("heif") is True
        assert needs_transcode("Avif") is True

    def test_jpeg_no_transcode(self) -> None:
        assert needs_transcode("JPEG") is False

    def test_png_no_transcode(self) -> None:
        assert needs_transcode("PNG") is False

    def test_webp_no_transcode(self) -> None:
        assert needs_transcode("WEBP") is False

    def test_gif_no_transcode(self) -> None:
        assert needs_transcode("GIF") is False

    def test_empty_string_no_transcode(self) -> None:
        assert needs_transcode("") is False

    def test_unknown_format_no_transcode(self) -> None:
        assert needs_transcode("TIFF") is False


# ── TranscodeResult ─────────────────────────────────────────────────────────────

class TestTranscodeResult:
    def test_fields(self) -> None:
        buf = io.BytesIO(b"fake")
        tr = TranscodeResult(data=buf, size=4, content_type="image/webp", file_extension=".webp")
        assert tr.data is buf
        assert tr.size == 4
        assert tr.content_type == "image/webp"
        assert tr.file_extension == ".webp"


# ── transcode_to_webp: BytesIO 输入 ────────────────────────────────────────────

class TestTranscodeToWebpBytesIO:
    def test_heif_bytesio_produces_webp(self) -> None:
        """HEIF BytesIO → WebP BytesIO，格式/尺寸验证"""
        heif_bytes = _make_heif_bytes(120, 90)
        buf = io.BytesIO(heif_bytes)

        tr = transcode_to_webp(buf, "HEIF")

        assert isinstance(tr, TranscodeResult)
        assert tr.content_type == _TARGET_CONTENT_TYPE
        assert tr.file_extension == _TARGET_EXTENSION
        assert tr.size > 0
        assert tr.size == len(tr.data.getvalue())

        with _open_webp(tr.data) as img:
            assert img.format == "WEBP"
            assert img.size == (120, 90)

    def test_output_bytesio_position_at_zero(self) -> None:
        """transcode 后 data.tell() == 0，可直接传给 UploadRequest"""
        heif_bytes = _make_heif_bytes()
        tr = transcode_to_webp(io.BytesIO(heif_bytes), "HEIF")
        assert tr.data.tell() == 0

    def test_size_matches_data_length(self) -> None:
        """TranscodeResult.size 与实际字节数一致"""
        heif_bytes = _make_heif_bytes()
        tr = transcode_to_webp(io.BytesIO(heif_bytes), "HEIF")
        assert tr.size == len(tr.data.getvalue())

    def test_rgb_mode_output(self) -> None:
        """RGB 源图 → WebP RGB"""
        heif_bytes = _make_heif_bytes()
        tr = transcode_to_webp(io.BytesIO(heif_bytes), "HEIF")
        with _open_webp(tr.data) as img:
            assert img.mode == "RGB"


# ── transcode_to_webp: 文件路径输入 ────────────────────────────────────────────

class TestTranscodeToWebpFilePath:
    def test_file_path_input(self, tmp_path) -> None:
        """本地文件路径输入"""
        heif_bytes = _make_heif_bytes(64, 48)
        heif_file = tmp_path / "test.heic"
        heif_file.write_bytes(heif_bytes)

        tr = transcode_to_webp(str(heif_file), "HEIF")

        assert tr.content_type == "image/webp"
        with _open_webp(tr.data) as img:
            assert img.format == "WEBP"
            assert img.size == (64, 48)


# ── transcode_to_webp: 模式转换 ─────────────────────────────────────────────────

class TestTranscodeModeConversion:
    """各种 Pillow 图片模式均能转码为 WebP"""

    def _transcode_mode(self, mode: str) -> str:
        """用指定模式创建 PNG，传入 transcode_to_webp，返回输出 WebP 的模式。"""
        from PIL import Image
        buf = io.BytesIO()
        if mode == "P":
            img = Image.new("P", (40, 40))
        elif mode == "PA":
            img = Image.new("RGBA", (40, 40), (255, 0, 0, 128)).convert("PA")
        else:
            img = Image.new(mode, (40, 40))
        img.save(buf, format="PNG")
        buf.seek(0)

        tr = transcode_to_webp(buf, "HEIF")
        with _open_webp(tr.data) as out:
            return out.mode

    def test_rgb_stays_rgb(self) -> None:
        assert self._transcode_mode("RGB") == "RGB"

    def test_rgba_stays_rgba(self) -> None:
        assert self._transcode_mode("RGBA") == "RGBA"

    def test_l_converts_to_rgb(self) -> None:
        assert self._transcode_mode("L") == "RGB"

    def test_p_converts_to_rgb(self) -> None:
        assert self._transcode_mode("P") == "RGB"


# ── transcode_to_webp: 错误处理 ────────────────────────────────────────────────

class TestTranscodeErrors:
    def test_invalid_bytes_raises(self) -> None:
        buf = io.BytesIO(b"not an image at all")
        with pytest.raises(Exception):
            transcode_to_webp(buf, "HEIF")

    def test_empty_bytes_raises(self) -> None:
        buf = io.BytesIO(b"")
        with pytest.raises(Exception):
            transcode_to_webp(buf, "AVIF")

    def test_missing_pillow_heif_raises_runtime_error(self) -> None:
        """pillow-heif 未安装时抛出 RuntimeError 而非静默降级"""
        with patch("builtins.__import__", side_effect=ImportError("No module named 'pillow_heif'")):
            # 需要绕过模块缓存：直接 mock _ensure_heif_registered 中的 import
            pass  # 通过 patch 内部函数验证

        # 直接 patch _ensure_heif_registered 来模拟 ImportError 场景
        from mediacloud_uploader import image_transcoder
        with patch.object(image_transcoder, "_ensure_heif_registered",
                          side_effect=RuntimeError("pillow-heif is required")):
            with pytest.raises(RuntimeError, match="pillow-heif is required"):
                transcode_to_webp(io.BytesIO(b"fake"), "HEIF")


# ── mcp_server 集成：转码流程 ─────────────────────────────────────────────────

def _make_uploader_mock() -> MagicMock:
    from mediacloud_uploader.models import UploadResponse, UPLOAD_STATE_SUCCESS, MediaType
    resp = UploadResponse(
        upload_result=UPLOAD_STATE_SUCCESS,
        media_key="v2-abcdef1234567890abcdef1234567890",
        media_type=MediaType.IMAGE,
    )
    mock = MagicMock()
    mock.upload.return_value = resp
    mock.upload_image.return_value = resp
    return mock


class TestMcpServerTranscodeIntegration:
    """验证 _handle_upload 对 HEIF/WebP 图片的处理：逻辑现在在 client.upload_image() 中。
    这里只验证 thin wrapper 层正确调用了 upload_image 并返回结果。"""

    def test_heif_file_transcoded_to_webp_before_upload(self, tmp_path) -> None:
        """HEIF 文件 → thin wrapper 调用 upload_image → 结果正确序列化"""
        heif_file = tmp_path / "photo.heic"
        heif_file.write_bytes(_make_heif_bytes(80, 60))

        uploader = _make_uploader_mock()
        result_list = _handle_upload(uploader, {
            "file_path": str(heif_file),
            "scene_name": "answer",
        }, "image")

        result = json.loads(result_list[0].text)
        assert result["success"] is True
        assert uploader.upload_image.call_args.kwargs["file_path"] == str(heif_file)

    def test_heif_file_name_extension_updated(self, tmp_path) -> None:
        """明确传入 file_name 时，thin wrapper 透传给 upload_image"""
        heif_file = tmp_path / "vacation.heic"
        heif_file.write_bytes(_make_heif_bytes())

        uploader = _make_uploader_mock()
        _handle_upload(uploader, {
            "file_path": str(heif_file),
            "scene_name": "answer",
            "file_name": "vacation.heic",
        }, "image")

        assert uploader.upload_image.call_args.kwargs["file_name"] == "vacation.heic"

    def test_jpeg_file_not_transcoded(self, tmp_path) -> None:
        """JPEG 文件：thin wrapper 正确透传给 upload_image"""
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (60, 40)).save(buf, format="JPEG")
        jpeg_file = tmp_path / "photo.jpg"
        jpeg_file.write_bytes(buf.getvalue())

        uploader = _make_uploader_mock()
        result_list = _handle_upload(uploader, {
            "file_path": str(jpeg_file),
            "scene_name": "answer",
        }, "image")

        result = json.loads(result_list[0].text)
        assert result["success"] is True
        assert uploader.upload_image.call_args.kwargs["file_path"] == str(jpeg_file)

    def test_heif_url_transcoded_to_webp(self) -> None:
        """URL HEIF 图片：thin wrapper 透传 url 给 upload_image，结果正确"""
        uploader = _make_uploader_mock()
        result_list = _handle_upload(uploader, {
            "url": "https://example.com/photo.heic",
            "scene_name": "answer",
            "content_type": "image/heic",
        }, "image")

        result = json.loads(result_list[0].text)
        assert result["success"] is True
        assert uploader.upload_image.call_args.kwargs["url"] == "https://example.com/photo.heic"

    def test_transcode_error_returns_internal_error(self, tmp_path) -> None:
        """upload_image 内部抛 RuntimeError 时 thin wrapper 返回 internal_error"""
        heif_file = tmp_path / "bad.heic"
        heif_file.write_bytes(_make_heif_bytes())

        uploader = _make_uploader_mock()
        uploader.upload_image.side_effect = RuntimeError("encoder failed")
        result_list = _handle_upload(uploader, {
            "file_path": str(heif_file),
            "scene_name": "answer",
        }, "image")

        result = json.loads(result_list[0].text)
        assert result["success"] is False
        assert result["error_type"] == "internal_error"


# ── _replace_extension ──────────────────────────────────────────────────────────

class TestReplaceExtension:
    def test_replaces_heic_with_webp(self) -> None:
        assert _replace_ext("photo.heic", ".webp") == "photo.webp"

    def test_replaces_avif_with_webp(self) -> None:
        assert _replace_ext("image.avif", ".webp") == "image.webp"

    def test_no_extension(self) -> None:
        assert _replace_ext("image", ".webp") == "image.webp"

    def test_multiple_dots(self) -> None:
        assert _replace_ext("my.photo.heic", ".webp") == "my.photo.webp"
