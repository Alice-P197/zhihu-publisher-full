# MCP Server 配置参考（AI 操作指南）

> 本文档供 AI Agent 在自动配置流程无法识别当前 Agent 类型时加载使用。
> 本文档是运行环境探测和 MCP 配置模板的唯一详细来源；`SKILL.md` 只保留入口和原则。
> 按以下步骤代替用户完成配置，**不要让用户手动编辑配置文件或复制命令**。
> 本文档只用于配置 MCP server。配置完成后必须停止并提示用户重启 Agent，不得在当前会话继续上传或直接调用 MCP stdio。

---

## 步骤一：询问用户使用的 Agent

用友好的方式询问一次：

> 我需要确认你使用的 AI 工具，以便自动完成配置。请问你用的是哪个？
> - Claude Code（命令行）
> - Cursor
> - Codex CLI（OpenAI）
> - Gemini CLI（Google）
> - Windsurf
> - VS Code + GitHub Copilot
> - Cline（VS Code 插件）
> - Kiro
> - Continue
> - CodeBuddy（腾讯云代码助手）
> - GitHub Copilot CLI（命令行独立版）
> - Augment Code
> - OpenCode
> - OpenClaw
> - 其他（请说明）

根据回答进入对应的配置路径（见步骤三）。

---

## 步骤二：解析 MCP Server 运行命令

先解析出要写入配置的 `UV_COMMAND`、`MCP_COMMAND` 和 `MCP_ARGS`。**不要在运行命令验证成功前写 MCP 配置**。

只允许使用 `"<uv 可执行文件绝对路径>" run --index-url https://pypi.tuna.tsinghua.edu.cn/simple --project <zhihu-mediacloud-uploader skill所在的绝对路径> zhihu-mediacloud-uploader`。不要降级为本地 Python 模块运行或 `uvx` 工具缓存运行。

### 2.1 使用 uv run --project 本地 skill 目录

定位 `uv` 可执行文件的绝对路径，并检查版本：

| 系统 | 命令 |
|---|---|
| macOS / Linux | `UV_COMMAND="$(command -v uv)" && "$UV_COMMAND" --version` |
| Windows PowerShell | `$UvCommand = (Get-Command uv).Source; & $UvCommand --version` |

`uv` 不存在时安装 uv，安装后重新打开终端再重试：

macOS / Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

`uv` 存在后，必须保留并写入 `uv` 可执行文件的绝对路径：

- macOS / Linux：`UV_COMMAND` 来自 `command -v uv`，例如 `/Users/alice/.local/bin/uv` 或 `/usr/local/bin/uv`。
- Windows PowerShell：`$UvCommand` 来自 `(Get-Command uv).Source`，例如 `C:/Users/Alice/.local/bin/uv.exe`。
- `MCP_COMMAND` 必须使用该绝对路径，不要写 `"uv"`、相对路径或 `~`。

然后定位 `zhihu-mediacloud-uploader` skill 所在目录：

- skill 所在目录必须是包含 `SKILL.md` 和 `pyproject.toml` 的目录。
- 如果当前 skill 以文件路径加载，取当前 `SKILL.md` 所在目录。
- 写入 MCP 配置时必须使用 skill 所在目录的绝对路径，不要使用相对路径或 `~`。
- 如果找不到 `pyproject.toml`，停止配置，告知用户无法定位可通过 `uv run --project` 运行的 skill 所在目录。

然后必须验证本地 skill 可运行：

```bash
"<uv 可执行文件绝对路径>" run --index-url https://pypi.tuna.tsinghua.edu.cn/simple --project "<zhihu-mediacloud-uploader skill所在的绝对路径>" zhihu-mediacloud-uploader --version
```

- 成功输出版本号：使用 `MCP_COMMAND="<uv 可执行文件绝对路径>"`，`MCP_ARGS=["run", "--index-url", "https://pypi.tuna.tsinghua.edu.cn/simple", "--project", "<zhihu-mediacloud-uploader skill所在的绝对路径>", "zhihu-mediacloud-uploader"]`
- 失败、卡住、或 skill 所在目录不可用：停止配置，不要写 MCP 配置；告知用户需要先修复 uv、Python 依赖源或 skill 所在目录。

不要使用 `uvx zhihu-mediacloud-uploader` 或 `uvx --from "<skill目录>" zhihu-mediacloud-uploader` 作为 MCP 标准启动命令。`uvx` 会使用工具环境和缓存，skill 升级但 Python 包版本号未变化时，重启后的 MCP server 可能继续使用旧安装产物。本 skill 的 MCP server 应通过 `uv run --project` 从当前 skill 项目目录启动。

