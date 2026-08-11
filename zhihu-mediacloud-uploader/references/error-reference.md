# Error Reference

> 按需加载：当错误排查不清晰，或需要了解某个 error_type 的详细成因时加载此文件。

---

## validation_error

**含义**：客户端参数错误，服务端在处理前已拒绝请求。

**常见原因和修复方式：**

| 原因 | 典型 message | 修复 |
|---|---|---|
| file_path 非绝对路径 | `"文件不存在: ./photo.jpg"` | 展开为绝对路径后重试 |
| 文件不存在 | `"文件不存在: /path/file.jpg"` | 确认文件路径是否正确，文件是否已存在 |
| media_type 无效 | `"invalid media_type: gif"` | 只能传 `image`/`video`/`object` |
| scene_name 为空（图片） | `"scene_name is required"` | 询问用户目标场景（answer/question/pin/article） |
| scene_name 为空（对象） | `"请提供 scene_name 参数..."` | 询问用户目标场景（answer/question/pin/article），或使用用户指定的场景码 |
| scene_name 值不合法（图片） | `"scene_name 值 'blog' 不合法，图片仅支持：answer..."` | 图片严格四选一；视频和对象允许透传任意值 |
| template_name 未提供（upload_object） | `"请提供 template_name 参数..."` | 向用户确认上传模板名称后重试 |
| file_path 和 url 同时提供 | `"file_path 和 url 不能同时提供"` | 只保留其中一个 |
| 两者均未提供 | `"请提供 file_path 或 url 之一"` | 传入 file_path 或 url |
| file_obj 未提供 file_size | `"file_size is required when using file_obj"` | 使用 file_path 代替 file_obj，或提供正确 file_size |

**不要重试**：参数错误重试不会有帮助，必须先修正参数.

---

## auth_error

**含义**：签名验证失败，服务端返回 HTTP 401。

**常见原因：**
1. 共享凭证文件或 `ZHIHU_OPENAPI_APP_KEY` / `ZHIHU_OPENAPI_APP_SECRET` 未设置或设置错误
2. `ZHIHU_OPENAPI_APP_KEY` 对应的 `ZHIHU_OPENAPI_APP_SECRET` 不匹配
3. 账号无权访问该接口

**排查步骤：**
1. 检查 `~/.zhihu/openapi-credentials.json` 是否存在且包含 `ZHIHU_OPENAPI_APP_KEY`、`ZHIHU_OPENAPI_APP_SECRET`
2. 如使用环境变量覆盖，检查 `ZHIHU_OPENAPI_APP_KEY` / `ZHIHU_OPENAPI_APP_SECRET`
3. 确认 `ZHIHU_OPENAPI_APP_SECRET` 是对应 `ZHIHU_OPENAPI_APP_KEY` 的 SK，两者必须配对
4. 如果最近更换过密钥，确认已重启 MCP server 使新值生效

**不能继续上传**，必须先修复配置。

---

## api_error

**含义**：服务端处理请求时返回业务错误（HTTP 200 但状态码非零，或 HTTP 4xx/5xx）。

**常见原因：**

| HTTP 状态 | 常见原因 |
|---|---|
| 400 | content_type 与文件实际格式不匹配；图片超过大小限制（非 GIF >30MB 或 GIF >15MB） |
| 403 | 当前 App Key 无权访问该 scene_name |
| 500/502/503 | 服务端内部错误，可重试 |

**处理策略：**
- 400 错误：查看 message 中的具体说明，修正参数
- 403 错误：scene_name 权限问题，联系平台申请权限
- 5xx 错误：等待片刻后重试一次；若持续失败，告知用户

---

## transfer_error

**含义**：文件上传到云存储时失败，通常是网络波动或临时凭证问题。

**常见原因：**

| 原因类型 | 处理 |
|---|---|
| 临时上传凭证无效或过期 | 重试一次（工具内部会自动刷新凭证） |
| 凭证权限不足 | 重试一次；若仍失败则为配置问题 |
| 网络超时 | 检查网络连接，重试 |
| 云存储内部错误 | 等待片刻后重试 |

**注意**：上传工具内部已包含一次凭证过期自动刷新重试。如果 `transfer_error` 透出到工具响应层，说明重试后仍失败，建议整体重新上传。

---

## session_expired

**含义**：上传会话已在服务端超期，凭证刷新失败。

**触发场景**：大文件上传过程中（通常 >= 500 MB 的分片上传），上传耗时过长导致会话超期；或上传开始后网络中断时间过长。

**处理方式**：
- **不要重试当前调用**
- 重新完整调用上传工具（工具会重新发起完整上传流程）
- 如果是网络不稳定导致的，建议在网络更稳定的环境下重试

---

## download_error

**含义**：通过 URL 下载文件时失败。

**常见原因：**

| 原因 | 典型 message | 修复 |
|---|---|---|
| URL 返回 404 | `"URL 返回 HTTP 404，无法下载文件"` | 确认 URL 是否正确且未失效 |
| URL 需要登录/鉴权（403/401） | `"URL 返回 HTTP 403"` | 该 URL 无法公开访问；让用户先下载到本地再用 file_path 上传 |
| 网络连接失败 | `"无法连接到该地址"` | 检查网络连接，或改用本地文件 |
| 下载超时 | `"下载超时"` | URL 响应太慢；建议先下载到本地再上传 |
| 协议不支持（ftp/file 等） | `"仅支持 http:// 和 https:// 协议"` | 只能使用 http/https URL |

**处理策略**：
- 告知用户 `message` 中的具体原因
- 建议用户先将文件手动下载到本地，再通过 `file_path` 参数上传
- 不要对 `download_error` 自动重试——URL 无法访问多次重试也不会成功

---

## internal_error

**含义**：MCP server 内部发生未预期的异常，已记录日志。

**常见原因**：
- 上传过程中发生意外异常
- 内存不足（极大文件）
- 系统资源问题

**处理方式**：
1. 告知用户稍后重试
2. 如果持续发生，建议联系平台支持并提供发生时间和文件信息
3. 开发者排查：查看 MCP server 日志（stderr），搜索 `unexpected error` 关键词
