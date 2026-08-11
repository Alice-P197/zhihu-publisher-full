# -*- coding: utf-8 -*-
"""client.py 单元测试：图片 MD5、秒传 meta、凭证刷新、_do_commit 字段"""

import hashlib
import io
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from mediacloud_uploader.client import MediaCloudUploader
from mediacloud_uploader.cloud.base import CloudUploadResponse
from mediacloud_uploader.models import (
    ApplyUploadResponse,
    CommitUploadResponse,
    CLIENT_UPLOAD_STATE_FAIL,
    CLIENT_UPLOAD_STATE_SUCCESS,
    MediaMeta,
    MediaType,
    MediaURL,
    UPLOAD_STATE_FAIL,
    UPLOAD_STATE_SUCCESS,
    UploadAuthInfo,
    UploadAddressInfo,
    UploadRequest,
    UploadResponse,
    UploadExtra,
)
from mediacloud_uploader.errors import (
    UploaderAPIError,
    UploaderOSSError,
    UploaderSessionExpiredError,
    UploaderValidationError,
)


def _make_uploader() -> MediaCloudUploader:
    return MediaCloudUploader(
        base_url="https://bi.example.com",
        app_key="k",
        app_secret="s",
    )


def _image_content() -> bytes:
    return b"\xff\xd8\xff\xe0" + b"x" * 100


def _apply_resp_uploading(vendor_code: str = "ali", processes: str = "", session_key: str = "sk") -> ApplyUploadResponse:
    return ApplyUploadResponse(
        upload_state="UPLOADING",
        session_key=session_key,
        vendor_code=vendor_code,
        commit_address="https://bi.example.com/commit",
        object_key="obj_key",
        processes=processes,
        upload_auth=UploadAuthInfo("kid", "sak", "tok"),
        address=UploadAddressInfo("oss.example.com", "bucket", "obj/key"),
        callback=None,
    )


def _commit_resp(upload_result: str = UPLOAD_STATE_SUCCESS, media_key: str = "mk") -> CommitUploadResponse:
    return CommitUploadResponse(
        upload_result=upload_result,
        media_key=media_key,
        space_name="sp",
    )


def _mock_cloud(put_object_side_effect: Any = None) -> tuple[MagicMock, MagicMock]:
    """返回一个 mock cloud 模块，内含 mock storage 实例"""
    mock_storage = MagicMock()
    mock_storage.put_object.return_value       = CloudUploadResponse(vendor_upload_id=None)
    mock_storage.multipart_upload.return_value = CloudUploadResponse(vendor_upload_id=None)
    if put_object_side_effect is not None:
        mock_storage.put_object.side_effect = put_object_side_effect

    mock_cloud = MagicMock()
    mock_cloud.validate_vendor_code = MagicMock()
    mock_cloud.get_storage.return_value = mock_storage
    mock_cloud.is_credential_expired.side_effect = (
        lambda vendor_code, err_code: err_code in {
            "InvalidAccessKeyId", "SecurityTokenExpired",
            "AccessDenied", "InvalidSecurityToken",
        }
    )
    return mock_cloud, mock_storage


# ── 图片 MD5 计算 ──────────────────────────────────────────────────────────────────

class TestImageMD5:
    def test_image_upload_sends_md5_hash(self) -> None:
        """图片上传时 ApplyUpload 收到的 content_hash 是文件内容的 MD5"""
        uploader     = _make_uploader()
        content      = _image_content()
        expected_hash = hashlib.md5(content).hexdigest()
        captured_req  = []

        def fake_apply(req):
            captured_req.append(req)
            return _apply_resp_uploading()

        uploader._http_client.apply_upload  = fake_apply
        uploader._http_client.commit_upload = MagicMock(return_value=_commit_resp())

        mock_cloud, _ = _mock_cloud()
        with patch("mediacloud_uploader.client.cloud", mock_cloud):
            uploader.upload(UploadRequest(
                media_type=MediaType.IMAGE, template_name="image-upload-default", scene_name="test",
                file_obj=io.BytesIO(content), file_size=len(content),
                content_type="image/jpeg",
            ))

        assert len(captured_req) == 1
        assert captured_req[0].content_hash == expected_hash

    def test_video_upload_does_not_compute_hash(self) -> None:
        """video/object 不计算 MD5"""
        uploader     = _make_uploader()
        captured_req = []

        def fake_apply(req):
            captured_req.append(req)
            return _apply_resp_uploading()

        uploader._http_client.apply_upload  = fake_apply
        uploader._http_client.commit_upload = MagicMock(return_value=_commit_resp())

        mock_cloud, _ = _mock_cloud()
        with patch("mediacloud_uploader.client.cloud", mock_cloud):
            uploader.upload(UploadRequest(
                media_type=MediaType.VIDEO, template_name="video-upload-default", scene_name="test",
                file_obj=io.BytesIO(b"video_data"), file_size=10,
                content_type="video/mp4",
            ))

        assert captured_req[0].content_hash == ""