必须显式带上 `--index-url https://pypi.tuna.tsinghua.edu.cn/simple`，用于解析本项目依赖；不要依赖用户机器上的默认 Python 源。

`--version` / `--help` 必须只打印信息并退出，不应读取凭证或进入 MCP stdio；若进入等待状态，说明用户安装的是旧版本，必须升级后再配置。

除上述 `--version` 验证命令外，不得运行无参数 `zhihu-mediacloud-uploader`，不得手写或运行 MCP stdio 客户端，不得扫描、修改或调用本 skill 的 Python 源码来绕过 Agent 的 MCP 工具注册。

### 2.2 写配置前的值

| 运行方式 | command | args |
|---|---|---|
| uv run --project 本地 skill 目录 | `"<uv 可执行文件绝对路径>"` | `["run", "--index-url", "https://pypi.tuna.tsinghua.edu.cn/simple", "--project", "<zhihu-mediacloud-uploader skill所在的绝对路径>", "zhihu-mediacloud-uploader"]` |

Windows 路径写入 JSON/TOML/YAML 时，优先使用 `/`，或将 `\` 转义为 `\\`。例如 `C:/Users/Alice/.local/bin/uv.exe`。

---

## 步骤三：写入配置文件

根据用户回答，直接写入对应文件。文件不存在则新建，已存在则先备份，再合并对应节点。

合并要求：

- 只新增或替换 `zhihu-mediacloud-uploader` 这一项
- 不覆盖其他 MCP server
- 不改变同文件中的无关配置
- 使用步骤二解析出的 `MCP_COMMAND` / `MCP_ARGS`

凭证默认读取 `~/.zhihu/openapi-credentials.json`，多个知乎 skill 共用该文件。以下 MCP 模板默认不写密钥 env；只有需要临时覆盖共享文件时，才额外写入 `ZHIHU_OPENAPI_APP_KEY` / `ZHIHU_OPENAPI_APP_SECRET`。

媒体云 MCP server 的可选运行配置读取优先级：

1. 启动环境变量：`ZHIHU_MEDIACLOUD_BASE_URL` 覆盖服务地址，`ZHIHU_MEDIACLOUD_API_TIMEOUT` 覆盖 HTTP 超时秒数
2. 共享配置文件：`~/.zhihu/openapi-config.json`
3. 默认值：`https://openapi.zhihu.com` 和 `30`

如果 Agent/MCP 客户端不能稳定向 MCP server 注入环境变量，或需要多个 Agent 稳定复用同一套运行配置，写入 `~/.zhihu/openapi-config.json`。文件使用专用键名，不要使用通用 `BASE_URL` / `API_TIMEOUT`，避免与其他 skill 或项目环境变量冲突。

示例：

```json
{
  "ZHIHU_MEDIACLOUD_BASE_URL": "https://openapi.zhihu.com",
  "ZHIHU_MEDIACLOUD_API_TIMEOUT": 30
}
```

本文件只保存可选运行配置，不保存 `ZHIHU_OPENAPI_APP_KEY` / `ZHIHU_OPENAPI_APP_SECRET`；凭证仍写入 `~/.zhihu/openapi-credentials.json`。

以下示例均为 `uv run --project` 本地 skill 目录方式。所有配置都必须使用步骤二验证通过的 `uv` 可执行文件绝对路径和 skill 所在目录绝对路径，并带上清华 PyPI 镜像参数。

---

### Claude Code

不使用配置文件，运行以下命令：

```bash
claude mcp add \
  --transport stdio \
  zhihu-mediacloud-uploader -- "<uv 可执行文件绝对路径>" run --index-url https://pypi.tuna.tsinghua.edu.cn/simple --project "<zhihu-mediacloud-uploader skill所在的绝对路径>" zhihu-mediacloud-uploader
```

### Cursor

配置文件：`.cursor/mcp.json`（项目级）或 `~/.cursor/mcp.json`（全局，推荐）

```json
{
  "mcpServers": {
    "zhihu-mediacloud-uploader": {
      "command": "<uv 可执行文件绝对路径>",
      "args": ["run", "--index-url", "https://pypi.tuna.tsinghua.edu.cn/simple", "--project", "<zhihu-mediacloud-uploader skill所在的绝对路径>", "zhihu-mediacloud-uploader"]
    }
  }
}
```

---

### Windsurf

配置文件：`~/.codeium/windsurf/mcp_config.json`

