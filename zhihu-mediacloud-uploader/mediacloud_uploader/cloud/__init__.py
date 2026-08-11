# -*- coding: utf-8 -*-
"""云存储 vendor registry

使用方式：
    from mediacloud_uploader import cloud
    from mediacloud_uploader.cloud.base import (
        CloudUploadAuth, CloudUploadConfig, CloudUploadAddress, CloudUploadCallback,
    )

    cloud.validate_vendor_code(vendor_code)
    storage = cloud.get_storage(vendor_code)
    result  = storage.put_object(auth, config, body)          # → CloudUploadResponse
    result  = storage.multipart_upload(auth, config, body, n) # → CloudUploadResponse
    cloud.is_credential_expired(vendor_code, err_code)
"""

from mediacloud_uploader.cloud.ali import VENDOR_CODE as VENDOR_ALI
from mediacloud_uploader.cloud.ali import AliOSS
from mediacloud_uploader.cloud.base import (
    CloudStorage,
    CloudUploadAddress,
    CloudUploadAuth,
    CloudUploadCallback,
    CloudUploadConfig,
    CloudUploadResponse,
)

__all__ = [
    "CloudStorage",
    "CloudUploadAuth",
    "CloudUploadAddress",
    "CloudUploadCallback",
    "CloudUploadConfig",
    "CloudUploadResponse",
    "VENDOR_ALI",
    "VENDOR_TX",
    "get_storage",
    "validate_vendor_code",
    "is_credential_expired",
]

# ── vendor 常量 ────────────────────────────────────────────────────────────────

VENDOR_TX = "tx"  # 腾讯云 COS（待实现）

# ── 注册表 ─────────────────────────────────────────────────────────────────────
# 只注册已实现的 vendor；TxCOS 文件存在但暂不注册，直到实现完成。

_REGISTRY: dict[str, CloudStorage] = {
    VENDOR_ALI: AliOSS(),
}


# ── 公共接口 ───────────────────────────────────────────────────────────────────


def get_storage(vendor_code: str) -> CloudStorage | None:
    """返回 vendor_code 对应的 CloudStorage 实现；未知 vendor 返回 None"""
    return _REGISTRY.get(vendor_code)


def validate_vendor_code(vendor_code: str) -> None:
    """校验 vendor_code 是否有注册实现；不合法则抛 UploaderUnsupportedVendorError"""
    if vendor_code not in _REGISTRY:
        from mediacloud_uploader.errors import UploaderUnsupportedVendorError

        raise UploaderUnsupportedVendorError(vendor_code)


def is_credential_expired(vendor_code: str, oss_error_code: str) -> bool:
    """判断给定 vendor 的 OSS 错误码是否表示凭证过期"""
    storage = _REGISTRY.get(vendor_code)
    if storage is None:
        return False
    return storage.is_credential_expired(oss_error_code)