# ── 图片秒传 ───────────────────────────────────────────────────────────────────────

class TestInstantUpload:
    def test_instant_upload_returns_meta_from_extra_params(self) -> None:
        """秒传时 UploadResponse 包含 extra_params 中的 media_meta"""
        uploader = _make_uploader()
        content  = _image_content()

        instant_resp = ApplyUploadResponse(
            upload_state=UPLOAD_STATE_SUCCESS,
            session_key="img123",
            object_key="img123",
            extra_params={"width": 1920, "height": 1080, "format": "jpeg", "size": 102400},
        )
        uploader._http_client.apply_upload  = MagicMock(return_value=instant_resp)
        uploader._http_client.commit_upload = MagicMock()

        resp = uploader.upload(UploadRequest(
            media_type=MediaType.IMAGE, template_name="image-upload-default", scene_name="test",
            file_obj=io.BytesIO(content), file_size=len(content),
            content_type="image/jpeg",
        ))

        assert resp.is_success
        assert resp.media_key.startswith("v2-")   # ImageID 已被替换为 v2-{hash} token
        assert resp.media_meta is not None
        assert resp.media_meta.width  == 1920
        assert resp.media_meta.height == 1080
        assert resp.media_meta.format == "jpeg"
        assert resp.media_meta.size   == 102400
        uploader._http_client.commit_upload.assert_not_called()

    def test_instant_upload_no_extra_params_media_meta_is_none(self) -> None:
        uploader = _make_uploader()
        content  = _image_content()

        uploader._http_client.apply_upload  = MagicMock(return_value=ApplyUploadResponse(
            upload_state=UPLOAD_STATE_SUCCESS, session_key="img999", object_key="img999",
        ))
        uploader._http_client.commit_upload = MagicMock()

        resp = uploader.upload(UploadRequest(
            media_type=MediaType.IMAGE, template_name="image-upload-default", scene_name="test",
            file_obj=io.BytesIO(content), file_size=len(content),
            content_type="image/jpeg",
        ))
        assert resp.media_meta is None


# ── _do_commit ────────────────────────────────────────────────────────────────────

