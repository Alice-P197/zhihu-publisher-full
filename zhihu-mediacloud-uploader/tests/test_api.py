# -*- coding: utf-8 -*-
"""api.py 单元测试：重点验证请求构造和响应解析"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from mediacloud_uploader.api import MediaAPIClient
from mediacloud_uploader.models import (
    ApplyUploadRequest,
    ApplyUploadResponse,
    CommitUploadRequest,
    CommitUploadResponse,
    CLIENT_UPLOAD_STATE_SUCCESS,
    ImageProcessResultResponse,
    MediaType,
    UPLOAD_STATE_SUCCESS,
)
from mediacloud_uploader.errors import UploaderAPIError, UploaderAuthError


def _make_client() -> MediaAPIClient:
    return MediaAPIClient(
        base_url="https://bi.example.com",
        app_key="testkey",
        app_secret="testsecret",
    )


def _mock_request(client: MediaAPIClient, response_data: Any, status_code: int = 200) -> MagicMock:
    """用给定的 data 构造 mock response，patch client._session.request。"""
    mock_resp = MagicMock()
    mock_resp.ok = (status_code < 400)
    mock_resp.status_code = status_code
    mock_resp.json.return_value = response_data
    mock_resp.text = json.dumps(response_data)
    client._session.request = MagicMock(return_value=mock_resp)
    return client._session.request


# ── ApplyUpload 请求头 ────────────────────────────────────────────────────────────

class TestApplyUploadRequest:
    def test_content_type_in_header_not_body(self) -> None:
        """B1: content_type 必须在 header X-Upload-Content-Type，不得在 body"""
        client = _make_client()
        req = ApplyUploadRequest(
            media_type=MediaType.VIDEO, template_name="test-tmpl", scene_name="test",
            content_type="video/mp4",
        )
        mock_req = _mock_request(client, {
            "upload_state": "UPLOADING", "session_key": "sk",
            "upload_media": {"key": "", "commit_address": "", "processes": ""},
        })
        client.apply_upload(req)

        _, kwargs = mock_req.call_args
        sent_headers = kwargs.get("headers", {})
        sent_body    = json.loads(kwargs.get("data", "{}"))

        assert sent_headers.get("X-Upload-Content-Type") == "video/mp4"
        assert "content_type" not in sent_body

    def test_content_hash_sent_for_image(self) -> None:
        """B2: 图片上传必须发送 X-Upload-Content-Hash header"""
        client = _make_client()
        req = ApplyUploadRequest(
            media_type=MediaType.IMAGE, template_name="test-tmpl", scene_name="test",
            content_type="image/jpeg", content_hash="abc123def456",
        )
        mock_req = _mock_request(client, {
            "upload_state": "UPLOADING", "session_key": "sk",
            "upload_media": {"key": "", "commit_address": "", "processes": ""},
        })
        client.apply_upload(req)

        _, kwargs = mock_req.call_args
        sent_headers = kwargs.get("headers", {})
        assert sent_headers.get("X-Upload-Content-Hash") == "abc123def456"

    def test_content_hash_not_sent_when_empty(self) -> None:
        """非图片（或未填 hash）时不发送 X-Upload-Content-Hash"""
        client = _make_client()
        req = ApplyUploadRequest(
            media_type=MediaType.VIDEO, template_name="test-tmpl", scene_name="test",
            content_type="video/mp4", content_hash="",
        )
        mock_req = _mock_request(client, {
            "upload_state": "UPLOADING", "session_key": "sk",
            "upload_media": {"key": "", "commit_address": "", "processes": ""},
        })
        client.apply_upload(req)

        _, kwargs = mock_req.call_args
        sent_headers = kwargs.get("headers", {})
        assert "X-Upload-Content-Hash" not in sent_headers

    def test_scene_name_in_header(self) -> None:
        client = _make_client()
        req = ApplyUploadRequest(
            media_type=MediaType.OBJECT, template_name="test-tmpl", scene_name="my-scene",
            content_type="application/pdf",
        )
        mock_req = _mock_request(client, {
            "upload_state": "UPLOADING", "session_key": "sk",
            "upload_media": {"key": "", "commit_address": "", "processes": ""},
        })
        client.apply_upload(req)

        _, kwargs = mock_req.call_args
        assert kwargs["headers"]["X-Media-Scene-Name"] == "my-scene"


# ── ApplyUpload 响应解析 ──────────────────────────────────────────────────────────

class TestApplyUploadResponseParsing:
    def _apply(self, data: Any) -> ApplyUploadResponse:
        client = _make_client()
        _mock_request(client, data)
        req = ApplyUploadRequest(
            media_type=MediaType.VIDEO, template_name="test-tmpl", scene_name="s", content_type="video/mp4",
        )
        return client.apply_upload(req)

    def test_upload_auth_field_names(self) -> None:
        """B3: upload_auth 字段名 secret_access_key / security_token"""
        resp = self._apply({
            "upload_state": "UPLOADING",
            "session_key": "sk1",
            "upload_media": {"key": "k", "commit_address": "http://x", "processes": ""},
            "upload_auth": {
                "access_key_id":    "AKI",
                "secret_access_key": "SAK",
                "security_token":   "TOK",
                "expiration":       9999999999,
            },
        })
        auth = resp.upload_auth
        assert auth is not None
        assert auth.access_key_id     == "AKI"
        assert auth.secret_access_key == "SAK"
        assert auth.security_token    == "TOK"
        assert auth.expiration        == 9999999999

    def test_upload_config_nested(self) -> None:
        """B4: address/callback/vendor_code 嵌套在 upload_config 下"""
        resp = self._apply({
            "upload_state": "UPLOADING",
            "session_key": "sk",
            "upload_media": {"key": "k", "commit_address": "http://x", "processes": "p"},
            "upload_config": {
                "vendor_code": "ali",
                "address": {
                    "endpoint":    "https://oss.example.com",
                    "bucket_name": "my-bucket",
                    "object_name": "obj/key.mp4",
                    "region":      "cn-beijing",
                    "is_cname":    False,
                },
                "callback": {
                    "url":       "https://cb.example.com",
                    "body":      "callback_body",
                    "body_type": "application/json",
                },
            },
        })
        assert resp.vendor_code           == "ali"
        assert resp.address.bucket_name   == "my-bucket"
        assert resp.address.object_name   == "obj/key.mp4"
        assert resp.address.is_cname      is False
        assert resp.callback.body_type    == "application/json"

    def test_processes_parsed_from_upload_media(self) -> None:
        """C4: processes 从 upload_media.processes 解析"""
        resp = self._apply({
            "upload_state": "UPLOADING",
            "session_key": "sk",
            "upload_media": {"key": "k", "commit_address": "http://c", "processes": "hd_1080p"},
        })
        assert resp.processes == "hd_1080p"

    def test_instant_upload_extra_params(self) -> None:
        """图片秒传：extra_params 包含 width/height/format/size"""
        resp = self._apply({
            "upload_state": UPLOAD_STATE_SUCCESS,
            "session_key": "img123",
            "upload_media": {"key": "img123", "commit_address": "", "processes": ""},
            "extra_params": {"width": 1920, "height": 1080, "format": "jpeg", "size": 102400},
        })
        assert resp.is_instant_upload
        assert resp.extra_params["width"] == 1920


# ── CommitUpload 请求头与路由 ─────────────────────────────────────────────────────

class TestCommitUploadRequest:
    def _commit(self, commit_address: str = "https://bi.example.com/commit",
                scene_name: str = "sc", platform: str = "web", security_token: str = "tok") -> MagicMock:
        client = _make_client()
        _mock_request(client, {
            "upload_results": UPLOAD_STATE_SUCCESS,
            "media_key": "mk",
            "space_name": "sp",
        })
        req = CommitUploadRequest(
            media_type=MediaType.VIDEO,
            session_key="sk",
            client_upload_state=CLIENT_UPLOAD_STATE_SUCCESS,
            security_token=security_token,
        )
        client.commit_upload(commit_address, req, scene_name, platform)
        return client._session.request

    def test_security_token_in_header_not_body(self) -> None:
        """B5: X-Security-Token 在 header，不在 body"""
        mock_req = self._commit(security_token="MYTOKEN")
        _, kwargs = mock_req.call_args
        headers   = kwargs.get("headers", {})
        body      = json.loads(kwargs.get("data", "{}"))

        assert headers.get("X-Security-Token") == "MYTOKEN"
        assert "security_token" not in body

    def test_scene_name_and_platform_in_header(self) -> None:
        """B6: X-Media-Scene-Name 和 X-Media-Upload-Platform 必须在 header"""
        mock_req = self._commit(scene_name="my-scene", platform="ios")
        _, kwargs = mock_req.call_args
        headers   = kwargs.get("headers", {})
        assert headers.get("X-Media-Scene-Name")      == "my-scene"
        assert headers.get("X-Media-Upload-Platform") == "ios"

    def test_fallback_url_when_commit_address_empty(self) -> None:
        """commit_address 为空时 fallback 到含 session_key 的新路径"""
        mock_req = self._commit(commit_address="")
        args, _ = mock_req.call_args
        called_url = args[1]   # request(method, url, ...)
        assert called_url == "https://bi.example.com/openapi/media/uploads/sk"


class TestCommitUploadRoute:
    def test_http_method_is_patch(self) -> None:
        """commit_upload 必须使用 PATCH 方法"""
        client = _make_client()
        mock_req = _mock_request(client, {
            "upload_results": UPLOAD_STATE_SUCCESS, "media_key": "mk", "space_name": "sp",
        })
        req = CommitUploadRequest(
            media_type=MediaType.IMAGE, session_key="sk123",
            client_upload_state=CLIENT_UPLOAD_STATE_SUCCESS,
        )
        client.commit_upload("", req, "answer", "web")

        args, _ = mock_req.call_args
        assert args[0] == "PATCH"

    def test_session_key_in_url_path_not_body(self) -> None:
        """session_key 必须在 URL path 中，不得在 body 中"""
        client = _make_client()
        mock_req = _mock_request(client, {
            "upload_results": UPLOAD_STATE_SUCCESS, "media_key": "mk", "space_name": "sp",
        })
        req = CommitUploadRequest(
            media_type=MediaType.IMAGE, session_key="sk_abc",
            client_upload_state=CLIENT_UPLOAD_STATE_SUCCESS,
        )
        client.commit_upload("", req, "answer", "web")

        args, kwargs = mock_req.call_args
        called_url = args[1]
        body = json.loads(kwargs.get("data", "{}"))

        assert "sk_abc" in called_url
        assert "session_key" not in body


# ── CommitUpload 响应解析 ─────────────────────────────────────────────────────────

class TestCommitUploadResponseParsing:
    def _parse(self, data: Any) -> CommitUploadResponse:
        client = _make_client()
        _mock_request(client, data)
        req = CommitUploadRequest(
            media_type=MediaType.VIDEO,
            session_key="sk",
            client_upload_state=CLIENT_UPLOAD_STATE_SUCCESS,
        )
        return client.commit_upload("https://bi.example.com/commit", req, "sc", "web")

    def test_upload_results_mapped_to_upload_result(self) -> None:
        """B7: JSON 字段 upload_results → CommitUploadResponse.upload_result"""
        resp = self._parse({
            "upload_results": UPLOAD_STATE_SUCCESS,
            "media_key": "vid123",
            "space_name": "vspace",
        })
        assert resp.upload_result == UPLOAD_STATE_SUCCESS
        assert resp.media_key     == "vid123"
        assert resp.space_name    == "vspace"

    def test_media_meta_parsed_for_image(self) -> None:
        """B8: media_meta 正确解析"""
        resp = self._parse({
            "upload_results": UPLOAD_STATE_SUCCESS,
            "media_key": "img456",
            "space_name": "default",
            "media_meta": {"width": 800, "height": 600, "format": "png", "size": 51200},
        })
        assert resp.media_meta is not None
        assert resp.media_meta.width  == 800
        assert resp.media_meta.height == 600
        assert resp.media_meta.format == "png"
        assert resp.media_meta.size   == 51200

    def test_media_meta_none_when_absent(self) -> None:
        resp = self._parse({
            "upload_results": UPLOAD_STATE_SUCCESS,
            "media_key": "obj789",
        })
        assert resp.media_meta is None


# ── GetImageProcessResult [WATERMARK PATCH] ───────────────────────────────────────

class TestGetImageProcessResult:
    def _get_watermark(self, data: Any) -> tuple[ImageProcessResultResponse, MagicMock]:
        client = _make_client()
        mock_req = _mock_request(client, data)
        resp = client.get_image_process_result("123456", "answer")
        return resp, mock_req

    def test_http_method_is_get(self) -> None:
        _, mock_req = self._get_watermark({"state": "processing"})
        args, _ = mock_req.call_args
        assert args[0] == "GET"

    def test_image_id_in_url(self) -> None:
        _, mock_req = self._get_watermark({"state": "processing"})
        args, _ = mock_req.call_args
        assert "123456" in args[1]

    def test_no_request_body(self) -> None:
        _, mock_req = self._get_watermark({"state": "processing"})
        _, kwargs = mock_req.call_args
        assert kwargs.get("data") is None

    def test_scene_name_in_header(self) -> None:
        client = _make_client()
        mock_req = _mock_request(client, {"state": "processing"})
        client.get_image_process_result("111", "pin")
        _, kwargs = mock_req.call_args
        assert kwargs["headers"]["X-Media-Scene-Name"] == "pin"

    def test_success_response_parsed(self) -> None:
        resp, _ = self._get_watermark({
            "state": "success",
            "original_image_token": "v2-orig",
            "watermark_image_token": "v2-wm",
            "watermark_image_url": {"primary": "https://img.example.com/wm.jpg", "backups": []},
        })
        assert resp.state                 == "success"
        assert resp.original_image_token  == "v2-orig"
        assert resp.watermark_image_token == "v2-wm"
        assert resp.watermark_image_url is not None
        assert resp.watermark_image_url.primary == "https://img.example.com/wm.jpg"

    def test_processing_state_no_url(self) -> None:
        resp, _ = self._get_watermark({
            "state": "processing",
            "original_image_token": "",
            "watermark_image_token": "",
        })
        assert resp.state                == "processing"
        assert resp.watermark_image_url is None

    def test_failed_state(self) -> None:
        resp, _ = self._get_watermark({"state": "failed"})
        assert resp.state == "failed"


# ── 错误处理 ──────────────────────────────────────────────────────────────────────

class TestErrorHandling:
    def test_http_401_raises_auth_error(self) -> None:
        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.ok = False
        client._session.request = MagicMock(return_value=mock_resp)
        req = ApplyUploadRequest(
            media_type=MediaType.VIDEO, template_name="test-tmpl", scene_name="s", content_type="video/mp4",
        )
        with pytest.raises(UploaderAuthError):
            client.apply_upload(req)

    def test_http_400_raises_api_error(self) -> None:
        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.ok = False
        mock_resp.text = json.dumps({"error": {"code": 10400, "name": "BadRequest", "message": "bad request"}})
        client._session.request = MagicMock(return_value=mock_resp)
        req = ApplyUploadRequest(
            media_type=MediaType.VIDEO, template_name="test-tmpl", scene_name="s", content_type="video/mp4",
        )
        with pytest.raises(UploaderAPIError):
            client.apply_upload(req)


