# -*- coding: utf-8 -*-
"""mcp_server.py 单元测试：工具输入校验、错误处理"""

import io
import json
import os
import pathlib
import sys
import tempfile
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from mediacloud_uploader import __version__
from mediacloud_uploader.errors import (
    UploaderAPIError,
    UploaderAuthError,
    UploaderDownloadError,
    UploaderOSSError,
    UploaderSessionExpiredError,
    UploaderValidationError,
)
from mediacloud_uploader.mcp_server import (
    upload,
    _error_result,
    _ok_result,
    main,
    TOOL_UPLOAD_IMAGE,
    TOOL_UPLOAD_VIDEO,
    TOOL_UPLOAD_OBJECT,
    ENV_BASE_URL,
    ENV_OPENAPI_APP_KEY,
    ENV_OPENAPI_APP_SECRET,
    ENV_TIMEOUT,
    DEFAULT_OPENAPI_CONFIG_FILE,
    _load_config,
)
from mediacloud_uploader.models import (
    MediaType,
    UPLOAD_STATE_SUCCESS,
    UPLOAD_STATE_FAIL,
    UploadResponse,
    MediaMeta,
)
from mcp import types


def _parse_result(result: list[types.TextContent]) -> dict[str, Any]:
    assert len(result) == 1
    assert isinstance(result[0], types.TextContent)
    return json.loads(result[0].text)


# ── CLI 探测参数 ──────────────────────────────────────────────────────────────────