class TestDoCommit:
    def test_security_token_from_auth_security_token(self) -> None:
        """CommitUpload 的 security_token 来自 apply_resp.upload_auth.security_token"""
        uploader       = _make_uploader()
        apply_resp_obj = _apply_resp_uploading(session_key="sk99")
        apply_resp_obj.upload_auth = UploadAuthInfo("kid", "sak", "MY_SECURITY_TOKEN")

        uploader._http_client.apply_upload = MagicMock(return_value=apply_resp_obj)
        commit_calls = []

        def fake_commit(commit_address, req, scene_name, platform):
            commit_calls.append(req)
            return _commit_resp()

        uploader._http_client.commit_upload = fake_commit

        mock_cloud, _ = _mock_cloud()
        with patch("mediacloud_uploader.client.cloud", mock_cloud):
            uploader.upload(UploadRequest(
                media_type=MediaType.VIDEO, template_name="video-upload-default", scene_name="test",
                file_obj=io.BytesIO(b"data"), file_size=4,
                content_type="video/mp4",
            ))

        assert commit_calls[0].security_token == "MY_SECURITY_TOKEN"

    def test_processes_from_apply_resp_not_upload_req(self) -> None:
        """CommitUpload.processes 来自 apply_resp.processes，不是 UploadRequest"""
        uploader = _make_uploader()
        uploader._http_client.apply_upload = MagicMock(
            return_value=_apply_resp_uploading(processes="transcode_hd_1080p"),
        )
        commit_calls = []

        def fake_commit(commit_address, req, scene_name, platform):
            commit_calls.append(req)
            return _commit_resp()

        uploader._http_client.commit_upload = fake_commit

        mock_cloud, _ = _mock_cloud()
        with patch("mediacloud_uploader.client.cloud", mock_cloud):
            uploader.upload(UploadRequest(
                media_type=MediaType.VIDEO, template_name="video-upload-default", scene_name="test",
                file_obj=io.BytesIO(b"data"), file_size=4,
                content_type="video/mp4",
            ))

        assert commit_calls[0].processes == "transcode_hd_1080p"

    def test_commit_called_even_on_oss_failure(self) -> None:
        """OSS 失败时 CommitUpload 仍被调用（上报失败状态）"""
        uploader = _make_uploader()
        uploader._http_client.apply_upload = MagicMock(return_value=_apply_resp_uploading())
        commit_calls = []

        def fake_commit(commit_address, req, scene_name, platform):
            commit_calls.append(req)
            return _commit_resp(upload_result=UPLOAD_STATE_FAIL)

        uploader._http_client.commit_upload = fake_commit

        mock_cloud, mock_storage = _mock_cloud(
            put_object_side_effect=UploaderOSSError("oss fail", oss_code="InternalError"),
        )
        with patch("mediacloud_uploader.client.cloud", mock_cloud):
            resp = uploader.upload(UploadRequest(
                media_type=MediaType.VIDEO, template_name="video-upload-default", scene_name="test",
                file_obj=io.BytesIO(b"data"), file_size=4,
                content_type="video/mp4",
            ))

        assert commit_calls[0].client_upload_state == CLIENT_UPLOAD_STATE_FAIL
        assert not resp.is_success

    def test_upload_response_contains_media_meta(self) -> None:
        """CommitUpload 返回的 media_meta 传入 UploadResponse"""
        uploader = _make_uploader()
        uploader._http_client.apply_upload = MagicMock(return_value=_apply_resp_uploading())
        uploader._http_client.commit_upload = MagicMock(return_value=CommitUploadResponse(
            upload_result=UPLOAD_STATE_SUCCESS,
            media_key="img001",
            space_name="default",
            media_meta=MediaMeta(width=640, height=480, format="png", size=8192),
        ))

        mock_cloud, _ = _mock_cloud()
        with patch("mediacloud_uploader.client.cloud", mock_cloud):
            resp = uploader.upload(UploadRequest(
                media_type=MediaType.IMAGE, template_name="image-upload-default", scene_name="test",
                file_obj=io.BytesIO(b"data"), file_size=4,
                content_type="image/png",
            ))

        assert resp.media_meta.width  == 640
        assert resp.media_meta.format == "png"


# ── 凭证刷新 ──────────────────────────────────────────────────────────────────────

class TestCredentialRefresh:
    def test_refresh_passes_content_hash_for_image(self) -> None:
        """凭证刷新时图片的 content_hash 被传入新的 ApplyUpload 请求"""
        uploader      = _make_uploader()
        content       = _image_content()
        expected_hash = hashlib.md5(content).hexdigest()
        apply_calls   = []
        call_count    = [0]

        def fake_apply(req):
            apply_calls.append(req)
            call_count[0] += 1
            return (_apply_resp_uploading()
                    if call_count[0] == 1
                    else _apply_resp_uploading(session_key="sk_refreshed"))

        uploader._http_client.apply_upload  = fake_apply
        uploader._http_client.commit_upload = MagicMock(return_value=_commit_resp())

        mock_cloud, mock_storage = _mock_cloud()
        mock_storage.put_object.side_effect = [
            UploaderOSSError("expired", oss_code="SecurityTokenExpired"),
            CloudUploadResponse(vendor_upload_id=None),
        ]
        with patch("mediacloud_uploader.client.cloud", mock_cloud):
            uploader.upload(UploadRequest(
                media_type=MediaType.IMAGE, template_name="image-upload-default", scene_name="test",
                file_obj=io.BytesIO(content), file_size=len(content),
                content_type="image/jpeg",
            ))

        assert len(apply_calls) == 2
        assert apply_calls[1].content_hash == expected_hash
        assert apply_calls[1].session_key  == "sk"

    def test_session_expired_raises(self) -> None:
        """会话超期（刷新返回 UPLOAD_FAIL）→ UploaderSessionExpiredError"""
        uploader   = _make_uploader()
        call_count = [0]

        def fake_apply(req):
            call_count[0] += 1
            return (_apply_resp_uploading()
                    if call_count[0] == 1
                    else ApplyUploadResponse(upload_state=UPLOAD_STATE_FAIL, session_key="sk"))

        uploader._http_client.apply_upload = fake_apply

        mock_cloud, mock_storage = _mock_cloud()
        mock_storage.put_object.side_effect = UploaderOSSError(
            "expired", oss_code="InvalidAccessKeyId",
        )
        with patch("mediacloud_uploader.client.cloud", mock_cloud):
            with pytest.raises(UploaderSessionExpiredError):
                uploader.upload(UploadRequest(
                    media_type=MediaType.VIDEO, template_name="video-upload-default", scene_name="test",
                    file_obj=io.BytesIO(b"data"), file_size=4,
                    content_type="video/mp4",
                ))


