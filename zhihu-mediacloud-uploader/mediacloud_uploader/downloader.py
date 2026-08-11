# -*- coding: utf-8 -*-
"""URL 下载工具：将公开可访问的 HTTP/HTTPS URL 流式下载到磁盘临时文件"""

import ipaddress
import logging
import os
import socket
import tempfile
from urllib.parse import urlparse

import requests

from mediacloud_uploader.errors import UploaderDownloadError

logger = logging.getLogger(__name__)

# ── 常量 ────────────────────────────────────────────────────────────────────────

_SUPPORTED_SCHEMES = frozenset({"http", "https"})
_DEFAULT_TIMEOUT = 60  # 秒，下载超时独立于 API 超时
_STREAM_CHUNK_SIZE = 8192  # bytes，iter_content 分块大小
_CONTENT_TYPE_HEADER = "Content-Type"


# ── 公共接口 ────────────────────────────────────────────────────────────────────


def download_url_to_file(url: str, timeout: int = _DEFAULT_TIMEOUT) -> tuple[str, int, str]:
    """将公开 URL 流式下载到磁盘临时文件。

    :param url:     http:// 或 https:// 开头的公开可访问 URL
    :param timeout: 连接 + 读取超时（秒）
    :return:        (临时文件路径, 文件大小字节数, content_type 字符串)
                    调用方负责在使用完毕后删除临时文件
    :raises UploaderDownloadError: URL 不合法、访问失败或超时
    """
    _validate_scheme(url)
    _validate_no_ssrf(url)  # H4: 拒绝内网 IP

    logger.info("[downloader] streaming to file: %s", url)
    try:
        resp = requests.get(url, stream=True, timeout=timeout, allow_redirects=True)
    except requests.exceptions.Timeout:
        raise UploaderDownloadError(
            "下载超时，请检查网络连接或稍后重试: {}".format(url),
            url=url,
        )
    except requests.exceptions.ConnectionError:
        raise UploaderDownloadError(
            "无法连接到该地址，请确认 URL 是否公开可访问: {}".format(url),
            url=url,
        )
    except requests.RequestException as e:
        raise UploaderDownloadError(
            "下载失败: {}".format(e),
            url=url,
        )

    if not resp.ok:
        raise UploaderDownloadError(
            "URL 返回 HTTP {}，无法下载文件。请确认该地址是否公开可访问，无需登录或鉴权: {}".format(
                resp.status_code, url
            ),
            http_status=resp.status_code,
            url=url,
        )

    content_type = _extract_content_type(resp)

    # 创建临时文件，delete=False 让调用方控制删除时机
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=_tmp_suffix(url))
    size = 0
    try:
        with os.fdopen(tmp_fd, "wb") as f:
            for chunk in resp.iter_content(chunk_size=_STREAM_CHUNK_SIZE):
                if chunk:
                    f.write(chunk)
                    size += len(chunk)
    except requests.RequestException as e:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise UploaderDownloadError(
            "下载中断: {}".format(e),
            url=url,
        )
    except OSError as e:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise UploaderDownloadError(
            "临时文件写入失败: {}".format(e),
            url=url,
        )

    logger.info("[downloader] saved %d bytes to %s content_type=%s", size, tmp_path, content_type)
    return tmp_path, size, content_type


def _tmp_suffix(url: str) -> str:
    """从 URL 路径提取文件扩展名，用于临时文件后缀（方便调试）"""
    name = filename_from_url(url)
    _, ext = os.path.splitext(name)
    return ext or ""


def is_url(value: str) -> bool:
    """判断字符串是否为 http/https URL"""
    lower = (value or "").lower()
    return lower.startswith("http://") or lower.startswith("https://")


def filename_from_url(url: str) -> str:
    """从 URL 路径中提取文件名，无法提取时返回空字符串"""
    return os.path.basename(urlparse(url).path) or ""


# ── 内部辅助 ────────────────────────────────────────────────────────────────────


def _validate_scheme(url: str) -> None:
    scheme = urlparse(url).scheme.lower()
    if scheme not in _SUPPORTED_SCHEMES:
        raise UploaderDownloadError(
            f"仅支持 http:// 和 https:// 协议，不支持: {scheme or '(空)'}://",
            url=url,
        )


def _validate_no_ssrf(url: str) -> None:
    """H4: 拒绝访问私有/保留 IP，防止 SSRF。"""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if not host:
        return
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(host))
    except (OSError, ValueError):
        return  # 无法解析时让后续请求自然失败
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        raise UploaderDownloadError(
            f"不允许访问内网地址（{ip}），URL 必须指向公开可访问的资源: {url}",
            url=url,
        )


def _extract_content_type(response: requests.Response) -> str:
    """从响应 Content-Type 头提取 MIME 类型，去除参数部分。

    示例: "image/jpeg; charset=utf-8" → "image/jpeg"
    """
    raw = response.headers.get(_CONTENT_TYPE_HEADER, "")
    return raw.split(";")[0].strip()
