# -*- coding: utf-8 -*-
"""请求/响应数据模型"""

from __future__ import annotations

from typing import BinaryIO

# ── 媒体类型 ────────────────────────────────────────────────────────────────────


class MediaType:
    OBJECT = "object"
    VIDEO = "video"
    IMAGE = "image"


# ── 上传状态（服务端 UploadState.String() 值）──────────────────────────────────

UPLOAD_STATE_UPLOADING = "UPLOADING"
UPLOAD_STATE_SUCCESS = "UPLOAD_SUCCESS"
UPLOAD_STATE_FAIL = "UPLOAD_FAIL"
UPLOAD_STATE_CANCEL = "UPLOAD_CANCEL"

# CommitUpload body 中 client_upload_state 合法值
CLIENT_UPLOAD_STATE_SUCCESS = "UPLOAD_SUCCESS"
CLIENT_UPLOAD_STATE_FAIL = "UPLOAD_FAIL"

# ── 分片上传阈值 ────────────────────────────────────────────────────────────────

MULTIPART_THRESHOLD_BYTES = 500 * 1024 * 1024  # 500 MB

# ── 上传模板名 ───────────────────────────────────────────────────────────────────

TEMPLATE_NAME_IMAGE  = "image-upload-default"
TEMPLATE_NAME_VIDEO  = "video-upload-default"
TEMPLATE_NAME_OBJECT = "object-upload-default"

# ── 上传平台 ────────────────────────────────────────────────────────────────────

UPLOAD_PLATFORM_WEB = "web"


# ── 数据类 ──────────────────────────────────────────────────────────────────────


class MediaMeta:
    """图片元数据（CommitUpload 响应中的 media_meta 字段）"""

    def __init__(self, width: int = 0, height: int = 0, format: str = "", size: int = 0) -> None:  # noqa: A002
        self.width = width
        self.height = height
        self.format = format
        self.size = size

    def __repr__(self) -> str:
        return f"MediaMeta(width={self.width}, height={self.height}, format={self.format}, size={self.size})"


class MediaURL:
    """图片可访问 URL（CommitUpload / ApplyUpload 秒传响应中的 media_url 字段）

    对应 Go 层 MediaURL struct（JSON key：primary / backups）。
    """

    _KEY_PRIMARY = "primary"
    _KEY_BACKUPS = "backups"

    def __init__(self, primary: str = "", backups: list[str] | None = None) -> None:
        self.primary = primary
        self.backups = backups or []

    @classmethod
    def from_dict(cls, data: dict) -> "MediaURL":
        return cls(
            primary=data.get(cls._KEY_PRIMARY, ""),
            backups=data.get(cls._KEY_BACKUPS) or [],
        )

    def __repr__(self) -> str:
        return f"MediaURL(primary={self.primary!r}, backups={self.backups})"


class UploadAuthInfo:
    """STS 临时凭证（ApplyUpload 响应中的 upload_auth 字段）"""

    def __init__(
        self,
        access_key_id: str,
        secret_access_key: str,
        security_token: str,
        expiration: int = 0,
    ) -> None:
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key  # JSON: secret_access_key
        self.security_token = security_token  # JSON: security_token
        self.expiration = expiration  # int64 unix timestamp


class UploadAddressInfo:
    """OSS 直传地址（upload_config.address）"""

    def __init__(
        self,
        endpoint: str,
        bucket_name: str,
        object_name: str,
        region: str = "",
        is_cname: bool = False,
    ) -> None:
        self.endpoint = endpoint
        self.bucket_name = bucket_name
        self.object_name = object_name
        self.region = region
        self.is_cname = is_cname


class UploadCallbackInfo:
    """OSS 上传回调（upload_config.callback）"""

    def __init__(self, url: str, body: str, body_type: str) -> None:
        self.url = url
        self.body = body
        self.body_type = body_type


