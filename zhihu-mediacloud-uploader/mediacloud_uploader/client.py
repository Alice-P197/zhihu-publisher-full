# -*- coding: utf-8 -*-
"""MediaCloudUploader 主客户端：三步式上传（ApplyUpload → OSS → CommitUpload）"""

from __future__ import annotations

import hashlib
import io
import logging
import mimetypes
import os
from typing import BinaryIO

from mediacloud_uploader import cloud
from mediacloud_uploader.api import MediaAPIClient
from mediacloud_uploader.cloud.base import (
    CloudUploadAddress,
    CloudUploadAuth,
    CloudUploadCallback,
    CloudUploadConfig,
)
from mediacloud_uploader.downloader import download_url_to_file, filename_from_url
from mediacloud_uploader.errors import (
    UploaderAPIError,
    UploaderOSSError,
    UploaderSessionExpiredError,
    UploaderUnsupportedVendorError,
    UploaderValidationError,
)
from mediacloud_uploader.image_transcoder import needs_transcode, transcode_to_webp
from mediacloud_uploader.image_validator import ImageMeta, probe_image, validate_image_meta
from mediacloud_uploader.models import (
    CLIENT_UPLOAD_STATE_FAIL,
    CLIENT_UPLOAD_STATE_SUCCESS,
    MULTIPART_THRESHOLD_BYTES,
    TEMPLATE_NAME_IMAGE,
    TEMPLATE_NAME_VIDEO,
    UPLOAD_STATE_FAIL,
    UPLOAD_STATE_SUCCESS,
    ApplyUploadRequest,
    ApplyUploadResponse,
    CommitUploadRequest,
    MediaMeta,
    MediaType,
    MediaURL,
    UploadRequest,
    UploadResponse,
)
from mediacloud_uploader.video_validator import probe_video, validate_video_meta
from mediacloud_uploader.watermark_poller import poll_watermark

logger = logging.getLogger(__name__)

# 图片 token 前缀，与 pier SDK 的 formatToken 保持一致（"v2-" + md5hex）
_IMAGE_TOKEN_PREFIX = "v2-"

# ── SDK 高层方法使用的常量与辅助函数 ─────────────────────────────────────────────────

_VALID_IMAGE_SCENE_NAMES: frozenset[str] = frozenset({"answer", "question", "pin", "article"})

_SDK_DEFAULT_CONTENT_TYPE: dict[str, str] = {
    MediaType.IMAGE: "image/jpeg",
    MediaType.VIDEO: "video/mp4",
    MediaType.OBJECT: "application/octet-stream",
}

_SDK_GENERIC_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "application/octet-stream",
        "application/binary",
        "binary/octet-stream",
    }
)

_SENSITIVE_PATH_PREFIXES = ("/etc/", "/proc/", "/sys/", "/dev/", "/root/", "/var/run/", "/run/")
_SENSITIVE_PATH_PATTERNS = (".ssh/", "/.gnupg/", "/keychain/")

_DEFAULT_BASE_URL = "https://openapi.zhihu.com"


def _check_path_safety(file_path: str) -> None:
    """路径安全检查：拒绝系统敏感路径和凭证目录。"""
    resolved = os.path.normpath(file_path)
    for prefix in _SENSITIVE_PATH_PREFIXES:
        if resolved.startswith(prefix):
            raise UploaderValidationError(f"不允许访问系统敏感路径: {file_path}")
    for pat in _SENSITIVE_PATH_PATTERNS:
        if pat in resolved:
            raise UploaderValidationError(f"不允许访问凭证目录下的文件: {file_path}")


def _check_upload_source(file_path: str | None, url: str | None) -> None:
    if file_path and url:
        raise UploaderValidationError("file_path 和 url 不能同时提供，请选择其中一个")
    if not file_path and not url:
        raise UploaderValidationError("请提供 file_path（本地路径）或 url（远程地址）之一")


def _detect_ct(path_or_name: str, media_type: str) -> str:
    guessed, _ = mimetypes.guess_type(path_or_name)
    if guessed:
        return guessed
    return _SDK_DEFAULT_CONTENT_TYPE.get(media_type, "application/octet-stream")


