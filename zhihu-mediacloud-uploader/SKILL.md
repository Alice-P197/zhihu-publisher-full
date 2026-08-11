---
name: zhihu-mediacloud-uploader
description: Uploads local image, video, and static files to Zhihu media cloud (知乎媒体云) and returns a media_key used in content publishing APIs. Also downloads from a public URL and uploads directly. Use when the user wants to upload a picture, image, photo, video, audio clip, document, or any file attachment; when a post, article, or 知乎 content needs an embedded image or video; when the user provides a URL to an online image/video/file that needs to be uploaded; when any downstream operation requires a media_key from Zhihu; or when the user asks about the zhihu-mediacloud-uploader version, update availability, checking for updates, or upgrading the skill. Also activate when user says 上传图片、上传视频、上传文件、图片上传、视频上传、文件上传、知乎媒体上传、URL上传、链接上传、检查更新、检查版本、更新 zhihu-mediacloud-uploader、升级 uploader skill.
license: MIT
compatibility: Requires zhihu-mediacloud-uploader MCP server running with ZHIHU_OPENAPI_APP_KEY (知乎用户 Token) and ZHIHU_OPENAPI_APP_SECRET (开放平台访问密钥) environment variables set.
allowed-tools: upload_image upload_video upload_object
metadata:
  author: zhihu
  version: "0.1.5"
---

# zhihu-mediacloud-uploader

上传本地文件或公开 URL 到知乎媒体云，获取用于内容发布的 `media_key`。

本 skill 使用知乎 OpenAPI 通用凭证。凭证详细说明和初始化流程见 `references/auth-info.md`。

## 会话首次版本检查

每个会话首次加载本 skill 后，或当用户询问 `zhihu-mediacloud-uploader` 是否有新版本、要求检查更新、检查版本、更新或升级时：

- 立即读取 `references/update.md`，按其中流程访问版本接口，并将同名 skill 的接口版本与本地 `SKILL.md` 中的 `metadata.version` 比较。
- 每个会话只自动检查一次；同一会话内只有用户再次明确询问更新、版本、升级，或遇到明显像旧版本导致的问题时，才重复检查。
- 自动检查发现新版本时，先提示当前版本、接口最新版本、更新建议和重启要求，并等待用户选择更新或暂不更新；用户选择前不要继续初始化或上传。
- 用户选择暂不更新或继续当前任务时，可以继续后续流程，但必须说明当前会话仍使用本地已加载版本。
- 用户明确询问版本或更新时，只返回版本判断、更新建议和重启要求；不要继续凭证配置、MCP 初始化或上传。
- 发现新版本时，只提示用户确认后再更新；不要静默自动更新 skill。
- 无法访问版本接口或无法解析版本时，按 `references/update.md` 区分自动检查和用户主动检查，不要猜测是否有新版本。

## 初始化（首次使用前检查）

**在执行任何初始化或上传操作之前**，如果本会话尚未完成版本检查，先执行上文“会话首次版本检查”。自动检查失败时简要说明原因并继续；发现新版本时先等待用户选择更新或暂不更新。用户明确询问版本或更新时，完成检查后停止，不执行初始化或上传。

版本检查完成或用户选择暂不更新后，再检查工具列表中是否存在 `upload_image`、`upload_video`、`upload_object`：

- **三个工具均可用** → 直接进入上传流程
- **任一工具不存在** → 进入初始化模式，本轮只允许完成凭证准备和 MCP 配置；配置完成后必须停止并提示用户重启 Agent，不得继续上传

初始化模式的硬性边界：

- 当前工具列表中缺少 `upload_image` / `upload_video` / `upload_object` 时，不得进入上传流程。
- 不得扫描、修改或调用本 skill 的 Python 源码来绕过 MCP 工具注册。
- 不得在当前会话内手写或运行 MCP stdio 客户端来调用 `zhihu-mediacloud-uploader`。
- 除按 `references/mcp-setup.md` 执行的运行环境探测和 MCP Server 运行命令验证外，不得启动 `zhihu-mediacloud-uploader`；尤其不得无参数启动 MCP server。
- 配置写入完成后，立即结束本轮响应，只提示用户重启 Agent。

