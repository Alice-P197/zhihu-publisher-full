# -*- coding: utf-8 -*-
"""zhihu-mediacloud-uploader: 端侧统一上传 skill"""

__version__ = "0.1.5"

from mediacloud_uploader.client import MediaCloudUploader
from mediacloud_uploader.errors import (
    UploaderAPIError,
    UploaderAuthError,
    UploaderDownloadError,
    UploaderError,
    UploaderOSSError,
    UploaderSessionExpiredError,
    UploaderUnsupportedVendorError,
    UploaderValidationError,
)
from mediacloud_uploader.models import (
    MediaMeta,
    MediaType,
    MediaURL,
    UploadResponse,
    UploadExtra,
)

__all__ = [
    # SDK 入口
    "MediaCloudUploader",
    # 返回值类型
    "UploadResponse",
    "MediaMeta",
    "MediaURL",
    "MediaType",
    "UploadExtra",
    # 错误类（catch 时需要）
    "UploaderError",
    "UploaderAuthError",
    "UploaderValidationError",
    "UploaderAPIError",
    "UploaderOSSError",
    "UploaderUnsupportedVendorError",
    "UploaderSessionExpiredError",
    "UploaderDownloadError",
]