# ── P1：upload_auth / address null 保护 ──────────────────────────────────────────

class TestMissingCredentials:
    def test_missing_upload_auth_raises_api_error(self) -> None:
        """apply_resp.upload_auth 为 None 时抛 UploaderAPIError，而非 AttributeError"""
        uploader = _make_uploader()
        # upload_auth=None，模拟 malformed ApplyUpload 响应
        apply_resp_no_auth = ApplyUploadResponse(
            upload_state="UPLOADING",
            session_key="sk",
            vendor_code="ali",
            commit_address="https://bi.example.com/commit",
            upload_auth=None,
            address=UploadAddressInfo("oss.example.com", "bucket", "obj/key"),
        )
        uploader._http_client.apply_upload = MagicMock(return_value=apply_resp_no_auth)

        mock_cloud, _ = _mock_cloud()
        with patch("mediacloud_uploader.client.cloud", mock_cloud):
            with pytest.raises(UploaderAPIError, match="missing auth or address"):
                uploader.upload(UploadRequest(
                    media_type=MediaType.VIDEO, template_name="video-upload-default", scene_name="test",
                    file_obj=io.BytesIO(b"data"), file_size=4,
                    content_type="video/mp4",
                ))

    def test_missing_address_raises_api_error(self) -> None:
        """apply_resp.address 为 None 时抛 UploaderAPIError，而非 AttributeError"""
        uploader = _make_uploader()
        apply_resp_no_addr = ApplyUploadResponse(
            upload_state="UPLOADING",
            session_key="sk",
            vendor_code="ali",
            commit_address="https://bi.example.com/commit",
            upload_auth=UploadAuthInfo("kid", "sak", "tok"),
            address=None,
        )
        uploader._http_client.apply_upload = MagicMock(return_value=apply_resp_no_addr)

        mock_cloud, _ = _mock_cloud()
        with patch("mediacloud_uploader.client.cloud", mock_cloud):
            with pytest.raises(UploaderAPIError, match="missing auth or address"):
                uploader.upload(UploadRequest(
                    media_type=MediaType.VIDEO, template_name="video-upload-default", scene_name="test",
                    file_obj=io.BytesIO(b"data"), file_size=4,
                    content_type="video/mp4",
                ))


# ── 图片 media_key v2-{hash} ───────────────────────────────────────────────────────

