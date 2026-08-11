# -*- coding: utf-8 -*-
"""阿里云 OSS 实现"""

import base64
import json
import logging
from typing import BinaryIO

import oss2
import oss2.models
from oss2 import Bucket, StsAuth

from mediacloud_uploader.cloud.base import (
    CloudStorage,
    CloudUploadAddress,
    CloudUploadAuth,
    CloudUploadCallback,
    CloudUploadConfig,
    CloudUploadResponse,
)
from mediacloud_uploader.errors import UploaderOSSError

logger = logging.getLogger(__name__)

VENDOR_CODE = "ali"

_PART_SIZE = 10 * 1024 * 1024  # 10 MB

_CALLBACK_VAR_UPLOAD_ID_KEY = "x:uploadID"

_CREDENTIAL_EXPIRED_CODES = frozenset(
    {
        "InvalidAccessKeyId",
        "SecurityTokenExpired",
        "AccessDenied",
        "InvalidSecurityToken",
    }
)


class AliOSS(CloudStorage):
    """阿里云 OSS 云存储实现"""

    def put_object(
        self, auth: CloudUploadAuth, config: CloudUploadConfig, body: bytes | BinaryIO
    ) -> CloudUploadResponse:
        """简单上传（PutObject）"""
        bucket = _build_bucket(auth, config.address)
        headers = _build_callback_headers(config.callback) if config.callback else {}

        try:
            result = bucket.put_object(config.address.object_name, body, headers=headers)
        except oss2.exceptions.OssError as e:
            raise UploaderOSSError(
                "PutObject failed: {}".format(e.message),
                oss_code=e.code,
                request_id=e.request_id,
            )

        logger.debug(
            "[PutObject] bucket=%s key=%s status=%s",
            config.address.bucket_name,
            config.address.object_name,
            result.status,
        )
        return CloudUploadResponse(
            vendor_upload_id=None,
            etag=result.etag,
            request_id=result.request_id,
        )

    def multipart_upload(
        self, auth: CloudUploadAuth, config: CloudUploadConfig, body: BinaryIO, file_size: int
    ) -> CloudUploadResponse:
        """分片上传（MultipartUpload）"""
        bucket = _build_bucket(auth, config.address)

        try:
            init_result = bucket.init_multipart_upload(config.address.object_name)
        except oss2.exceptions.OssError as e:
            raise UploaderOSSError(
                "MultipartUpload init failed: {}".format(e.message),
                oss_code=e.code,
                request_id=e.request_id,
            )

        upload_id = init_result.upload_id
        logger.debug(
            "[MultipartUpload] init bucket=%s key=%s upload_id=%s",
            config.address.bucket_name,
            config.address.object_name,
            upload_id,
        )

        parts = []
        part_number = 1
        offset = 0

        try:
            while offset < file_size:
                size = min(_PART_SIZE, file_size - offset)
                body.seek(offset)
                chunk = body.read(size)

                part_result = bucket.upload_part(
                    config.address.object_name,
                    upload_id,
                    part_number,
                    chunk,
                )
                parts.append(oss2.models.PartInfo(part_number, part_result.etag))
                logger.debug("[MultipartUpload] part %d size=%d", part_number, size)
                part_number += 1
                offset += size

            headers = _build_multipart_callback_headers(config.callback, upload_id) if config.callback else {}
            complete_result = bucket.complete_multipart_upload(
                config.address.object_name,
                upload_id,
                parts,
                headers=headers,
            )

        # H2 修复：所有异常（包括 IOError/body.seek 失败）都触发 abort，不仅限于 OssError
        except Exception as e:
            try:
                bucket.abort_multipart_upload(config.address.object_name, upload_id)
            except Exception:
                pass
            if isinstance(e, oss2.exceptions.OssError):
                raise UploaderOSSError(
                    f"MultipartUpload failed: {e.message}",
                    oss_code=e.code,
                    request_id=e.request_id,
                )
            raise UploaderOSSError(f"MultipartUpload failed: {e}")

        logger.debug(
            "[MultipartUpload] complete bucket=%s key=%s upload_id=%s",
            config.address.bucket_name,
            config.address.object_name,
            upload_id,
        )
        return CloudUploadResponse(
            vendor_upload_id=upload_id,
            etag=getattr(complete_result, "etag", None),
            request_id=getattr(complete_result, "request_id", None),
        )

    def is_credential_expired(self, _oss_error_code: str) -> bool:
        return _oss_error_code in _CREDENTIAL_EXPIRED_CODES


# ── 内部辅助 ────────────────────────────────────────────────────────────────────


def _build_bucket(auth: CloudUploadAuth, address: CloudUploadAddress) -> Bucket:
    sts_auth = StsAuth(
        access_key_id=auth.access_key_id,
        access_key_secret=auth.secret_access_key,
        security_token=auth.security_token,
    )
    return Bucket(
        auth=sts_auth,
        endpoint=address.endpoint,
        bucket_name=address.bucket_name,
        is_cname=address.is_cname,
    )


def _build_callback_headers(callback: CloudUploadCallback) -> dict[str, str]:
    params = {
        "callbackUrl": callback.url,
        "callbackBody": callback.body,
        "callbackBodyType": callback.body_type,
    }
    encoded = base64.b64encode(json.dumps(params).encode("utf-8")).decode("utf-8")
    return {"x-oss-callback": encoded}


def _build_multipart_callback_headers(callback: CloudUploadCallback, upload_id: str) -> dict[str, str]:
    params = {
        "callbackUrl": callback.url,
        "callbackBody": callback.body,
        "callbackBodyType": callback.body_type,
    }
    callback_var = {_CALLBACK_VAR_UPLOAD_ID_KEY: upload_id}

    encoded_callback = base64.b64encode(
        json.dumps(params).encode("utf-8"),
    ).decode("utf-8")
    encoded_var = base64.b64encode(
        json.dumps(callback_var).encode("utf-8"),
    ).decode("utf-8")

    return {
        "x-oss-callback": encoded_callback,
        "x-oss-callback-var": encoded_var,
    }
