# -*- coding: utf-8 -*-
"""media 上传 OpenAPI 客户端封装"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
import uuid
from typing import Any

import requests

from mediacloud_uploader.errors import UploaderAPIError, UploaderAuthError
from mediacloud_uploader.models import (
    ApplyUploadRequest,
    ApplyUploadResponse,
    CommitUploadRequest,
    CommitUploadResponse,
    ImageProcessResultResponse,
    MediaMeta,
    MediaURL,
    UploadAddressInfo,
    UploadAuthInfo,
    UploadCallbackInfo,
)

logger = logging.getLogger(__name__)

# ── API 路径 ─────────────────────────────────────────────────────────────────────

_PATH_APPLY_UPLOAD = "/openapi/media/uploads"
_PATH_COMMIT_UPLOAD = "/openapi/media/uploads/{}"  # {} = session_key
_PATH_GET_IMAGE_WATERMARK = "/openapi/media/images/{}/watermark"  # {} = image_id

# ── 请求 Header 名 ───────────────────────────────────────────────────────────────

_H_CONTENT_TYPE = "Content-Type"
_H_APP_KEY = "X-App-Key"
_H_TIMESTAMP = "X-Timestamp"
_H_LOG_ID = "X-Log-Id"
_H_EXTRA_INFO = "X-Extra-Info"
_H_SIGN = "X-Sign"
_H_SCENE_NAME = "X-Media-Scene-Name"
_H_UPLOAD_PLATFORM = "X-Media-Upload-Platform"
_H_UPLOAD_CTYPE = "X-Upload-Content-Type"
_H_UPLOAD_HASH = "X-Upload-Content-Hash"
_H_SECURITY_TOKEN = "X-Security-Token"

# ── 签名格式 ─────────────────────────────────────────────────────────────────────

_SIGN_FORMAT = "app_key:{app_key}|ts:{ts}|logid:{log_id}|extra_info:{extra_info}"

# ── 响应 JSON key ────────────────────────────────────────────────────────────────

_RESP_UPLOAD_STATE = "upload_state"
_RESP_SESSION_KEY = "session_key"
_RESP_UPLOAD_MEDIA = "upload_media"
_RESP_UPLOAD_CONFIG = "upload_config"
_RESP_UPLOAD_AUTH = "upload_auth"
_RESP_EXTRA_PARAMS = "extra_params"
_RESP_VENDOR_CODE = "vendor_code"
_RESP_UPLOAD_RESULTS = "upload_results"
_RESP_MEDIA_KEY = "media_key"
_RESP_SPACE_NAME = "space_name"
_RESP_MEDIA_META = "media_meta"
_RESP_MEDIA_URL = "media_url"
_RESP_COMMIT_ADDR = "commit_address"
_RESP_KEY = "key"
_RESP_PROCESSES = "processes"

_DEFAULT_TIMEOUT = 30

_HTTP_STATUS_UNAUTHORIZED = 401


class MediaAPIClient:
    """Media 上传 OpenAPI 客户端

    :param base_url:   服务地址，如 "https://openapi.zhihu.com"
    :param app_key:    知乎用户 Token（知乎主页 URL 中的用户名，如 zhihu.com/people/abc → abc）
    :param app_secret: 开放平台访问密钥（SK），在知乎开放平台申请
    :param timeout:    HTTP 超时（秒）
    """

    def __init__(self, base_url: str, app_key: str, app_secret: str, timeout: int = _DEFAULT_TIMEOUT) -> None:
        self.base_url = base_url.rstrip("/")
        self.app_key = app_key
        self.app_secret = app_secret
        self.timeout = timeout
        self._session = requests.Session()

    # ── ApplyUpload ───────────────────────────────────────────────────────────────

    def apply_upload(self, req: ApplyUploadRequest) -> ApplyUploadResponse:
        """调用 ApplyUpload OpenAPI

        :param req: ApplyUploadRequest
        :return:    ApplyUploadResponse
        :raises UploaderAPIError:
        """
        url = self.base_url + _PATH_APPLY_UPLOAD

        headers = self._build_auth_headers()
        headers[_H_SCENE_NAME] = req.scene_name
        headers[_H_UPLOAD_PLATFORM] = req.platform
        headers[_H_UPLOAD_CTYPE] = req.content_type
        if req.content_hash:
            headers[_H_UPLOAD_HASH] = req.content_hash

        body: dict[str, Any] = {
            "template_name": req.template_name,
            "media_type": req.media_type,
        }
        if req.file_name:
            body["file_name"] = req.file_name
        if req.file_extension:
            body["file_extension"] = req.file_extension
        if req.file_size:
            body["file_size"] = req.file_size
        if req.session_key:
            body["session_key"] = req.session_key

        logger.debug(
            "[ApplyUpload] POST %s template=%s scene=%s",
            url,
            req.template_name,
            req.scene_name,
        )
        resp_data = self._request("POST", url, headers=headers, json_body=body)
        return self._parse_apply_upload_response(resp_data)

    # ── CommitUpload ──────────────────────────────────────────────────────────────

    def commit_upload(
        self, commit_address: str, req: CommitUploadRequest, scene_name: str, platform: str
    ) -> CommitUploadResponse:
        """调用 CommitUpload OpenAPI

        :param commit_address: ApplyUpload 动态下发的地址（图片为空，fallback 到默认路径）
        :param req:            CommitUploadRequest
        :param scene_name:     X-Media-Scene-Name（required header）
        :param platform:       X-Media-Upload-Platform（required header）
        :return:               CommitUploadResponse
        :raises UploaderAPIError:
        """
        # session_key 在 URL path，不在 body
        default_url = self.base_url + _PATH_COMMIT_UPLOAD.format(req.session_key)
        url = commit_address or default_url

        headers = self._build_auth_headers()
        headers[_H_SCENE_NAME] = scene_name
        headers[_H_UPLOAD_PLATFORM] = platform
        headers[_H_SECURITY_TOKEN] = req.security_token

        body: dict[str, Any] = {
            "media_type": req.media_type,
            "client_upload_state": req.client_upload_state,
        }
        if req.vendor_upload_id:
            body["vendor_upload_id"] = req.vendor_upload_id
        if req.error_log:
            body["error_log"] = req.error_log
        if req.processes:
            body["processes"] = req.processes

        logger.debug(
            "[CommitUpload] PATCH %s session_key=%s state=%s",
            url,
            req.session_key,
            req.client_upload_state,
        )
        resp_data = self._request("PATCH", url, headers=headers, json_body=body)
        return self._parse_commit_upload_response(resp_data)

    # ── GetImageProcessResult [WATERMARK PATCH] ───────────────────────────────────

    def get_image_process_result(self, image_id: str, scene_name: str) -> ImageProcessResultResponse:
        """查询图片水印处理结果（供水印 Patch 轮询使用）

        :param image_id:   ImageID（即 ApplyUpload 响应的 session_key）
        :param scene_name: X-Media-Scene-Name
        :return:           ImageProcessResultResponse
        :raises UploaderAPIError:
        """
        url = self.base_url + _PATH_GET_IMAGE_WATERMARK.format(image_id)
        headers = self._build_auth_headers()
        headers[_H_SCENE_NAME] = scene_name

        logger.debug("[GetImageProcessResult] GET %s image_id=%s", url, image_id)
        data = self._request("GET", url, headers=headers)
        return self._parse_image_process_result_response(data)

    # ── 内部辅助 ──────────────────────────────────────────────────────────────────

    def _build_auth_headers(self) -> dict[str, str]:
        """构建 OpenAPI 鉴权 Header（HMAC-SHA256 签名）"""
        ts = str(int(time.time()))
        log_id = f"req_{uuid.uuid4().hex}"
        extra_info = ""
        sign_str = _SIGN_FORMAT.format(
            app_key=self.app_key,
            ts=ts,
            log_id=log_id,
            extra_info=extra_info,
        )
        h = hmac.new(self.app_secret.encode("utf-8"), sign_str.encode("utf-8"), hashlib.sha256)
        sign = base64.b64encode(h.digest()).decode("utf-8")

        return {
            _H_CONTENT_TYPE: "application/json",
            _H_APP_KEY: self.app_key,
            _H_TIMESTAMP: ts,
            _H_LOG_ID: log_id,
            _H_EXTRA_INFO: extra_info,
            _H_SIGN: sign,
        }

    def _request(self, method: str, url: str, headers: dict[str, str], json_body: dict | None = None) -> dict:
        """发送 HTTP 请求并解析响应封装

        :param method:    HTTP method（"POST" / "PATCH" / "GET"）
        :param url:       请求 URL
        :param headers:   请求头
        :param json_body: 请求 body（GET 时为 None）
        :return:          data 字段内容（dict）
        :raises UploaderAPIError:
        """
        logger.info(f"[_request] {method} {url}")
        try:
            resp = self._session.request(
                method,
                url,
                headers=headers,
                data=json.dumps(json_body) if json_body is not None else None,
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise UploaderAPIError(f"HTTP request failed: {e}")

        if resp.status_code == _HTTP_STATUS_UNAUTHORIZED:
            raise UploaderAuthError("Authentication failed: HTTP 401")

        if not resp.ok:
            raise UploaderAPIError(
                f"HTTP error: method={method} url={url} status={resp.status_code} body={resp.text}",
                http_status=resp.status_code,
            )

        try:
            payload = resp.json()
        except ValueError as e:
            raise UploaderAPIError(f"Invalid JSON response: {e}")

        return payload

    @staticmethod
    def _parse_apply_upload_response(data: dict) -> ApplyUploadResponse:
        # address/callback/vendor_code 嵌套在 upload_config 下（区别于顶层字段）
        upload_config_raw = data.get(_RESP_UPLOAD_CONFIG) or {}
        vendor_code = upload_config_raw.get(_RESP_VENDOR_CODE, "")
        address_raw = upload_config_raw.get("address") or {}
        # callback 为 null/missing 时给空 dict：避免 None or {} = {} 被当作 truthy 触发构建
        _callback_val = upload_config_raw.get("callback")
        callback_raw = _callback_val if isinstance(_callback_val, dict) else {}

        # brand-influence 服务层使用 snake_case，字段名与旧版 API 不同
        upload_auth_raw = data.get(_RESP_UPLOAD_AUTH) or {}
        upload_auth = (
            UploadAuthInfo(
                access_key_id=upload_auth_raw.get("access_key_id", ""),
                secret_access_key=upload_auth_raw.get("secret_access_key", ""),
                security_token=upload_auth_raw.get("security_token", ""),
                expiration=upload_auth_raw.get("expiration", 0),
            )
            if upload_auth_raw
            else None
        )

        address = (
            UploadAddressInfo(
                endpoint=address_raw.get("endpoint", ""),
                bucket_name=address_raw.get("bucket_name", ""),
                object_name=address_raw.get("object_name", ""),
                region=address_raw.get("region", ""),
                is_cname=address_raw.get("is_cname", False),
            )
            if address_raw
            else None
        )

        # 只有 callback 包含有效 url 时才构建（图片 callback 为空）
        callback = (
            UploadCallbackInfo(
                url=callback_raw.get("url", ""),
                body=callback_raw.get("body", ""),
                body_type=callback_raw.get("body_type", ""),
            )
            if callback_raw.get("url")
            else None
        )

        upload_media = data.get(_RESP_UPLOAD_MEDIA) or {}

        return ApplyUploadResponse(
            upload_state=data.get(_RESP_UPLOAD_STATE, ""),
            session_key=data.get(_RESP_SESSION_KEY, ""),
            vendor_code=vendor_code,
            commit_address=upload_media.get(_RESP_COMMIT_ADDR, ""),
            object_key=upload_media.get(_RESP_KEY, ""),
            processes=upload_media.get(_RESP_PROCESSES, ""),
            extra_params=data.get(_RESP_EXTRA_PARAMS) or {},
            upload_auth=upload_auth,
            address=address,
            callback=callback,
        )

    @staticmethod
    def _parse_commit_upload_response(data: dict) -> CommitUploadResponse:
        raw_meta = data.get(_RESP_MEDIA_META)
        media_meta = (
            MediaMeta(
                width=raw_meta.get("width", 0),
                height=raw_meta.get("height", 0),
                format=raw_meta.get("format", ""),
                size=raw_meta.get("size", 0),
            )
            if raw_meta
            else None
        )

        # JSON 字段名 upload_results，映射到 CommitUploadResponse.upload_result
        raw_url = data.get(_RESP_MEDIA_URL)
        media_url = MediaURL.from_dict(raw_url) if isinstance(raw_url, dict) else None

        return CommitUploadResponse(
            upload_result=data.get(_RESP_UPLOAD_RESULTS, ""),
            media_key=data.get(_RESP_MEDIA_KEY, ""),
            space_name=data.get(_RESP_SPACE_NAME, ""),
            media_meta=media_meta,
            media_url=media_url,
        )

    @staticmethod
    def _parse_image_process_result_response(data: dict) -> ImageProcessResultResponse:
        raw_url = data.get("watermark_image_url")
        watermark_url = MediaURL.from_dict(raw_url) if isinstance(raw_url, dict) else None
        return ImageProcessResultResponse(
            state=data.get("state", ""),
            original_image_token=data.get("original_image_token", ""),
            watermark_image_token=data.get("watermark_image_token", ""),
            watermark_image_url=watermark_url,
        )
