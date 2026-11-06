# CodeBuddy Agent SDK 调研与教学案例

> 调研日期：2026-11-06
> 依据：本地内置中文文档 `/usr/local/lib/node_modules/@tencent-ai/codebuddy-code/dist/web-ui/docs/cn%2Fcli%2Fsdk*.md`，并以 `codebuddy-agent-sdk==0.3.299` 实测校验
> 教学语言：Python（承接本仓库已建好的 UV 项目）；配套代码在 `cases/`

---

## 一、CodeBuddy SDK 是什么

有两套，别混淆：

- **CodeBuddy Agent SDK**（本系列主题）：`@tencent-ai/agent-sdk` / `codebuddy-agent-sdk`。它不是远程 HTTP API，而是**在你代码里拉起本地 `codebuddy` CLI 子进程**（stream-json 长连接），把 Agent 的全部能力编程化。Python ≥ 3.10 全异步，Node ≥ 18.20。当前处于 Preview 阶段。
- **AgentOS / Cloud Agent SDK**：`@tencent-ai/cloud-agent-sdk` / `codebuddy-cloud-agent-sdk`，是云端 REST 接口的封装，用于实例/会话/产物管理，另属一套。

**最重要的一个设计**：SDK 默认**不加载任何文件系统配置**（`settings.json`、`CODEBUDDY.md`、MCP、子代理、Skills、Rules 全不读），行为完全由代码里的 `options` 决定。要加载得显式指定 `setting_sources`。这是与 CLI 交互最大的差异，也是新手第一个坑。

## 二、常用 API 清单

| 层 | API | 说明 |
|---|---|---|
| 入口 | `query(prompt, options=None, transport=None)` | 单次查询 → `AsyncIterator[Message]`，最常用 |
| 入口 | `CodeBuddySDKClient` | 多轮双向：`connect/query/receive_response/receive_messages/disconnect/interrupt/set_model/set_permission_mode/mcp_server_status` |
| 配置 | `CodeBuddyAgentOptions` | 28 个字段。常用：`permission_mode` `cwd` `model` `max_turns` `allowed_tools` `disallowed_tools` `system_prompt` `env` `setting_sources` `resume` `hooks` `can_use_tool` `agents` `mcp_servers` `thinking` `effort` |
| 消息 | `SystemMessage` `AssistantMessage` `UserMessage` `ResultMessage` `StreamEvent` | 消息联合类型 |
| 内容块 | `TextBlock` `ThinkingBlock` `ToolUseBlock` `ToolResultBlock` | `AssistantMessage.content` 是这些块的**列表** |
| 后台任务 | `TaskStarted/Progress/Updated/NotificationMessage` | `SystemMessage` 子类 |
| 权限 | `PermissionMode` = `default/acceptEdits/plan/bypassPermissions`；`can_use_tool` → `PermissionResultAllow(updated_input)` / `PermissionResultDeny(message, interrupt)`；`CanUseToolOptions` | 细粒度拦截、改写入参 |
| Hook | `HookMatcher(matcher, hooks, timeout)`、`HookContext`；事件 `PreToolUse/PostToolUse/UserPromptSubmit/Stop/...` | 工具执行前后插逻辑 |
| 子 Agent | `AgentDefinition(description, prompt, tools, disallowed_tools, model)` | 定制专门化代理 |
| 会话 | `session_id`（`SystemMessage.data` / `ResultMessage`）、`resume`、`continue_conversation`、`fork_session`、`persist_session` | 恢复/续接 |
| 认证 | `authenticate() → AuthFlow(auth_url, wait(), cancel())`、`logout()`、`AuthenticateResponse`/`UserInfo` | 两阶段登录；或用 `CODEBUDDY_API_KEY` / `CODEBUDDY_AUTH_TOKEN` |
| 扩展 | `@tool` + `create_sdk_mcp_server`、`mcp_servers`（stdio/http/sse）、`mcp_server_status()` | 进程内自定义工具 / MCP |
| 异常 | `CodeBuddySDKError` → `CLIConnectionError` `CLINotFoundError` `CLIStartupError` `ExecutionError` `AuthenticationError` 等 | 统一异常树 |

TypeScript 对照：`query({prompt, options}) → Query`（AsyncGenerator 扩展 `interrupt/setPermissionMode/setModel/supportedCommands/mcpServerStatus/accountInfo/streamInput`）、`unstable_v2_createSession/resumeSession/prompt/authenticate`、`HOOK_EVENTS`、`EXIT_REASONS`、`AbortError`。

认证相关环境变量：`CODEBUDDY_API_KEY`、`CODEBUDDY_INTERNET_ENVIRONMENT`（中国版 `internal`、iOA 版 `ioa` 等）、`CODEBUDDY_CODE_PATH`（CLI 路径，可选）、`CODEBUDDY_AUTH_TOKEN`（OAuth Client Credentials）。

## 三、课程大纲（由浅入深）

1. **Hello, query()** — 消息流、3 类消息、`CodeBuddyAgentOptions` 初见 ← 本文已含
2. Options 全景 & 环境隔离 `setting_sources`
3. 让 Agent 干活：工具白名单、`ToolUseBlock`、只读分析项目
4. 多轮对话：`CodeBuddySDKClient` + `receive_response`
5. 会话持久化：`session_id` / `resume` / `continue_conversation`
6. 权限控制：`can_use_tool` 白名单与危险命令拦截
7. Hook 系统：`PreToolUse` 审计与阻断
8. 自定义子 Agent：`AgentDefinition`
9. 自定义工具：`@tool` + `create_sdk_mcp_server` / 外部 MCP
10. 综合实战：批量代码审查 CLI（流式输入、中断、错误处理、成本统计）

