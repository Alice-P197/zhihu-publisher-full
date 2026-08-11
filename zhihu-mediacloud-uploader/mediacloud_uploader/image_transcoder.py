# -*- coding: utf-8 -*-
"""图片格式转码：将服务端暂不支持的格式（HEIC/HEIF/AVIF）转为 WebP 后再上传。

【临时兼容方案】当前图片服务端方案落后，尚不支持 HEIC/HEIF/AVIF 格式的处理，
因此在端侧上传前做格式转换，将其转为服务端支持的 WebP 格式。
待服务端完成格式支持改造后，可删除此模块及 mcp_server.py 中的转码调用逻辑。

上传前由 mcp_server 调用；仅对需要转码的格式执行，其余格式直接跳过。
依赖已在 pyproject.toml 中声明：Pillow>=12.3.0、pillow-heif>=1.4.0。
"""

from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)

# Pillow format 字段值（Image.format）：需要转码才能上传的格式
# pillow-heif 将 .heic/.heif/.hif 注册为 "HEIF"，.avif 注册为 "AVIF"
_FORMATS_NEED_TRANSCODE: frozenset[str] = frozenset({"HEIF", "AVIF"})

# 转码目标
_TARGET_FORMAT = "WEBP"
_TARGET_CONTENT_TYPE = "image/webp"
_TARGET_EXTENSION = ".webp"

# WebP 编码参数
_WEBP_QUALITY = 85  # 有损质量 1-100
_WEBP_METHOD = 4  # 压缩速度 0（快）~6（最小体积）；4 是质量/速度平衡点


# ── 公共接口 ────────────────────────────────────────────────────────────────────


class TranscodeResult:
    """transcode_to_webp 返回值"""

    __slots__ = ("data", "size", "content_type", "file_extension")

    def __init__(
        self,
        data: io.BytesIO,
        size: int,
        content_type: str,
        file_extension: str,
    ) -> None:
        self.data = data
        self.size = size
        self.content_type = content_type
        self.file_extension = file_extension


def needs_transcode(pillow_format: str) -> bool:
    """判断该 Pillow format 是否需要转码后才能上传。

    :param pillow_format: probe_image() 返回的 ImageMeta.format，如 "HEIF"、"AVIF"
    """
    return pillow_format.upper() in _FORMATS_NEED_TRANSCODE


def transcode_to_webp(source: str | io.IOBase, pillow_format: str) -> TranscodeResult:
    """将 source 中的图片转为 WebP 格式，返回内存缓冲区。

    :param source:        本地文件路径（str）或 file-like 对象（需支持 seek）
    :param pillow_format: 源格式标识，probe_image 返回的 ImageMeta.format（如 "HEIF"、"AVIF"）；
                          Pillow 根据文件头自动识别格式，此参数不影响解码行为。
    :return:              TranscodeResult
    :raises RuntimeError: pillow-heif 未安装，或 Pillow 无法打开/转码图片时抛出
    """
    _ensure_heif_registered()

    from PIL import Image

    # file-like 游标归位
    if hasattr(source, "seek"):
        source.seek(0)

    with Image.open(source) as src:
        original_size = src.size
        original_mode = src.mode

        # 模式归一化：
        #   含 alpha 通道（RGBA / LA / RGBa / PA）→ RGBA（WebP 原生支持透明）
        #   其余（RGB / L / P / CMYK 等）→ RGB
        if src.mode in ("RGBA", "LA", "RGBa", "PA"):
            img = src.convert("RGBA")
        elif src.mode != "RGB":
            img = src.convert("RGB")
        else:
            img = src

        out = io.BytesIO()
        img.save(out, format=_TARGET_FORMAT, quality=_WEBP_QUALITY, method=_WEBP_METHOD)

    # out.tell() 即写入字节数（从位置 0 开始写）
    size = out.tell()
    out.seek(0)

    logger.info(
        "[transcoder] %s %s %dx%d → WebP %d bytes",
        pillow_format,
        original_mode,
        original_size[0],
        original_size[1],
        size,
    )

    return TranscodeResult(
        data=out,
        size=size,
        content_type=_TARGET_CONTENT_TYPE,
        file_extension=_TARGET_EXTENSION,
    )


# ── 内部辅助 ────────────────────────────────────────────────────────────────────


def _ensure_heif_registered() -> None:
    """注册 pillow-heif 插件，使 Pillow 支持 HEIC/HEIF/AVIF 读取。

    pillow_heif.register_heif_opener() 本身幂等，重复调用安全。
    :raises RuntimeError: pillow-heif 未安装时抛出，避免后续产生误导性错误。
    """
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
        logger.debug("[transcoder] pillow-heif registered")
    except ImportError as e:
        raise RuntimeError(
            "pillow-heif is required for HEIC/HEIF/AVIF transcoding. Install it with: pip install 'pillow-heif>=1.4.0'"
        ) from e
