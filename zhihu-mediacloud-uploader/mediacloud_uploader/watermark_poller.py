# -*- coding: utf-8 -*-
"""
[WATERMARK PATCH] 图片水印处理结果轮询

兼容性 Patch 逻辑，方案不合理（详见 brand-influence service/zmedia.go 注释）。
移除方式：
  1. 删除本文件
  2. 删除 client.py 中 [WATERMARK PATCH BEGIN] 到 [WATERMARK PATCH END] 的代码块
  3. 删除 models.py 中 [WATERMARK PATCH] 标注的内容（可选）
"""

from __future__ import annotations

import logging
import time

from mediacloud_uploader.api import MediaAPIClient
from mediacloud_uploader.errors import UploaderAPIError, UploaderAuthError
from mediacloud_uploader.models import ImageProcessState, MediaURL, UploadExtra

logger = logging.getLogger(__name__)

_POLL_INTERVAL_S = 0.5
_POLL_TIMEOUT_S = 30.0


def poll_watermark(
    http_client: MediaAPIClient,
    image_id: str,
    scene_name: str,
    fallback_key: str,
    fallback_url: MediaURL,
) -> UploadExtra:
    """轮询水印处理结果，失败/超时时降级为原图。

    :param http_client:   MediaAPIClient 实例
    :param image_id:      ImageID（ApplyUpload 响应的 session_key）
    :param scene_name:    X-Media-Scene-Name
    :param fallback_key:  降级用：原图 media_key
    :param fallback_url:  降级用：原图 media_url
    :return:              UploadExtra（success 或降级）
    """
    deadline = time.monotonic() + _POLL_TIMEOUT_S

    while time.monotonic() < deadline:
        try:
            resp = http_client.get_image_process_result(image_id, scene_name)
        except UploaderAuthError:
            logger.error("[watermark_poller] auth error, degrading. image_id=%s", image_id)
            break
        except UploaderAPIError as e:
            if e.http_status is not None and 400 <= e.http_status < 500:
                logger.error(
                    "[watermark_poller] permanent client error http=%s, degrading. image_id=%s",
                    e.http_status,
                    image_id,
                )
                break
            logger.warning(
                "[watermark_poller] transient error: %s, retrying. image_id=%s",
                e.message,
                image_id,
            )
            time.sleep(_POLL_INTERVAL_S)
            continue
        except Exception as e:
            logger.warning(
                "[watermark_poller] unexpected error: %s, retrying. image_id=%s",
                e,
                image_id,
            )
            time.sleep(_POLL_INTERVAL_S)
            continue

        if resp.state == ImageProcessState.SUCCESS:
            if resp.watermark_image_url is None:
                logger.warning(
                    "[watermark_poller] success but no url, degrading. image_id=%s",
                    image_id,
                )
                break
            return UploadExtra(
                watermark_image_key=resp.watermark_image_token,
                watermark_image_url=resp.watermark_image_url,
            )

        if resp.state == ImageProcessState.FAILED:
            logger.warning(
                "[watermark_poller] server returned FAILED, degrading. image_id=%s",
                image_id,
            )
            break

        time.sleep(_POLL_INTERVAL_S)

    logger.warning("[watermark_poller] degraded to original image. image_id=%s", image_id)
    return UploadExtra(
        watermark_image_key=fallback_key,
        watermark_image_url=fallback_url,
    )
