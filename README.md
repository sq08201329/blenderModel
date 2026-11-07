# blenderModel

CodeBuddy Agent SDK 的调研笔记与由浅入深的 Python 教学案例。

> 仓库名沿用 `blenderModel`，当前内容以 SDK 教学为主。完整调研、API 清单与案例讲解见 [docs/codebuddy-agent-sdk-tutorial.md](docs/codebuddy-agent-sdk-tutorial.md)。

## 环境要求

| 项 | 值 |
|---|---|
| Python | 3.12（`.python-version` 固定） |
| 包管理 | [UV](https://docs.astral.sh/uv/) |
| SDK | `codebuddy-agent-sdk>=0.3.299` |
| 前置 | 已安装 `codebuddy` CLI 并完成登录，或设置 `CODEBUDDY_API_KEY` |

## 快速开始

```bash
git clone git@github.com:sq08201329/blenderModel.git
cd blenderModel
uv sync
uv run python cases/01_hello_query.py
```

`query()` 会真实调用模型并产生费用，运行前请确认认证可用。

## 目录结构

```
cases/
  01_hello_query.py        # 案例 01：query() 消息流
  _common/
    sdk_helpers.py         # 公共函数：format_message / dump_message / dump_stream
docs/
  codebuddy-agent-sdk-tutorial.md   # 调研 + API 清单 + 课程大纲 + 案例讲解
pyproject.toml / uv.lock   # UV 项目与锁定依赖
```

案例按路径运行时 `cases/` 会进入 `sys.path`，因此公共模块用
`from _common.sdk_helpers import ...` 导入，无需额外配置。

## 课程进度

案例 **01** 已完成：`query()` 基础用法、消息流分层、`CodeBuddyAgentOptions` 初见。
案例 02–10（Options 与环境隔离、多轮对话、会话恢复、权限控制、Hooks、自定义 Agent、自定义工具/MCP、综合实战）待补充，完整大纲见教程文档。

## 几个已验证的要点

- **环境隔离**：SDK 默认不加载 `settings.json`、`CODEBUDDY.md`、MCP、Skills 等文件配置，行为完全由代码中的 `options` 决定；需要时用 `setting_sources` 显式加载。
- **提问不在返回值里**：`query(prompt="...")` 把提问通过 stdin 发给 CLI，消息流不会回显原始 prompt，需要自己保留变量。
- **工具结果走 `UserMessage`**：Anthropic 风格消息格式里 `tool_result` 属于 user 角色，不在 `AssistantMessage.content` 中。
- **会话落盘**：`~/.codebuddy/projects/<项目路径>/<session_id>.jsonl`，可用 `resume` 恢复。
- **全异步**：所有 API 基于 `asyncio`，必须用 `async for` 消费消息流。

## 相关链接

- [CodeBuddy Agent SDK 文档](https://www.codebuddy.cn/docs/cli/sdk)
- [Python SDK 参考](https://www.codebuddy.cn/docs/cli/sdk-python)
- [TypeScript SDK 参考](https://www.codebuddy.cn/docs/cli/sdk-typescript)