### 自动配置流程

**步骤 1：收集凭证**

先检查当前进程环境变量 `ZHIHU_OPENAPI_APP_KEY` / `ZHIHU_OPENAPI_APP_SECRET`，以及共享凭证文件 `~/.zhihu/openapi-credentials.json` 是否能提供完整凭证。

- **已有完整且一致的凭证** → 直接继续步骤 2
- **凭证缺失、来源不一致、用户不清楚如何获取、用户直接提供凭证、或需要写入共享文件** → 立即加载 `references/auth-info.md`，按其中初始化流程处理


**步骤 2：配置 MCP Server**

立即加载 `references/mcp-setup.md`，按其中步骤自动完成运行环境探测和 MCP 配置。`SKILL.md` 不维护各平台命令和各 Agent 配置模板，避免与 reference 内容重复。

执行时遵守以下原则：

- 先按 `references/mcp-setup.md` 解析并验证 MCP Server 运行命令，再写 MCP 配置；验证失败时停止配置。
- MCP Server 运行命令、`uv` 可执行文件绝对路径、依赖源参数、skill 所在目录、版本验证和各 Agent 配置模板都以 `references/mcp-setup.md` 为准；`SKILL.md` 不复制这些细节。
- 配置文件已存在时，先备份，再只新增或替换 `zhihu-mediacloud-uploader` 这一项，不覆盖其他 MCP server。
- 如果无法识别当前 Agent，按 `references/mcp-setup.md` 询问用户使用的工具后再配置。

**步骤 3：提示重启**

配置写入后告知用户：
> 配置已完成。请**重启 Agent**（完全退出并重新打开），重启后重新发起上传请求即可自动继续。

这是终止步骤。输出上述提示后必须停止，不得继续检查当前会话是否能直接调用 MCP stdio，不得继续上传，不得编写临时代码调用 uploader。

> ⚠️ 凭证默认保存于本地共享凭证文件 `~/.zhihu/openapi-credentials.json`，不要提交到代码仓库；如额外写入 `ZHIHU_OPENAPI_*` MCP env，同样不要提交对应配置文件。

## 输入来源

每次上传提供 **file_path 或 url 之一**，不能同时提供：

| 场景 | 使用参数 |
|---|---|
| 用户本地文件 | `file_path`（绝对路径） |
| 网络上的公开文件/图片/视频 | `url`（http:// 或 https://） |

## 选哪个工具

根据文件类型选择工具，不要猜测——看扩展名：

| 文件类型 | 使用工具 |
|---|---|
| 图片：JPEG / PNG / WebP / HEIC / HEIF / AVIF / BMP / TIFF 等 | `upload_image` |
| 视频：MP4 / MOV / AVI / MKV；音频：MP3 / AAC / WAV / FLAC | `upload_video` |
| 其他一切：PDF / ZIP / DOCX / 二进制 | `upload_object` |

扩展名不明确、或无扩展名且用户未说明类型时，**必须询问用户**，不得自行猜测或默认选择任何工具。

## 上传流程

**角色定义**：在整个上传流程中，你扮演的是**数据中继**角色，不是信息摘要员——你可以对工具返回的数据进行进一步封装，但不能对返回的数据有任何筛选、压缩，最终输出的数据必须完整包含原始数据。

每次上传按此顺序执行，不要跳步：

- [ ] **0. 确认媒体类型** — 如果用户没有明确说明文件类型（"上传这个图片/视频/文件"），**必须先询问**，不要猜测（见 Gotchas #0）
- [ ] **1. 确认输入源** — 用户给的是本地路径还是 URL？（见输入来源表）
  - 本地路径：转为绝对路径（见 Gotchas #1）
  - URL：确认是 http:// 或 https:// 开头（见 Gotchas #9）
- [ ] **2. 确认 scene_name**：
  - **图片**：根据用户指令推断（见 Gotchas #2 表格关键词），无法推断时询问
  - **视频**：默认 `pin`，用户明确指定场景码时透传
  - **对象**：根据用户指令推断或询问，用户明确指定场景码时透传