```json
{
  "mcpServers": {
    "zhihu-mediacloud-uploader": {
      "command": "<uv 可执行文件绝对路径>",
      "args": ["run", "--index-url", "https://pypi.tuna.tsinghua.edu.cn/simple", "--project", "<zhihu-mediacloud-uploader skill所在的绝对路径>", "zhihu-mediacloud-uploader"]
    }
  }
}
```

---

### VS Code + GitHub Copilot

配置文件：`.vscode/mcp.json`（项目级）

> ⚠️ VS Code 使用 `"servers"` 作为顶层键，**不是** `"mcpServers"`。

```json
{
  "servers": {
    "zhihu-mediacloud-uploader": {
      "command": "<uv 可执行文件绝对路径>",
      "args": ["run", "--index-url", "https://pypi.tuna.tsinghua.edu.cn/simple", "--project", "<zhihu-mediacloud-uploader skill所在的绝对路径>", "zhihu-mediacloud-uploader"]
    }
  }
}
```

---

### Cline（VS Code 插件）

配置文件路径（按操作系统）：

| 系统 | 路径 |
|---|---|
| macOS | `~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json` |
| Windows | `%APPDATA%\Code\User\globalStorage\saoudrizwan.claude-dev\settings\cline_mcp_settings.json` |
| Linux | `~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json` |

```json
{
  "mcpServers": {
    "zhihu-mediacloud-uploader": {
      "command": "<uv 可执行文件绝对路径>",
      "args": ["run", "--index-url", "https://pypi.tuna.tsinghua.edu.cn/simple", "--project", "<zhihu-mediacloud-uploader skill所在的绝对路径>", "zhihu-mediacloud-uploader"]
    }
  }
}
```

---

### Kiro

配置文件：`.kiro/settings/mcp.json`（项目级）

```json
{
  "mcpServers": {
    "zhihu-mediacloud-uploader": {
      "command": "<uv 可执行文件绝对路径>",
      "args": ["run", "--index-url", "https://pypi.tuna.tsinghua.edu.cn/simple", "--project", "<zhihu-mediacloud-uploader skill所在的绝对路径>", "zhihu-mediacloud-uploader"]
    }
  }
}
```

---

### Codex CLI（OpenAI）

配置文件：`~/.codex/config.toml`（全局）或 `.codex/config.toml`（项目级，需信任项目）

> ⚠️ Codex 使用 **TOML 格式**，不是 JSON。

直接写入 `~/.codex/config.toml`（文件不存在则新建，已存在则追加 `[mcp_servers.*]` 节点）：

```toml
[mcp_servers.zhihu-mediacloud-uploader]
command = "<uv 可执行文件绝对路径>"
args = ["run", "--index-url", "https://pypi.tuna.tsinghua.edu.cn/simple", "--project", "<zhihu-mediacloud-uploader skill所在的绝对路径>", "zhihu-mediacloud-uploader"]
```

---

### Gemini CLI（Google）

配置文件：`~/.gemini/settings.json`（全局）

直接写入（合并 `mcpServers` 节点，不覆盖其他配置）：

```json
{
  "mcpServers": {
    "zhihu-mediacloud-uploader": {
      "command": "<uv 可执行文件绝对路径>",
      "args": ["run", "--index-url", "https://pypi.tuna.tsinghua.edu.cn/simple", "--project", "<zhihu-mediacloud-uploader skill所在的绝对路径>", "zhihu-mediacloud-uploader"]
    }
  }
}
```

---

### Continue

配置文件：`.continue/config.yaml`（项目级）或 `~/.continue/config.yaml`（全局）

> ⚠️ Continue 使用 **YAML 格式**，`mcpServers` 是数组，每个条目需要 `name` 字段。
> 如果用户的全局配置是旧版 `.json` 格式，优先使用项目级 `.continue/config.yaml`。

```yaml
mcpServers:
  - name: zhihu-mediacloud-uploader
    command: "<uv 可执行文件绝对路径>"
    args:
      - run
      - --index-url
      - https://pypi.tuna.tsinghua.edu.cn/simple
      - --project
      - <zhihu-mediacloud-uploader skill所在的绝对路径>
      - zhihu-mediacloud-uploader
```

---

### CodeBuddy（腾讯云代码助手）

配置文件：`~/.codebuddy/mcp.json`（全局）或 `.codebuddy/mcp.json`（项目级）

```json
{
  "mcpServers": {
    "zhihu-mediacloud-uploader": {
      "command": "<uv 可执行文件绝对路径>",
      "args": ["run", "--index-url", "https://pypi.tuna.tsinghua.edu.cn/simple", "--project", "<zhihu-mediacloud-uploader skill所在的绝对路径>", "zhihu-mediacloud-uploader"]
    }
  }
}
```

