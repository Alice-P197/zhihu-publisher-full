# -*- coding: utf-8 -*-
"""云存储抽象接口及云层专属数据类型

所有注册的云服务（AliOSS、TxCOS 等）通过同一套 API 和参数交互。
调用方（client.py）负责将 models 层类型翻译为此处定义的云层类型。
"""

from abc import ABC, abstractmethod
from typing import BinaryIO

# ── 云层数据类型 ────────────────────────────────────────────────────────────────
# 使用 __slots__ 减少内存占用，与 zmediacloud-sdk-py 保持一致


class CloudUploadAuth:
    """STS 临时凭证（云层专属，不依赖 models.UploadAuthInfo）"""

    __slots__ = ("access_key_id", "secret_access_key", "security_token", "expiration")

    def __init__(self, access_key_id: str, secret_access_key: str, security_token: str, expiration: int = 0) -> None:
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.security_token = security_token
        self.expiration = expiration


class CloudUploadAddress:
    """OSS 直传地址（云层专属）"""

    __slots__ = ("endpoint", "bucket_name", "object_name", "region", "is_cname")

    def __init__(
        self, endpoint: str, bucket_name: str, object_name: str, region: str = "", is_cname: bool = False
    ) -> None:
        self.endpoint = endpoint
        self.bucket_name = bucket_name
        self.object_name = object_name
        self.region = region
        self.is_cname = is_cname


class CloudUploadCallback:
    """OSS 服务端回调（云层专属）"""

    __slots__ = ("url", "body", "body_type")

    def __init__(self, url: str, body: str, body_type: str) -> None:
        self.url = url
        self.body = body
        self.body_type = body_type


class CloudUploadConfig:
    """address + callback 的组合体，简化上传接口参数

    callback 可为 None（图片上传无服务端回调）。
    """

    __slots__ = ("address", "callback")

    def __init__(self, address: CloudUploadAddress, callback: CloudUploadCallback | None = None) -> None:
        self.address = address
        self.callback = callback


class CloudUploadResponse:
    """云存储操作结果，统一 put_object 和 multipart_upload 的返回类型

    vendor_upload_id: 简单上传为 None；分片上传为 OSS UploadId（用于 CommitUpload）
    """

    __slots__ = ("vendor_upload_id", "etag", "request_id")

    def __init__(
        self, vendor_upload_id: str | None = None, etag: str | None = None, request_id: str | None = None
    ) -> None:
        self.vendor_upload_id = vendor_upload_id
        self.etag = etag
        self.request_id = request_id


# ── 抽象接口 ────────────────────────────────────────────────────────────────────


class CloudStorage(ABC):
    """云存储上传接口，所有 vendor 实现此抽象类

    统一 API：所有实现通过相同的 CloudUpload* 类型交互，
    调用方无需感知底层 vendor SDK 的细节。
    """

    @abstractmethod
    def put_object(
        self, auth: CloudUploadAuth, config: CloudUploadConfig, body: bytes | BinaryIO
    ) -> CloudUploadResponse:
        """简单上传（PutObject）

        :param auth:   STS 凭证
        :param config: OSS 地址 + 回调配置
        :param body:   bytes 或 file-like object
        :return:       CloudUploadResponse（vendor_upload_id 为 None）
        :raises UploaderOSSError:
        """

    @abstractmethod
    def multipart_upload(
        self, auth: CloudUploadAuth, config: CloudUploadConfig, body: BinaryIO, file_size: int
    ) -> CloudUploadResponse:
        """分片上传

        :param auth:      STS 凭证
        :param config:    OSS 地址 + 回调配置
        :param body:      file-like object（需支持 seek）
        :param file_size: 文件总大小（bytes）
        :return:          CloudUploadResponse（vendor_upload_id 为 OSS UploadId）
        :raises UploaderOSSError:
        """

    def is_credential_expired(self, _oss_error_code: str) -> bool:
        """判断 OSS 错误码是否表示凭证过期；子类如有此机制可覆写，默认安全降级返回 False"""
        return False
