# -*- coding: utf-8 -*-
"""image_validator.py 单元测试"""

import io
from unittest.mock import MagicMock, patch

import pytest

from mediacloud_uploader.errors import UploaderValidationError
from mediacloud_uploader.image_validator import (
    ImageMeta,
    _MAX_LONG_SIDE_PX,
    _MAX_TOTAL_PIXELS,
    _SIZE_LIMIT_GIF_BYTES,
    _SIZE_LIMIT_OTHER_BYTES,
    probe_image,
    validate_image_meta,
)


# ── 辅助：构造最小合法图片字节 ────────────────────────────────────────────────────

def _make_jpeg_bytes(width: int = 100, height: int = 100) -> bytes:
    """生成最小 JPEG，只包含 SOI + APP0 + SOF0（让 Pillow 能读尺寸）"""
    # 用 Pillow 生成一张真实 JPEG
    try:
        from PIL import Image
        buf = io.BytesIO()
        img = Image.new("RGB", (width, height), color=(255, 0, 0))
        img.save(buf, format="JPEG")
        buf.seek(0)
        return buf.read()
    except ImportError:
        pytest.skip("Pillow not installed")


def _make_png_bytes(width: int = 100, height: int = 100) -> bytes:
    try:
        from PIL import Image
        buf = io.BytesIO()
        img = Image.new("RGB", (width, height))
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf.read()
    except ImportError:
        pytest.skip("Pillow not installed")


def _make_gif_bytes(width: int = 100, height: int = 100) -> bytes:
    try:
        from PIL import Image
        buf = io.BytesIO()
        img = Image.new("P", (width, height))
        img.save(buf, format="GIF")
        buf.seek(0)
        return buf.read()
    except ImportError:
        pytest.skip("Pillow not installed")


# ── ImageMeta ─────────────────────────────────────────────────────────────────────

class TestImageMeta:
    def test_fields(self) -> None:
        m = ImageMeta("JPEG", "image/jpeg", 1920, 1080, 204800)
        assert m.format == "JPEG"
        assert m.mime == "image/jpeg"
        assert m.width == 1920
        assert m.height == 1080
        assert m.size_bytes == 204800

    def test_repr(self) -> None:
        m = ImageMeta("PNG", "image/png", 800, 600, 1024 * 1024)
        r = repr(m)
        assert "PNG" in r
        assert "800" in r
        assert "600" in r


# ── probe_image ───────────────────────────────────────────────────────────────────

class TestProbeImage:
    def test_probe_jpeg_from_bytesio(self) -> None:
        data = _make_jpeg_bytes(200, 150)
        buf  = io.BytesIO(data)
        meta = probe_image(buf)
        assert meta.format == "JPEG"
        assert meta.width  == 200
        assert meta.height == 150
        assert meta.size_bytes == len(data)

    def test_probe_png_from_bytesio(self) -> None:
        data = _make_png_bytes(640, 480)
        buf  = io.BytesIO(data)
        meta = probe_image(buf)
        assert meta.format == "PNG"
        assert meta.width  == 640
        assert meta.height == 480

    def test_probe_gif_from_bytesio(self) -> None:
        data = _make_gif_bytes(320, 240)
        buf  = io.BytesIO(data)
        meta = probe_image(buf)
        assert meta.format == "GIF"
        assert meta.width  == 320
        assert meta.height == 240

    def test_probe_resets_bytesio_position(self) -> None:
        """probe 后 BytesIO 游标归零，不影响后续上传"""
        data = _make_jpeg_bytes(50, 50)
        buf  = io.BytesIO(data)
        probe_image(buf)
        assert buf.tell() == 0

    def test_probe_invalid_bytes_raises_validation_error(self) -> None:
        """非图片文件抛 UploaderValidationError（不是 AttributeError 等）"""
        buf = io.BytesIO(b"this is not an image at all PDF%version1.0")
        with pytest.raises(UploaderValidationError, match="无法识别"):
            probe_image(buf)

    def test_probe_empty_bytes_raises_validation_error(self) -> None:
        buf = io.BytesIO(b"")
        with pytest.raises(UploaderValidationError):
            probe_image(buf)


# ── validate_image_meta ───────────────────────────────────────────────────────────

