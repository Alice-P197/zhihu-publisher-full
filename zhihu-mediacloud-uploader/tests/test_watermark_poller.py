# -*- coding: utf-8 -*-
"""watermark_poller.py 单元测试：轮询各场景及降级逻辑"""

from unittest.mock import MagicMock, call, patch
import pytest

from mediacloud_uploader.watermark_poller import poll_watermark
from mediacloud_uploader.models import ImageProcessState, ImageProcessResultResponse, MediaURL, UploadExtra
from mediacloud_uploader.errors import UploaderAPIError, UploaderAuthError


_FALLBACK_KEY = "v2-original"
_FALLBACK_URL = MediaURL(primary="https://img.example.com/orig.jpg", backups=[])
_WM_URL       = MediaURL(primary="https://img.example.com/wm.jpg", backups=[])


def _make_resp(state: str, wm_token: str = "", wm_url: MediaURL | None = None) -> ImageProcessResultResponse:
    return ImageProcessResultResponse(
        state=state,
        original_image_token="v2-orig",
        watermark_image_token=wm_token,
        watermark_image_url=wm_url,
    )


def _make_http(side_effects: list) -> MagicMock:
    """构造 mock API 客户端，get_image_process_result 依次返回 side_effects 中的值/异常"""
    http = MagicMock()
    http.get_image_process_result.side_effect = side_effects
    return http


def _poll(http: MagicMock, timeout: float = 5.0) -> UploadExtra:
    with patch("mediacloud_uploader.watermark_poller._POLL_TIMEOUT_S", timeout), \
         patch("mediacloud_uploader.watermark_poller._POLL_INTERVAL_S", 0.0):
        return poll_watermark(
            http_client =http,
            image_id    ="123456",
            scene_name  ="answer",
            fallback_key=_FALLBACK_KEY,
            fallback_url=_FALLBACK_URL,
        )


# ── 成功路径 ──────────────────────────────────────────────────────────────────────

class TestSuccess:
    def test_first_poll_success(self) -> None:
        """首次轮询即 SUCCESS，立即返回水印结果"""
        http = _make_http([_make_resp("success", wm_token="v2-wm", wm_url=_WM_URL)])
        result = _poll(http)

        assert result.watermark_image_key == "v2-wm"
        assert result.watermark_image_url.primary == _WM_URL.primary
        http.get_image_process_result.assert_called_once_with("123456", "answer")

    def test_processing_then_success(self) -> None:
        """多次 PROCESSING 后 SUCCESS，轮询次数正确"""
        http = _make_http([
            _make_resp("processing"),
            _make_resp("processing"),
            _make_resp("success", wm_token="v2-wm", wm_url=_WM_URL),
        ])
        result = _poll(http)

        assert result.watermark_image_key == "v2-wm"
        assert http.get_image_process_result.call_count == 3


# ── 降级路径 ──────────────────────────────────────────────────────────────────────

class TestDegradation:
    def test_server_failed_state_degrades(self) -> None:
        """服务端返回 FAILED，立即降级为原图"""
        http = _make_http([_make_resp("failed")])
        result = _poll(http)

        assert result.watermark_image_key == _FALLBACK_KEY
        assert result.watermark_image_url.primary == _FALLBACK_URL.primary
        http.get_image_process_result.assert_called_once()

    def test_auth_error_degrades_immediately(self) -> None:
        """UploaderAuthError 立即降级，不重试"""
        http = _make_http([UploaderAuthError("auth failed")])
        result = _poll(http)

        assert result.watermark_image_key == _FALLBACK_KEY
        http.get_image_process_result.assert_called_once()

    def test_permanent_4xx_degrades_immediately(self) -> None:
        """HTTP 4xx 错误立即降级，不重试"""
        http = _make_http([UploaderAPIError("not found", http_status=404)])
        result = _poll(http)

        assert result.watermark_image_key == _FALLBACK_KEY
        http.get_image_process_result.assert_called_once()

    def test_timeout_degrades(self) -> None:
        """超时后降级为原图"""
        # PROCESSING 持续返回，timeout=0 使首次循环后立即超时
        http = _make_http([_make_resp("processing")] * 10)
        result = _poll(http, timeout=0.0)

        assert result.watermark_image_key == _FALLBACK_KEY


# ── 重试路径 ──────────────────────────────────────────────────────────────────────

class TestRetry:
    def test_network_error_retries_then_success(self) -> None:
        """网络错误（http_status=None）后重试，最终成功"""
        http = _make_http([
            UploaderAPIError("connection error"),   # http_status=None → 瞬时
            _make_resp("success", wm_token="v2-wm", wm_url=_WM_URL),
        ])
        result = _poll(http)

        assert result.watermark_image_key == "v2-wm"
        assert http.get_image_process_result.call_count == 2

    def test_5xx_retries_then_success(self) -> None:
        """HTTP 5xx 错误重试，最终成功"""
        http = _make_http([
            UploaderAPIError("server error", http_status=503),
            _make_resp("success", wm_token="v2-wm", wm_url=_WM_URL),
        ])
        result = _poll(http)

        assert result.watermark_image_key == "v2-wm"
        assert http.get_image_process_result.call_count == 2

    def test_unexpected_exception_retries(self) -> None:
        """未知异常重试，最终成功"""
        http = _make_http([
            RuntimeError("unexpected"),
            _make_resp("success", wm_token="v2-wm", wm_url=_WM_URL),
        ])
        result = _poll(http)

        assert result.watermark_image_key == "v2-wm"
        assert http.get_image_process_result.call_count == 2

    def test_4xx_after_network_error_degrades(self) -> None:
        """先网络错误（重试），再收到 4xx（立即降级）"""
        http = _make_http([
            UploaderAPIError("network"),          # 重试
            UploaderAPIError("bad request", http_status=400),  # 立即降级
        ])
        result = _poll(http)

        assert result.watermark_image_key == _FALLBACK_KEY
        assert http.get_image_process_result.call_count == 2
