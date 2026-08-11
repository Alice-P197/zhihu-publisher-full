# -*- coding: utf-8 -*-
"""models.py 单元测试"""

import io
import pytest

from mediacloud_uploader.models import (
    UploadRequest,
    ApplyUploadRequest,
    ApplyUploadResponse,
    CLIENT_UPLOAD_STATE_FAIL,
    CLIENT_UPLOAD_STATE_SUCCESS,
    CommitUploadRequest,
    CommitUploadResponse,
    MediaMeta,
    MediaType,
    UPLOAD_STATE_FAIL,
    UPLOAD_STATE_SUCCESS,
    UploadAuthInfo,
    UploadResponse,
)
from mediacloud_uploader.errors import UploaderValidationError


# ── MediaMeta ─────────────────────────────────────────────────────────────────────

class TestMediaMeta:
    def test_defaults(self) -> None:
        m = MediaMeta()
        assert m.width  == 0
        assert m.height == 0
        assert m.format == ""
        assert m.size   == 0

    def test_values(self) -> None:
        m = MediaMeta(width=1920, height=1080, format="jpeg", size=204800)
        assert m.width  == 1920
        assert m.height == 1080
        assert m.format == "jpeg"
        assert m.size   == 204800


# ── UploadAuthInfo ────────────────────────────────────────────────────────────────

class TestUploadAuthInfo:
    def test_field_names(self) -> None:
        auth = UploadAuthInfo(
            access_key_id="kid",
            secret_access_key="sak",
            security_token="tok",
            expiration=1234567890,
        )
        assert auth.access_key_id     == "kid"
        assert auth.secret_access_key == "sak"
        assert auth.security_token    == "tok"
        assert auth.expiration        == 1234567890

    def test_expiration_default_int(self) -> None:
        auth = UploadAuthInfo("k", "s", "t")
        assert isinstance(auth.expiration, int)
        assert auth.expiration == 0


# ── 上传状态常量 ──────────────────────────────────────────────────────────────────

class TestUploadStateConstants:
    def test_client_upload_state_success_is_upload_success(self) -> None:
        # M7: 服务端校验的合法值是 "UPLOAD_SUCCESS"，不是 "SUCCESS"
        assert CLIENT_UPLOAD_STATE_SUCCESS == "UPLOAD_SUCCESS"

    def test_client_upload_state_fail(self) -> None:
        assert CLIENT_UPLOAD_STATE_FAIL == "UPLOAD_FAIL"

    def test_upload_state_success(self) -> None:
        assert UPLOAD_STATE_SUCCESS == "UPLOAD_SUCCESS"


# ── UploadResponse ────────────────────────────────────────────────────────────────

class TestUploadResponse:
    def test_media_key_field_exists(self) -> None:
        r = UploadResponse(upload_result=UPLOAD_STATE_SUCCESS, media_key="key123")
        assert r.media_key == "key123"

    def test_space_name_field(self) -> None:
        r = UploadResponse(upload_result=UPLOAD_STATE_SUCCESS, space_name="default")
        assert r.space_name == "default"

    def test_media_meta_field(self) -> None:
        meta = MediaMeta(width=800, height=600)
        r = UploadResponse(upload_result=UPLOAD_STATE_SUCCESS, media_meta=meta)
        assert r.media_meta is meta
        assert r.media_meta.width == 800

    def test_is_success_true(self) -> None:
        r = UploadResponse(upload_result=UPLOAD_STATE_SUCCESS)
        assert r.is_success is True

    def test_is_success_false(self) -> None:
        r = UploadResponse(upload_result=UPLOAD_STATE_FAIL)
        assert r.is_success is False


# ── CommitUploadResponse ──────────────────────────────────────────────────────────

class TestCommitUploadResponse:
    def test_upload_result_field(self) -> None:
        r = CommitUploadResponse(upload_result=UPLOAD_STATE_SUCCESS, media_key="mk")
        assert r.upload_result == UPLOAD_STATE_SUCCESS
        assert r.media_key     == "mk"

    def test_is_success(self) -> None:
        assert CommitUploadResponse(upload_result=UPLOAD_STATE_SUCCESS).is_success is True
        assert CommitUploadResponse(upload_result=UPLOAD_STATE_FAIL).is_success    is False

    def test_media_meta(self) -> None:
        meta = MediaMeta(format="png")
        r    = CommitUploadResponse(upload_result=UPLOAD_STATE_SUCCESS, media_meta=meta)
        assert r.media_meta.format == "png"


