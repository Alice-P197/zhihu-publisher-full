# -*- coding: utf-8 -*-
"""图片上传前置元信息检测与校验

上传前对图片进行格式、尺寸、大小的检测，拦截不合规图片。
支持格式：JPEG / PNG / GIF / WebP / BMP / TIFF / HEIC / HEIF / AVIF
"""

import io
import logging
import os

from mediacloud_uploader.errors import UploaderValidationError

logger = logging.getLogger(__name__)

# ── 常量 ────────────────────────────────────────────────────────────────────────

# 图片大小上限
_SIZE_LIMIT_GIF_BYTES = 15 * 1024 * 1024  # 15 MB（GIF）
_SIZE_LIMIT_OTHER_BYTES = 30 * 1024 * 1024  # 30 MB（其他格式）

# 分辨率上限
_MAX_LONG_SIDE_PX = 4 * 4096  # 16 384 px（长边）
_MAX_TOTAL_PIXELS = 200_000_000  # 2 亿（总像素数）

# GIF format 标识（大小写均有可能）
_GIF_FORMAT = "GIF"


# ── 数据类 ──────────────────────────────────────────────────────────────────────


class ImageMeta:
    """从文件头读取的图片元信息"""

    __slots__ = ("format", "mime", "width", "height", "size_bytes")

    def __init__(self, format: str, mime: str, width: int, height: int, size_bytes: int):
        self.format = format  # "JPEG" | "PNG" | "GIF" | "WEBP" | "HEIF" | ...
        self.mime = mime  # "image/jpeg" | "image/png" | ...
        self.width = width
        self.height = height
        self.size_bytes = size_bytes

    def __repr__(self) -> str:
        return f"ImageMeta(format={self.format}, mime={self.mime}, {self.width}x{self.height}, {self.size_bytes / (1024 * 1024):.1f}MB)"


# ── 公共接口 ────────────────────────────────────────────────────────────────────


def probe_image(source: str | io.IOBase) -> ImageMeta:
    """从文件头读取图片元信息，仅读约 4–10 KB，不解码像素。

    :param source: 文件路径（str）或 file-like 对象（需支持 seek，如 BytesIO）
    :return:       ImageMeta
    :raises UploaderValidationError: 无法识别的图片格式或非图片文件
    """
    _ensure_heif_registered()

    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:
        raise ImportError("Pillow is required for image validation. Run: pip install Pillow>=12.3.0")

    # 获取文件大小
    size_bytes = _measure_size(source)

    # R2 修复: 关闭 Pillow 内置像素炸弹保护（阈值 ~178.9MP < 代码上限 200MP），
    # 由代码自身的 _check_resolution 统一校验分辨率上限
    Image.MAX_IMAGE_PIXELS = None

    # 打开图片（仅读文件头，不解码像素）
    try:
        with Image.open(source) as img:
            fmt = img.format or "UNKNOWN"
            width, height = img.size
            mime = Image.MIME.get(fmt, f"image/{fmt.lower()}")
    except Exception as e:
        # 兼容 PIL.UnidentifiedImageError 和其他格式错误
        raise UploaderValidationError(
            f"无法识别文件格式，请确认上传的是有效图片文件（JPEG / PNG / GIF / WebP / HEIC 等）。"
            f"（详情：{type(e).__name__}）"
        )
    finally:
        # 确保 file-like 对象游标归零，不影响后续上传
        if hasattr(source, "seek"):
            source.seek(0)

    logger.debug("[image_validator] probed %s", ImageMeta(fmt, mime, width, height, size_bytes))
    return ImageMeta(fmt, mime, width, height, size_bytes)


def validate_image_meta(meta: ImageMeta) -> None:
    """对已探测的元信息应用所有前置拦截规则。

    :raises UploaderValidationError: 任一规则未通过
    """
    _check_size(meta)
    _check_resolution(meta)


# ── 内部辅助 ────────────────────────────────────────────────────────────────────

_heif_registered = False


def _ensure_heif_registered() -> None:
    """注册 pillow-heif 插件（幂等），使 Pillow 支持 HEIC / HEIF / AVIF。"""
    global _heif_registered
    if _heif_registered:
        return
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
        _heif_registered = True
        logger.debug("[image_validator] pillow-heif registered")
    except ImportError:
        logger.warning("[image_validator] pillow-heif not installed; HEIC/HEIF/AVIF validation unavailable")


def _measure_size(source: str | io.IOBase) -> int:
    """获取字节数：文件路径用 os.path.getsize，file-like 用 seek。"""
    if isinstance(source, (str, os.PathLike)):
        return os.path.getsize(source)
    # BytesIO / file-like
    pos = source.tell()
    source.seek(0, io.SEEK_END)
    size = source.tell()
    source.seek(pos)
    return size


def _check_size(meta: ImageMeta) -> None:
    is_gif = meta.format.upper() == _GIF_FORMAT
    limit = _SIZE_LIMIT_GIF_BYTES if is_gif else _SIZE_LIMIT_OTHER_BYTES
    limit_mb = limit / (1024 * 1024)
    size_mb = meta.size_bytes / (1024 * 1024)

    if meta.size_bytes > limit:
        if is_gif:
            raise UploaderValidationError(
                f"GIF 图片大小超限（{size_mb:.1f} MB），上限 {limit_mb:.0f} MB，请压缩后重试。"
            )
        raise UploaderValidationError(f"图片大小超限（{size_mb:.1f} MB），上限 {limit_mb:.0f} MB，请压缩后重试。")


def _check_resolution(meta: ImageMeta) -> None:
    long_side = max(meta.width, meta.height)
    total_pixels = meta.width * meta.height

    if long_side > _MAX_LONG_SIDE_PX:
        raise UploaderValidationError(
            f"图片分辨率过高（{meta.width}×{meta.height}），长边上限 {_MAX_LONG_SIDE_PX}px（当前长边 {long_side}px），"
            f"请缩小后重试。"
        )

    if total_pixels > _MAX_TOTAL_PIXELS:
        raise UploaderValidationError(
            f"图片总像素数超限（{meta.width}×{meta.height} = {total_pixels:,}px），上限 2 亿像素，请缩小后重试。"
        )