class TestValidateImageMetaSize:
    def _meta(self, format: str, size_bytes: int, w: int = 100, h: int = 100) -> ImageMeta:
        return ImageMeta(format, "image/{}".format(format.lower()), w, h, size_bytes)

    def test_gif_within_limit_passes(self) -> None:
        meta = self._meta("GIF", _SIZE_LIMIT_GIF_BYTES)
        validate_image_meta(meta)  # no error

    def test_gif_over_limit_raises(self) -> None:
        meta = self._meta("GIF", _SIZE_LIMIT_GIF_BYTES + 1)
        with pytest.raises(UploaderValidationError) as exc_info:
            validate_image_meta(meta)
        assert "GIF" in exc_info.value.message
        assert "15" in exc_info.value.message

    def test_jpeg_within_limit_passes(self) -> None:
        meta = self._meta("JPEG", _SIZE_LIMIT_OTHER_BYTES)
        validate_image_meta(meta)  # no error

    def test_jpeg_over_limit_raises(self) -> None:
        meta = self._meta("JPEG", _SIZE_LIMIT_OTHER_BYTES + 1)
        with pytest.raises(UploaderValidationError) as exc_info:
            validate_image_meta(meta)
        assert "30" in exc_info.value.message

    def test_png_over_limit_raises(self) -> None:
        meta = self._meta("PNG", _SIZE_LIMIT_OTHER_BYTES + 1)
        with pytest.raises(UploaderValidationError):
            validate_image_meta(meta)

    def test_gif_uses_gif_limit_not_other(self) -> None:
        """GIF 在 30MB 内但超过 15MB → 应该失败"""
        size = _SIZE_LIMIT_GIF_BYTES + 1  # 超过 GIF 限制
        assert size < _SIZE_LIMIT_OTHER_BYTES  # 但没超过非 GIF 限制
        meta = self._meta("GIF", size)
        with pytest.raises(UploaderValidationError):
            validate_image_meta(meta)


class TestValidateImageMetaResolution:
    def _meta(self, w: int, h: int) -> ImageMeta:
        return ImageMeta("JPEG", "image/jpeg", w, h, 1024)

    def test_long_side_at_limit_passes(self) -> None:
        meta = self._meta(_MAX_LONG_SIDE_PX, 100)
        validate_image_meta(meta)  # no error

    def test_long_side_over_limit_raises(self) -> None:
        meta = self._meta(_MAX_LONG_SIDE_PX + 1, 100)
        with pytest.raises(UploaderValidationError) as exc_info:
            validate_image_meta(meta)
        assert "16384" in exc_info.value.message

    def test_height_as_long_side(self) -> None:
        meta = self._meta(100, _MAX_LONG_SIDE_PX + 1)
        with pytest.raises(UploaderValidationError):
            validate_image_meta(meta)

    def test_total_pixels_at_limit_passes(self) -> None:
        # 使用一个接近 2 亿但不超过的尺寸
        w = 14142  # ~14142*14142 ≈ 199,995,164 < 200,000,000
        h = 14142
        assert w * h <= _MAX_TOTAL_PIXELS
        assert max(w, h) <= _MAX_LONG_SIDE_PX
        meta = self._meta(w, h)
        validate_image_meta(meta)  # no error

    def test_total_pixels_over_limit_raises(self) -> None:
        # 长边不超限，但总像素超限
        # 16384 * 16384 = 268,435,456 > 200,000,000
        # 但长边也超限了，所以找另一个组合
        # 15000 * 14000 = 210,000,000 > 200M；长边 15000 < 16384
        w, h = 15000, 14000
        assert max(w, h) <= _MAX_LONG_SIDE_PX
        assert w * h > _MAX_TOTAL_PIXELS
        meta = self._meta(w, h)
        with pytest.raises(UploaderValidationError) as exc_info:
            validate_image_meta(meta)
        assert "2 亿" in exc_info.value.message

    def test_long_side_error_takes_priority_over_pixel_error(self) -> None:
        """长边超限时先报长边错误（size 检查先于 resolution）"""
        meta = self._meta(_MAX_LONG_SIDE_PX + 1, _MAX_LONG_SIDE_PX + 1)
        with pytest.raises(UploaderValidationError) as exc_info:
            validate_image_meta(meta)
        assert "长边" in exc_info.value.message
