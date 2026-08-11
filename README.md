# zhihu-publisher-full — 知乎发布完整 Skill 包

知乎内容发布全家桶，包含两个 Skill：**zhihu-publisher**（内容转换、预览与发布）和 **zhihu-mediacloud-uploader**（媒体云上传）。

## 包含内容

### zhihu-publisher — 知乎发布

将用户内容转换为知乎适配格式，生成浏览器预览，用户确认后发布。支持：

- **文章（article）**
- **提问（question）**
- **想法（pin）**

完整流程：草稿整理 → 结构化转换 → 本地浏览器预览 → 用户确认 → 发布，产物按固定链路派生：

```text
用户输入 -> draft/latest-draft.md -> validate/latest.json -> preview/latest.html -> 用户确认 -> publish/latest-request.json -> publish/latest-response.json
```

### zhihu-mediacloud-uploader — 知乎媒体云上传

帮助 AI Agent 将图片、视频和各类文件上传到知乎媒体云，获取用于内容发布的媒资标识符（`media_key`）。支持：

- 独立 MCP server 接入，也可作为依赖 Skill 与其他 Skill 协作
- 三种上传服务与完整的错误处理、鉴权流程
- 自动引导完成 MCP 配置，凭证保存到 `~/.zhihu/openapi-credentials.json`

## 授权与凭证

首次使用需要知乎 OpenAPI 凭证：

1. 从知乎个人主页 URL 获取 `ZHIHU_OPENAPI_APP_KEY`
2. 前往[知乎开放平台](https://www.zhihu.com/playground/zhihu-publisher)申请 `ZHIHU_OPENAPI_APP_SECRET`
3. 多个知乎 OpenAPI Skill 复用同一套凭证，配置一次即可

> ⚠️ 请勿将凭证提交到代码仓库或分享给他人；若泄露请立即在开放平台重置。

## 安装

发布到 Skill 注册中心后，可使用注册中心标识安装，例如：

```bash
npx skills add zhihu/zhihu-publisher -g
```

图片上传依赖：

```bash
npx skills add zhihu/zhihu-mediacloud-uploader
```

## 使用示例

- “把这篇 Markdown 转成知乎文章并生成预览。”
- “把这段内容和图片发成知乎想法。”
- “预览没问题，确认发布。”

> 当前发布流程只支持图片上传，暂不支持视频。

## 仓库结构

```
zhihu-publisher-full/
├── zhihu-publisher/               # 知乎发布 Skill（含 preview / publish / validate 子 Skill）
│   ├── SKILL.md
│   ├── README.md
│   ├── reference/                 # 凭证、更新等参考文档
│   └── zhihu-{preview,publish,validate}/  # 子流程定义
└── zhihu-mediacloud-uploader/     # 知乎媒体云上传 Skill（含完整 Python MCP server）
    ├── SKILL.md
    ├── README.md
    ├── mediacloud_uploader/       # Python 包（API 客户端、上传器、校验器等）
    ├── references/                # 凭证、错误码、MCP 配置等文档
    └── tests/                     # 单元测试
```