def _detect_ct_no_fallback(path_or_name: str) -> str:
    if not path_or_name:
        return ""
    guessed, _ = mimetypes.guess_type(path_or_name)
    return guessed or ""


def _resolve_ct(
    content_type_arg: str,
    resp_ct: str,
    url_filename: str,
    media_type: str,
) -> str | None:
    if content_type_arg:
        return content_type_arg
    if resp_ct and resp_ct not in _SDK_GENERIC_CONTENT_TYPES:
        return resp_ct
    detected = _detect_ct_no_fallback(url_filename)
    if detected:
        return detected
    if media_type == MediaType.OBJECT:
        return resp_ct or _SDK_DEFAULT_CONTENT_TYPE[MediaType.OBJECT]
    return None  # IMAGE/VIDEO 无法推断 → 调用方报错


def _replace_ext(file_name: str, new_ext: str) -> str:
    root, _ = os.path.splitext(file_name)
    return root + new_ext


def _validate_image_source(source: str | io.IOBase) -> ImageMeta:
    try:
        meta = probe_image(source)
        validate_image_meta(meta)
        return meta
    except UploaderValidationError:
        raise
    except Exception:
        logger.exception("unexpected error during image pre-validation")
        raise


def _validate_video_source(source: str) -> None:
    try:
        meta = probe_video(source)
        validate_video_meta(meta)
    except UploaderValidationError:
        raise
    except Exception:
        logger.exception("unexpected error during video pre-validation")
        raise