class UploadRequest:
    """端侧三步式上传入参（调用方传入）

    :param media_type:     MediaType.OBJECT / VIDEO / IMAGE
    :param scene_name:     X-Media-Scene-Name，必填
    :param template_name:  上传模板名称，必填，由调用方传入
    :param file_path:      本地文件路径（与 file_obj/file_size 二选一）
    :param file_obj:       file-like 对象（需支持 seek；与 file_path 二选一）
    :param file_size:      文件大小（bytes）；使用 file_obj 时必填
    :param content_type:   MIME 类型（推荐填写）
    :param file_extension: 文件扩展名（可选）
    :param file_name:      文件名（可选）
    :param platform:       X-Media-Upload-Platform，默认 "web"
    """

    def __init__(
        self,
        media_type: str,
        scene_name: str,
        template_name: str,
        file_path: str | None = None,
        file_obj: BinaryIO | None = None,
        file_size: int = 0,
        content_type: str = "",
        file_extension: str = "",
        file_name: str = "",
        platform: str = UPLOAD_PLATFORM_WEB,
    ) -> None:
        self.media_type = media_type
        self.scene_name = scene_name
        self.template_name = template_name
        self.file_path = file_path
        self.file_obj = file_obj
        self.file_size = int(file_size)
        self.content_type = content_type
        self.file_extension = file_extension
        self.file_name = file_name
        self.platform = platform

    def validate(self) -> None:
        from mediacloud_uploader.errors import UploaderValidationError

        if not self.media_type:
            raise UploaderValidationError("media_type is required")
        if self.media_type not in (MediaType.OBJECT, MediaType.VIDEO, MediaType.IMAGE):
            raise UploaderValidationError(f"invalid media_type: {self.media_type}")
        if not self.scene_name:
            raise UploaderValidationError("scene_name is required")
        if not self.template_name:
            raise UploaderValidationError("template_name is required")
        if self.file_path is None and self.file_obj is None:
            raise UploaderValidationError("file_path or file_obj is required")
        if self.file_obj is not None and self.file_size == 0:
            raise UploaderValidationError("file_size is required when using file_obj")


class UploadResponse:
    """端侧三步式上传响应

    :param upload_result:   UPLOAD_SUCCESS / UPLOAD_FAIL
    :param media_key:       媒资 key（image token / video vid / object key）
    :param media_type:      媒体类型
    :param space_name:      存储空间名
    :param media_meta:      图片元数据（仅 image 类型有值）
    :param media_url:       图片可访问 URL（仅 image 类型有值，秒传时从 extra_params 取）
    :param raw_session_key: [WATERMARK PATCH] 内部用，ImageID；仅 image 类型赋值，供水印轮询用
    :param extra:           [WATERMARK PATCH] 水印处理结果（仅 image 上传成功后有值）
    """

    def __init__(
        self,
        upload_result: str,
        media_key: str = "",
        media_type: str = "",
        space_name: str = "",
        media_meta: MediaMeta | None = None,
        media_url: MediaURL | None = None,
        raw_session_key: str = "",
        extra: "UploadExtra | None" = None,
    ) -> None:
        self.upload_result = upload_result
        self.media_key = media_key
        self.media_type = media_type
        self.space_name = space_name
        self.media_meta = media_meta
        self.media_url = media_url
        self._raw_session_key = raw_session_key  # [WATERMARK PATCH] 内部用
        self.extra = extra                        # [WATERMARK PATCH]

    @property
    def is_success(self) -> bool:
        return self.upload_result == UPLOAD_STATE_SUCCESS

    def __repr__(self) -> str:
        return f"UploadResponse(upload_result={self.upload_result}, media_key={self.media_key}, media_type={self.media_type})"


class ApplyUploadRequest:
    """ApplyUpload HTTP 请求参数

    :param template_name: 上传模板名称，由调用方传入
    :param content_hash:  文件 MD5 hex（图片必填，用于秒传去重）
    :param session_key:   刷新凭证时携带
    """

    def __init__(
        self,
        media_type: str,
        scene_name: str,
        template_name: str,
        platform: str = UPLOAD_PLATFORM_WEB,
        content_type: str = "",
        content_hash: str = "",
        file_extension: str = "",
        file_name: str = "",
        file_size: int = 0,
        session_key: str = "",
    ) -> None:
        self.media_type = media_type
        self.scene_name = scene_name
        self.platform = platform
        self.template_name = template_name
        self.content_type = content_type
        self.content_hash = content_hash
        self.file_extension = file_extension
        self.file_name = file_name
        self.file_size = int(file_size)
        self.session_key = session_key