class TestImageMediaKeyToken:
    def test_normal_upload_returns_v2_token(self) -> None:
        """正常上传图片后，media_key 应为 v2-{md5hex}"""
        uploader = _make_uploader()
        content  = _image_content()
        expected_hash  = hashlib.md5(content).hexdigest()
        expected_token = "v2-" + expected_hash

        uploader._http_client.apply_upload = MagicMock(return_value=_apply_resp_uploading())
        uploader._http_client.commit_upload = MagicMock(return_value=CommitUploadResponse(
            upload_result=UPLOAD_STATE_SUCCESS,
            media_key="99999",
            space_name="default",
        ))

        mock_cloud, _ = _mock_cloud()
        with patch("mediacloud_uploader.client.cloud", mock_cloud):
            resp = uploader.upload(UploadRequest(
                media_type=MediaType.IMAGE, template_name="image-upload-default", scene_name="test",
                file_obj=io.BytesIO(content), file_size=len(content),
                content_type="image/jpeg",
            ))

        assert resp.media_key == expected_token
        assert resp.media_key.startswith("v2-")

    def test_instant_upload_returns_v2_token(self) -> None:
        """秒传图片后，media_key 同样应为 v2-{md5hex}"""
        uploader = _make_uploader()
        content  = _image_content()
        expected_token = "v2-" + hashlib.md5(content).hexdigest()

        instant_resp = ApplyUploadResponse(
            upload_state=UPLOAD_STATE_SUCCESS,
            session_key="img123",
            object_key="img123",
            extra_params={"width": 100, "height": 100, "format": "jpeg", "size": len(content)},
        )
        uploader._http_client.apply_upload  = MagicMock(return_value=instant_resp)
        uploader._http_client.commit_upload = MagicMock()

        resp = uploader.upload(UploadRequest(
            media_type=MediaType.IMAGE, template_name="image-upload-default", scene_name="test",
            file_obj=io.BytesIO(content), file_size=len(content),
            content_type="image/jpeg",
        ))

        assert resp.media_key == expected_token
        uploader._http_client.commit_upload.assert_not_called()

    def test_video_media_key_not_modified(self) -> None:
        """video 上传的 media_key 不做任何修改"""
        uploader = _make_uploader()
        original_media_key = "V_vid_abc123"

        uploader._http_client.apply_upload = MagicMock(return_value=_apply_resp_uploading(
            vendor_code="ali", processes="", session_key="sk",
        ))
        uploader._http_client.commit_upload = MagicMock(return_value=CommitUploadResponse(
            upload_result=UPLOAD_STATE_SUCCESS,
            media_key=original_media_key,
            space_name="vspace",
        ))

        mock_cloud, _ = _mock_cloud()
        with patch("mediacloud_uploader.client.cloud", mock_cloud):
            resp = uploader.upload(UploadRequest(
                media_type=MediaType.VIDEO, template_name="video-upload-default", scene_name="test",
                file_obj=io.BytesIO(b"data"), file_size=4,
                content_type="video/mp4",
            ))

        assert resp.media_key == original_media_key

    def test_failed_upload_media_key_not_modified(self) -> None:
        """图片上传失败时，不做 v2-token 替换"""
        uploader = _make_uploader()
        content  = _image_content()

        uploader._http_client.apply_upload = MagicMock(return_value=_apply_resp_uploading())
        uploader._http_client.commit_upload = MagicMock(return_value=CommitUploadResponse(
            upload_result=UPLOAD_STATE_FAIL,
            media_key="",
            space_name="default",
        ))

        mock_cloud, mock_storage = _mock_cloud()
        mock_storage.put_object.side_effect = UploaderOSSError("fail", oss_code="InternalError")

        with patch("mediacloud_uploader.client.cloud", mock_cloud):
            resp = uploader.upload(UploadRequest(
                media_type=MediaType.IMAGE, template_name="image-upload-default", scene_name="test",
                file_obj=io.BytesIO(content), file_size=len(content),
                content_type="image/jpeg",
            ))

        assert not resp.is_success
        assert not resp.media_key.startswith("v2-")


# ── [WATERMARK PATCH] raw_session_key 透传 ────────────────────────────────────────

class TestRawSessionKey:
    def test_normal_image_upload_sets_raw_session_key(self) -> None:
        """正常图片上传后 raw_session_key = apply_resp.session_key"""
        uploader = _make_uploader()
        content  = _image_content()

        uploader._http_client.apply_upload = MagicMock(
            return_value=_apply_resp_uploading(session_key="99887766"),
        )
        uploader._http_client.commit_upload = MagicMock(return_value=CommitUploadResponse(
            upload_result=UPLOAD_STATE_SUCCESS, media_key="img001", space_name="default",
        ))

        mock_cloud, _ = _mock_cloud()
        with patch("mediacloud_uploader.client.cloud", mock_cloud):
            resp = uploader.upload(UploadRequest(
                media_type=MediaType.IMAGE, template_name="image-upload-default", scene_name="test",
                file_obj=io.BytesIO(content), file_size=len(content),
                content_type="image/jpeg",
            ))

        assert resp._raw_session_key == "99887766"

    def test_instant_image_upload_sets_raw_session_key(self) -> None:
        """秒传图片后 raw_session_key = apply_resp.session_key"""
        uploader = _make_uploader()
        content  = _image_content()

        instant_resp = ApplyUploadResponse(
            upload_state=UPLOAD_STATE_SUCCESS,
            session_key="55443322",
            object_key="55443322",
            extra_params={"width": 100, "height": 100, "format": "jpeg", "size": len(content)},
        )
        uploader._http_client.apply_upload = MagicMock(return_value=instant_resp)

        resp = uploader.upload(UploadRequest(
            media_type=MediaType.IMAGE, template_name="image-upload-default", scene_name="test",
            file_obj=io.BytesIO(content), file_size=len(content),
            content_type="image/jpeg",
        ))

        assert resp._raw_session_key == "55443322"

    def test_video_upload_raw_session_key_is_empty(self) -> None:
        """video 上传 raw_session_key 为空"""
        uploader = _make_uploader()
        uploader._http_client.apply_upload = MagicMock(
            return_value=_apply_resp_uploading(session_key="sk_vid"),
        )
        uploader._http_client.commit_upload = MagicMock(return_value=_commit_resp())

        mock_cloud, _ = _mock_cloud()
        with patch("mediacloud_uploader.client.cloud", mock_cloud):
            resp = uploader.upload(UploadRequest(
                media_type=MediaType.VIDEO, template_name="video-upload-default", scene_name="test",
                file_obj=io.BytesIO(b"data"), file_size=4,
                content_type="video/mp4",
            ))

        assert resp._raw_session_key == ""