class MediaCloudUploader:
    """端侧三步式统一上传客户端

    :param app_key:    知乎用户 Token（知乎主页 URL 中的用户名，如 zhihu.com/people/abc → abc）
    :param app_secret: 开放平台访问密钥（SK），在知乎开放平台申请
    :param base_url:   服务地址
    :param timeout:    HTTP 超时（秒）
    """

    def __init__(self, app_key: str = "", app_secret: str = "", base_url: str = "", timeout: int = 30) -> None:
        self._http_client = MediaAPIClient(
            app_key=app_key,
            app_secret=app_secret,
            base_url=base_url or _DEFAULT_BASE_URL,
            timeout=timeout,
        )

    # ── SDK 高层方法 ──────────────────────────────────────────────────────────────

    def upload_image(
        self,
        *,
        file_path: str | None = None,
        url: str | None = None,
        scene_name: str,
        content_type: str = "",
        file_name: str = "",
    ) -> UploadResponse:
        """上传图片（含前置校验、URL 下载、格式转码、水印轮询）。

        :param file_path:    本地绝对路径（与 url 二选一）
        :param url:          公开可访问的图片 URL（与 file_path 二选一）
        :param scene_name:   发布场景：answer / question / pin / article
        :param content_type: MIME 类型（不填则自动检测）
        :param file_name:    文件名（可选）
        :return:             UploadResponse（失败抛 UploaderError 子类）
        """
        if scene_name not in _VALID_IMAGE_SCENE_NAMES:
            msg = (
                "请提供 scene_name 参数，有效值：answer（回答）、question（问题）、pin（想法）、article（文章）。"
                if not scene_name
                else f"scene_name 值 {scene_name!r} 不合法，有效值：answer / question / pin / article。"
            )
            raise UploaderValidationError(msg)

        _check_upload_source(file_path, url)

        tmp_path: str | None = None
        try:
            if url:
                tmp_path, _, resp_ct = download_url_to_file(url)
                url_filename = filename_from_url(url)
                resolved_ct = _resolve_ct(content_type, resp_ct, url_filename, MediaType.IMAGE)
                if resolved_ct is None:
                    raise UploaderValidationError(
                        f"无法从 URL 确认文件类型（响应 Content-Type: {resp_ct!r}，URL 无可识别扩展名）。"
                        "请通过 content_type 参数明确指定，例如：image/jpeg、image/png、image/webp、image/heic。"
                    )
                content_type = resolved_ct
                file_path = tmp_path
                file_name = file_name or url_filename
            else:
                assert file_path is not None
                _check_path_safety(file_path)
                if not os.path.isfile(file_path):
                    raise UploaderValidationError(f"文件不存在: {file_path}")
                if not content_type:
                    content_type = _detect_ct(file_path, MediaType.IMAGE)

            image_meta = _validate_image_source(file_path)
            file_ext = os.path.splitext(file_path)[1]

            req_file_path: str | None = file_path
            req_file_obj: io.IOBase | None = None
            req_file_size: int = 0

            # ── [WATERMARK PATCH] 转码：HEIC/HEIF/AVIF → WebP ────────────────────
            if needs_transcode(image_meta.format):
                try:
                    tr = transcode_to_webp(file_path, image_meta.format)
                except Exception:
                    logger.exception("[upload_image] transcoding failed")
                    raise
                req_file_path = None
                req_file_obj = tr.data
                req_file_size = tr.size
                content_type = tr.content_type
                file_ext = tr.file_extension
                if file_name:
                    file_name = _replace_ext(file_name, tr.file_extension)

            req = UploadRequest(
                media_type=MediaType.IMAGE,
                scene_name=scene_name,
                template_name=TEMPLATE_NAME_IMAGE,
                file_path=req_file_path,
                file_obj=req_file_obj,
                file_size=req_file_size,
                content_type=content_type,
                file_extension=file_ext,
                file_name=file_name,
            )
            resp = self.upload(req)

            # ── [WATERMARK PATCH BEGIN] 水印轮询 ─────────────────────────────────
            if resp.is_success and resp._raw_session_key:
                if resp.media_url:
                    wm = poll_watermark(
                        http_client=self._http_client,
                        image_id=resp._raw_session_key,
                        scene_name=scene_name,
                        fallback_key=resp.media_key,
                        fallback_url=resp.media_url,
                    )
                    resp.extra = wm
                else:
                    logger.warning(
                        "[upload_image] watermark skipped: media_url is None. image_id=%s",
                        resp._raw_session_key,
                    )
            # ── [WATERMARK PATCH END] ─────────────────────────────────────────────

            return resp

        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def upload_video(
        self,
        *,
        file_path: str | None = None,
        url: str | None = None,
        scene_name: str = "pin",
        content_type: str = "",
        file_name: str = "",
        template_name: str = TEMPLATE_NAME_VIDEO,
    ) -> UploadResponse:
        """上传视频/音频（含前置校验、URL 下载）。

        :param file_path:     本地绝对路径（与 url 二选一）
        :param url:           公开可访问的视频 URL（与 file_path 二选一）
        :param scene_name:    发布场景，默认 "pin"
        :param content_type:  MIME 类型（不填则自动检测）
        :param file_name:     文件名（可选）
        :param template_name: 上传模板名称（默认 video_template）
        :return:              UploadResponse（失败抛 UploaderError 子类）
        """
        _check_upload_source(file_path, url)

        tmp_path: str | None = None
        try:
            if url:
                tmp_path, _, resp_ct = download_url_to_file(url)
                url_filename = filename_from_url(url)
                resolved_ct = _resolve_ct(content_type, resp_ct, url_filename, MediaType.VIDEO)
                if resolved_ct is None:
                    raise UploaderValidationError(
                        f"无法从 URL 确认文件类型（响应 Content-Type: {resp_ct!r}，URL 无可识别扩展名）。"
                        "请通过 content_type 参数明确指定，例如：video/mp4、video/quicktime、audio/mpeg。"
                    )
                content_type = resolved_ct
                file_path = tmp_path
                file_name = file_name or url_filename
            else:
                assert file_path is not None
                _check_path_safety(file_path)
                if not os.path.isfile(file_path):
                    raise UploaderValidationError(f"文件不存在: {file_path}")
                if not content_type:
                    content_type = _detect_ct(file_path, MediaType.VIDEO)

            _validate_video_source(file_path)

            req = UploadRequest(
                media_type=MediaType.VIDEO,
                scene_name=scene_name,
                template_name=template_name,
                file_path=file_path,
                content_type=content_type,
                file_extension=os.path.splitext(file_path)[1],
                file_name=file_name,
            )
            return self.upload(req)

        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def upload_object(
        self,
        *,
        file_path: str | None = None,
        url: str | None = None,
        scene_name: str,
        template_name: str,
        content_type: str = "",
        file_name: str = "",
    ) -> UploadResponse:
        """上传任意静态文件（PDF、ZIP、二进制等）。

        :param file_path:     本地绝对路径（与 url 二选一）
        :param url:           公开可访问的文件 URL（与 file_path 二选一）
        :param scene_name:    发布场景（必填）
        :param template_name: 上传模板名称（必填，由平台分配）
        :param content_type:  MIME 类型（不填则自动检测）
        :param file_name:     文件名（可选）
        :return:              UploadResponse（失败抛 UploaderError 子类）
        """
        if not scene_name:
            raise UploaderValidationError(
                "请提供 scene_name 参数：answer（回答）、question（问题）、pin（想法）、article（文章）。"
            )
        if not template_name:
            raise UploaderValidationError("template_name 是必填参数，请向平台确认上传模板名称。")

        _check_upload_source(file_path, url)

        tmp_path: str | None = None
        try:
            if url:
                tmp_path, _, resp_ct = download_url_to_file(url)
                url_filename = filename_from_url(url)
                resolved_ct = _resolve_ct(content_type, resp_ct, url_filename, MediaType.OBJECT)
                content_type = resolved_ct or _SDK_DEFAULT_CONTENT_TYPE[MediaType.OBJECT]
                file_path = tmp_path
                file_name = file_name or url_filename
            else:
                assert file_path is not None
                _check_path_safety(file_path)
                if not os.path.isfile(file_path):
                    raise UploaderValidationError(f"文件不存在: {file_path}")
                if not content_type:
                    content_type = _detect_ct(file_path, MediaType.OBJECT)

            req = UploadRequest(
                media_type=MediaType.OBJECT,
                scene_name=scene_name,
                template_name=template_name,
                file_path=file_path,
                content_type=content_type,
                file_extension=os.path.splitext(file_path)[1],
                file_name=file_name,
            )
            return self.upload(req)

        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    # ── 低层传输 API ──────────────────────────────────────────────────────────────

    def upload(self, req: UploadRequest) -> UploadResponse:
        """端侧三步式上传入口

        :param req: UploadRequest
        :return:    UploadResponse
        :raises UploaderError:
        """
        req.validate()
        if req.file_path:
            return self._upload_from_file(req)
        if req.file_obj is None:
            raise UploaderValidationError("file_path or file_obj is required")
        return self._upload_from_obj(req, req.file_obj, req.file_size)

    # ── 内部实现 ──────────────────────────────────────────────────────────────────

    def _upload_from_file(self, req: UploadRequest) -> UploadResponse:
        if req.file_path is None:
            raise UploaderValidationError("file_path is required")
        with open(req.file_path, "rb") as f:
            file_size = os.path.getsize(req.file_path)
            return self._upload_from_obj(req, f, file_size)

    def _upload_from_obj(self, req: UploadRequest, file_obj: BinaryIO, file_size: int) -> UploadResponse:
        # 图片分块计算 MD5 用于秒传去重（分块与整体 hash 结果完全一致）
        # video/object 不计算（需求明确不做秒传）
        content_hash = ""
        if req.media_type == MediaType.IMAGE:
            md5 = hashlib.md5()
            for chunk in iter(lambda: file_obj.read(8192), b""):
                md5.update(chunk)
            content_hash = md5.hexdigest()
            file_obj.seek(0)

        # ── Step 1: ApplyUpload ───────────────────────────────────────────────────
        apply_req = ApplyUploadRequest(
            media_type=req.media_type,
            scene_name=req.scene_name,
            template_name=req.template_name,
            platform=req.platform,
            content_type=req.content_type,
            content_hash=content_hash,
            file_extension=req.file_extension,
            file_name=req.file_name,
            file_size=file_size,
        )
        apply_resp = self._http_client.apply_upload(apply_req)
        logger.info(
            "[upload] ApplyUpload state=%s session_key=%s",
            apply_resp.upload_state,
            apply_resp.session_key,
        )

        # 图片秒传（apply 阶段即返回 UPLOAD_SUCCESS，含 meta）
        if apply_resp.is_instant_upload:
            ep = apply_resp.extra_params
            media_meta = (
                MediaMeta(
                    width=int(ep.get("width", 0)),
                    height=int(ep.get("height", 0)),
                    format=str(ep.get("format", "")),
                    size=int(ep.get("size", 0)),
                )
                if ep
                else None
            )
            raw_url = ep.get("url") if ep else None
            media_url = MediaURL.from_dict(raw_url) if isinstance(raw_url, dict) else None
            resp = UploadResponse(
                upload_result=UPLOAD_STATE_SUCCESS,
                media_key=apply_resp.object_key,
                media_type=req.media_type,
                media_meta=media_meta,
                media_url=media_url,
                raw_session_key=apply_resp.session_key if req.media_type == MediaType.IMAGE else "",
            )
        else:
            # ── Step 2: vendor 校验 ───────────────────────────────────────────────
            cloud.validate_vendor_code(apply_resp.vendor_code)

            # ── Step 3: OSS 直传（含凭证刷新重试）────────────────────────────────
            vendor_upload_id, apply_resp, upload_error = self._do_oss_upload_with_refresh(
                req,
                file_obj,
                file_size,
                apply_resp,
                content_hash,
            )

            # ── Step 4: CommitUpload ──────────────────────────────────────────────
            # C2 修复：使用可能已刷新的 apply_resp（含新 security_token / session_key）
            resp = self._do_commit(req, apply_resp, vendor_upload_id, upload_error)

        # 图片成功时，用 v2-{hash} token 替代 ImageID
        # 与 pier SDK 的 formatToken("v2-" + md5hex) 保持一致
        if req.media_type == MediaType.IMAGE and content_hash and resp.is_success:
            resp.media_key = _IMAGE_TOKEN_PREFIX + content_hash

        return resp

    def _do_oss_upload_with_refresh(
        self, req: UploadRequest, file_obj: BinaryIO, file_size: int, apply_resp: ApplyUploadResponse, content_hash: str
    ) -> tuple[str | None, ApplyUploadResponse, str | None]:
        """执行 OSS 直传，凭证过期时自动刷新一次

        :return: (vendor_upload_id, apply_resp, upload_error)
                 apply_resp 可能是已刷新的新实例，调用方需使用返回值
        """
        try:
            vendor_upload_id = self._oss_upload(req, file_obj, file_size, apply_resp)
            return vendor_upload_id, apply_resp, None
        except UploaderOSSError as e:
            if _is_credential_expired(apply_resp.vendor_code, e):
                logger.info("[upload] OSS 凭证过期，刷新中")
                apply_resp = self._refresh_credentials(req, apply_resp, content_hash)
                try:
                    file_obj.seek(0)
                    vendor_upload_id = self._oss_upload(req, file_obj, file_size, apply_resp)
                    return vendor_upload_id, apply_resp, None
                except UploaderOSSError as retry_e:
                    return None, apply_resp, str(retry_e)
            return None, apply_resp, str(e)

    def _refresh_credentials(
        self, req: UploadRequest, prev_apply_resp: ApplyUploadResponse, content_hash: str = ""
    ) -> ApplyUploadResponse:
        """携带 session_key 重调 ApplyUpload 刷新凭证

        :raises UploaderSessionExpiredError: 会话已超期（返回 UPLOAD_FAIL）
        """
        apply_req = ApplyUploadRequest(
            media_type=req.media_type,
            scene_name=req.scene_name,
            template_name=req.template_name,
            platform=req.platform,
            content_type=req.content_type,
            content_hash=content_hash,
            session_key=prev_apply_resp.session_key,
        )
        new_resp = self._http_client.apply_upload(apply_req)
        if new_resp.upload_state == UPLOAD_STATE_FAIL:
            raise UploaderSessionExpiredError(f"upload session expired, session_key={prev_apply_resp.session_key}")
        return new_resp

    def _oss_upload(
        self, req: UploadRequest, file_obj: BinaryIO, file_size: int, apply_resp: ApplyUploadResponse
    ) -> str | None:
        """执行实际 OSS 直传，按大小分派

        图片恒走 PutObject；其他文件 >= 500 MB 走 MultipartUpload。
        将 models 层类型翻译为 cloud 层统一类型后调用 storage。
        :return: vendor_upload_id（PutObject 为 None，MultipartUpload 为 upload_id）
        """
        # P1: ApplyUpload 响应完整性校验，防止 malformed 响应导致 AttributeError
        if not apply_resp.upload_auth or not apply_resp.address:
            raise UploaderAPIError("ApplyUpload response missing auth or address credentials")

        # ── models 层 → cloud 层类型翻译 ─────────────────────────────────────────
        auth = CloudUploadAuth(
            access_key_id=apply_resp.upload_auth.access_key_id,
            secret_access_key=apply_resp.upload_auth.secret_access_key,
            security_token=apply_resp.upload_auth.security_token,
            expiration=apply_resp.upload_auth.expiration,
        )
        address = CloudUploadAddress(
            endpoint=apply_resp.address.endpoint,
            bucket_name=apply_resp.address.bucket_name,
            object_name=apply_resp.address.object_name,
            region=apply_resp.address.region,
            is_cname=apply_resp.address.is_cname,
        )
        cb = apply_resp.callback
        callback = CloudUploadCallback(cb.url, cb.body, cb.body_type) if cb else None
        config = CloudUploadConfig(address=address, callback=callback)

        use_simple = req.media_type == MediaType.IMAGE or file_size < MULTIPART_THRESHOLD_BYTES
        storage = cloud.get_storage(apply_resp.vendor_code)
        # P2②: validate_vendor_code 已在上游调用，此处 storage 必须非 None
        if storage is None:
            raise UploaderUnsupportedVendorError(f"vendor_code validated but not in registry: {apply_resp.vendor_code}")

        if use_simple:
            logger.info(
                "[upload] PutObject bucket=%s key=%s size=%d",
                address.bucket_name,
                address.object_name,
                file_size,
            )
            result = storage.put_object(auth=auth, config=config, body=file_obj)
        else:
            logger.info(
                "[upload] MultipartUpload bucket=%s key=%s size=%d",
                address.bucket_name,
                address.object_name,
                file_size,
            )
            result = storage.multipart_upload(
                auth=auth,
                config=config,
                body=file_obj,
                file_size=file_size,
            )

        return result.vendor_upload_id

    def _do_commit(
        self,
        req: UploadRequest,
        apply_resp: ApplyUploadResponse,
        vendor_upload_id: str | None,
        upload_error: str | None,
    ) -> UploadResponse:
        """调用 CommitUpload；OSS 失败时也上报（保证服务端状态一致）"""
        security_token = ""
        if apply_resp.upload_auth:
            security_token = apply_resp.upload_auth.security_token

        commit_req = CommitUploadRequest(
            media_type=req.media_type,
            session_key=apply_resp.session_key,
            client_upload_state=(CLIENT_UPLOAD_STATE_FAIL if upload_error else CLIENT_UPLOAD_STATE_SUCCESS),
            platform=req.platform,
            security_token=security_token,
            vendor_upload_id=vendor_upload_id or "",
            error_log=upload_error or "",
            processes=apply_resp.processes,
        )

        commit_resp = self._http_client.commit_upload(
            apply_resp.commit_address,
            commit_req,
            scene_name=req.scene_name,
            platform=req.platform,
        )
        logger.info("[upload] CommitUpload state=%s", commit_resp.upload_result)

        return UploadResponse(
            upload_result=commit_resp.upload_result,
            media_key=commit_resp.media_key or apply_resp.object_key,
            media_type=req.media_type,
            space_name=commit_resp.space_name,
            media_meta=commit_resp.media_meta,
            media_url=commit_resp.media_url,
            raw_session_key=apply_resp.session_key if req.media_type == MediaType.IMAGE else "",  # [WATERMARK PATCH]
        )


# ── 辅助 ─────────────────────────────────────────────────────────────────────────


def _is_credential_expired(vendor_code: str, oss_error: UploaderOSSError) -> bool:
    return cloud.is_credential_expired(vendor_code, str(oss_error.code)) if oss_error.code else False