# ── ApplyUploadRequest ────────────────────────────────────────────────────────────

class TestApplyUploadRequest:
    def test_content_hash_field(self) -> None:
        req = ApplyUploadRequest(
            media_type="image", scene_name="test", template_name="tmpl", content_hash="abc123",
        )
        assert req.content_hash == "abc123"

    def test_content_hash_default_empty(self) -> None:
        req = ApplyUploadRequest(media_type="video", scene_name="test", template_name="tmpl")
        assert req.content_hash == ""

    def test_template_name_explicit(self) -> None:
        """template_name 由调用方显式传入，不再自动推导"""
        req = ApplyUploadRequest(media_type=MediaType.IMAGE, scene_name="s", template_name="my-tmpl")
        assert req.template_name == "my-tmpl"


# ── CommitUploadRequest ───────────────────────────────────────────────────────────

class TestCommitUploadRequest:
    def test_processes_is_str(self) -> None:
        req = CommitUploadRequest(
            media_type="video", session_key="sk",
            client_upload_state=CLIENT_UPLOAD_STATE_SUCCESS,
            processes="transcode_hd",
        )
        assert isinstance(req.processes, str)
        assert req.processes == "transcode_hd"

    def test_processes_default_empty_str(self) -> None:
        req = CommitUploadRequest(
            media_type="image", session_key="sk",
            client_upload_state=CLIENT_UPLOAD_STATE_SUCCESS,
        )
        assert req.processes == ""

    def test_has_platform_field(self) -> None:
        req = CommitUploadRequest(
            media_type="object", session_key="sk",
            client_upload_state=CLIENT_UPLOAD_STATE_SUCCESS,
            platform="web",
        )
        assert req.platform == "web"


# ── ApplyUploadResponse ───────────────────────────────────────────────────────────

class TestApplyUploadResponse:
    def test_is_instant_upload_true(self) -> None:
        r = ApplyUploadResponse(upload_state=UPLOAD_STATE_SUCCESS)
        assert r.is_instant_upload is True

    def test_is_instant_upload_false(self) -> None:
        r = ApplyUploadResponse(upload_state="UPLOADING")
        assert r.is_instant_upload is False

    def test_processes_field(self) -> None:
        r = ApplyUploadResponse(upload_state="UPLOADING", processes="hd")
        assert r.processes == "hd"

    def test_extra_params_default_empty_dict(self) -> None:
        r = ApplyUploadResponse(upload_state="UPLOADING")
        assert r.extra_params == {}


# ── UploadRequest.validate ────────────────────────────────────────────────────────

class TestUploadRequestValidate:
    def test_missing_media_type(self) -> None:
        req = UploadRequest(media_type="", scene_name="s", template_name="tmpl", file_path="/tmp/f")
        with pytest.raises(UploaderValidationError, match="media_type"):
            req.validate()

    def test_invalid_media_type(self) -> None:
        req = UploadRequest(media_type="gif", scene_name="s", template_name="tmpl", file_path="/tmp/f")
        with pytest.raises(UploaderValidationError, match="invalid media_type"):
            req.validate()

    def test_missing_scene_name(self) -> None:
        req = UploadRequest(media_type=MediaType.IMAGE, scene_name="", template_name="tmpl", file_path="/tmp/f")
        with pytest.raises(UploaderValidationError, match="scene_name"):
            req.validate()

    def test_missing_template_name(self) -> None:
        req = UploadRequest(media_type=MediaType.IMAGE, scene_name="s", template_name="", file_path="/tmp/f")
        with pytest.raises(UploaderValidationError, match="template_name"):
            req.validate()

    def test_file_obj_without_size(self) -> None:
        req = UploadRequest(
            media_type=MediaType.IMAGE, scene_name="s", template_name="tmpl",
            file_obj=io.BytesIO(b"data"), file_size=0,
        )
        with pytest.raises(UploaderValidationError, match="file_size"):
            req.validate()
