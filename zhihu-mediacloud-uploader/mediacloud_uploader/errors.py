# -*- coding: utf-8 -*-
"""统一错误类型（FR-13）"""


class UploaderError(Exception):
    """所有 uploader 错误的基类"""

    def __init__(self, message: str, code: int | str | None = None) -> None:
        self.message = message
        self.code = code
        super().__init__(self.message)

    def __str__(self) -> str:
        if self.code:
            return f"UploaderError(code={self.code}, message={self.message})"
        return f"UploaderError({self.message})"


class UploaderAuthError(UploaderError):
    """鉴权失败（CQ-003，TODO: app_key/app_secret 待接入）"""


class UploaderValidationError(UploaderError):
    """参数校验失败（FR-1, FR-5, CQ-004）"""


class UploaderAPIError(UploaderError):
    """brand-influence HTTP API 错误"""

    def __init__(self, message: str, http_status: int | None = None, api_code: int | None = None) -> None:
        super().__init__(message, code=api_code)
        self.http_status = http_status


class UploaderOSSError(UploaderError):
    """OSS 直传错误（FR-11）"""

    def __init__(self, message: str, oss_code: str | None = None, request_id: str | None = None) -> None:
        super().__init__(message, code=oss_code)
        self.request_id = request_id


class UploaderUnsupportedVendorError(UploaderError):
    """不支持的 vendor_code（FR-11）

    当前仅支持 vendor_code = "ali"（阿里云 OSS）。
    """

    def __init__(self, vendor_code: str) -> None:
        super().__init__(f"unsupported vendor_code: {vendor_code}. only 'ali' is supported.")
        self.vendor_code = vendor_code


class UploaderSessionExpiredError(UploaderError):
    """会话已超期（FR-14，CommitUpload 返回 UPLOAD_FAIL）

    会话超期时不再重试，终止上传。
    """


class UploaderDownloadError(UploaderError):
    """URL 下载失败

    当远程 URL 不可访问、返回非 200 状态码、连接超时或协议不支持时抛出。
    """

    def __init__(self, message: str, http_status: int | None = None, url: str | None = None) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.url = url