- [ ] **2b. 确认 template_name（仅 upload_object）** — 静态文件没有默认模板，必须向用户确认（见 Gotchas #13）
- [ ] **3. 选择工具** — 按上表判断 media_type
- [ ] **4. 告知用户并调用工具** — 调用前先告知用户上传已开始（见 Gotchas #12），再调用对应的 upload_* 工具，传入 `file_path` 或 `url`
- [ ] **5. 输出前决策流（不可跳过）** — 工具调用返回后，按以下子步骤顺序执行：

  **5-1. 解析工具返回值**
  将工具 response 解析为 JSON，得到 `data`。
  若解析失败 → 向用户报告"工具返回了无效数据"，终止。

  **5-2. 检查 success 字段**
  - `data["success"] == false` → 跳到步骤 6（错误处理）
  - `data["success"] == true` → 继续 5-3

  **5-3. 输出检测门**（在实际输出前于内部完成，不向用户展示）
  1. 记录 `keys_tool` = `data` 的顶层键集合
  2. 构造即将输出的 JSON，记录其顶层键集合 `keys_out`
  3. 验证 `keys_out == keys_tool`（数量相同、无增删）
  4. 对 `data` 中每个值为对象的顶层键，验证对应嵌套字段也完整保留
  5. 验证即将输出的内容已被包裹在 ` ```json ` 代码块中，而非裸 JSON 字符串
  - **全部通过** → 执行 5-4
  - **未通过** → 重新构造输出，再执行一次检测；仍不通过 → 将 `data` 序列化为缩进 JSON，包裹在 ` ```json ` 代码块中输出（兜底，确保数据不丢失且格式正确）

  **5-4. 执行输出**

  上传成功。完整数据如下：

  ````json
  {通过检测的完整 JSON，原样输出，不增删字段，不修改值}
  ````

  ✅ 完整示例、❌ 错误示例见"使用上传结果"节。

- [ ] **6. 处理错误** — `success: false` 时见"错误处理"节

## Gotchas

这些是最常见的失败原因，优先检查：

**#0 媒体类型不明确时必须先询问，不能猜测**

三个工具服务于不同的知乎服务，选错无法补救：
- `upload_image` → 知乎图片服务
- `upload_video` → 知乎点播云
- `upload_object` → 知乎基础对象存储服务

**触发询问的情形**（以下任一即需询问）：
- 用户说"上传这个文件"、"帮我传一下"——没有指明图片/视频/文件
- 用户提供的是无扩展名 URL（如 `https://example.com/media/abc123`）且未说明类型
- 用户提供的本地文件无扩展名或扩展名不属于已知图片/视频格式，且未说明类型
- 用户的描述中出现歧义（如"上传这段内容"，不确定是图片还是视频）

**询问方式示例**：
> 请问这是图片、视频，还是其他类型的文件（如 PDF、压缩包等）？

**明确可以直接推断的情形**（不需要询问）：
- 用户明确说"上传这张图片/截图/照片" → `upload_image`
- 用户明确说"上传这个视频/音频" → `upload_video`
- 用户明确说"上传这个文件/PDF/压缩包" → `upload_object`
- 文件扩展名清晰（`.jpg`/`.png` → image；`.mp4`/`.mov` → video；`.pdf`/`.zip` → object）

**#1 file_path 必须是绝对路径**
- ✅ `/Users/alice/Downloads/photo.jpg`
- ❌ `./photo.jpg`、`~/photo.jpg`、`photo.jpg`
- 用户给了相对路径时，先把它展开为绝对路径再调用工具。

**#2 scene_name 规则因工具而异**

有效的标准场景码：

| scene_name | 知乎内容类型 | 推断信号（用户说了这些词可直接使用） |
|---|---|---|
| `answer` | 回答 | 「回答里」「回答配图」「这篇回答」 |
| `question` | 问题 | 「问题封面」「给提问添加图片」「这个问题的图」 |
| `pin` | 想法 | 「发个想法」「想法视频」「动态」 |
| `article` | 文章 | 「文章配图」「专栏视频」「这篇文章」 |

