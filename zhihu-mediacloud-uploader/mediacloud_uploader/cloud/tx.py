# -*- coding: utf-8 -*-
"""腾讯云 COS 实现（占位，暂未实现）"""

from typing import BinaryIO

from mediacloud_uploader.cloud.base import (
    CloudStorage,
    CloudUploadAuth,
    CloudUploadConfig,
    CloudUploadResponse,
)

VENDOR_CODE = "tx"


class TxCOS(CloudStorage):
    """腾讯云 COS 云存储实现（待接入）"""

    def put_object(
        self, auth: CloudUploadAuth, config: CloudUploadConfig, body: bytes | BinaryIO
    ) -> CloudUploadResponse:
        raise NotImplementedError("Tencent COS support is not yet implemented")

    def multipart_upload(
        self, auth: CloudUploadAuth, config: CloudUploadConfig, body: BinaryIO, file_size: int
    ) -> CloudUploadResponse:
        raise NotImplementedError("Tencent COS support is not yet implemented")

    # is_credential_expired 继承 CloudStorage 默认实现，返回 False（安全降级）