# ── 高层方法: upload_image / upload_video / upload_object ──────────────────────────


def _make_image_meta(fmt: str = "JPEG"):
    from mediacloud_uploader.image_validator import ImageMeta
    return ImageMeta(format=fmt, mime="image/jpeg", width=800, height=600, size_bytes=10000)


def _upload_image_resp(session_key: str = "sk123") -> UploadResponse:
    return UploadResponse(
        upload_result=UPLOAD_STATE_SUCCESS,
        media_key="v2-abc123",
        media_type=MediaType.IMAGE,
        space_name="default",
        media_url=MediaURL(primary="https://img.example.com/v2-abc123"),
        raw_session_key=session_key,
    )


class TestUploadImageHighLevel:
    def test_file_path_success(self, tmp_path) -> None:
        """upload_image(file_path=...) 基础成功路径（session_key 为空跳过水印）"""
        f = tmp_path / "photo.jpg"
        f.write_bytes(b"x" * 100)

        uploader = _make_uploader()
        # raw_session_key="" → 水印轮询不触发，避免网络调用
        resp = _upload_image_resp(session_key="")

        with patch("mediacloud_uploader.client._validate_image_source", return_value=_make_image_meta()), \
             patch("mediacloud_uploader.image_transcoder.needs_transcode", return_value=False), \
             patch.object(uploader, "upload", return_value=resp):
            result = uploader.upload_image(file_path=str(f), scene_name="answer")

        assert result.upload_result == UPLOAD_STATE_SUCCESS
        assert result.media_key == "v2-abc123"

    def test_invalid_scene_name_raises(self, tmp_path) -> None:
        """scene_name 非法时立即抛 UploaderValidationError，不调用 upload"""
        f = tmp_path / "photo.jpg"
        f.write_bytes(b"x")

        uploader = _make_uploader()
        with pytest.raises(UploaderValidationError, match="scene_name"):
            uploader.upload_image(file_path=str(f), scene_name="bad_scene")

    def test_empty_scene_name_raises(self, tmp_path) -> None:
        """scene_name 为空时抛 UploaderValidationError"""
        f = tmp_path / "photo.jpg"
        f.write_bytes(b"x")

        uploader = _make_uploader()
        with pytest.raises(UploaderValidationError):
            uploader.upload_image(file_path=str(f), scene_name="")

    def test_both_file_path_and_url_raises(self) -> None:
        """file_path 和 url 同时提供时抛 UploaderValidationError"""
        uploader = _make_uploader()
        with pytest.raises(UploaderValidationError, match="不能同时"):
            uploader.upload_image(
                file_path="/tmp/x.jpg",
                url="https://example.com/x.jpg",
                scene_name="answer",
            )

    def test_missing_source_raises(self) -> None:
        """file_path 和 url 都未提供时抛 UploaderValidationError"""
        uploader = _make_uploader()
        with pytest.raises(UploaderValidationError):
            uploader.upload_image(scene_name="answer")

    def test_extra_set_when_watermark_succeeds(self, tmp_path) -> None:
        """上传成功后 poll_watermark 返回值赋给 resp.extra（直接 mock HTTP 层）"""
        f = tmp_path / "photo.jpg"
        f.write_bytes(b"x" * 100)

        uploader = _make_uploader()
        from mediacloud_uploader.models import ImageProcessState, ImageProcessResultResponse
        # mock HTTP 层让 poller 第一次即得到 SUCCESS 响应
        uploader._http_client = MagicMock()
        uploader._http_client.get_image_process_result.return_value = ImageProcessResultResponse(
            state=ImageProcessState.SUCCESS,
            watermark_image_token="v2-wm999",
            watermark_image_url=MediaURL(primary="https://img.example.com/wm999"),
        )

        with patch("mediacloud_uploader.client._validate_image_source", return_value=_make_image_meta()), \
             patch("mediacloud_uploader.image_transcoder.needs_transcode", return_value=False), \
             patch.object(uploader, "upload", return_value=_upload_image_resp(session_key="sk999")):
            result = uploader.upload_image(file_path=str(f), scene_name="answer")

        assert result.extra is not None
        assert result.extra.watermark_image_key == "v2-wm999"
        assert result.extra.watermark_image_url.primary == "https://img.example.com/wm999"

    def test_extra_none_when_media_url_missing(self, tmp_path) -> None:
        """media_url 为 None 时跳过水印轮询，resp.extra 为 None"""
        f = tmp_path / "photo.jpg"
        f.write_bytes(b"x" * 100)

        uploader = _make_uploader()
        resp_no_url = UploadResponse(
            upload_result=UPLOAD_STATE_SUCCESS,
            media_key="v2-abc",
            media_type=MediaType.IMAGE,
            raw_session_key="sk001",
        )

        with patch("mediacloud_uploader.client._validate_image_source", return_value=_make_image_meta()), \
             patch("mediacloud_uploader.image_transcoder.needs_transcode", return_value=False), \
             patch.object(uploader, "upload", return_value=resp_no_url):
            result = uploader.upload_image(file_path=str(f), scene_name="answer")

        assert result.extra is None


