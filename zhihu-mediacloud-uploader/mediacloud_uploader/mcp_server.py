# -*- coding: utf-8 -*-
"""zhihu-mediacloud-uploader MCP stdio Server

启动方式：
  zhihu-mediacloud-uploader
  或：python -m mediacloud_uploader.mcp_server

凭证来源（按优先级）：
  ZHIHU_OPENAPI_APP_KEY / ZHIHU_OPENAPI_APP_SECRET
  ~/.zhihu/openapi-credentials.json

可选配置来源（按优先级）：
  ZHIHU_MEDIACLOUD_BASE_URL      — 服务地址（默认：https://openapi.zhihu.com）
  ZHIHU_MEDIACLOUD_API_TIMEOUT   — HTTP 请求超时秒数（默认：30）
  ~/.zhihu/openapi-config.json  — 使用同名 JSON key 作为环境变量缺省值
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from mediacloud_uploader import __version__
from mediacloud_uploader.client import MediaCloudUploader
from mediacloud_uploader.errors import (
    UploaderAPIError,
    UploaderAuthError,
    UploaderDownloadError,
    UploaderOSSError,
    UploaderSessionExpiredError,
    UploaderValidationError,
)
from mediacloud_uploader.models import (
    TEMPLATE_NAME_VIDEO,
    MediaType,
)

logger = logging.getLogger(__name__)

# ── 工具名 ────────────────────────────────────────────────────────────────────────

TOOL_UPLOAD_IMAGE = "upload_image"
TOOL_UPLOAD_VIDEO = "upload_video"
TOOL_UPLOAD_OBJECT = "upload_object"

# ── 环境变量 ──────────────────────────────────────────────────────────────────────

ENV_BASE_URL = "ZHIHU_MEDIACLOUD_BASE_URL"

ENV_OPENAPI_APP_KEY = "ZHIHU_OPENAPI_APP_KEY"
ENV_OPENAPI_APP_SECRET = "ZHIHU_OPENAPI_APP_SECRET"

DEFAULT_BASE_URL = "https://openapi.zhihu.com"
ENV_TIMEOUT = "ZHIHU_MEDIACLOUD_API_TIMEOUT"

DEFAULT_OPENAPI_CONFIG_FILE = "~/.zhihu/openapi-config.json"
DEFAULT_CREDENTIALS_FILE = "~/.zhihu/openapi-credentials.json"
DEFAULT_TIMEOUT = 30

# ── 上传模板默认值 ────────────────────────────────────────────────────────────────

# ── 错误类型字符串 ────────────────────────────────────────────────────────────────

_ERR_VALIDATION = "validation_error"
_ERR_AUTH = "auth_error"
_ERR_API = "api_error"
_ERR_TRANSFER = "transfer_error"
_ERR_SESSION = "session_expired"
_ERR_DOWNLOAD = "download_error"
_ERR_INTERNAL = "internal_error"


# ── 工具定义 ──────────────────────────────────────────────────────────────────────

_FILE_PATH_PROP = {
    "type": "string",
    "description": "本地文件绝对路径（与 url 二选一）",
}
_URL_PROP = {
    "type": "string",
    "description": "公开可访问的文件 URL（http:// 或 https://）。与 file_path 二选一",
}
_SCENE_NAME_PROP_IMAGE = {
    "type": "string",
    "enum": ["answer", "question", "pin", "article"],
    "description": (
        "上传内容的发布目标场景（必须与实际内容场景严格匹配）：\n"
        "  answer   — 回答：用户说「回答里」「回答配图」「这篇回答」等\n"
        "  question — 问题：用户说「问题封面」「给提问添加图片」「这个问题的图」等\n"
        "  pin      — 想法：用户说「发个想法」「想法视频」「动态」等\n"
        "  article  — 文章：用户说「文章配图」「专栏视频」「这篇文章」等\n"
        "规则：用户指令中出现上述关键词时直接使用对应值；否则必须先询问用户，不能根据上下文猜测。"
    ),
}
_SCENE_NAME_PROP_VIDEO = {
    "type": "string",
    "description": ("上传场景码（可选，默认 pin）。如用户明确指定场景码值（如「场景码：xxx」），则直接透传该值。"),
}
_SCENE_NAME_PROP_OBJECT = {
    "type": "string",
    "description": (
        "上传场景码（必填）。默认需询问用户选择 answer（回答）/ question（问题）/ pin（想法）/ article（文章）。"
        "如用户明确指定场景码值（如「场景码：xxx」），则直接透传该值。"
    ),
}
_CONTENT_TYPE_PROP = {
    "type": "string",
    "description": "MIME 类型（不填则自动检测）",
}

_TOOL_DEFINITIONS = [
    types.Tool(
        name=TOOL_UPLOAD_IMAGE,
        description=(
            "上传图片文件到知乎图片服务。支持 JPEG、PNG、WebP、HEIC、HEIF、AVIF 等常见格式。"
            "成功后返回图片 media_key 及尺寸、格式等元信息。"
            "file_path 和 url 二选一：提供本地路径或公开可访问的图片 URL。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": _FILE_PATH_PROP,
                "url": _URL_PROP,
                "scene_name": _SCENE_NAME_PROP_IMAGE,
                "content_type": _CONTENT_TYPE_PROP,
            },
            "required": ["scene_name"],
        },
    ),
    types.Tool(
        name=TOOL_UPLOAD_VIDEO,
        description=(
            "上传视频或音频文件到知乎点播云。支持大文件上传（自动处理，无需手动分片）。"
            "成功后返回视频 ID（media_key）；视频需异步转码完成后才可分发、播放。"
            "file_path 和 url 二选一：提供本地路径或公开可访问的视频 URL。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": _FILE_PATH_PROP,
                "url": _URL_PROP,
                "scene_name": _SCENE_NAME_PROP_VIDEO,
                "content_type": _CONTENT_TYPE_PROP,
            },
            "required": [],
        },
    ),
    types.Tool(
        name=TOOL_UPLOAD_OBJECT,
        description=(
            "上传任意静态文件（PDF、ZIP、二进制等）到知乎云。支持大文件上传（自动处理，无需手动分片）。"
            "成功后返回对象 key（media_key）。"
            "file_path 和 url 二选一：提供本地路径或公开可访问的文件 URL。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": _FILE_PATH_PROP,
                "url": _URL_PROP,
                "scene_name": _SCENE_NAME_PROP_OBJECT,
                "content_type": _CONTENT_TYPE_PROP,
                "template_name": {
                    "type": "string",
                    "description": (
                        "上传模板名称（必填）。不同业务场景使用不同的存储模板，"
                        "请向用户确认或查阅业务文档获取具体模板名称。\n"
                        "规则：用户未提供时，必须先询问「请提供上传模板名称（template_name）」，"
                        "不得自行猜测或填写默认值。"
                    ),
                },
            },
            "required": ["scene_name", "template_name"],
        },
    ),
]


# ── 辅助函数 ──────────────────────────────────────────────────────────────────────


def _load_credentials_from_file(path: str) -> tuple[str | None, str | None]:
    credentials_path = Path(path).expanduser()
    if not credentials_path.exists():
        return None, None
    try:
        data = json.loads(credentials_path.read_text(encoding="utf-8"))
    except OSError as exc:
        print(
            f"[zhihu-mediacloud-uploader] 读取共享凭证文件失败: {credentials_path}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(
            f"[zhihu-mediacloud-uploader] 共享凭证文件不是合法 JSON: {credentials_path}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
    if not isinstance(data, dict):
        print(
            f"[zhihu-mediacloud-uploader] 共享凭证文件内容必须是 JSON object: {credentials_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    app_key = data.get(ENV_OPENAPI_APP_KEY)
    app_secret = data.get(ENV_OPENAPI_APP_SECRET)
    return app_key, app_secret


def _load_openapi_config_from_file(path: str) -> dict[str, Any]:
    config_path = Path(path).expanduser()
    if not config_path.exists():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        print(
            f"[zhihu-mediacloud-uploader] 读取共享 OpenAPI 配置文件失败: {config_path}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(
            f"[zhihu-mediacloud-uploader] 共享 OpenAPI 配置文件不是合法 JSON: {config_path}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
    if not isinstance(data, dict):
        print(
            f"[zhihu-mediacloud-uploader] 共享 OpenAPI 配置文件内容必须是 JSON object: {config_path}",
            file=sys.stderr,
        )
        sys.exit(1)
    return data


def _has_env_value(env_name: str) -> bool:
    return os.environ.get(env_name) not in (None, "")


def _config_value(env_name: str, file_config: dict[str, Any], default: str) -> str:
    env_value = os.environ.get(env_name)
    if env_value not in (None, ""):
        return env_value
    file_value = file_config.get(env_name)
    if file_value in (None, ""):
        return default
    return str(file_value)


def _load_openapi_credentials() -> tuple[str | None, str | None, str]:
    openapi_app_key = os.environ.get(ENV_OPENAPI_APP_KEY)
    openapi_app_secret = os.environ.get(ENV_OPENAPI_APP_SECRET)
    if openapi_app_key and openapi_app_secret:
        return openapi_app_key, openapi_app_secret, f"{ENV_OPENAPI_APP_KEY}/{ENV_OPENAPI_APP_SECRET}"

    credentials_file = DEFAULT_CREDENTIALS_FILE
    file_app_key, file_app_secret = _load_credentials_from_file(credentials_file)
    return file_app_key, file_app_secret, credentials_file


def _load_config() -> dict[str, Any]:
    """加载并校验知乎 OpenAPI 凭证，缺少任一则立即退出。"""
    app_key, app_secret, credential_source = _load_openapi_credentials()
    missing = []
    if not app_key:
        missing.append("app_key")
    if not app_secret:
        missing.append("app_secret")
    if missing:
        print(
            (
                "[zhihu-mediacloud-uploader] 缺少知乎 OpenAPI 凭证: {}. "
                "请设置 ZHIHU_OPENAPI_APP_KEY/ZHIHU_OPENAPI_APP_SECRET，或写入 ~/.zhihu/openapi-credentials.json"
            ).format(", ".join(missing)),
            file=sys.stderr,
        )
        print(f"[zhihu-mediacloud-uploader] 当前凭证来源: {credential_source}", file=sys.stderr)
        sys.exit(1)

    needs_file_config = not _has_env_value(ENV_BASE_URL) or not _has_env_value(ENV_TIMEOUT)
    openapi_config = _load_openapi_config_from_file(DEFAULT_OPENAPI_CONFIG_FILE) if needs_file_config else {}
    timeout_value = _config_value(ENV_TIMEOUT, openapi_config, str(DEFAULT_TIMEOUT))

    return {
        "base_url": _config_value(ENV_BASE_URL, openapi_config, DEFAULT_BASE_URL),
        "app_key": app_key,
        "app_secret": app_secret,
        # R3: 非整数 ZHIHU_MEDIACLOUD_API_TIMEOUT 不应使 server 启动崩溃
        "timeout": _parse_timeout(timeout_value),
    }


def _parse_timeout(value: str) -> int:
    """R3: 安全解析超时秒数，非整数时打印警告并返回默认值。"""
    try:
        return int(value)
    except ValueError:
        print(
            f"[zhihu-mediacloud-uploader] {ENV_TIMEOUT} 值无效（{value!r}），使用默认值 {DEFAULT_TIMEOUT}s",
            file=sys.stderr,
        )
        return DEFAULT_TIMEOUT


def _ok_result(data: dict) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))]


def _error_result(error_type: str, message: str) -> list[types.TextContent]:
    return _ok_result({"success": False, "error_type": error_type, "message": message})


def upload(uploader: MediaCloudUploader, arguments: dict, media_type: str) -> list[types.TextContent]:
    """MCP 工具适配层：参数提取 → 调用 SDK → 结果/异常转为 TextContent。"""
    file_path = arguments.get("file_path") or None
    url = arguments.get("url") or None
    content_type = arguments.get("content_type", "")
    file_name = arguments.get("file_name", "")

    try:
        if media_type == MediaType.IMAGE:
            scene_name = arguments.get("scene_name", "")
            resp = uploader.upload_image(
                file_path=file_path,
                url=url,
                scene_name=scene_name,
                content_type=content_type,
                file_name=file_name,
            )
        elif media_type == MediaType.VIDEO:
            scene_name = arguments.get("scene_name", "pin")
            template_name = arguments.get("template_name", TEMPLATE_NAME_VIDEO)
            resp = uploader.upload_video(
                file_path=file_path,
                url=url,
                scene_name=scene_name,
                content_type=content_type,
                file_name=file_name,
                template_name=template_name,
            )
        else:
            scene_name = arguments.get("scene_name", "")
            template_name = arguments.get("template_name", "")
            if not template_name:
                return _error_result(
                    _ERR_VALIDATION,
                    "请提供 template_name 参数。不同业务场景使用不同的存储模板，"
                    "请向用户确认具体的上传模板名称后再调用。",
                )
            resp = uploader.upload_object(
                file_path=file_path,
                url=url,
                scene_name=scene_name,
                template_name=template_name,
                content_type=content_type,
                file_name=file_name,
            )

    except UploaderValidationError as e:
        return _error_result(_ERR_VALIDATION, e.message)
    except UploaderAuthError:
        return _error_result(_ERR_AUTH, "鉴权失败，请检查共享凭证文件或 ZHIHU_OPENAPI_APP_KEY / ZHIHU_OPENAPI_APP_SECRET 配置")
    except UploaderAPIError as e:
        return _error_result(_ERR_API, "服务端错误 (code={}): {}".format(e.code, e.message))
    except UploaderOSSError as e:
        return _error_result(_ERR_TRANSFER, "文件上传失败: {}".format(e.message))
    except UploaderSessionExpiredError:
        return _error_result(_ERR_SESSION, "上传会话过期，请重试")
    except UploaderDownloadError as e:
        return _error_result(_ERR_DOWNLOAD, e.message)
    except Exception:
        logger.exception("unexpected error during upload")
        return _error_result(_ERR_INTERNAL, "内部错误，请稍后重试")

    # ── 构造结果 ──────────────────────────────────────────────────────────────────
    result: dict = {
        "success": resp.is_success,
        "media_type": resp.media_type,
        "media_key": resp.media_key,
        "space_name": resp.space_name,
        "upload_result": resp.upload_result,
    }
    if resp.media_meta:
        result["media_meta"] = {
            "width": resp.media_meta.width,
            "height": resp.media_meta.height,
            "format": resp.media_meta.format,
            "size": resp.media_meta.size,
        }
    if resp.media_type == MediaType.IMAGE and resp.media_url is not None:
        result["media_url"] = {
            "primary": resp.media_url.primary,
            "backups": resp.media_url.backups,
        }
    # ── [WATERMARK PATCH BEGIN] ───────────────────────────────────────────────────
    if resp.extra is not None:
        result["extra"] = {
            "watermark_image_key": resp.extra.watermark_image_key,
            "watermark_image_url": {
                "primary": resp.extra.watermark_image_url.primary,
                "backups": resp.extra.watermark_image_url.backups,
            },
        }
    # ── [WATERMARK PATCH END] ─────────────────────────────────────────────────────

    return _ok_result(result)


# ── Server 构建 ───────────────────────────────────────────────────────────────────


def _build_server(uploader: MediaCloudUploader) -> Server:
    server = Server("zhihu-mediacloud-uploader")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return _TOOL_DEFINITIONS

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        if name == TOOL_UPLOAD_IMAGE:
            return await asyncio.to_thread(
                upload,
                uploader,
                arguments,
                MediaType.IMAGE,
            )
        if name == TOOL_UPLOAD_VIDEO:
            return await asyncio.to_thread(
                upload,
                uploader,
                arguments,
                MediaType.VIDEO,
            )
        if name == TOOL_UPLOAD_OBJECT:
            return await asyncio.to_thread(
                upload,
                uploader,
                arguments,
                MediaType.OBJECT,
            )
        return _error_result(_ERR_INTERNAL, "未知工具: {}".format(name))

    return server


# ── 入口 ──────────────────────────────────────────────────────────────────────────


async def _async_main() -> None:
    cfg = _load_config()
    uploader = MediaCloudUploader(
        app_key=cfg["app_key"],
        app_secret=cfg["app_secret"],
        base_url=cfg["base_url"],
        timeout=cfg["timeout"],
    )
    server = _build_server(uploader)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    if _handle_cli_args(sys.argv[1:]):
        return
    asyncio.run(_async_main())


def _print_usage() -> None:
    print(
        "Usage: zhihu-mediacloud-uploader [--version|--help]\n\n"
        "Without options, start the MCP stdio server.\n"
        "--version, -V  Print version and exit without loading credentials.\n"
        "--help, -h     Print this help and exit."
    )


def _handle_cli_args(argv: list[str]) -> bool:
    if not argv:
        return False
    if argv in (["--version"], ["-V"]):
        print(f"zhihu-mediacloud-uploader {__version__}")
        return True
    if argv in (["--help"], ["-h"]):
        _print_usage()
        return True

    print(f"[zhihu-mediacloud-uploader] unsupported arguments: {' '.join(argv)}", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