**三种工具的规则：**

- **`upload_image`（图片）**：严格四选一，必须通过校验
  - 出现上表推断信号 → 直接使用对应值
  - 无法推断 → 询问「请问这个图片是用于回答、问题、想法，还是文章？」
  - 传入非四个值之一会返回 `validation_error`

- **`upload_video`（视频）**：默认 `pin`，允许透传任意值
  - 用户未指定 → 直接使用 `pin`，无需询问
  - 用户明确说「场景码：xxx」→ 直接透传，不校验，由服务端处理

- **`upload_object`（对象）**：询问四选一，允许透传任意值
  - 出现上表推断信号 → 直接使用对应值
  - 无法推断 → 询问「请问这个文件是用于回答、问题、想法、文章？如果是其他场景，请输入明确的场景码参数值」
  - 用户明确说「场景码：xxx」→ 直接透传，不校验，由服务端处理

**#3 图片秒传是正常行为，不是错误**
- 相同内容的图片重复上传会返回同一个 `media_key`，这是去重机制。
- 不要向用户报告"已存在"为错误，告知这是正常的去重结果。

**#4 视频 upload_result=UPLOAD_SUCCESS ≠ 视频可播放**
- 成功仅表示文件已被接收，视频还需要异步转码（可能需要数分钟到数十分钟）。
- 如果用户立即要嵌入或播放视频，告知他需要等待转码完成后才可使用。

**#5 media_key 不是 URL，不能直接访问**
- 它是内容发布 API 的内部引用标识符（如图片 ID、视频 Vid、对象 key）。
- 不能放进 `<img src="">` 或浏览器地址栏——需要通过知乎发布 API 使用。

**#6 图片有上传限制（客户端前置校验）**
- 非 GIF 图片：≤ 30 MB
- GIF 动图：≤ 15 MB
- 图片长边（max(宽, 高)）：≤ 16384 px
- 图片总像素数：≤ 2 亿
- 超出限制直接返回 `validation_error`，消息中包含具体超出项和当前值。

**#7 content_type 必须匹配文件实际格式**
- 传 `image/jpeg` 但文件实际是 PNG 会触发 400 错误。
- 不确定时省略 content_type 参数，工具会自动从扩展名检测。

**#8 大文件（≥ 500 MB）上传耗时较长**
- 视频和对象文件超过 500 MB 时自动切换为分片上传（10 MB/片），无需特殊处理。
- 上传大文件前应告知用户预计需要较长时间，建议在网络稳定时操作。

**#9 URL 必须公开可访问，无需登录或鉴权**
- 需要登录、需要 Cookie、或通过 CDN 防盗链保护的 URL 会返回 403/401，无法下载。
- 如果下载失败，工具返回 `download_error`，消息中包含 HTTP 状态码。
- **图片** URL：流式下载到磁盘临时文件（与视频/对象相同），上传完成后自动清理。
- **视频/对象** URL：流式下载到磁盘临时文件（不占用内存），上传完成后自动清理；数 GB 的视频可直接使用 URL 上传，无需预先下载到本地。

**#10 URL 的 content_type 自动从响应头检测**
- 工具优先使用响应头的 `Content-Type`，其次从 URL 文件名扩展名推断。
- 若响应头返回 `application/octet-stream` 但实际是图片，建议手动传 `content_type` 参数覆盖。

**#11 视频/音频有上传限制（客户端前置校验）**
- 文件大小：≤ 20 GB
- 时长：≤ 4 小时（仅支持格式：MP4/MOV/MP3/AAC/WAV/FLAC 等主流格式；AVI/MKV 等格式跳过时长检测）
- 超出限制直接返回 `validation_error`，消息中包含具体超出项。

**#12 上传是同步阻塞操作，调用前必须告知用户**
- 三个上传工具均为同步阻塞调用：工具执行期间不会产生任何中间响应。
- 大文件（视频 ≥ 500 MB）可能需要数分钟；小图片通常数秒内完成。
- **在发起 tool call 之前，必须先向用户说明上传即将开始**，例如：
  - 图片：「正在上传图片，请稍候…」
  - 视频/大文件：「正在上传文件，可能需要几分钟，请耐心等待…」
