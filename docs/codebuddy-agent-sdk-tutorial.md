# CodeBuddy Agent SDK 调研与教学案例

> 调研日期：2026-11-06
> 依据：[CodeBuddy CLI SDK 文档](https://www.codebuddy.cn/docs/cli/sdk)，并以 `uv.lock` 锁定的 `codebuddy-agent-sdk` 0.3.299 实测校验
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

1. **Hello, query()** — 消息流、3 类消息、`CodeBuddyAgentOptions` 初见 ← 案例 01
2. Options 全景 & 环境隔离 `setting_sources` ← 案例 02
3. 让 Agent 干活：工具白名单、`ToolUseBlock`、只读分析项目 ← 案例 03
4. 多轮对话：`CodeBuddySDKClient` + `receive_response` ← 案例 04
5. 会话持久化：`session_id` / `resume` / `continue_conversation` ← 案例 05
6. 权限控制：`can_use_tool` 白名单与危险命令拦截 ← 案例 06
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
uv sync
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

## 案例 02 · Options 全景与环境隔离（setting_sources）

难度：★★☆☆☆
目标：认识 `CodeBuddyAgentOptions` 这个「唯一控制面」，掌握字段分组，并理解 SDK 默认不加载任何文件系统配置的设计。

可运行文件：[`cases/02_options_and_settings.py`](../cases/02_options_and_settings.py)。本例只发起 1 次真实模型调用，并复用 [`cases/_common/sdk_helpers.py`](../cases/_common/sdk_helpers.py) 的 `dump_message()`。

### 知识点：28 个字段

以 `dataclasses.fields(CodeBuddyAgentOptions)` 实测为准（v0.3.299），按用途分组：

| 分组 | 字段 |
|---|---|
| 运行控制 | `cwd` `permission_mode` `max_turns` `request_timeout_ms` `env` `extra_args` `stderr` `codebuddy_code_path` |
| 工具与权限 | `tools` `allowed_tools` `disallowed_tools` `can_use_tool` `hooks` |
| 模型与推理 | `model` `fallback_model` `system_prompt` `thinking` `effort` `max_thinking_tokens` |
| 会话 | `session_id` `resume` `continue_conversation` `fork_session` `persist_session` |
| 扩展 | `agents` `mcp_servers` `include_partial_messages` |
| 环境隔离 | `setting_sources` |

两个容易混的字段：

- `tools`：**从根本上限定内置工具集**（`tools=[]` 禁用全部内置工具，仅留 MCP 工具）。
- `allowed_tools`：只是**自动批准**白名单，不缩小工具集。

`system_prompt` 传普通 `str` 会替换默认系统提示词，传 `AppendSystemPrompt(append=...)` 是追加——通常推荐追加。

### 环境隔离 `setting_sources`

SDK 默认 `None`，源码里映射为 CLI 参数 `--setting-sources none`（见 `codebuddy_agent_sdk/transport/subprocess.py:293-300`）：

| 值 | 加载位置 |
|---|---|
| `None`（默认） | 不加载任何文件配置 |
| `["user"]` | `~/.codebuddy/settings.json`、`~/.codebuddy/CODEBUDDY.md` |
| `["project"]` | `.codebuddy/settings.json`、`CODEBUDDY.md` |
| `["local"]` | `.codebuddy/settings.local.json`、`CODEBUDDY.local.md` |
| `["user","project","local"]` | 全部加载，接近 CLI 行为 |

默认不加载 Settings / Memory / MCP / Subagent / Commands / Rules / Skills。设计意图是**可预测、可复现**：应用行为完全由代码里的 `options` 决定，不受某台机器上配置文件的影响。

### 代码

```python
"""案例 02 · Options 全景与环境隔离（setting_sources）"""

from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path

from codebuddy_agent_sdk import (
    AppendSystemPrompt,
    CodeBuddyAgentOptions,
    ResultMessage,
    SystemMessage,
    query,
)
from _common.sdk_helpers import dump_message

# 教学分组：字段名以 dataclasses.fields() 实测为准，避免照抄文档漏字段
GROUPS: dict[str, list[str]] = {
    "运行控制": ["cwd", "permission_mode", "max_turns", "request_timeout_ms",
             "env", "extra_args", "stderr", "codebuddy_code_path"],
    "工具与权限": ["tools", "allowed_tools", "disallowed_tools",
              "can_use_tool", "hooks"],
    "模型与推理": ["model", "fallback_model", "system_prompt",
              "thinking", "effort", "max_thinking_tokens"],
    "会话": ["session_id", "resume", "continue_conversation",
           "fork_session", "persist_session"],
    "扩展": ["agents", "mcp_servers", "include_partial_messages"],
    "环境隔离": ["setting_sources"],
}


def show_all_fields() -> None:
    """列出当前安装版本的全部字段，并按用途分组。"""
    names = {f.name for f in dataclasses.fields(CodeBuddyAgentOptions)}
    print(f"=== CodeBuddyAgentOptions 共 {len(names)} 个字段 ===")
    grouped: set[str] = set()
    for group, fields in GROUPS.items():
        valid = [n for n in fields if n in names]
        grouped.update(valid)
        print(f"  [{group}] {', '.join(valid)}")
    extra = sorted(names - grouped)
    if extra:
        print(f"  [本版本新增/未归类] {', '.join(extra)}")
    print()


def demo_typical_options() -> CodeBuddyAgentOptions:
    """组装一份「完全由代码控制」的配置并打印。"""
    options = CodeBuddyAgentOptions(
        cwd=str(Path(__file__).resolve().parent.parent),
        permission_mode="plan",                       # 只读，最安全
        max_turns=5,                                  # 防止跑飞
        tools=["Read", "Glob", "Grep"],               # 限制内置工具集（init.tools 仍列全部）
        allowed_tools=["Read", "Glob", "Grep"],       # 这三个自动批准，不再逐次询问
        system_prompt=AppendSystemPrompt(              # 追加（而非替换）系统提示词
            append="回答一律使用简体中文，且尽量简短。"
        ),
        setting_sources=None,                         # 默认：不加载任何文件配置
    )
    print("=== 一份典型配置（只看显式设置过的字段）===")
    for key, value in dataclasses.asdict(options).items():
        if value not in (None, [], {}, False, ""):
            print(f"  {key:<24} = {value!r}")
    print()
    return options


async def show_init_snapshot(options: CodeBuddyAgentOptions) -> None:
    """发一次查询，从 init 消息读回 CLI 实际生效的配置。

    这比「让模型回答问题」可靠：init 是 CLI 启动时发出的确定性快照。
    """
    print("=== 从 SystemMessage(init) 读回生效配置 ===")
    async for message in query(prompt="只回复 ok", options=options):
        if isinstance(message, SystemMessage) and message.subtype == "init":
            for key in ("cwd", "model", "permissionMode", "apiKeySource",
                        "output_style", "mcp_servers", "tools", "slash_commands"):
                value = message.data.get(key)
                if isinstance(value, list) and len(value) > 6:
                    value = f"{value[:6]} ... (共 {len(value)} 项)"
                print(f"  {key:<16} = {value}")
        elif isinstance(message, ResultMessage):
            dump_message(message, max_len=260)        # 复用案例 01 的公共模块


def explain_setting_sources() -> None:
    print("\n=== setting_sources：环境隔离 ===")
    print("  默认 None                      -> SDK 传 --setting-sources none")
    print("  ['user'] / ['project'] / ['local'] -> 分别加载对应位置的配置")
    print("  ['user','project','local']     -> 全部加载（接近 CLI 行为）")
    print("  映射见 codebuddy_agent_sdk/transport/subprocess.py:293-300")
    print()
    print("  配置源：")
    print("    user     ~/.codebuddy/settings.json, ~/.codebuddy/CODEBUDDY.md")
    print("    project  .codebuddy/settings.json,  CODEBUDDY.md")
    print("    local    .codebuddy/settings.local.json, CODEBUDDY.local.md")
    print("  默认不加载 Settings / Memory / MCP / Subagent / Commands / Rules / Skills。")
    print()
    print("  验证陷阱：不要用「模型能否复述 CODEBUDDY.md 里的内容」来测试")
    print("  setting_sources —— 模型可能用 Read/Grep 直接读到文件，结论不可靠。")
    print("  更稳妥的是看 init 快照的 mcp_servers / slash_commands，或审视 CLI 参数。")
    print("  设计意图本就是：所需行为显式写进 options，不依赖机器上的文件配置。")


async def main() -> None:
    show_all_fields()
    options = demo_typical_options()
    await show_init_snapshot(options)
    explain_setting_sources()


if __name__ == "__main__":
    asyncio.run(main())
```

### 运行与实测输出

```bash
uv run python cases/02_options_and_settings.py
```

init 快照片段（实测）：

```
=== 从 SystemMessage(init) 读回生效配置 ===
  cwd              = /home/sunqi/src/blenderModel
  model            = hy4free
  permissionMode   = plan
  apiKeySource     = copilot.tencent.com
  output_style     = default
  mcp_servers      = []
  tools            = ['Agent', 'Read', 'Write', 'Edit', 'Bash', 'PowerShell'] ... (共 66 项)
  slash_commands   = ['add-dir', 'agents', 'approve', 'background', 'bg', 'branch'] ... (共 79 项)
```

`permissionMode = plan` 和 `cwd` 说明 options 确实生效。注意 `init.tools` 列出的仍是**全部可用工具**，并不会因为设了 `tools=["Read","Glob","Grep"]` 而缩短。

### 验证陷阱（实测）

不要用「模型能否复述 `CODEBUDDY.md` 里的代号」来验证 `setting_sources`：本环境实测里，默认与 `["project"]` 两边都答出了代号——模型可以用 `Read` / `Grep` 直接读到 cwd 里的文件，与配置加载无关；init 快照的 `mcp_servers` / `slash_commands` 在两种设置下也未拉开差异。要验证应直接审视 CLI 启动参数，或按设计意图把所需行为显式写进 `options`，不依赖文件配置。

### 思考题

把 `setting_sources` 改成 `["user","project","local"]`，对比 init 快照里 `mcp_servers` 的变化；再把 `system_prompt` 从 `AppendSystemPrompt` 换成普通 `str`，观察回答风格差异。

---

## 案例 03 · 让 Agent 干活：工具白名单与只读分析

难度：★★★☆☆
目标：让 Agent 真正调用工具完成任务，看清 `ToolUseBlock` → `ToolResultBlock` 的完整轨迹，并验证工具白名单是否生效。

可运行文件：[`cases/03_readonly_analysis.py`](../cases/03_readonly_analysis.py)。本例发起 1 次真实模型调用（内部含多个工具轮次），复用 [`cases/_common/sdk_helpers.py`](../cases/_common/sdk_helpers.py) 的 `brief()` 与 `dump_message()`。

### 知识点：三种工具控制字段

| 字段 | 作用 | 层次 |
|---|---|---|
| `tools` | **从根本上限定内置工具集**；`tools=[]` 禁用全部内置工具（仅留 MCP 工具） | 改模型可见的工具 schema，最彻底 |
| `allowed_tools` | 自动批准白名单（支持模式匹配），**不缩小**工具集 | 权限层 |
| `disallowed_tools` | 禁止使用的工具（支持模式匹配） | 权限层 |

本例用 `tools=["Read","Glob","Grep"]` 加 `permission_mode="plan"`（只读）做双保险。`can_use_tool` 细粒度回调留到案例 6。

### 消息流的完整形状（本例实测）

```
SystemMessage(init)                     ← data.tools 是 CLI 全部可用工具（66 项）
AssistantMessage [TextBlock]            ← "三个只读操作互不依赖，并行执行"
AssistantMessage [ToolUseBlock × 3]     ← 一轮并行发出 3 个工具调用
UserMessage      [ToolResultBlock × 3]  ← 工具结果统一以 user 角色回来
AssistantMessage [TextBlock]            ← 最终汇总
ResultMessage                           ← 统计
```

三个要点：

- `ToolUseBlock` 在 `AssistantMessage`，`ToolResultBlock` 在 `UserMessage`（案例 01 修正过的坑）。
- 模型可以**一轮发多个 `ToolUseBlock` 并行执行**，结果一起回来——别假设「一次调用对应一次结果」。
- **`init.tools` 不代表模型实际可用集**：实测设了 `tools=["Read","Glob","Grep"]` 后 init 仍列 66 项，但实际调用只有那 3 个。验证白名单要看实际调用的工具名，不是看 init 快照。

### 代码

```python
"""案例 03 · 让 Agent 干活：工具白名单与只读分析"""

from __future__ import annotations

import asyncio
from pathlib import Path

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
from _common.sdk_helpers import brief, dump_message

PROJECT = Path(__file__).resolve().parent.parent
WHITELIST = {"Read", "Glob", "Grep"}

PROMPT = """请只读分析当前项目，完成三件事：
1. 用 Glob 列出 cases/ 下所有 .py 文件；
2. 用 Read 读取 pyproject.toml，告诉我依赖的 SDK 及版本要求；
3. 用 Grep 找出 cases/ 下 import 了 ToolUseBlock 的文件。
最后用简短中文汇总。不要修改任何文件。"""


async def main() -> None:
    options = CodeBuddyAgentOptions(
        cwd=str(PROJECT),
        permission_mode="plan",          # 只读模式，双保险
        max_turns=8,                     # 工具轮次上限，防止跑飞
        tools=["Read", "Glob", "Grep"],  # 只暴露这 3 个内置工具
    )

    used: list[str] = []
    step = 0
    print(f"=== 白名单 tools={sorted(WHITELIST)} ===\n")

    async for message in query(prompt=PROMPT, options=options):

        # ① init：注意 tools 字段是 CLI 全部可用工具，不代表模型实际可用集
        if isinstance(message, SystemMessage) and message.subtype == "init":
            all_tools = message.data.get("tools") or []
            print(f"[init] CLI 全部可用工具 {len(all_tools)} 项（不代表模型可用集）")

        # ② 助手消息：ToolUseBlock 在这里；最终文本也在这里
        elif isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    step += 1
                    used.append(block.name)
                    print(f"  {step}. [调用] {block.name}({brief(block.input)})")
                elif isinstance(block, TextBlock) and block.text.strip():
                    print(f"\n[回答] {block.text.strip()}")

        # ③ 工具结果走 UserMessage（tool_result 属于 user 角色）
        elif isinstance(message, UserMessage) and isinstance(message.content, list):
            for block in message.content:
                if isinstance(block, ToolResultBlock):
                    print(f"       [结果] {brief(block.content)}")

        # ④ 收尾统计
        elif isinstance(message, ResultMessage):
            dump_message(message, max_len=400)

    print("\n=== 白名单校验 ===")
    print(f"  实际调用: {used}")
    print(f"  越界工具: {sorted(set(used) - WHITELIST) or '无'}")
    print(f"  结论: {'通过 ✓' if set(used) <= WHITELIST else '未通过 ✗'}")


if __name__ == "__main__":
    asyncio.run(main())
```

### 运行与实测输出

```bash
uv run python cases/03_readonly_analysis.py
```

```
=== 白名单 tools=['Glob', 'Grep', 'Read'] ===
[init] CLI 全部可用工具 66 项（不代表模型可用集）
[回答] 三个只读操作互不依赖，并行执行。
  1. [调用] Glob({'pattern': 'cases/**/*.py'})
  2. [调用] Read({'file_path': '.../pyproject.toml'})
  3. [调用] Grep({'pattern': 'import.*ToolUseBlock|from.*ToolUseBlock', ...})
       [结果] [{'type': 'text', 'text': '[".../01_hello_query.py",".../0…(共 271 字符)
       [结果] [{'type': 'text', 'text': '   1→[project]\n   2→name = "blendermodel"…(共 209 字符)
       [结果] [{'type': 'text', 'text': '[".../03_readonly_analysis.py"]'}]
[回答] ## 只读分析汇总 …（略）
=== 白名单校验 ===
  实际调用: ['Glob', 'Read', 'Grep']
  越界工具: 无
  结论: 通过 ✓
```

### 三个值得注意的观察

1. **白名单确实生效**：`init.tools` 是 66 项，但实际调用严格落在 3 个工具内。所以判断 `tools` 是否生效要看调用轨迹，不能看 init。
2. **`num_turns=11` 而 `max_turns=8`**：两者计数口径不同（`num_turns` 把工具结果轮次也算进去），别拿它们直接对比来推断「是否超限」。
3. **工具结果要自己核对**：模型自己写的 Grep 正则只匹配了单行 `import`，漏掉了案例 01 里多行 `from ... import (...)` 形式的 `ToolUseBlock`，所以汇总里只报了 1 个文件。Agent 给出的检索结论不等于事实——这正是做只读分析时该复核的地方。

### 思考题

- 把 `tools` 改成 `[]`，看模型还能不能完成任务、会怎么回应。
- 去掉 `tools` 但保留 `permission_mode="plan"`，观察模型会不会改用 `Bash`。
- 把 `max_turns` 调到 2，看被截断时的 `ResultMessage.subtype` 与 `errors`。

> 案例 04 正好用上了 `tools=[]`——不过目的不同：那里是为了**阻止模型读历史 transcript**，避免把「搜到的信息」误当成「会话上下文」。

---

## 案例 04 · 多轮对话：CodeBuddySDKClient

难度：★★★☆☆
目标：理解 `query()` 是一次性单轮，多轮交互必须用 `CodeBuddySDKClient`；用 A/B 对比看到会话是否共享。

可运行文件：[`cases/04_multi_turn.py`](../cases/04_multi_turn.py)。本例发起 4 次真实模型调用，复用 `brief()`。

### 知识点：`query()` vs `CodeBuddySDKClient`

| | `query()` | `CodeBuddySDKClient` |
|---|---|---|
| 会话 | 每次调用都是**新会话** | 一个 Client 内**共享同一会话** |
| 轮次 | 单轮 | 多轮（`query()` 可反复调用） |
| 轮次结束 | 首个 `ResultMessage` 处停止并关闭子进程 | `receive_response()` 收到 `ResultMessage` 就 return，子进程保持 |
| 适用 | 一次性任务、批处理 | 交互式应用、需要上下文的连续对话 |

Client 的主要方法（源码 `client.py`）：

| 方法 | 说明 |
|---|---|
| `connect(prompt=None)` | 建立连接；`async with` 会自动调用 |
| `query(prompt, session_id="default")` | 发送本轮用户消息 |
| `receive_response()` | 消费到 `ResultMessage` 自动停；出错抛 `ExecutionError` |
| `receive_messages()` | **不自动停**，需自己 break；后台任务通知要靠它（案例 10） |
| `disconnect()` | 断开；`async with` 退出时自动调用 |
| `interrupt()` / `set_model()` / `set_permission_mode()` / `mcp_server_status()` | 运行期动态控制 |

### 代码

```python
"""案例 04 · 多轮对话：CodeBuddySDKClient"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable

from codebuddy_agent_sdk import (
    AssistantMessage,
    CodeBuddyAgentOptions,
    CodeBuddySDKClient,
    SystemMessage,
    TextBlock,
    query,
)
from _common.sdk_helpers import brief

MARKER = "ORION-9"
PROMPT1 = f"请记住这个代号：{MARKER}。只回复「已记住」。"
PROMPT2 = "我刚才让你记住的代号是什么？只回答代号本身，不要解释。"


def make_options() -> CodeBuddyAgentOptions:
    # 每次新建，避免多个 query 共享同一个 options 对象。
    # tools=[] 禁用内置工具：否则模型会去 Read/Grep 历史 transcript，
    # 把「跨文件搜到的信息」误当成「会话上下文」（见下方验证陷阱）。
    return CodeBuddyAgentOptions(permission_mode="plan", max_turns=10, tools=[])


async def collect(stream: AsyncIterable) -> tuple[str, str | None]:
    """消费一轮消息，返回 (助手文本, init 消息里的 session_id)。"""
    chunks: list[str] = []
    session_id: str | None = None
    async for message in stream:
        if isinstance(message, SystemMessage) and message.subtype == "init":
            session_id = message.data.get("session_id")
        elif isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    chunks.append(block.text)
    return "".join(chunks).strip(), session_id


async def demo_query() -> None:
    """A：两次独立 query —— 各自新会话，第二轮答不出代号。"""
    print("=== A：两次独立 query() ===")
    sids: list[str | None] = []
    answers: list[str] = []
    for prompt in (PROMPT1, PROMPT2):
        text, sid = await collect(query(prompt=prompt, options=make_options()))
        sids.append(sid)
        answers.append(text)
        print(f"  {brief(prompt, 34)} -> {text!r}  session={sid}")
    print(f"  不同会话数: {len(set(sids))}  → 两次 query 各自开新会话")
    print(f"  第二轮答出代号 {MARKER}: {MARKER in answers[1]}\n")


async def demo_client() -> None:
    """B：同一个 Client 内两轮 —— 共享会话，第二轮答得出代号。"""
    print("=== B：CodeBuddySDKClient 两轮 ===")
    sids: list[str | None] = []
    answers: list[str] = []
    # async with 自动调用 connect() / disconnect()
    async with CodeBuddySDKClient(options=make_options()) as client:
        for prompt in (PROMPT1, PROMPT2):
            await client.query(prompt)                          # 发送本轮消息
            text, sid = await collect(client.receive_response())  # 收到 ResultMessage 自动停
            sids.append(sid)
            answers.append(text)
            print(f"  {brief(prompt, 34)} -> {text!r}  session={sid}")
        print(f"  [动态控制] 当前权限模式: {client.get_permission_mode()}")
    same = sids[0] is not None and sids[0] == sids[1]
    print(f"  不同会话数: {len(set(sids))}  → 两轮共享同一会话: {same}")
    print(f"  第二轮答出代号 {MARKER}: {MARKER in answers[1]}\n")


def explain() -> None:
    print("=== 要点 ===")
    print("  · query() 每次都是新会话；多轮必须靠 Client，或靠 resume（案例 5）。")
    print("  · async with CodeBuddySDKClient(...) 自动 connect() / disconnect()。")
    print("  · receive_response() 收到 ResultMessage 就 return（出错抛 ExecutionError）；")
    print("    receive_messages() 不自动停，需自己 break，用于后台任务通知（案例 10）。")
    print("  · Client 还有 interrupt() / set_model() / set_permission_mode() / mcp_server_status()。")
    print()
    print("=== 验证陷阱（实测）===")
    print(f"  若不加 tools=[]，A 组两次独立 query 的第二轮「也会」答出 {MARKER}。")
    print("  实测 grep 发现该代号出现在 7 个 transcript 文件里——query() 默认")
    print("  persist_session=True，对话写入 ~/.codebuddy/projects/<slug>/<session_id>.jsonl，")
    print("  模型用 Grep/Read 就能读到，于是「答出代号」被误当成「保持了上下文」。")
    print("  所以本例用 tools=[] 关掉读取能力，并以 session_id 作为确定性判据：")
    print("  A 组 2 个会话，B 组 1 个会话。")


async def main() -> None:
    await demo_query()
    await demo_client()
    explain()


if __name__ == "__main__":
    asyncio.run(main())
```

### 运行与实测输出

```bash
uv run python cases/04_multi_turn.py
```

```
=== A：两次独立 query() ===
  请记住这个代号：ORION-9… -> '已记住'                    session=01a1b5fd-…f80
  我刚才让你记住的代号是什么？… -> '当前对话中没有您让我记住的代号。'  session=01a1b5fe-…020
  不同会话数: 2  → 两次 query 各自开新会话
  第二轮答出代号 ORION-9: False

=== B：CodeBuddySDKClient 两轮 ===
  请记住这个代号：ORION-9… -> '已记住'                    session=01a1b5ff-…d49
  我刚才让你记住的代号是什么？… -> 'ORION-9'             session=01a1b5ff-…d49
  [动态控制] 当前权限模式: plan
  不同会话数: 1  → 两轮共享同一会话: True
  第二轮答出代号 ORION-9: True
```

两条判据同时成立：**A 组 2 个 session_id 且答不出代号，B 组 1 个 session_id 且答得出**。

### 验证陷阱（实测）

这是本系列里第二次踩到同一类坑（第一次在案例 02）。最初版本没有加 `tools=[]`，结果 A 组两次独立 `query()` 的第二轮**也答出了 ORION-9**，看似「上下文跨会话保持了」。

静态检查给出了原因：`grep -rl ORION-9 ~/.codebuddy/projects/home-sunqi-src-blenderModel/` 命中 **7 个文件**，其中就包含第一轮那个会话的 transcript。因为 `query()` 默认 `persist_session=True`，每轮对话都落盘；模型拿到完整工具集后会用 `Grep` / `Read` 去翻这些历史文件，于是「搜到的信息」被误当成「记住的信息」。反复运行还会让 transcript 越堆越多、搜索越来越慢（一次复跑直接卡在第二轮超时）。

解法有两点，缺一不可：

- **关掉读取能力**：`tools=[]` 禁用全部内置工具（案例 03 讲过的字段），模型只能依据本轮上下文作答。
- **用确定性判据**：`session_id` 来自 `SystemMessage(init)`，不依赖模型回答内容。A 组 2 个、B 组 1 个，这才是「会话是否共享」的直接证据。

顺带一提，案例 03 的思考题「把 `tools` 改成 `[]` 会怎样」在这里有了答案：不是让模型干不了活，而是可以主动用它来隔离信息源。

### 思考题

- 把 `tools=[]` 去掉再跑一次，复现 A 组第二轮答出代号的陷阱。
- 把 `receive_response()` 换成 `receive_messages()`，观察它为什么不会自己停下来。
- 在 B 组两轮之间调用 `await client.set_model(...)` 或 `await client.interrupt()`，看看动态控制的效果。

---

## 案例 05 · 会话持久化：session_id / resume / continue_conversation

难度：★★★☆☆
目标：拿到 `session_id`、确认会话落盘，并用 `resume` 与 `continue_conversation` 把上下文带回来。

可运行文件：[`cases/05_session_persistence.py`](../cases/05_session_persistence.py)。本例发起 4 次真实模型调用。

### 知识点：会话字段与 CLI 参数

SDK 的 `CodeBuddyAgentOptions` 里与会话相关的字段，最终都映射成 CLI 参数（源码 `transport/subprocess.py:259-273`）：

| 字段 | CLI 参数 | 作用 |
|---|---|---|
| `resume` | `--resume <sid>` | 恢复指定 ID 的会话 |
| `continue_conversation` | `--continue` | 加载**当前目录最近**的对话 |
| `fork_session` | `--fork-session` | 从会话分叉出新分支 |
| `persist_session=False` | `--no-session-persistence` | 不写 transcript，只留内存 |
| `session_id` | `--session-id <id>` | 指定会话 ID（有格式校验） |

`session_id` 有两个来源，实测**完全一致**：`SystemMessage(init).data["session_id"]` 和 `ResultMessage.session_id`。会话落盘位置为 `~/.codebuddy/projects/<cwd 的 / 换成 ->/<session_id>.jsonl`（案例 01 之后已确认过）。

### 代码

```python
"""案例 05 · 会话持久化：session_id / resume / continue_conversation"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from codebuddy_agent_sdk import (
    AssistantMessage,
    CodeBuddyAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    query,
)

MARKER = "VEGA-42"
PROMPT_SET = f"请记住这个代号：{MARKER}。只回复「已记住」。"
PROMPT_ASK = "我刚才让你记住的代号是什么？只回答代号本身，不要解释。"

PROJECT_DIR = Path(__file__).resolve().parent.parent


def transcript_dir(cwd: Path) -> Path:
    """CLI 把 cwd 的 / 换成 - 作为项目目录名（Linux 路径）。"""
    slug = str(cwd).replace("/", "-").lstrip("-")
    return Path.home() / ".codebuddy" / "projects" / slug


def make_options(**overrides: Any) -> CodeBuddyAgentOptions:
    # tools=[] 关掉读取能力：否则模型会去翻历史 transcript，
    # 把「搜到的信息」误当成「恢复的上下文」（案例 04 的验证陷阱）。
    base: dict[str, Any] = dict(
        cwd=str(PROJECT_DIR),
        permission_mode="plan",
        max_turns=10,
        tools=[],
    )
    base.update(overrides)
    return CodeBuddyAgentOptions(**base)


async def ask(prompt: str, **overrides: Any) -> tuple[str, str | None, str | None]:
    """跑一次 query，返回 (助手文本, init.session_id, ResultMessage.session_id)。"""
    chunks: list[str] = []
    init_sid: str | None = None
    result_sid: str | None = None
    async for message in query(prompt=prompt, options=make_options(**overrides)):
        if isinstance(message, SystemMessage) and message.subtype == "init":
            init_sid = message.data.get("session_id")
        elif isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    chunks.append(block.text)
        elif isinstance(message, ResultMessage):
            result_sid = message.session_id
    return "".join(chunks).strip(), init_sid, result_sid


def show(label: str, text: str, sid: str | None, original: str) -> None:
    print(f"  {label}")
    print(f"    回答      = {text!r}")
    print(f"    命中代号  = {MARKER in text}")
    print(f"    session_id= {sid}  (与原会话相同: {sid == original})")


async def main() -> None:
    print("=== 1. 建立会话，取 session_id ===")
    _, init_sid, result_sid = await ask(PROMPT_SET)
    original = result_sid or init_sid or ""
    print(f"  init.session_id   = {init_sid}")
    print(f"  result.session_id = {result_sid}")
    print(f"  两者一致          = {init_sid == result_sid}")
    path = transcript_dir(PROJECT_DIR) / f"{original}.jsonl"
    print(f"  transcript 落盘   = {path.exists()}  {path}")

    print("\n=== 2. continue_conversation=True（当前目录最近的会话）===")
    text, _, sid = await ask(PROMPT_ASK, continue_conversation=True)
    show("紧跟第 1 步执行，--continue 加载最近会话", text, sid, original)

    print("\n=== 3. 不带任何恢复（对照）===")
    text, _, sid = await ask(PROMPT_ASK)
    show("全新会话，无 resume / continue", text, sid, original)

    print("\n=== 4. resume=<sid>（恢复指定会话）===")
    text, _, sid = await ask(PROMPT_ASK, resume=original)
    show("显式恢复到第 1 步的会话", text, sid, original)

    print("\n=== 字段与 CLI 参数映射 ===")
    print("  resume               -> --resume <sid>")
    print("  continue_conversation-> --continue（加载当前目录最近的对话）")
    print("  fork_session         -> --fork-session")
    print("  persist_session=False-> --no-session-persistence")
    print("  session_id           -> --session-id <id>（有格式校验）")


if __name__ == "__main__":
    asyncio.run(main())
```

### 运行与实测输出

```bash
uv run python cases/05_session_persistence.py
```

```
=== 1. 建立会话，取 session_id ===
  init.session_id   = 01a1b663-dd54-771e-8466-56afb75eacb1
  result.session_id = 01a1b663-dd54-771e-8466-56afb75eacb1
  两者一致          = True
  transcript 落盘   = True  ~/.codebuddy/projects/home-sunqi-src-blenderModel/01a1b663-….jsonl

=== 2. continue_conversation=True ===
    回答      = 'VEGA-42'                 命中代号 = True
    session_id= 01a1b663-…  (与原会话相同: True)

=== 3. 不带任何恢复（对照）===
    回答      = '本次对话是你发来的第一条消息…'   命中代号 = False
    session_id= 01a1b664-…  (与原会话相同: False)

=== 4. resume=<sid> ===
    回答      = 'VEGA-42'                 命中代号 = True
    session_id= 01a1b663-…  (与原会话相同: True)
```

### 三个结论

1. **`session_id` 是会话的身份**：`init` 与 `ResultMessage` 两处取值一致；恢复会话（`resume` / `continue`）时 `ResultMessage.session_id` 保持原值不变，而全新会话会拿到新 ID。这比「模型答没答对」可靠得多。
2. **两种恢复都带回了上下文**：`--continue` 续接当前目录最近的对话，`--resume` 精确恢复指定 ID。两者第二轮都答出了代号。
3. **对照组证明不是巧合**：不带任何恢复的调用拿到新 `session_id`，并明确回答「本轮没有记录过代号」。

### 两个必须注意的点

- **仍要 `tools=[]`**。和案例 04 完全一样：不禁用内置工具，模型会用 `Grep` / `Read` 翻到落盘的 transcript，对照组也会「答出代号」，整个实验就失效了。
- **`continue_conversation` 依赖「当前目录最近的对话」**，是多会话/并行环境下最不确定的一个：如果别的进程在同一 `cwd` 又开了会话，它续接的可能不是你想要的那个。需要精确控制时优先用 `resume=<sid>`；本例第 2 步紧跟第 1 步执行，才保证了「最近」指向刚建的会话。

`fork_session` / `persist_session` / `session_id` 本例只列了映射，没有实跑；`persist_session=False` 可以让会话不落盘，正好能从根本上避开上面那个 transcript 干扰。

### 思考题

- 把第 4 步的 `resume` 换成一个不存在的 ID，观察 SDK 抛什么异常、属于 `CodeBuddySDKError` 的哪一支。
- 给所有调用加 `persist_session=False`，再去掉 `tools=[]`，看对照组是否还会被 transcript 干扰。
- 用 `fork_session=True` 配合 `resume=<sid>` 跑一次，对比 `ResultMessage.session_id` 是保持原值还是分叉出新 ID。

---

## 案例 06 · 权限控制：can_use_tool 白名单与危险命令拦截

难度：★★★★☆
目标：掌握运行时权限回调，能改写入参、拦截危险命令、中断会话，并避开「没有回调就自动拒绝」的坑。

可运行文件：[`cases/06_permission_control.py`](../cases/06_permission_control.py)。本例发起 3 次真实模型调用；所有 Bash 命令都是无害的 `echo`，危险命令在工具执行前就被拦截，不会真正运行。

### 知识点：回调签名与三种返回

`can_use_tool` 是**异步**回调（源码 `types.py:79-83`）：

```python
CanUseTool = Callable[
    [str, dict[str, Any], CanUseToolOptions],   # tool_name, input_data, options
    Awaitable[PermissionResult],
]
```

| 返回 | 效果 |
|---|---|
| `PermissionResultAllow(updated_input=...)` | 允许执行；传入的 dict 会**替换**工具入参，可用来改写命令 |
| `PermissionResultAllow()` | 允许，不改入参（安装版 `updated_input` 默认 `None`） |
| `PermissionResultDeny(message=..., interrupt=False)` | 拒绝本次调用，会话继续 |
| `PermissionResultDeny(message=..., interrupt=True)` | 拒绝并**中断整个会话** |

`CanUseToolOptions` 携带 `tool_use_id` / `agent_id` / `suggestions` / `blocked_path` / `decision_reason` 等上下文，可用来做审计或更细的判断。

**权限模式决定回调是否会被触发**（`permission_mode`）：

| 模式 | 行为 |
|---|---|
| `default` | 所有工具操作需确认 → **触发 `can_use_tool`** |
| `acceptEdits` | 自动批准文件编辑，其余仍需确认 |
| `plan` | 仅允许只读工具 |
| `bypassPermissions` | 跳过所有权限检查，回调不会被调用 |

本例统一用 `default` + `tools=["Bash"]`，强制每个工具调用都走权限回调。

### 代码

```python
"""案例 06 · 权限控制：can_use_tool 白名单与危险命令拦截"""

from __future__ import annotations

import asyncio
from typing import Any

from codebuddy_agent_sdk import (
    AssistantMessage,
    CanUseToolOptions,
    CodeBuddyAgentOptions,
    CodeBuddySDKError,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    TextBlock,
    query,
)
from _common.sdk_helpers import brief

READ_ONLY = {"Read", "Glob", "Grep"}
DANGEROUS = ("rm -rf", "sudo", "chmod 777")
MARKER = "APPROVED_BY_CALLBACK"


def log(decision: str, tool: str, detail: str = "") -> None:
    print(f"    [权限] {decision:<4} {tool:<8} {brief(detail, 90)}")


async def allow_and_rewrite(
    tool_name: str,
    input_data: dict[str, Any],
    options: CanUseToolOptions,
):
    """场景 A：只读工具放行；Bash 放行但改写入参；其余拒绝。"""
    if tool_name in READ_ONLY:
        log("允许", tool_name, "只读工具")
        return PermissionResultAllow(updated_input=input_data)

    if tool_name == "Bash":
        command = input_data.get("command", "")
        log("改写", tool_name, f"{command}  ->  echo {MARKER}")
        return PermissionResultAllow(
            updated_input={**input_data, "command": f"echo {MARKER}"}
        )

    log("拒绝", tool_name, "不在白名单")
    return PermissionResultDeny(message=f"{tool_name} 不在允许列表")


async def block_dangerous(
    tool_name: str,
    input_data: dict[str, Any],
    options: CanUseToolOptions,
):
    """场景 B：命中危险关键词就拒绝并中断整个会话。"""
    command = input_data.get("command", "") if tool_name == "Bash" else ""
    if any(word in command for word in DANGEROUS):
        log("拦截", tool_name, command)
        return PermissionResultDeny(
            message=f"危险命令被拦截：{command}",
            interrupt=True,
        )
    log("允许", tool_name, command or str(input_data))
    return PermissionResultAllow(updated_input=input_data)


async def run(label: str, prompt: str, callback: Any) -> None:
    print(f"\n=== {label} ===")
    options = CodeBuddyAgentOptions(
        permission_mode="default",   # 需要确认 → 才会触发 can_use_tool
        max_turns=5,
        tools=["Bash"],              # 只暴露 Bash，强制走权限回调
        can_use_tool=callback,
    )
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock) and block.text.strip():
                        print(f"    [回答] {brief(block.text.strip(), 170)}")
            elif isinstance(message, ResultMessage):
                print(f"    [结果] subtype={message.subtype} "
                      f"is_error={message.is_error} errors={message.errors}")
    except CodeBuddySDKError as exc:
        print(f"    [异常] {type(exc).__name__}: {exc}")


def explain() -> None:
    print("\n=== 要点 ===")
    print("  · 回调签名: async (tool_name, input_data, CanUseToolOptions) -> PermissionResult")
    print("  · PermissionResultAllow(updated_input=...) 可改写入参；省略则不改。")
    print("  · PermissionResultDeny(message=..., interrupt=True) 会中断整个会话；")
    print("    实测表现为 query() 直接抛 ExecutionError（'Permission denied for tool(s): Bash'），")
    print("    而不是返回一条 ResultMessage，调用方必须 try/except。")
    print("  · permission_mode='default' 才会触发回调；'bypassPermissions' 直接跳过检查，")
    print("    'plan' 只允许只读，'acceptEdits' 自动批准文件编辑。")
    print("  · 坑：不提供 can_use_tool 时，SDK 对权限请求一律回 allowed=False")
    print("    （_internal/query.py:434-441），工具不会执行；SDK 因此默认注入")
    print("    CODEBUDDY_DISABLE_AUTO_MEMORY=1，避免 auto-memory 触发 Write 被拒。")
    print("  · 三层分工：tools 限定工具集 → allowed_tools/disallowed_tools 静态过滤")
    print("    → can_use_tool 运行时动态审批。")


async def main() -> None:
    await run(
        "A：白名单 + 改写入参",
        "请调用 Bash 工具执行命令 echo ORIGINAL，然后把输出告诉我。必须使用工具，不要只回答文字。",
        allow_and_rewrite,
    )
    await run(
        "B：危险命令拦截并中断",
        '请调用 Bash 工具执行命令 echo "rm -rf /tmp/case06_nonexistent"，然后把输出告诉我。必须使用工具。',
        block_dangerous,
    )
    await run(
        "C：不提供回调（对照）",
        "请调用 Bash 工具执行命令 echo HELLO，然后把输出告诉我。必须使用工具，不要只回答文字。",
        None,
    )
    explain()


if __name__ == "__main__":
    asyncio.run(main())
```

### 运行与实测输出

```bash
uv run python cases/06_permission_control.py
```

```
=== A：白名单 + 改写入参 ===
    [权限] 改写   Bash     echo ORIGINAL  ->  echo APPROVED_BY_CALLBACK
    [回答] 我执行了命令，但返回的输出与预期不符，我再验证一次。
    [权限] 改写   Bash     echo ORIGINAL  ->  echo APPROVED_BY_CALLBACK
    [回答] 已按你的要求用 Bash 工具执行了 `echo APPROVED_BY_CALLBACK`（两次验证）…
    [结果] subtype=success is_error=False errors=None

=== B：危险命令拦截并中断 ===
    [权限] 拦截   Bash     echo "rm -rf /tmp/case06_nonexistent"
    [异常] ExecutionError: Permission denied for tool(s): Bash

=== C：不提供回调（对照） ===
    [回答] 我已按要求调用了 Bash 工具…都返回同一个错误：No permission handler provided…
    [结果] subtype=success is_error=False errors=None
```

### 四个实测结论

1. **`updated_input` 真的会替换工具入参**：A 场景两次调用都被从 `echo ORIGINAL` 改成 `echo APPROVED_BY_CALLBACK`，模型甚至察觉到输出不符、主动重试了一次并指出「有 hook/回调在改写命令」。这是做命令审计、注入 `set -e` 之类安全前缀的抓手。
2. **`interrupt=True` 不是返回一条消息，而是抛异常**：B 场景 `query()` 直接抛 `ExecutionError: Permission denied for tool(s): Bash`，循环里必须 `try/except CodeBuddySDKError`，否则程序会崩。
3. **不提供回调 = 全部拒绝**：C 场景模型反复尝试都拿到 `No permission handler provided`，工具一次也没执行，但 `ResultMessage` 仍是 `subtype=success`——**不能只看 result 判断工具是否成功**。源码 `_internal/query.py:434-441` 在没有 `can_use_tool` 时直接回 `allowed=False`。SDK 也因此默认注入 `CODEBUDDY_DISABLE_AUTO_MEMORY=1`，避免 auto-memory 触发 `Write` 被拒、破坏会话状态。
4. **三层权限控制的分工**：`tools` 限定「模型能看到哪些工具」→ `allowed_tools` / `disallowed_tools` 做静态过滤 → `can_use_tool` 做运行时动态审批（能改写、能中断、能接人工确认）。生产环境别用 `bypassPermissions`。

### 安全说明

本例故意用 `echo` 承载危险关键词（如 `echo "rm -rf /tmp/case06_nonexistent"`）：既能触发拦截规则，又保证即使回调失效也不会执行任何破坏性命令。`can_use_tool` 在工具**执行前**触发，所以被拒绝的命令根本不会运行。

### 思考题

- 把 B 场景的 `interrupt=True` 改成 `False`，对比 `ResultMessage` 和模型回答的变化。
- 把 `permission_mode` 改成 `bypassPermissions`，观察回调是否还被触发。
- 在回调里打印 `options.suggestions` / `options.decision_reason`，看看 CLI 给了哪些权限建议。

---

## 环境信息

| 项 | 值 |
|---|---|
| Python | 3.12（由 `.python-version` 指定） |
| 包管理 | UV，`uv sync` / `uv run` |
| SDK | 项目约束 `>=0.3.299`，`uv.lock` 锁定 0.3.299 |
| CLI | `/usr/local/bin/codebuddy` |

## 下一步

案例 7：Hook 系统——`PreToolUse` 审计与阻断。