class TestUploadVideoHighLevel:
    def test_file_path_success(self, tmp_path) -> None:
        """upload_video(file_path=...) 基础成功路径"""
        f = tmp_path / "clip.mp4"
        f.write_bytes(b"x" * 100)

        uploader = _make_uploader()
        resp = UploadResponse(
            upload_result=UPLOAD_STATE_SUCCESS,
            media_key="vid_001",
            media_type=MediaType.VIDEO,
            space_name="default",
        )

        with patch("mediacloud_uploader.client._validate_video_source"), \
             patch.object(uploader, "upload", return_value=resp):
            result = uploader.upload_video(file_path=str(f), scene_name="pin")

        assert result.upload_result == UPLOAD_STATE_SUCCESS
        assert result.media_key == "vid_001"

    def test_both_file_path_and_url_raises(self) -> None:
        """file_path 和 url 同时提供时抛 UploaderValidationError"""
        uploader = _make_uploader()
        with pytest.raises(UploaderValidationError, match="不能同时"):
            uploader.upload_video(file_path="/tmp/v.mp4", url="https://example.com/v.mp4")


class TestUploadObjectHighLevel:
    def test_file_path_success(self, tmp_path) -> None:
        """upload_object(file_path=...) 基础成功路径"""
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"x" * 100)

        uploader = _make_uploader()
        resp = UploadResponse(
            upload_result=UPLOAD_STATE_SUCCESS,
            media_key="obj/path/doc.pdf",
            media_type=MediaType.OBJECT,
            space_name="default",
        )

        with patch.object(uploader, "upload", return_value=resp):
            result = uploader.upload_object(
                file_path=str(f),
                scene_name="answer",
                template_name="obj-tmpl",
            )

        assert result.upload_result == UPLOAD_STATE_SUCCESS
        assert result.media_key == "obj/path/doc.pdf"

    def test_missing_template_raises(self, tmp_path) -> None:
        """template_name 为空时抛 UploaderValidationError"""
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"x")

        uploader = _make_uploader()
        with pytest.raises(UploaderValidationError, match="template_name"):
            uploader.upload_object(file_path=str(f), scene_name="answer", template_name="")

    def test_missing_scene_raises(self, tmp_path) -> None:
        """scene_name 为空时抛 UploaderValidationError"""
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"x")

        uploader = _make_uploader()
        with pytest.raises(UploaderValidationError):
            uploader.upload_object(file_path=str(f), scene_name="", template_name="tmpl")