class ApplyUploadResponse:
    """ApplyUpload HTTP 响应解析结果

    :param upload_state:    UPLOADING / UPLOAD_SUCCESS / UPLOAD_FAIL
    :param session_key:     会话 key（image = ImageID）
    :param vendor_code:     供应商标识（"ali"）
    :param commit_address:  CommitUpload 动态地址（图片为空，使用默认路径）
    :param object_key:      媒资 key（apply 阶段的初始 key）
    :param extra_params:    额外参数（图片秒传时包含 width/height/format/size）
    :param upload_auth:     STS 凭证（UPLOADING 时有值）
    :param address:         OSS 直传地址（UPLOADING 时有值）
    :param callback:        OSS 回调信息（UPLOADING 时有值，图片为 None）
    """

    def __init__(
        self,
        upload_state: str,
        session_key: str = "",
        vendor_code: str = "",
        commit_address: str = "",
        object_key: str = "",
        processes: str = "",
        extra_params: dict[str, object] | None = None,
        upload_auth: UploadAuthInfo | None = None,
        address: UploadAddressInfo | None = None,
        callback: UploadCallbackInfo | None = None,
    ) -> None:
        self.upload_state = upload_state
        self.session_key = session_key
        self.vendor_code = vendor_code
        self.commit_address = commit_address
        self.object_key = object_key
        self.processes = processes  # 来自 upload_media.processes，透传给 CommitUpload
        self.extra_params = extra_params or {}
        self.upload_auth = upload_auth
        self.address = address
        self.callback = callback

    @property
    def is_instant_upload(self) -> bool:
        """是否秒传（apply 阶段即返回 UPLOAD_SUCCESS）"""
        return self.upload_state == UPLOAD_STATE_SUCCESS


class CommitUploadRequest:
    """CommitUpload HTTP 请求参数

    scene_name 由 API 客户端直接通过参数接收，不放入 body。
    security_token 通过 X-Security-Token header 发送，不放入 body。
    """

    def __init__(
        self,
        media_type: str,
        session_key: str,
        client_upload_state: str,
        platform: str = UPLOAD_PLATFORM_WEB,
        security_token: str = "",
        vendor_upload_id: str = "",
        error_log: str = "",
        processes: str = "",
    ) -> None:
        self.media_type = media_type
        self.session_key = session_key
        self.client_upload_state = client_upload_state
        self.platform = platform
        self.security_token = security_token
        self.vendor_upload_id = vendor_upload_id
        self.error_log = error_log
        self.processes = processes  # str，来自 apply_resp.upload_media.processes


class CommitUploadResponse:
    """CommitUpload HTTP 响应解析结果

    :param upload_result: 对应 JSON 字段 upload_results
    :param media_meta:    图片元数据（仅 image 类型有值）
    :param media_url:     图片可访问 URL（仅 image 类型有值）
    """

    def __init__(
        self,
        upload_result: str,
        media_key: str = "",
        space_name: str = "",
        media_meta: MediaMeta | None = None,
        media_url: MediaURL | None = None,
    ) -> None:
        self.upload_result = upload_result
        self.media_key = media_key
        self.space_name = space_name
        self.media_meta = media_meta
        self.media_url = media_url

    @property
    def is_success(self) -> bool:
        return self.upload_result == UPLOAD_STATE_SUCCESS


# ── [WATERMARK PATCH] 水印处理结果模型 ────────────────────────────────────────────


class ImageProcessState:
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"


class ImageProcessResultResponse:
    """GetImageProcessResult HTTP 响应解析结果"""

    def __init__(
        self,
        state: str = "",
        original_image_token: str = "",
        watermark_image_token: str = "",
        watermark_image_url: "MediaURL | None" = None,
    ) -> None:
        self.state = state
        self.original_image_token = original_image_token
        self.watermark_image_token = watermark_image_token
        self.watermark_image_url = watermark_image_url


class UploadExtra:
    """水印处理结果（包含最终 media_key 和可访问 URL）

    [WATERMARK PATCH] 临时兼容方案，待服务端改造后删除。
    """

    def __init__(self, watermark_image_key: str, watermark_image_url: MediaURL) -> None:
        self.watermark_image_key = watermark_image_key
        self.watermark_image_url = watermark_image_url
