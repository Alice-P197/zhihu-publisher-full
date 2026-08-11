# -*- coding: utf-8 -*-
"""音视频上传前置元信息检测与校验

上传前对视频/音频文件进行时长、大小检测，拦截不合规文件。
支持格式：MP4 / MOV / MP3 / AAC(M4A) / WAV / AIFF / FLAC 等 mutagen 支持的格式。
AVI / MKV 等不支持格式：跳过时长检测，仅执行大小检测。
"""

from __future__ import annotations

import logging
import os

import mutagen

from mediacloud_uploader.errors import UploaderValidationError

logger = logging.getLogger(__name__)

# ── 常量 ────────────────────────────────────────────────────────────────────────

_SIZE_LIMIT_BYTES = 20 * 1024 * 1024 * 1024  # 20 GB
_DURATION_LIMIT_SECS = 4 * 60 * 60  # 4 小时 = 14400 秒


# ── 数据类 ──────────────────────────────────────────────────────────────────────


class VideoMeta:
    """从文件头读取的音视频元信息"""

    __slots__ = ("format", "duration_secs", "size_bytes")

    def __init__(self, format: str, duration_secs: float | None, size_bytes: int) -> None:
        self.format = format  # "MP4" / "MP3" / "FLAC" / "UNKNOWN" 等
        self.duration_secs = duration_secs  # None 表示 mutagen 无法识别格式时长
        self.size_bytes = size_bytes

    def __repr__(self) -> str:
        dur = f"{self.duration_secs:.1f}s" if self.duration_secs is not None else "unknown"
        return f"VideoMeta(format={self.format}, duration={dur}, size={self.size_bytes / (1024 * 1024):.1f}MB)"


# ── 公共接口 ────────────────────────────────────────────────────────────────────


def probe_video(source: str) -> VideoMeta:
    """读取音视频文件元信息，不解码媒体数据。

    :param source:  本地文件路径（str）
    :return:        VideoMeta；duration_secs 为 None 表示格式不支持时长检测
    :raises UploaderValidationError: 文件不存在或文件完全无法读取
    """
    if not os.path.isfile(source):
        raise UploaderValidationError(f"文件不存在: {source}")

    size_bytes = os.path.getsize(source)
    duration_secs = None
    fmt = "UNKNOWN"

    try:
        f = mutagen.File(source)
        if f is not None:
            fmt = type(f).__name__  # e.g. "MP4", "MP3", "FLAC"
            if hasattr(f, "info") and hasattr(f.info, "length"):
                duration_secs = float(f.info.length)
    except Exception as e:
        # mutagen 无法解析时不报错，duration 保持 None
        logger.debug("[video_validator] mutagen could not parse %s: %s", source, e)

    logger.debug("[video_validator] probed %s", VideoMeta(fmt, duration_secs, size_bytes))
    return VideoMeta(fmt, duration_secs, size_bytes)


def validate_video_meta(meta: VideoMeta) -> None:
    """应用所有前置拦截规则。

    :raises UploaderValidationError: 任一规则未通过
    """
    _check_size(meta)
    _check_duration(meta)


# ── 内部辅助 ────────────────────────────────────────────────────────────────────


def _check_size(meta: VideoMeta) -> None:
    limit_gb = _SIZE_LIMIT_BYTES / (1024**3)
    size_gb = meta.size_bytes / (1024**3)

    if meta.size_bytes > _SIZE_LIMIT_BYTES:
        raise UploaderValidationError(f"文件大小超限（{size_gb:.1f} GB），上限 {limit_gb:.0f} GB，请压缩后重试。")


def _check_duration(meta: VideoMeta) -> None:
    if meta.duration_secs is None:
        # 格式不受支持，跳过时长检测（大小检测已执行）
        logger.warning("[video_validator] duration check skipped for unsupported format: %s", meta.format)
        return

    # M4: 时长为 0 的文件可能已损坏，拒绝上传
    if meta.duration_secs <= 0:
        raise UploaderValidationError("文件时长为 0，文件可能已损坏，请确认后重试。")

    limit_h = _DURATION_LIMIT_SECS / 3600
    dur_h = meta.duration_secs / 3600

    if meta.duration_secs > _DURATION_LIMIT_SECS:
        raise UploaderValidationError(f"文件时长超限（{dur_h:.1f} 小时），上限 {limit_h:.0f} 小时，请剪辑后重试。")
