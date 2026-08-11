# Tool Parameters Reference

> 按需加载：当需要确认参数名称、类型或响应字段时加载此文件。

---

## 响应结构（所有工具统一）

三种工具的成功响应包含以下公共字段：

| 字段 | 类型 | 始终返回 | 说明 |
|---|---|---|---|
| `success` | boolean | ✓ | 是否成功 |
| `media_type` | string | ✓ | `"image"` / `"video"` / `"object"` |
| `media_key` | string | ✓ | 媒资标识符（用于内容发布 API） |
| `space_name` | string | ✓ | 存储空间名 |
| `upload_result` | string | ✓ | 上传状态（成功时始终为 `"UPLOAD_SUCCESS"`） |
| `media_meta` | object | 仅图片 | 图片尺寸信息 |
| `media_url` | object | 仅图片（有值时） | 图片可访问 URL，含 `primary`（主 URL）和 `backups`（备用 URL 列表） |
| `extra` | object | 仅图片 | 图片扩展信息，含水印图相关字段 |

---

## upload_image

上传图片文件，支持秒传去重。

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file_path` | string | 二选一 | 本地文件**绝对路径** |
| `url` | string | 二选一 | 公开可访问的图片 URL |
| `scene_name` | string | ✓ | 发布目标场景，严格四选一：`answer`（回答）/ `question`（问题）/ `pin`（想法）/ `article`（文章）。传入其他值返回 `validation_error` |
| `content_type` | string | — | MIME 类型，如 `image/jpeg`。不填则根据扩展名自动检测 |

### 响应（成功）

```json
{
  "success": true,
  "media_type": "image",
  "media_key": "v2-a3d4e5f6c7b8...",
  "space_name": "default",
  "upload_result": "UPLOAD_SUCCESS",
  "media_meta": {
    "width": 1920,
    "height": 1080,
    "format": "jpeg",
    "size": 204800
  },
  "media_url": {
    "primary": "zhihu-image-url",
    "backups": []
  },
  "extra": {
    "watermark_image_key": "v2-b4e5f6a7c8d9...",
    "watermark_image_url": {
      "primary": "zhihu-image-url",
      "backups": []
    }
  }
}
```

| 字段 | 说明 |
|---|---|
| `media_key` | 图片 token，格式为 `v2-{md5hex}`，用于内容发布 API |
| `space_name` | 存储空间名（通常为 `"default"`） |
| `upload_result` | 始终为 `"UPLOAD_SUCCESS"` |
| `media_meta.width` | 图片宽度（像素） |
| `media_meta.height` | 图片高度（像素） |
| `media_meta.format` | 图片格式（`"jpeg"` / `"png"` / `"webp"` / `"heif"` / `"avif"` 等） |
| `media_meta.size` | 文件大小（字节） |
| `media_url.primary` | 原图主访问 URL |
| `media_url.backups` | 原图备用 URL 列表 |
| `extra.watermark_image_key` | 水印图 token；处理失败时降级为原图 `media_key` |
| `extra.watermark_image_url.primary` | 水印图主访问 URL；处理失败时降级为原图 URL |
| `extra.watermark_image_url.backups` | 水印图备用 URL 列表 |

**注**：秒传（相同内容图片）时 `media_meta` 同样有值，来自服务端已有记录。

---

## upload_video

上传视频或音频文件。>= 500 MB 自动分片上传。

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file_path` | string | 二选一 | 本地文件**绝对路径** |
| `url` | string | 二选一 | 公开可访问的视频/音频 URL |
| `scene_name` | string | — | 发布目标场景码（可选，默认 `pin`）。用户明确指定时直接透传任意值，不校验 |
| `content_type` | string | — | MIME 类型，如 `video/mp4`、`audio/mpeg`。不填则自动检测 |

### 响应（成功）

```json
{
  "success": true,
  "media_type": "video",
  "media_key": "1891080672866722741",
  "space_name": "zhihu-video",
  "upload_result": "UPLOAD_SUCCESS"
}
```

| 字段 | 说明 |
|---|---|
| `media_key` | 视频 ID（Vid），用于内容发布 API |
| `space_name` | 存储空间名 |
| `upload_result` | `"UPLOAD_SUCCESS"` 表示文件已接收并开始转码 |

**注**：`upload_result: UPLOAD_SUCCESS` 不代表视频可播放，需等待异步转码完成。

---

## upload_object

上传任意静态文件。>= 500 MB 自动分片上传。

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file_path` | string | 二选一 | 本地文件**绝对路径** |
| `url` | string | 二选一 | 公开可访问的文件 URL |
| `scene_name` | string | ✓ | 发布目标场景码（必填）。默认需询问用户选择四个标准值（answer/question/pin/article），用户明确指定时直接透传任意值 |
| `template_name` | string | ✓ | 上传模板名称，由业务方提供；不同业务场景使用不同的存储模板 |
| `content_type` | string | — | MIME 类型，如 `application/pdf`。不填则自动检测，最终 fallback 到 `application/octet-stream` |

### 响应（成功）

```json
{
  "success": true,
  "media_type": "object",
  "media_key": "obj/path/to/file.pdf",
  "space_name": "zhihu-objects",
  "upload_result": "UPLOAD_SUCCESS"
}
```

| 字段 | 说明 |
|---|---|
| `media_key` | 对象存储 key，用于内容发布 API |
| `space_name` | 存储空间名 |
| `upload_result` | 始终为 `"UPLOAD_SUCCESS"` |

---

## 响应（失败，所有工具通用）

```json
{
  "success": false,
  "error_type": "validation_error",
  "message": "文件不存在: /path/to/file.jpg"
}
```

| 字段 | 说明 |
|---|---|
| `success` | 固定为 `false` |
| `error_type` | 错误分类，见 `error-reference.md` |
| `message` | 人类可读的错误说明 |