---

## 案例 01 · Hello, query()

难度：★☆☆☆☆
目标：跑通一次最简单的 SDK 查询，看懂消息流里到底流过了什么。

可运行文件：[`cases/01_hello_query.py`](../cases/01_hello_query.py)（已验证所有符号可导入、语法通过；**未实际执行**，执行会调用模型产生费用且需要登录态）。

完整打印复用公共模块 [`cases/_common/sdk_helpers.py`](../cases/_common/sdk_helpers.py)：`format_message()` / `dump_message()` / `dump_stream()`，后续案例共用。

### 代码

```python
"""
案例 01 · Hello, query()

本例涉及的 API：
    query(prompt=..., options=...)   -> AsyncIterator[Message]
    CodeBuddyAgentOptions
    SystemMessage / AssistantMessage / UserMessage / ResultMessage
    TextBlock / ToolUseBlock / ToolResultBlock

公共函数：_common.sdk_helpers.dump_stream()（完整打印每条消息并原样 yield）
"""

import asyncio

from codebuddy_agent_sdk import (
    AssistantMessage,
    CodeBuddyAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)
from _common.sdk_helpers import dump_stream


async def main() -> None:
    prompt = "用一句话解释什么是递归函数"
    print(f"[提问] {prompt}")

    options = CodeBuddyAgentOptions(
        permission_mode="plan",  # 只读模式：本例不需要任何写操作，最安全
        max_turns=5,             # 限制最大轮数，防止跑飞
    )

    # dump_stream 给出「完整视图」；下面的分支给出「按需提取」。
    async for message in dump_stream(query(prompt=prompt, options=options)):

        # ① 会话初始化
        if isinstance(message, SystemMessage):
            print(f"  → [system] subtype={message.subtype} "
                  f"session_id={message.data.get('session_id')}")

        # ② 助手输出：文本 / 思考 / 工具调用
        elif isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(f"  → [文本] {block.text}")
                elif isinstance(block, ToolUseBlock):
                    print(f"  → [工具调用] {block.name}({block.input})")

        # ③ 工具结果走 UserMessage（tool_result 属于 user 角色）
        elif isinstance(message, UserMessage):
            if isinstance(message.content, list):
                for block in message.content:
                    if isinstance(block, ToolResultBlock):
                        print(f"  → [工具结果] {block.content}")

        # ④ 收尾统计
        elif isinstance(message, ResultMessage):
            print(f"  → [结果] subtype={message.subtype} turns={message.num_turns} "
                  f"耗时={message.duration_ms}ms 费用={message.total_cost_usd}")
            if message.is_error:
                print(f"  → [错误] {message.errors}")


if __name__ == "__main__":
    asyncio.run(main())
```

### 运行

```bash
# 前置：codebuddy 已登录，或 export CODEBUDDY_API_KEY=...
uv add codebuddy-agent-sdk
uv run python cases/01_hello_query.py
```

### 三个要建立的认知

1. **全异步**：SDK 基于 `asyncio`，`query()` 返回 `AsyncIterator[Message]`，不是字符串。必须 `async for`。
2. **消息流是分层结构**：一次查询依次流过 `SystemMessage`（init，含 `session_id`）→ 若干 `AssistantMessage` → 最后一条 `ResultMessage`。`AssistantMessage.content` 是 **ContentBlock 列表**（文本 / 思考 / 工具调用），不是 `message.text`；而**工具结果是 `UserMessage`**——Anthropic 消息格式里 `tool_result` 属于 user 角色，`_message_parser.py` 把 `type: "user"` 解析成 `UserMessage`。把 `ToolResultBlock` 写在 `AssistantMessage` 分支里是最常见的踩坑点（本案例早期版本就犯过）。
3. **收尾看 `ResultMessage`**：`duration_ms`、`num_turns`、`total_cost_usd`、`is_error` / `errors` 都在这里，费用与失败判定靠它。

### 两个先埋伏笔的坑

- `query()` 在**首个 `ResultMessage` 处就停止并关闭子进程**，且会自动注入 `CODEBUDDY_CODE_DISABLE_BACKGROUND_TASKS=1` 禁用后台任务。要收后台完成事件得用 `CodeBuddySDKClient` + `receive_messages()`（案例 4 / 10 讲）。
- 案例里用 `permission_mode="plan"`（只读）最安全；生产别用 `bypassPermissions`（案例 6 讲）。

### 思考题

把 prompt 改成「读一下 pyproject.toml 并说明」，观察 `ToolUseBlock`（`AssistantMessage`）与 `ToolResultBlock`（`UserMessage`）的出现顺序；再把 `permission_mode` 改成 `default` 看行为差异。

---

## 环境信息

| 项 | 值 |
|---|---|
| Python | 3.12.3（`.python-version` 固定） |
| 包管理 | UV，`uv add` / `uv sync` / `uv run` |
| SDK | `codebuddy-agent-sdk==0.3.299` |
| CLI | `/usr/local/bin/codebuddy` |

## 下一步

案例 2：Options 全景与环境隔离 `setting_sources`。