---

### GitHub Copilot CLI（命令行独立版）

> ⚠️ 此配置针对 GitHub Copilot **CLI 独立命令行版**，与 VS Code 扩展版（`.vscode/mcp.json`）配置文件不同，互不影响。

配置文件：`~/.copilot/mcp-config.json`（全局）

```json
{
  "mcpServers": {
    "zhihu-mediacloud-uploader": {
      "command": "<uv 可执行文件绝对路径>",
      "args": ["run", "--index-url", "https://pypi.tuna.tsinghua.edu.cn/simple", "--project", "<zhihu-mediacloud-uploader skill所在的绝对路径>", "zhihu-mediacloud-uploader"]
    }
  }
}
```

---

### Augment Code

配置文件：`~/.augment/settings.json`（全局，同时适用于 CLI 和 VS Code 扩展）

```json
{
  "mcpServers": {
    "zhihu-mediacloud-uploader": {
      "command": "<uv 可执行文件绝对路径>",
      "args": ["run", "--index-url", "https://pypi.tuna.tsinghua.edu.cn/simple", "--project", "<zhihu-mediacloud-uploader skill所在的绝对路径>", "zhihu-mediacloud-uploader"]
    }
  }
}
```

---

### OpenCode

配置文件：`~/.config/opencode/opencode.json`（全局）或 `./opencode.json`（项目级）

> ⚠️ OpenCode 格式与其他 Agent 不同，三处差异：
> - 顶层键为 `"mcp"`，不是 `"mcpServers"`
> - `"command"` 是数组（command + args 合并），不需要单独的 `"args"` 字段
> - 环境变量键名为 `"environment"`，不是 `"env"`

```json
{
  "mcp": {
    "zhihu-mediacloud-uploader": {
      "type": "local",
      "command": ["<uv 可执行文件绝对路径>", "run", "--index-url", "https://pypi.tuna.tsinghua.edu.cn/simple", "--project", "<zhihu-mediacloud-uploader skill所在的绝对路径>", "zhihu-mediacloud-uploader"]
    }
  }
}
```

---

### OpenClaw

配置文件：`~/.openclaw/openclaw.json`（全局）

> ⚠️ OpenClaw 使用嵌套结构 `mcp.servers`，不是扁平 `mcpServers`。文件为 JSON5 格式（支持注释和尾逗号）。合并写入时只新增 `mcp.servers` 下的节点，不替换整个文件。

```json
{
  "mcp": {
    "servers": {
      "zhihu-mediacloud-uploader": {
        "command": "<uv 可执行文件绝对路径>",
        "args": ["run", "--index-url", "https://pypi.tuna.tsinghua.edu.cn/simple", "--project", "<zhihu-mediacloud-uploader skill所在的绝对路径>", "zhihu-mediacloud-uploader"]
      }
    }
  }
}
```

---

### 未识别的 Agent

向用户说明无法自动配置，并告知其需要提供的配置内容。以下使用步骤二验证通过的 `uv run --project` 本地 skill 目录方式：

> 你的 AI 工具暂不在自动配置支持列表中。请在其 MCP 设置界面或配置文件中添加以下服务器配置：
>
> ```json
> {
>   "mcpServers": {
>     "zhihu-mediacloud-uploader": {
>       "command": "<uv 可执行文件绝对路径>",
>       "args": ["run", "--index-url", "https://pypi.tuna.tsinghua.edu.cn/simple", "--project", "<zhihu-mediacloud-uploader skill所在的绝对路径>", "zhihu-mediacloud-uploader"]
>     }
>   }
> }
> ```
>
> 如果你的工具顶层键名不是 `"mcpServers"`（如 VS Code 用 `"servers"`），请以该工具的实际键名为准。配置完成后重启工具。

---

## 步骤四：提示重启

配置写入后告知用户：

> 配置已写入完成。请**重启你的 AI 工具**（完全退出后重新打开），重启后重新发起上传请求即可继续。

这是终止步骤。输出上述提示后必须停止本轮任务，不要继续执行上传流程，不要检查当前会话内是否能直接通过 MCP stdio 调用，不要编写临时代码调用 uploader。必须等待用户重启 Agent 后，由新会话中暴露的 `upload_*` 工具完成上传。

> ⚠️ 凭证默认保存于本地共享凭证文件 `~/.zhihu/openapi-credentials.json`，不要提交到代码仓库；如额外写入 `ZHIHU_OPENAPI_*` MCP env，同样不要提交对应配置文件。
