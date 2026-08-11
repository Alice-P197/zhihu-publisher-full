# zhihu-mediacloud-uploader

知乎媒体云上传 [Skill](./SKILL.md)。帮助 AI Agent 将图片、视频和各类文件上传到知乎媒体云，获取用于内容发布的媒资标识符（`media_key`）。

## 目录

- [使用方式](#使用方式)
  - [方式一：独立使用](#方式一独立使用)
  - [方式二：与其他 Skill 协作使用](#方式二与其他-skill-协作使用)
- [功能介绍](#功能介绍)
  - [两种上传方式](#两种上传方式)
  - [上传限制](#上传限制)
  - [三种上传服务](#三种上传服务)
  - [返回结果](#返回结果)
- [最佳实践](#最佳实践)
- [错误处理](#错误处理)
- [OpenSDK 用法](#opensdk-用法)

## 使用方式

### 方式一：独立使用

将本 skill 作为独立 MCP server 接入 AI Agent，直接调用上传工具。

**首选方式**

```bash
npx skills add zhihu/zhihu-mediacloud-uploader
```

安装完成后，**首次发起上传请求时 AI 会自动引导你完成 MCP 配置**——只需提供知乎用户 Token 和开放平台访问密钥，AI 会优先保存到 `~/.zhihu/openapi-credentials.json`，其余步骤（安装依赖、写入 MCP 配置文件）由 AI 自动完成。

凭证获取方式详见 [`references/auth-info.md`](references/auth-info.md)。推荐把知乎 OpenAPI 通用凭证持久化到 `~/.zhihu/openapi-credentials.json`；如需临时覆盖，只使用 `ZHIHU_OPENAPI_APP_KEY` / `ZHIHU_OPENAPI_APP_SECRET`。

> 如当前 Agent 未被自动识别，可加载 [`references/mcp-setup.md`](references/mcp-setup.md)——MCP Server 自动配置指南，覆盖 Claude Code、Cursor、Windsurf、VS Code、Cline、Kiro、Codex CLI、Gemini CLI、Continue 等主流 Agent。



### 方式二：与其他 Skill 协作使用

> 本节面向**外层 skill 开发者**，说明如何将本 skill 作为媒体上传能力组件集成到你的 skill 中。

**推荐做法：在你的 skill manifest 中声明依赖**

在外层 skill 的 manifest（如 `skill.json` 或等效配置）中声明对 `zhihu/zhihu-mediacloud-uploader` 的依赖：

```json
{
  "dependencies": {
    "skills": ["zhihu/zhihu-mediacloud-uploader"]
  }
}
```

用户安装你的 skill 时（如 `npx skills add your-skill`），skills CLI 会自动安装 `zhihu/zhihu-mediacloud-uploader` 的指令文件。MCP Server 配置会在用户首次发起上传时由 AI 自动引导完成，**用户无需手动操作**。

同时在你的 SKILL.md 中声明依赖关系，AI Agent 读取后即可自动协调调用：

```markdown
## 依赖 Skill
- **zhihu-mediacloud-uploader**：当需要上传图片、视频或文件时，调用此 skill 的工具获取 media_key。
```

两个 skill 各自独立运行，AI Agent 作为连接者，**无需任何代码集成**。

**备选：手动注册两个 MCP server**

知乎 OpenAPI 凭证建议统一保存到 `~/.zhihu/openapi-credentials.json`，多个知乎 skill 直接读取这个共享文件或各自的专用环境变量，不要解析其他 skill 的 MCP 配置。

适用于不支持依赖声明的宿主环境，手动将两个 skill 注册到同一 MCP 宿主：

```json
{
  "mcpServers": {
    "your-skill": {
      "command": "...",
      "env": { "...": "..." }
    },
    "zhihu-mediacloud-uploader": {
      "command": "<uv 可执行文件绝对路径>",
      "args": [
        "run",
        "--index-url",
        "https://pypi.tuna.tsinghua.edu.cn/simple",
        "--project",
        "<zhihu-mediacloud-uploader skill所在的绝对路径>",
        "zhihu-mediacloud-uploader"
      ]
    }
  }
}
```

---

## 功能介绍

### 两种上传方式

所有工具均支持 **本地文件** 或 **URL** 两种输入（上传方式），二者互斥：

```
file_path: /Users/alice/Downloads/photo.jpg    # 本地文件，必须是绝对路径
url:       https://example.com/banner.jpg      # 公开 URL，自动下载后上传
```

**URL 上传说明：**
- 仅支持公开可访问的 URL（无需登录、Cookie 或鉴权）
- 工具自动从响应头检测 `Content-Type`，也可手动通过 `content_type` 参数指定
- URL 中文件类型不明确时（如无扩展名且响应头为通用类型），需明确指定 `content_type`
- 所有 URL 均流式下载到磁盘临时文件，上传完成后自动清理，无内存压力


上传支持**简单上传**和**分片上传**两种方式：文件 ≥ 500 MB 时自动切换为分片上传。

---

### 上传限制

所有限制均在客户端前置校验，超出限制直接返回 `validation_error`，消息中包含具体超出项和当前值。

| 上传类型 | 限制项 | 限制值 |
|---|---|---|
| 图片（非 GIF） | 文件大小 | ≤ 30 MB |
| 图片（GIF） | 文件大小 | ≤ 15 MB |
| 图片 | 长边（max(宽, 高)） | ≤ 16384 px |
| 图片 | 总像素数 | ≤ 2 亿 |
| 视频/音频 | 文件大小 | ≤ 20 GB |
| 视频/音频 | 时长 | ≤ 4 小时（仅 MP4/MOV/MP3/AAC/WAV/FLAC 等主流格式；AVI/MKV 等跳过时长检测） |
| 静态文件 | 无限制 | — |

---

### 三种上传服务

#### `upload_image` 上传图片

支持 JPEG、PNG、WebP、HEIC、HEIF、AVIF、BMP、TIFF 等常见图片格式。

**参数：**

| 参数 | 必填 | 说明 |
|---|---|---|
| `scene_name` | ✓ | 发布目标场景：`answer`（回答）/ `question`（问题）/ `pin`（想法）/ `article`（文章） |
| `file_path` | 二选一 | 本地文件绝对路径 |
| `url` | 二选一 | 公开可访问的图片 URL |
| `content_type` | — | MIME 类型（如 `image/jpeg`），不填则自动检测 |

---

#### `upload_video` 上传视频/音频

支持 MP4、MOV、AVI、MKV 等视频格式，以及 MP3、AAC、WAV、FLAC 等音频格式。

> 注意：**上传成功 ≠ 可以播放**：视频需要异步转码，转码完成后才可播放（可能需要数分钟到数十分钟）

**参数：**

| 参数 | 必填 | 说明 |
|---|---|---|
| `scene_name` | — | 发布目标场景码，默认 `pin`。用户明确指定时直接透传，不校验 |
| `file_path` | 二选一 | 本地文件绝对路径 |
| `url` | 二选一 | 公开可访问的视频 URL |
| `content_type` | — | MIME 类型（如 `video/mp4`），不填则自动检测 |

---

#### `upload_object` 上传静态文件

上传 PDF、ZIP、文档、二进制等任意类型文件到对象存储。

**参数：**

| 参数 | 必填 | 说明 |
|---|---|---|
| `scene_name` | ✓ | 发布目标场景：`answer`（回答）/ `question`（问题）/ `pin`（想法）/ `article`（文章） |
| `template_name` | ✓ | 上传模板名称，由业务方提供；静态文件无默认模板，必须显式传入 |
| `file_path` | 二选一 | 本地文件绝对路径 |
| `url` | 二选一 | 公开可访问的文件 URL |
| `content_type` | — | MIME 类型，不填则自动检测 |

---

### 返回结果

所有工具均返回结构化 JSON，`success` 字段表示是否成功：

**成功示例（图片）：**
```json
{
  "success": true,
  "media_type": "image",
  "media_key": "v2-a3d4e5f6c7b8d9...",
  "space_name": "default",
  "upload_result": "UPLOAD_SUCCESS",
  "media_meta": {
    "width": 1920,
    "height": 1080,
    "format": "webp",
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

**成功示例（视频）：**
```json
{
  "success": true,
  "media_type": "video",
  "media_key": "1891080672866722741",
  "space_name": "default",
  "upload_result": "UPLOAD_SUCCESS"
}
```

**成功示例（静态文件）：**
```json
{
  "success": true,
  "media_type": "object",
  "media_key": "obj/path/to/document.pdf",
  "space_name": "default",
  "upload_result": "UPLOAD_SUCCESS"
}
```

**`media_key` 说明：** 这是内容发布 API 使用的内部标识符，不是可直接访问的 URL，需要通过知乎内容发布接口引用。

---

## 最佳实践

**1. 先确认文件类型，再调用工具**

三个工具对应不同的存储服务，选错无法事后纠正。当文件类型不明确时（如用户只说"上传这个文件"，或提供无扩展名的 URL），先询问确认是图片、视频还是其他文件类型。

**2. 本地路径使用绝对路径**

传入 `file_path` 时使用绝对路径（如 `/Users/alice/file.jpg`），不要使用 `./file.jpg` 或 `~/file.jpg`。

**3. `scene_name` 必须与发布场景一致**

有效值为以下四个，传入其他值会返回 `validation_error`：

| 值 | 知乎内容类型 |
|---|---|
| `answer` | 回答 |
| `question` | 问题 |
| `pin` | 想法 |
| `article` | 文章 |

AI Agent 调用时应根据用户指令推断场景，无法确定时先询问用户再调用。

**4. 大文件上传前告知用户**

500 MB 以上的视频或文件上传时间较长，建议提前告知用户，并确保网络连接稳定。

**5. 视频上传后需等待转码**

视频上传成功（`upload_result: UPLOAD_SUCCESS`）后，视频进入异步转码流程，需要等待转码完成才可播放或嵌入内容。

**6. `upload_object` 调用前需确认 `template_name`**

静态文件存储没有默认模板，不同业务使用不同的模板。AI Agent 调用前必须先询问用户或查阅业务文档获取正确的模板名称，不得自行猜测或填写。

---

## 错误处理

| error_type | 含义 | 处理建议 |
|---|---|---|
| `validation_error` | 参数错误（路径不存在、scene_name 无效、upload_object 缺少 template_name、同时传了 file_path 和 url 等） | 检查参数后重试 |
| `auth_error` | 鉴权失败 | 检查共享凭证文件或 `ZHIHU_OPENAPI_APP_KEY` / `ZHIHU_OPENAPI_APP_SECRET` 配置 |
| `api_error` | 服务端返回错误 | 查看 `message` 中的描述，可重试一次 |
| `transfer_error` | 文件传输到存储失败（通常是网络问题） | 重试 |
| `session_expired` | 上传会话超期（多见于大文件上传耗时过长） | 重新发起整个上传 |
| `download_error` | URL 无法访问（404、403、超时等） | 检查 URL 是否公开可访问；可先手动下载到本地再用 `file_path` 上传 |
| `internal_error` | 服务内部错误 | 稍后重试；持续发生请联系平台支持 |

**失败返回示例：**
```json
{
  "success": false,
  "error_type": "download_error",
  "message": "URL 返回 HTTP 403，无法下载文件。请确认该地址是否公开可访问，无需登录或鉴权: https://..."
}
```

---

## OpenSDK 用法

除作为 MCP Skill 使用外，本包也可直接作为 Python SDK 集成到业务代码中。

```python
from mediacloud_uploader import MediaCloudUploader, UploaderError

uploader = MediaCloudUploader(
    app_key="your-zhihu-user-token",
    app_secret="your-app-secret",
)

resp = uploader.upload_{image|video|object}(...)
```