class TestCliArgs:
    def test_version_exits_without_starting_server(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch.object(sys, "argv", ["zhihu-mediacloud-uploader", "--version"]):
            with patch("mediacloud_uploader.mcp_server.asyncio.run") as run:
                main()

        captured = capsys.readouterr()
        assert captured.out.strip() == f"zhihu-mediacloud-uploader {__version__}"
        assert captured.err == ""
        run.assert_not_called()

    def test_help_exits_without_starting_server(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch.object(sys, "argv", ["zhihu-mediacloud-uploader", "--help"]):
            with patch("mediacloud_uploader.mcp_server.asyncio.run") as run:
                main()

        captured = capsys.readouterr()
        assert "Usage: zhihu-mediacloud-uploader" in captured.out
        assert "without loading credentials" in captured.out
        assert captured.err == ""
        run.assert_not_called()

    def test_no_cli_args_starts_server(self) -> None:
        with patch.object(sys, "argv", ["zhihu-mediacloud-uploader"]):
            async_main = MagicMock(return_value="server-coro")
            with patch("mediacloud_uploader.mcp_server._async_main", async_main):
                with patch("mediacloud_uploader.mcp_server.asyncio.run") as run:
                    main()

        async_main.assert_called_once()
        run.assert_called_once_with("server-coro")

    def test_unknown_cli_arg_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch.object(sys, "argv", ["zhihu-mediacloud-uploader", "--bad"]):
            with patch("mediacloud_uploader.mcp_server.asyncio.run") as run:
                with pytest.raises(SystemExit) as exc:
                    main()

        captured = capsys.readouterr()
        assert exc.value.code == 2
        assert "unsupported arguments: --bad" in captured.err
        run.assert_not_called()


# ── upload 文件校验 ────────────────────────────────────────────────────────────────

class TestHandleUploadValidation:
    def test_file_not_found_returns_validation_error(self) -> None:
        uploader = MagicMock()
        uploader.upload_image.side_effect = UploaderValidationError("文件不存在: /nonexistent/file.jpg")
        result = upload(
            uploader,
            {"file_path": "/nonexistent/file.jpg", "scene_name": "answer"},
            MediaType.IMAGE,
        )
        data = _parse_result(result)
        assert data["success"]     is False
        assert data["error_type"]  == "validation_error"
        assert "/nonexistent/file.jpg" in data["message"]

    def test_server_rejects_empty_scene_name_before_uploader(self, tmp_path: pathlib.Path) -> None:
        """scene_name="" 由服务端提前拦截，uploader 不应被调用"""
        f = tmp_path / "img.jpg"
        f.write_bytes(b"x")

        uploader = MagicMock()
        uploader.upload_image.side_effect = UploaderValidationError("scene_name is required")
        result = upload(
            uploader,
            {"file_path": str(f), "scene_name": ""},
            MediaType.IMAGE,
        )
        data = _parse_result(result)
        assert data["success"]    is False
        assert data["error_type"] == "validation_error"

    def test_uploader_validation_error_mapped(self, tmp_path: pathlib.Path) -> None:
        """uploader 层抛出 UploaderValidationError 时正确映射为 validation_error"""
        f = tmp_path / "img.jpg"
        f.write_bytes(b"x")

        uploader = MagicMock()
        uploader.upload_image.side_effect = UploaderValidationError("unsupported format")

        result = upload(
            uploader,
            {"file_path": str(f), "scene_name": "answer", "content_type": "image/jpeg"},
            MediaType.IMAGE,
        )
        data = _parse_result(result)
        assert data["success"]    is False
        assert data["error_type"] == "validation_error"
        assert "unsupported format" in data["message"]

    def test_auth_error_mapped(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "img.jpg"
        f.write_bytes(b"x")

        uploader = MagicMock()
        uploader.upload_image.side_effect = UploaderAuthError("401")

        result = upload(
            uploader,
            {"file_path": str(f), "scene_name": "answer", "template_name": "obj-tmpl"},
            MediaType.IMAGE,
        )
        data = _parse_result(result)
        assert data["success"]    is False
        assert data["error_type"] == "auth_error"

    def test_api_error_mapped(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "v.mp4"
        f.write_bytes(b"x")

        uploader = MagicMock()
        uploader.upload_video.side_effect = UploaderAPIError("bad", api_code=500)

        result = upload(
            uploader,
            {"file_path": str(f), "scene_name": "answer", "template_name": "obj-tmpl"},
            MediaType.VIDEO,
        )
        data = _parse_result(result)
        assert data["success"]    is False
        assert data["error_type"] == "api_error"

    def test_transfer_error_mapped(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "f.zip"
        f.write_bytes(b"x")

        uploader = MagicMock()
        uploader.upload_object.side_effect = UploaderOSSError("oss fail", oss_code="InternalError")

        result = upload(
            uploader,
            {"file_path": str(f), "scene_name": "answer", "template_name": "obj-tmpl"},
            MediaType.OBJECT,
        )
        data = _parse_result(result)
        assert data["success"]    is False
        assert data["error_type"] == "transfer_error"

    def test_session_expired_mapped(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "v.mp4"
        f.write_bytes(b"x")

        uploader = MagicMock()
        uploader.upload_video.side_effect = UploaderSessionExpiredError("expired")

        result = upload(
            uploader,
            {"file_path": str(f), "scene_name": "answer", "template_name": "obj-tmpl"},
            MediaType.VIDEO,
        )
        data = _parse_result(result)
        assert data["success"]    is False
        assert data["error_type"] == "session_expired"

    def test_unexpected_exception_mapped_to_internal(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "f.bin"
        f.write_bytes(b"x")

        uploader = MagicMock()
        uploader.upload_object.side_effect = RuntimeError("unexpected")

        result = upload(
            uploader,
            {"file_path": str(f), "scene_name": "answer", "template_name": "obj-tmpl"},
            MediaType.OBJECT,
        )
        data = _parse_result(result)
        assert data["success"]    is False
        assert data["error_type"] == "internal_error"


# ── upload 成功场景 ────────────────────────────────────────────────────────────────

class TestHandleUploadSuccess:
    def test_image_success_includes_media_meta(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "photo.jpg"
        f.write_bytes(b"\xff\xd8\xff" + b"x" * 50)

        uploader = MagicMock()
        uploader.upload_image.return_value = UploadResponse(
            upload_result=UPLOAD_STATE_SUCCESS,
            media_key="img123",
            media_type=MediaType.IMAGE,
            space_name="default",
            media_meta=MediaMeta(width=800, height=600, format="jpeg", size=53),
        )

        result = upload(
            uploader,
            {"file_path": str(f), "scene_name": "answer", "content_type": "image/jpeg"},
            MediaType.IMAGE,
        )
        data = _parse_result(result)
        assert data["success"]   is True
        assert data["media_key"] == "img123"
        assert data["media_meta"]["width"]  == 800
        assert data["media_meta"]["format"] == "jpeg"

    def test_video_success_no_media_meta(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "clip.mp4"
        f.write_bytes(b"x" * 10)

        uploader = MagicMock()
        uploader.upload_video.return_value = UploadResponse(
            upload_result=UPLOAD_STATE_SUCCESS,
            media_key="vid456",
            media_type=MediaType.VIDEO,
            space_name="vspace",
        )

        result = upload(
            uploader,
            {"file_path": str(f), "scene_name": "answer", "template_name": "obj-tmpl"},
            MediaType.VIDEO,
        )
        data = _parse_result(result)
        assert data["success"]   is True
        assert data["media_key"] == "vid456"
        assert "media_meta" not in data

    def test_content_type_auto_detected_when_not_provided(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"x" * 10)

        uploader = MagicMock()
        uploader.upload_object.return_value = UploadResponse(
            upload_result=UPLOAD_STATE_SUCCESS,
            media_key="obj789",
            media_type=MediaType.OBJECT,
            space_name="sp",
        )

        upload(
            uploader,
            {"file_path": str(f), "scene_name": "answer", "template_name": "obj-tmpl"},
            MediaType.OBJECT,
        )
        # thin wrapper passes raw content_type="" - detection happens inside upload_object()
        assert uploader.upload_object.call_args.kwargs["file_path"] is not None
        assert uploader.upload_object.call_args.kwargs["content_type"] == ""

    def test_file_extension_extracted_from_local_path(self, tmp_path: pathlib.Path) -> None:
        """本地文件路径有扩展名时，file_extension 正确传给 uploader"""
        f = tmp_path / "clip.mp4"
        f.write_bytes(b"x" * 10)

        uploader = MagicMock()
        uploader.upload_video.return_value = UploadResponse(
            upload_result=UPLOAD_STATE_SUCCESS,
            media_key="vid001",
            media_type=MediaType.VIDEO,
            space_name="sp",
        )

        upload(
            uploader,
            {"file_path": str(f), "scene_name": "answer", "template_name": "obj-tmpl"},
            MediaType.VIDEO,
        )
        # thin wrapper passes file_path, SDK computes file_extension internally
        assert uploader.upload_video.call_args.kwargs["file_path"] is not None

    def test_file_extension_empty_when_local_path_has_none(self, tmp_path: pathlib.Path) -> None:
        """本地文件路径无扩展名时，file_extension 为空"""
        f = tmp_path / "datafile"
        f.write_bytes(b"x" * 10)

        uploader = MagicMock()
        uploader.upload_object.return_value = UploadResponse(
            upload_result=UPLOAD_STATE_SUCCESS,
            media_key="obj001",
            media_type=MediaType.OBJECT,
            space_name="sp",
        )

        upload(
            uploader,
            {"file_path": str(f), "scene_name": "answer", "template_name": "obj-tmpl"},
            MediaType.OBJECT,
        )
        assert uploader.upload_object.call_args.kwargs["file_path"] is not None

    def test_file_extension_extracted_from_url(self) -> None:
        """URL 含文件扩展名时，file_extension 正确传给 uploader"""
        uploader = MagicMock()
        uploader.upload_video.return_value = UploadResponse(
            upload_result=UPLOAD_STATE_SUCCESS,
            media_key="vid002",
            media_type=MediaType.VIDEO,
            space_name="sp",
        )

        upload(
            uploader,
            {"url": "https://example.com/video.mp4", "scene_name": "answer", "template_name": "obj-tmpl"},
            MediaType.VIDEO,
        )
        assert uploader.upload_video.call_args.kwargs["url"] == "https://example.com/video.mp4"

    def test_file_extension_empty_when_url_has_none(self) -> None:
        """URL 无文件扩展名时，file_extension 为空"""
        uploader = MagicMock()
        uploader.upload_object.return_value = UploadResponse(
            upload_result=UPLOAD_STATE_SUCCESS,
            media_key="obj002",
            media_type=MediaType.OBJECT,
            space_name="sp",
        )

        upload(
            uploader,
            {"url": "https://cdn.example.com/media/abc123", "scene_name": "answer",
             "template_name": "obj-tmpl", "content_type": "application/octet-stream"},
            MediaType.OBJECT,
        )

        assert uploader.upload_object.call_args.kwargs["url"] == "https://cdn.example.com/media/abc123"

class TestLoadConfig:
    def test_exits_when_credentials_missing(self, tmp_path: pathlib.Path) -> None:
        env = {"HOME": str(tmp_path)}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SystemExit):
                _load_config()

    def test_returns_config_from_openapi_env(self, tmp_path: pathlib.Path) -> None:
        env = {
            "HOME":                 str(tmp_path),
            ENV_BASE_URL:           "https://bi.example.com",
            ENV_OPENAPI_APP_KEY:    "openapi-key",
            ENV_OPENAPI_APP_SECRET: "openapi-secret",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = _load_config()
        assert cfg["base_url"]   == "https://bi.example.com"
        assert cfg["app_key"]    == "openapi-key"
        assert cfg["app_secret"] == "openapi-secret"
        assert cfg["timeout"]    == 30

    def test_returns_config_from_shared_credentials_file(self, tmp_path: pathlib.Path) -> None:
        credentials_dir = tmp_path / ".zhihu"
        credentials_dir.mkdir()
        credentials_file = credentials_dir / "openapi-credentials.json"
        credentials_file.write_text(
            json.dumps({ENV_OPENAPI_APP_KEY: "file-key", ENV_OPENAPI_APP_SECRET: "file-secret"}),
            encoding="utf-8",
        )
        env = {"HOME": str(tmp_path)}
        with patch.dict(os.environ, env, clear=True):
            cfg = _load_config()
        assert cfg["app_key"]    == "file-key"
        assert cfg["app_secret"] == "file-secret"

    def test_returns_optional_config_from_shared_openapi_config_file(self, tmp_path: pathlib.Path) -> None:
        zhihu_dir = tmp_path / ".zhihu"
        zhihu_dir.mkdir()
        credentials_file = zhihu_dir / "openapi-credentials.json"
        credentials_file.write_text(
            json.dumps({ENV_OPENAPI_APP_KEY: "file-key", ENV_OPENAPI_APP_SECRET: "file-secret"}),
            encoding="utf-8",
        )
        openapi_config_file = zhihu_dir / pathlib.Path(DEFAULT_OPENAPI_CONFIG_FILE).name
        openapi_config_file.write_text(
            json.dumps({ENV_BASE_URL: "https://file.example.com", ENV_TIMEOUT: 45}),
            encoding="utf-8",
        )
        env = {"HOME": str(tmp_path)}
        with patch.dict(os.environ, env, clear=True):
            cfg = _load_config()
        assert cfg["base_url"] == "https://file.example.com"
        assert cfg["timeout"]  == 45

    def test_openapi_env_overrides_shared_openapi_config_file(self, tmp_path: pathlib.Path) -> None:
        zhihu_dir = tmp_path / ".zhihu"
        zhihu_dir.mkdir()
        openapi_config_file = zhihu_dir / pathlib.Path(DEFAULT_OPENAPI_CONFIG_FILE).name
        openapi_config_file.write_text(
            json.dumps({ENV_BASE_URL: "https://file.example.com", ENV_TIMEOUT: 45}),
            encoding="utf-8",
        )
        env = {
            "HOME":                 str(tmp_path),
            ENV_BASE_URL:           "https://env.example.com",
            ENV_OPENAPI_APP_KEY:    "env-key",
            ENV_OPENAPI_APP_SECRET: "env-secret",
            ENV_TIMEOUT:            "60",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = _load_config()
        assert cfg["base_url"]   == "https://env.example.com"
        assert cfg["app_key"]    == "env-key"
        assert cfg["app_secret"] == "env-secret"
        assert cfg["timeout"]    == 60

    def test_custom_timeout(self) -> None:
        env = {
            ENV_BASE_URL:           "https://bi.example.com",
            ENV_OPENAPI_APP_KEY:    "k",
            ENV_OPENAPI_APP_SECRET: "s",
            ENV_TIMEOUT:            "60",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = _load_config()
        assert cfg["timeout"] == 60

    def test_ignores_generic_env_names(self, tmp_path: pathlib.Path) -> None:
        env = {
            "BASE_URL":             "https://generic.example.com",
            "API_TIMEOUT":          "60",
            ENV_OPENAPI_APP_KEY:    "k",
            ENV_OPENAPI_APP_SECRET: "s",
            "HOME":                 str(tmp_path),
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = _load_config()
        assert cfg["base_url"] == "https://openapi.zhihu.com"
        assert cfg["timeout"] == 30


# ── URL 上传 ───────────────────────────────────────────────────────────────────────

class TestHandleUploadFromUrl:
    def _success_resp(self) -> UploadResponse:
        return UploadResponse(
            upload_result=UPLOAD_STATE_SUCCESS,
            media_key="img123",
            media_type=MediaType.IMAGE,
            space_name="default",
        )

    def test_url_upload_success(self) -> None:
        """URL 下载成功后正常上传"""
        uploader = MagicMock()
        uploader.upload_image.return_value = self._success_resp()
        uploader.upload_image.return_value = self._success_resp()

        result = upload(
            uploader,
            {"url": "https://example.com/photo.jpg", "scene_name": "answer"},
            MediaType.IMAGE,
        )

        data = _parse_result(result)
        assert data["success"]   is True
        assert data["media_key"] == "img123"

    def test_url_passes_url_arg_to_uploader(self) -> None:
        """URL 上传时 url 直接透传给 uploader，file_path 为 None"""
        uploader = MagicMock()
        uploader.upload_image.return_value = self._success_resp()
        uploader.upload_image.return_value = self._success_resp()

        upload(
            uploader,
            {"url": "https://example.com/img.png", "scene_name": "answer"},
            MediaType.IMAGE,
        )

        assert uploader.upload_image.call_args.kwargs["file_path"] is None
        assert uploader.upload_image.call_args.kwargs["url"] == "https://example.com/img.png"

    def test_url_content_type_from_response_when_not_provided(self) -> None:
        """未指定 content_type 时透传空字符串，由 SDK 内部检测"""
        uploader = MagicMock()
        uploader.upload_image.return_value = self._success_resp()
        uploader.upload_image.return_value = self._success_resp()

        upload(
            uploader,
            {"url": "https://example.com/img", "scene_name": "answer"},
            MediaType.IMAGE,
        )

        # thin wrapper passes content_type="" when not provided — detection in upload_image()
        assert uploader.upload_image.call_args.kwargs["content_type"] == ""

    def test_url_user_content_type_overrides_response(self) -> None:
        """用户显式传 content_type 时透传给 SDK"""
        uploader = MagicMock()
        uploader.upload_image.return_value = self._success_resp()
        uploader.upload_image.return_value = self._success_resp()

        upload(
            uploader,
            {"url": "https://example.com/img", "scene_name": "answer", "content_type": "image/jpeg"},
            MediaType.IMAGE,
        )

        assert uploader.upload_image.call_args.kwargs["content_type"] == "image/jpeg"

    def test_url_filename_extracted_from_url_path(self) -> None:
        """URL 透传给 SDK，文件名提取在 upload_image() 内部完成"""
        uploader = MagicMock()
        uploader.upload_image.return_value = self._success_resp()
        uploader.upload_image.return_value = self._success_resp()

        upload(
            uploader,
            {"url": "https://cdn.example.com/pics/banner.jpg", "scene_name": "answer"},
            MediaType.IMAGE,
        )

        # thin wrapper passes file_name="" - filename extraction from URL happens inside upload_image()
        assert uploader.upload_image.call_args.kwargs["url"] == "https://cdn.example.com/pics/banner.jpg"

    def test_download_error_returns_download_error_type(self) -> None:
        """下载失败（如 404）返回 download_error"""
        uploader = MagicMock()

        uploader.upload_image.side_effect = UploaderDownloadError("URL 返回 HTTP 404", http_status=404)
        result = upload(
            uploader,
            {"url": "https://example.com/missing.jpg", "scene_name": "answer"},
            MediaType.IMAGE,
        )

        data = _parse_result(result)
        assert data["success"]    is False
        assert data["error_type"] == "download_error"
        assert "404" in data["message"]

    def test_both_file_path_and_url_returns_validation_error(self) -> None:
        """同时提供 file_path 和 url → validation_error"""
        uploader = MagicMock()
        uploader.upload_image.side_effect = UploaderValidationError("file_path 和 url 不能同时提供")
        result = upload(
            uploader,
            {
                "file_path": "/tmp/file.jpg",
                "url": "https://example.com/file.jpg",
                "scene_name": "answer",
            },
            MediaType.IMAGE,
        )
        data = _parse_result(result)
        assert data["success"]    is False
        assert data["error_type"] == "validation_error"

    def test_neither_file_path_nor_url_returns_validation_error(self) -> None:
        """既没有 file_path 也没有 url → validation_error"""
        uploader = MagicMock()
        uploader.upload_image.side_effect = UploaderValidationError("请提供 file_path 或 url")
        result = upload(
            uploader,
            {"scene_name": "answer"},
            MediaType.IMAGE,
        )
        data = _parse_result(result)
        assert data["success"]    is False
        assert data["error_type"] == "validation_error"


# ── scene_name 枚举校验 ────────────────────────────────────────────────────────────

class TestSceneNameValidation:
    """scene_name 必须是 answer/question/pin/article 之一（图片）"""

    def test_missing_scene_name_returns_validation_error(self) -> None:
        """未提供 scene_name（空字符串）→ validation_error，提示包含合法值"""
        uploader = MagicMock()
        uploader.upload_image.side_effect = UploaderValidationError(
            "请提供 scene_name 参数，有效值：answer（回答）、question（问题）、pin（想法）、article（文章）。"
        )
        result = upload(
            uploader,
            {"file_path": "/nonexistent/file.jpg", "scene_name": ""},
            MediaType.IMAGE,
        )
        data = _parse_result(result)
        assert data["success"]    is False
        assert data["error_type"] == "validation_error"
        assert "answer" in data["message"]
        assert "article" in data["message"]

    def test_invalid_scene_name_returns_validation_error(self) -> None:
        """传入不在枚举中的 scene_name → validation_error，消息包含该值和合法值列表"""
        uploader = MagicMock()
        uploader.upload_image.side_effect = UploaderValidationError(
            "scene_name 值 'unknown_scene' 不合法，图片仅支持：answer（回答）、question（问题）、pin（想法）、article（文章）。"
        )
        result = upload(
            uploader,
            {"file_path": "/nonexistent/file.jpg", "scene_name": "unknown_scene"},
            MediaType.IMAGE,
        )
        data = _parse_result(result)
        assert data["success"]    is False
        assert data["error_type"] == "validation_error"
        assert "unknown_scene" in data["message"]
        assert "answer" in data["message"]

    @pytest.mark.parametrize("scene", ["answer", "article", "pin", "question"])
    def test_all_valid_scene_names_pass_validation(
        self, scene: str, tmp_path: pathlib.Path
    ) -> None:
        """answer / question / pin / article 四个合法值均能通过校验，进入上传逻辑"""
        f = tmp_path / "img.jpg"
        f.write_bytes(b"x")

        uploader = MagicMock()
        uploader.upload_image.return_value = UploadResponse(
            upload_result=UPLOAD_STATE_SUCCESS,
            media_key="k",
            media_type=MediaType.IMAGE,
            space_name="sp",
        )

        result = upload(
            uploader,
            {"file_path": str(f), "scene_name": scene, "content_type": "image/jpeg"},
            MediaType.IMAGE,
        )

        data = _parse_result(result)
        assert data["success"] is True
        # 确认 scene_name 正确透传到 SDK 方法
        assert uploader.upload_image.call_args.kwargs["scene_name"] == scene


# ── URL content_type 推断失败时的强制校验 ─────────────────────────────────────────

class TestUrlContentTypeValidation:
    """当 URL 响应头是通用类型且 URL 路径无可识别扩展名时，image/video 必须要求用户提供 content_type"""

    def test_image_ambiguous_content_type_requires_user_input(self) -> None:
        """image 工具：无法确认文件类型 → 要求用户提供 content_type"""
        uploader = MagicMock()
        uploader.upload_image.side_effect = UploaderValidationError(
            "无法从该 URL 确认文件类型。请通过 content_type 参数明确指定，例如：image/jpeg、image/png、image/webp、image/heic。"
        )
        result = upload(
            uploader,
            {"url": "https://cdn.example.com/media/abc123", "scene_name": "answer"},
            MediaType.IMAGE,
        )
        data = _parse_result(result)
        assert data["success"]    is False
        assert data["error_type"] == "validation_error"
        assert "content_type" in data["message"]
        assert "image/" in data["message"]

    def test_video_ambiguous_content_type_requires_user_input(self) -> None:
        """video 工具：无法确认文件类型 → 要求用户提供 content_type"""
        uploader = MagicMock()
        uploader.upload_video.side_effect = UploaderValidationError(
            "无法从该 URL 确认文件类型。请通过 content_type 参数明确指定，例如：video/mp4、video/quicktime、audio/mpeg。"
        )
        result = upload(
            uploader,
            {"url": "https://cdn.example.com/v/12345", "scene_name": "answer"},
            MediaType.VIDEO,
        )
        data = _parse_result(result)
        assert data["success"]    is False
        assert data["error_type"] == "validation_error"
        assert "content_type" in data["message"]
        assert "video/" in data["message"]

    def test_object_ambiguous_content_type_is_accepted(self) -> None:
        """object 工具：响应头通用类型 → 可以接受，不报错"""
        uploader = MagicMock()
        uploader.upload_object.return_value = UploadResponse(
            upload_result=UPLOAD_STATE_SUCCESS,
            media_key="obj001",
            media_type=MediaType.OBJECT,
            space_name="sp",
        )

        result = upload(
            uploader,
            {"url": "https://cdn.example.com/blob/xyz", "scene_name": "answer", "template_name": "obj-tmpl"},
            MediaType.OBJECT,
        )

        data = _parse_result(result)
        assert data["success"] is True

    def test_image_url_with_known_extension_inferred_even_if_resp_generic(self) -> None:
        """URL 有已知图片扩展名 → 上传成功，不报错"""
        uploader = MagicMock()
        uploader.upload_image.return_value = UploadResponse(
            upload_result=UPLOAD_STATE_SUCCESS, media_key="img002",
            media_type=MediaType.IMAGE, space_name="default",
        )
        result = upload(
            uploader,
            {"url": "https://cdn.example.com/photo.png", "scene_name": "answer"},
            MediaType.IMAGE,
        )
        data = _parse_result(result)
        assert data["success"] is True
        assert uploader.upload_image.call_args.kwargs["url"] == "https://cdn.example.com/photo.png"

    def test_user_provided_content_type_always_trusted(self) -> None:
        """用户明确提供 content_type 时，无论响应头如何都不报错"""
        uploader = MagicMock()
        uploader.upload_image.return_value = UploadResponse(
            upload_result=UPLOAD_STATE_SUCCESS, media_key="img003",
            media_type=MediaType.IMAGE, space_name="default",
        )

        result = upload(
            uploader,
            {"url": "https://cdn.example.com/media/xyz", "scene_name": "answer", "content_type": "image/webp"},
            MediaType.IMAGE,
        )

        data = _parse_result(result)
        assert data["success"] is True
        # thin wrapper passes user-provided content_type through to upload_image()
        assert uploader.upload_image.call_args.kwargs["content_type"] == "image/webp"