- 不要在工具返回后才告知用户，用户在等待期间应知道发生了什么。

**#13 upload_object 必须提供 template_name，不能猜测**

静态文件的存储路径由上传模板决定，不同业务使用不同的存储模板，工具没有默认值。

- **用户未提供时，必须先询问**：「请提供上传模板名称（template_name），您可以从业务文档或负责人处获取。」
- 不得自行猜测或填写任何字符串作为默认值
- 传入错误的模板名会导致文件存储到错误的位置，影响后续业务

## 使用上传结果

`success: true` 时，**必须**按以下格式输出。将工具返回的完整原始 JSON 原样嵌入代码块，不得用文字摘要代替：

上传成功。完整数据如下：

````json
  {工具返回的完整原始 JSON，原样输出，可以格式化，但不能增删任何字段，不能修改任何值}
````

### ✅ 正确示例（图片上传）

上传成功。完整数据如下：

```json
{
  "success": true,
  "media_type": "image",
  "media_key": "v2-103232c019c647......",
  "space_name": "default",
  "upload_result": "UPLOAD_SUCCESS",
  "media_meta": {
    "width": 1080,
    "height": 603,
    "format": "webp",
    "size": 58376
  },
  "media_url": {
    "primary": "zhihu-image-url",
    "backups": []
  },
  "extra": {
    "watermark_image_key": "v2-7691ce592892e......",
    "watermark_image_url": {
      "primary": "zhihu-image-url",
      "backups": []
    }
  }
}
```

### ❌ 错误示例（禁止）

以下输出省略了大量字段，导致调用方无法获取 `media_url`、`extra.watermark_image_key` 等关键字段：

> 上传成功。
> - **media_key**: `v2-103232c019c6470......`
> - **尺寸**: 1080 × 603，webp，58KB

**视频额外提示**：`upload_result: UPLOAD_SUCCESS` 仅表示文件已接收，还需异步转码（可能数分钟到数十分钟）完成后才可播放。输出完整 JSON 后，告知用户等待转码。

## 错误处理

**上传失败时，向用户说明具体失败原因，以及应该如何处理或下一步怎么做。**

| error_type | 处置方式 |
|---|---|
| `validation_error` | 修正参数重试。最常见原因：路径非绝对路径、图片的 scene_name 不在合法值（answer/question/pin/article）之列、upload_object 缺少 scene_name 或 template_name、同时传了 file_path 和 url |
| `auth_error` | 停止上传，告知用户检查共享凭证文件或 `ZHIHU_OPENAPI_APP_KEY` / `ZHIHU_OPENAPI_APP_SECRET` 配置 |
| `api_error` | 重试一次；仍失败则将 `message` 中的错误信息告知用户 |
| `transfer_error` | 网络问题，重试一次；仍失败则告知用户网络异常 |
| `session_expired` | 不要重试旧调用——重新完整调用上传工具（从步骤4重新开始） |
| `download_error` | URL 无法访问。告知用户 `message` 中的原因，建议先将文件下载到本地再用 `file_path` 上传 |
| `internal_error` | 告知用户稍后重试；若持续发生请联系平台支持 |

需要深入排查错误时，加载 `references/error-reference.md`。

## 参考资料（按需加载）

- **`references/update.md`** — 版本接口检查和更新流程。每个会话首次加载本 skill，或用户询问版本、更新、升级时加载。
- **`references/auth-info.md`** — 知乎凭证说明：凭证含义、获取方式、多 skill 复用逻辑。当用户不清楚如何获取凭证、或涉及凭证复用判断时加载。
- **`references/mcp-setup.md`** — MCP Server 配置参考（AI 自动写入），当自动配置流程无法识别当前 Agent 类型时加载；支持的 Agent 范围和具体配置模板以该文档为准。
- **`references/tool-parameters.md`** — 三个工具的完整参数列表和响应字段说明。当需要确认某个参数名称或响应字段时加载。
- **`references/error-reference.md`** — 每个错误类型的详细成因和逐步排查步骤。当错误排查不清晰时加载。
