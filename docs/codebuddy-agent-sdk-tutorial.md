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
7. Hook 系统：`PreToolUse` 审计与阻断 ← 案例 07
8. 自定义子 Agent：`AgentDefinition` ← 案例 08
9. 自定义工具：`@tool` + `create_sdk_mcp_server` / 外部 MCP ← 案例 09
10. 综合实战：批量代码审查 CLI（流式输入、中断、错误处理、成本统计） ← 案例 10

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

## 案例 07 · Hook 系统：PreToolUse 审计与阻断

难度：★★★★☆
目标：拿到 Hook 的类型全貌、用 `PreToolUse` 做执行前审计、用 `decision="block"` 拦截命令、用 `matcher` 限定作用范围，并分清 Hook 层与案例 06 `can_use_tool` 权限层的分工。

可运行文件：[`cases/07_hooks.py`](../cases/07_hooks.py)。本例发起 3 次真实模型调用；所有 Bash 命令均为无害的 `echo`，危险命令在工具执行前被 Hook 拦截，不会真正运行。

### 知识点：Hook 与权限回调的分层

`CodeBuddyAgentOptions.hooks` 的类型是 `dict[HookEvent, list[HookMatcher]] | None`（源码 `types.py:623`）。三块积木：

| 类型 | 定义 | 要点 |
|---|---|---|
| `HookEvent` | `types.py:90-102`，11 个字符串 Literal | `PreToolUse` `PostToolUse` `PostToolUseFailure` `UserPromptSubmit` `Stop` `SubagentStop` `PreCompact` `PostCompact` `Notification` `SubagentStart` `PermissionRequest`；**Python 没有 `HOOK_EVENTS` 常量**，那是 TypeScript 的 |
| `HookMatcher` | `types.py:453-459` | `matcher`（工具名，支持正则；`None` / `"*"` / `""` 匹配全部）、`hooks: list[HookCallback]`、`timeout`（**秒**，TS 是毫秒） |
| `HookCallback` | `types.py:447-450` | `async (hook_input: Any, tool_use_id, context: HookContext) -> HookJSONOutput`，**必须 `async`** |

`HookJSONOutput`（`types.py:435-445`，等于 `SyncHookJSONOutput`）是 TypedDict，键为 `continue_` / `suppressOutput` / `stopReason` / `decision: "block"` / `reason`。注意是 **`continue_`** 不是 `continue`：`_internal/query.py:487-492` 的 `_execute_hook` 会 `await` 回调，并把 `continue_` 改写成控制协议里的 `continue`。常用返回：

| 返回 | 效果 |
|---|---|
| `{"continue_": True}` | 放行 |
| `{"decision": "block", "reason": "..."}` | 阻止本次工具调用（仅 `PreToolUse` 有意义） |
| `{"continue_": False, "stopReason": "..."}` | 停止 |

**注册方式与通道**。`hooks` 不是 CLI 参数：`transport/subprocess.py` 的 `_build_args()` 完全不序列化 `opts.hooks`。它由 `_protocol.py:61-97` 的 `build_hooks_config()` 编成 `{event: [{matcher, hookCallbackIds, timeout}]}`，随 `initialize` 控制请求发给 CLI（`_internal/query.py:91,104`），回调 id 形如 `hook_PreToolUse_0_0`；CLI 再用 `hook_callback` 控制请求回调本地 Python 函数。推论：**程序化 Hook 不受 `setting_sources` 影响**，案例 02 的「SDK 默认不加载文件配置」关不掉它——这是与案例 02 最值得对照的一点。

**分层**（本例实测的 TRACE 顺序）：

```
模型发出 tool_use
  → PreToolUse Hook（可 block / 可用 hookSpecificOutput.updatedInput 改写入参）
  → can_use_tool 权限层（案例 06：PermissionResultAllow / PermissionResultDeny）
  → 工具真正执行
  → ToolResultBlock / PostToolUse
```

实测放行时 `PreToolUse` 会在权限判断前后各触发一次；被 `block` 时只触发一次并直接短路，权限层完全不参与（见结论 2）。

| 维度 | PreToolUse Hook（案例 07） | `can_use_tool`（案例 06） |
|---|---|---|
| 注册 | `options.hooks` | `options.can_use_tool` |
| 触发时机 | 工具执行前，且在权限层之前 | 工具执行前，权限判断时 |
| 拦截 | `{"decision": "block"}` | `PermissionResultDeny(message=...)` |
| 改写入参 | `hookSpecificOutput.updatedInput` | `PermissionResultAllow(updated_input=...)` |
| 中断会话 | `continue_: False` | `interrupt=True` → 抛 `ExecutionError` |
| 依赖 `permission_mode` | 否 | 是（`default` 才触发；`plan` / `bypassPermissions` 会跳过） |
| 被拦后的表现 | 一条 `is_error=True` 的 `ToolResultBlock`，`ResultMessage` 仍是 `success` | `interrupt=True` 时 `query()` 直接抛异常 |
| 通道 | 控制协议 `initialize` | 控制协议 `can_use_tool` 请求 |

**坑速查**：

| 坑 | 表现 | 正确写法 |
|---|---|---|
| 回调写成同步函数 | 被 `_execute_hook` 的 `await` 吞掉，工具像「没反应」 | `async def cb(hook_input, tool_use_id, context)` |
| 写成 `{"continue": True}` | Python 里 `continue` 是关键字，且控制协议的键由 SDK 改写 | `{"continue_": True}` |
| 以为 `setting_sources=None` 能关掉 Hook | Hook 照常触发 | 不注册 `hooks` 才会关闭 |
| `timeout` 按毫秒填 | 超时被放大 1000 倍 | Python 单位是**秒** |
| 以为 `matcher` 省略会不匹配 | 实测 `matcher=None` 匹配全部 | 显式写 `"Bash"` 限定范围 |
| 找 `HOOK_EVENTS` 常量 | Python SDK 里不存在 | 直接写字符串 `"PreToolUse"` |

> `HookCallback` 的首参类型是 `Any`。CLI 文档 `sdk-hooks.md:384-392` 给的输入 schema 是 `{"tool_name", "tool_input": {"command"}}`，但同文件 `:138-139` 的 Python 示例却写成扁平的 `input_data.get("command")`；实测 `raw hook_input` 还额外带 `hook_event_name` / `session_id` / `transcript_path` / `cwd` 等字段。本例的 `hook_command()` 因此兼容两种取法，并在首次回调把原始值打印出来定稿。

### 代码

完整可运行代码见 [`cases/07_hooks.py`](../cases/07_hooks.py)。这里只放最核心的几行示意（省略了日志、打印与权限回调）；下面的实测输出来自完整代码文件。

**① 注册**：`hooks` 是 `dict[HookEvent, list[HookMatcher]]`，事件名是字符串，`matcher` 限定工具：

```python
hooks = {"PreToolUse": [HookMatcher(matcher="Bash", hooks=[guard_cb])]}
```

**② 拦截与放行**：回调必须 `async`；返回 `{"continue_": True}` 放行、`{"decision": "block", ...}` 拦截。`continue_` 由 SDK 改写成控制协议里的 `continue`：

```python
async def guard_cb(hook_input, tool_use_id, context):
    _, command = hook_command(hook_input)
    if any(word in command for word in DANGEROUS):
        return {"decision": "block", "reason": "危险命令被 PreToolUse 拦截"}
    return {"continue_": True}
```

其余部分——`show_hook_types()` 零成本类型自省、`TRACE` 有序日志、`allow_all` 放行型权限回调、`verify()` 三条确定性判据——都在代码文件里。

### 运行与实测输出

```bash
uv run python cases/07_hooks.py
```

```
=== Hook 类型自省（不消耗模型调用）===
  HookEvent（11 种）= PreToolUse, PostToolUse, PostToolUseFailure, UserPromptSubmit, Stop, SubagentStop, PreCompact, PostCompact, Notification, SubagentStart, PermissionRequest
  HookMatcher 字段 = matcher, hooks, timeout
  HookJSONOutput 键 = continue_, suppressOutput, stopReason, decision, reason
  HookCallback = async (hook_input: Any, tool_use_id, context: HookContext)
    -> HookJSONOutput；HookContext 键 = signal
  · Python 里没有 HOOK_EVENTS 常量（那是 TypeScript 的），事件名就是字符串。
  · 键名是 continue_ 不是 continue；_execute_hook 会改写成线上的 continue。
  · HookMatcher.timeout 单位是秒（TypeScript 是毫秒）。

=== A：PreToolUse 执行前审计 ===
    [Hook/PRE] 审计 Bash: echo AUDIT_OK
    [Hook/PRE] raw hook_input = {'hook_event_name': 'PreToolUse', 'session_id': '01a1c0de-767e-7fab-a638-961245c8b713', 'transcript_path': '/Users/sunqi/.codebuddy/projects/Users-sunqi-projects-blenderModel/01a1c0de-767e-7fab-a638-961245c8b713.jsonl', 'cwd': '/Users/sunqi…(共 464 字符)
    [流] 工具调用 Bash {'command': 'echo AUDIT_OK', 'description': 'Execute echo AUDIT_OK and show output'}
    [权限] 放行 Bash（Hook 之后、执行之前）
    [Hook/PRE] 审计 Bash: echo AUDIT_OK
    [流] 工具结果 [{'type': 'text', 'text': 'Stdout: AUDIT_OK\n\nStderr: (empty)\nExit Code: 0\nSignal: (non…(共 95 字符) is_error=False
    [回答] 已执行 `echo AUDIT_OK`，工具输出如下：\n\n```\nAUDIT_OK\n```\n\n- stdout: `AUDIT_OK`\n- stderr: （空）\n- 退出码: `0`
    [结果] subtype=success session_id=01a1c0de-767e-7fab-a638-961245c8b713 is_error=False errors=None
    [判据] hook=2 ToolUseBlock=1 ToolResultBlock=1
    [判据] (a) PreToolUse 先于工具执行：通过 ✓  hook_seq=1 result_seq=5

=== B：decision=block 拦截危险命令 ===
    [Hook/PRE] 拦截 echo "rm -rf /tmp/case07_nonexistent"
    [流] 工具调用 Bash {'command': 'echo "rm -rf /tmp/case07_nonexistent"', 'description': 'Print the string with…(共 97 字符)
    [流] 工具结果 [{'type': 'text', 'text': 'Error: PreToolUse:Bash hook blocked this tool call: 危险命令被 PreTo…(共 139 字符) is_error=True
    [回答] Bash 工具已被调用，但命令被 `PreToolUse:Bash` 钩子拦截，因此没有产生任何输出。\n\n- 实际执行的命令：`echo "rm -rf /tmp/case07_nonexistent"`\n- 结果：`Error: PreToolUse:Bash hook blocked this tool call: 危险命令被 …(共 364 字符)
    [结果] subtype=success session_id=01a1c0de-9d98-7026-80d3-365cc6b24cb2 is_error=False errors=None
    [判据] hook=1 ToolUseBlock=1 ToolResultBlock=1
    [判据] (b) 被拦命令从未执行：通过 ✓  blocked=['chatcmpl-tool-984a6665c0bf3d1f'] 成功执行=[]

=== C：matcher 只匹配 Bash ===
    [流] 工具调用 Read {'file_path': '/Users/sunqi/projects/blenderModel/cases/01_hello_query.py', 'limit': 10}
    [流] 工具结果 [{'type': 'text', 'text': '   1→"""\n   2→案例 01 · Hello, query()\n   3→\n   4→难度：★☆☆☆☆\n  …(共 334 字符) is_error=False
    [Hook/PRE] 命中 matcher=Bash 的回调，tool_name=Bash
    [流] 工具调用 Bash {'command': 'echo MATCH_OK', 'description': 'Print MATCH_OK'}
    [权限] 放行 Bash（Hook 之后、执行之前）
    [Hook/PRE] 命中 matcher=Bash 的回调，tool_name=Bash
    [流] 工具结果 [{'type': 'text', 'text': 'Stdout: MATCH_OK\n\nStderr: (empty)\nExit Code: 0\nSignal: (non…(共 95 字符) is_error=False
    [回答] 已按要求依次使用两个工具：\n\n- **Read** 读取了 `cases/01_hello_query.py` 前 10 行（是「案例 01 · Hello, query()」的文档说明）。\n- **Bash** 执行 `echo MATCH_OK`，命令输出为：\n\n```\nMATCH_OK\n```\n\n退出码 0，标准错…(共 174 字符)
    [结果] subtype=success session_id=01a1c0de-c4e8-7f79-b440-455ad7c72cd1 is_error=False errors=None
    [判据] hook=2 ToolUseBlock=2 ToolResultBlock=2
    [判据] (c) matcher 只作用于 Bash：通过 ✓  非 Bash 工具调用=1 其中命中 Hook=0

=== 要点 ===
  · hooks: dict[HookEvent, list[HookMatcher]]，事件名是字符串，
    Python 没有 HOOK_EVENTS 常量（那是 TypeScript 的）。
  · HookCallback 必须 async，签名 (hook_input, tool_use_id, context)；
    同步函数会被 _execute_hook 的 await 吞掉，异常也会被吞成 continue=False。
  · 返回 {'continue_': True} 放行；{'decision':'block','reason':...} 拦截 PreToolUse；
    'continue_' 由 _internal/query.py:490 改写成线上的 'continue'。
  · matcher 按工具名匹配（支持正则；None/'*'/'' 匹配全部）；timeout 单位是秒。
  · hooks 走进程内控制协议的 initialize 请求，不是 CLI 参数：
    transport/subprocess.py 完全不序列化 opts.hooks，所以 setting_sources=None
    也关不掉程序化 Hook（对照案例 02 的环境隔离）。
  · 分层：tool_use → PreToolUse Hook → can_use_tool 权限层 → 执行 → ToolResultBlock。
    Hook 能 block/改写入参；案例 06 的 can_use_tool 用 PermissionResultDeny/Allow。
  · 坑：不提供 can_use_tool 时 SDK 一律回 allowed=False（案例 06），
    三个场景都挂了放行型回调，工具才会真正执行、Hook 的先后才可观测。
```

### 五个实测结论

1. **`PreToolUse` 确实先于工具执行**：A 场景的 TRACE 顺序是 `hook(seq=1) → ToolUseBlock(2) → 权限(3) → hook(4) → ToolResultBlock(5)`，`hook_seq=1 < result_seq=5`，判据 (a) 通过。Hook 是本地 Python 回调，这条时序不依赖模型回答。
2. **放行的 Bash 调用触发两次 `PreToolUse`，被拦的只触发一次，且权限层完全不参与**：A/C 里每次 Bash 各有 2 条 hook 记录，B 里只有 1 条；B 场景没有出现 `[权限] 放行`。结合放行时「hook → 权限 → hook → 结果」的顺序看，第一次 Hook 在权限判断前、第二次在执行前；一旦第一次就 `block`，整条链直接短路。
3. **`decision: block` 不抛异常**：B 场景拿到的是一条 `is_error=True` 的 `ToolResultBlock`，内容为 `Error: PreToolUse:Bash hook blocked this tool call: 危险命令被 …`，而 `ResultMessage` 仍是 `subtype=success is_error=False errors=None`。这与案例 06 的 `PermissionResultDeny(interrupt=True)` 让 `query()` 直接抛 `ExecutionError` 完全不同。
4. **拦截的判据要看 `is_error`，不能只看有没有 `ToolResultBlock`**：B 场景 `ToolResultBlock=1`，但成功执行集合为空、判据 (b) 通过——命令从未真正运行。这正是 `verify()` 把 `is_error=True` 的结果排除在「已执行」之外的原因；只看「有结果块」会得出相反结论。
5. **`matcher` 按工具名过滤**：C 场景 `tools=["Read","Bash"]`，Read 的 `ToolUseBlock` 一次 Hook 都没触发，2 条 Hook 全是 `tool_name=Bash`，判据 (c) 通过。另外实测 `raw hook_input` 除了 `tool_name` 还带 `hook_event_name` / `session_id` / `transcript_path` / `cwd`，比 CLI 文档给出的 JSON schema 丰富。

### 验证陷阱

- **不要用「模型有没有答对」当判据**（案例 04/05 的教训）。本例 `verify()` 只读本地 `TRACE`：`hook` / `perm` / `stream` 三类带 `seq` 的记录。模型可能不调用工具，所以场景无 `ToolUseBlock` 时打印「跳过断言」而不是硬失败；有工具调用但 Hook 没触发时也会单独提示检查 `matcher`。
- **`HookCallback` 首参是 `Any`**：CLI 文档 `sdk-hooks.md:384-392` 的 JSON schema 是嵌套 `tool_input.command`，同文件 `:138-139` 的 Python 示例却是扁平 `input_data.get("command")`，实测还多出会话上下文字段。别硬编码一种形状——用 `hook_command()` 兼容两种，并首次打印 raw 定稿。
- **别把 `is_error=True` 的 tool_result 当成「命令执行过」**（见结论 4）。
- **回调必须 `async`**：同步函数会被 `_execute_hook` 的 `await` 吞掉，异常也会被吞成 `{"continue": false, "stopReason": str(e)}`（`_internal/query.py:486-494`），表面上看只是「工具没跑」，很难排查。
- **记得挂 `can_use_tool`**：案例 06 的坑在这里同样适用——不提供回调时 SDK 对所有权限请求回 `allowed=False`，放行场景的工具根本不会执行，也就无法用 `ToolResultBlock` 证明 Hook 的先后。本例三个场景都用了放行型 `allow_all`。

### 安全说明

沿用案例 06 的做法，用 `echo` 承载危险关键词（`echo "rm -rf /tmp/case07_nonexistent"`）：既能触发 `guard_cb` 的拦截规则，又保证即使 Hook 失效也不会执行任何破坏性命令。`PreToolUse` 在工具执行前触发，被拦命令根本不会运行；`max_turns=5` 防止模型反复重试跑飞。

### 思考题

- 把 `guard_cb` 的返回改成 `{"continue_": False, "stopReason": "..."}`，对比 `decision: block` 的表现差异。
- 用 `hookSpecificOutput: {"hookEventName": "PreToolUse", "updatedInput": {...}}` 改写命令（CLI 文档 `sdk-hooks.md:474-504`），与案例 06 的 `PermissionResultAllow(updated_input=...)` 对照。
- 在同一个 `hooks` 里加 `PostToolUse`，观察它相对 `ToolResultBlock` 的时序。
- 把 `permission_mode` 改成 `bypassPermissions`，看 `can_use_tool` 与 `PreToolUse` 分别是否还触发（对照案例 06 的思考题）。
- `matcher` 写成正则（如 `"Bash|Write"`）或 `"*"`，观察命中范围的变化。

---

## 案例 08 · 自定义子 Agent：AgentDefinition

难度：★★★★☆
目标：认识 `AgentDefinition` 五个字段与 `agents` 的注册方式、定义多个专用子代理并让主 Agent 显式委派、用 `tools` 白名单划分能力边界、用「不注册 `agents`」作对照。

可运行文件：[`cases/08_subagents.py`](../cases/08_subagents.py)。本例发起 3 次真实模型调用。

### 知识点：AgentDefinition 与委派链路

`CodeBuddyAgentOptions.agents` 的类型是 `dict[str, AgentDefinition] | None`（`types.py:642`），**key 就是子代理名**。`AgentDefinition`（`types.py:109-118`）是 dataclass，五个字段：

| 字段 | 类型 | 作用 |
|---|---|---|
| `description` | `str` | 子代理用途的自然语言描述；写 `MUST BE USED` / `use PROACTIVELY` 能提高被主动选用的概率 |
| `prompt` | `str` | 子代理的系统提示词 |
| `tools` | `list[str]`，可省略 | **省略 → 继承主线程全部工具**；显式列出才成为白名单 |
| `disallowed_tools` | `list[str]`，可省略 | 黑名单；线上 key 是 `disallowedTools`（`_protocol.py:34-36`） |
| `model` | `str`，可省略 | 省略 / `inherit` / `default` 都不强制具体模型，走正常解析链 |

**注册与链路**：

```
options.agents = {"case-reader": AgentDefinition(...), ...}
  → build_agents_config() 用 asdict 序列化、丢掉 None 字段（_protocol.py:41-58）
  → 放进 initialize 控制请求的 agents 字段（_internal/query.py:107）
  → CLI 注册为候选子代理
  → 主 Agent 调用 Agent 工具，subagent_type 填 key
  → Spawned successfully（后台任务，返回 agent_id）
  → 子代理在自己的上下文里用 tools 白名单干活
  → 结果经 TaskOutput / 后台通知回传
```

和案例 07 的 `hooks` 一样，`agents` **不是 CLI 参数**：`transport/subprocess.py` 不序列化它，它走进程内控制协议。所以 `setting_sources=None` 关不掉程序化子代理——这正是与案例 02 的对照点：文件型子代理放在 `.codebuddy/agents/` 下，要靠 `setting_sources` 显式加载；`options.agents` 始终生效。

委派靠主 Agent 发起 `Agent` 工具调用，入参形如 `{"description", "prompt", "subagent_type": "case-reader", "name": "case-reader"}`（本例实测）。可以在 prompt 里点名子代理做**显式调用**，也可以靠 `description` 让模型自动选用。

**坑速查**：

| 坑 | 表现 | 正确做法 |
|---|---|---|
| 想从 `SystemMessage(init).data` 里找 `agents` | 实测 `init.data` 根本没有这个字段 | 用 `ToolUseBlock(name="Agent")` 的 `subagent_type` 判断 |
| 以为 `ResultMessage` 到了子代理就完成 | 主流程可能在子代理还在 `running` 时就结束 | 用 `TaskOutput` 轮询 / 后台任务通知 |
| 以为 `tools` 默认是白名单 | 省略时继承主线程全部工具 | 显式列出才限制 |
| 忘了 `can_use_tool` | 子代理的工具请求也被 SDK 一律拒绝 | 提供放行型回调（案例 06 的坑） |
| 以为 `setting_sources` 能关掉程序化 `agents` | 照常生效 | 不注册 `agents` 才关闭 |

### 代码

完整可运行代码见 [`cases/08_subagents.py`](../cases/08_subagents.py)。这里只放注册部分的最小示意（省略了消息流收集、权限回调与 `verify()`）：

```python
agents = {
    "case-reader": AgentDefinition(
        description="只读分析助手。MUST BE USED when asked to inspect case files.",
        prompt="你是只读分析助手，只读取文件并给出简短结论。",
        tools=["Read", "Glob", "Grep"],   # 省略则继承主线程全部工具
    ),
    "case-counter": AgentDefinition(
        description="计数助手。MUST BE USED when asked to count lines.",
        prompt="你是计数助手，用 wc -l 统计行数，只回报数字。",
        tools=["Bash"],
    ),
}
options = make_options(agents=agents)
```

主 Agent 侧的委派由模型发起（不是我们手写）：调用 `Agent` 工具并填 `subagent_type="case-reader"`。判据、对照场景与 `explain()` 要点都在代码文件里，配合下面的实测输出阅读。

### 运行与实测输出

```bash
uv run python cases/08_subagents.py
```

```
=== Agent 类型自省（不消耗模型调用）===
  AgentDefinition 字段 = description, prompt, tools, disallowed_tools, model
  agents: dict[str, AgentDefinition] | None（types.py:642）
  · key 是子代理名；主 Agent 通过 Agent 工具的 subagent_type 指定。
  · tools 省略 → 继承主线程全部工具；指定则成为白名单。
  · disallowed_tools 在线上叫 disallowedTools（_protocol.py:34-36）。
  · agents 与 hooks 一样走 initialize 控制协议，setting_sources 不影响。
  已注册子代理 = ['case-counter', 'case-reader']

=== A：注册并显式委派 case-reader ===
    [init] keys=['__timestamp', 'apiKeySource', 'cwd', 'mcp_servers', 'model', 'output_style', 'permissionMode', 'session_id', 'slash_commands', 'subtype', 'tools', 'type', 'uuid']
    [流] 工具调用 Agent {'description': '读取案例并说明难度星级', 'prompt': '请读取 cases/01_hello_query.py 文件，并说明它的难度星级（难度几颗星）。请给出你的判断依据。', 'subagent_type': 'case-reader', 'name': 'case-reader'}
    [流] 工具结果 [{'type': 'text', 'text': 'Spawned successfully.\nagent_id: case-reader@_auto_01a1c3ef-6fbd-787e-a884-d2198979ba26\nname…(共 313 字符) is_error=False
    [init] keys=['__timestamp', 'apiKeySource', 'cwd', 'mcp_servers', 'model', 'output_style', 'permissionMode', 'session_id', 'slash_commands', 'subtype', 'tools', 'type', 'uuid']
    [回答] 已委派给 `case-reader` 子代理。等待它的结果。
    [流] 工具调用 TaskOutput {'task_id': 'agent-bf4a47d7-b915-438b-a774-fd9216455942', 'block': True}
    [流] 工具结果 [{'type': 'text', 'text': 'Task ID: agent-bf4a47d7-b915-438b-a774-fd9216455942\nStatus: running\n\nThis is a team member…(共 253 字符) is_error=False
    [流] 工具调用 Glob {'pattern': '**/cases/01_hello_query.py'}
    [流] 工具结果 [{'type': 'text', 'text': '["/Users/sunqi/projects/blenderModel/cases/01_hello_query.py"]'}] is_error=False
    [流] 工具调用 Read {'file_path': '/Users/sunqi/projects/blenderModel/cases/01_hello_query.py'}
    [流] 工具调用 Glob {'pattern': '**/cases/*.py'}
    [流] 工具结果 [{'type': 'text', 'text': '   1→"""\n   2→案例 01 · Hello, query()\n   3→\n   4→难度：★☆☆☆☆\n   5→目标：跑通一次最简单的 SDK 查询，看懂消息流里到底…(共 3074 字符) is_error=False
    [流] 工具结果 [{'type': 'text', 'text': '["/Users/sunqi/projects/blenderModel/cases/01_hello_query.py","/Users/sunqi/projects/blenderM…(共 540 字符) is_error=False
    [回答] 子代理 `case-reader` 正在后台读取文件并分析，完成后会把结果通过消息返回。我会在收到结果后向你汇报难度星级及判断依据。
    [结果] subtype=success session_id=01a1c3ef-6fbd-787e-a884-d2198979ba26 is_error=False errors=None
    [判据] ToolUseBlock=5 其中 Agent 工具=1
    [判据] (a) 委派到 case-reader：通过 ✓  命中=1

=== B：委派 case-counter（tools 白名单只给 Bash） ===
    [init] keys=['__timestamp', 'apiKeySource', 'cwd', 'mcp_servers', 'model', 'output_style', 'permissionMode', 'session_id', 'slash_commands', 'subtype', 'tools', 'type', 'uuid']
    [流] 工具调用 Agent {'description': '统计文件行数', 'prompt': '请使用 Bash 工具执行命令 `wc -l cases/07_hooks.py`，统计该文件的行数，并把命令输出的行数结果报告给我。只执行这一条命令即可。', 'subagent_type': 'case-counter', 'name': '…(共 174 字符)
    [流] 工具结果 [{'type': 'text', 'text': 'Spawned successfully.\nagent_id: case-counter@_auto_01a1c3ef-a39c-7e7c-93d3-d094d3aee9b6\nnam…(共 315 字符) is_error=False
    [init] keys=['__timestamp', 'apiKeySource', 'cwd', 'mcp_servers', 'model', 'output_style', 'permissionMode', 'session_id', 'slash_commands', 'subtype', 'tools', 'type', 'uuid']
    [回答] 已委派给 `case-counter` 子代理，等待其返回统计结果。
    [流] 工具调用 TaskOutput {'task_id': 'agent-e0c1cf22-2481-456b-93e8-ccf77aa22a9f', 'block': True}
    [流] 工具结果 [{'type': 'text', 'text': 'Task ID: agent-e0c1cf22-2481-456b-93e8-ccf77aa22a9f\nStatus: running\n\nThis is a team member…(共 253 字符) is_error=False
    [流] 工具调用 Bash {'command': 'wc -l cases/07_hooks.py', 'description': 'Count lines in cases/07_hooks.py'}
    [权限] 放行 Bash
    [init] keys=['__timestamp', 'apiKeySource', 'cwd', 'mcp_servers', 'model', 'output_style', 'permissionMode', 'session_id', 'slash_commands', 'subtype', 'tools', 'type', 'uuid']
    [流] 工具结果 [{'type': 'text', 'text': 'Stdout:      299 cases/07_hooks.py\n\nStderr: (empty)\nExit Code: 0\nSignal: (none)'}] is_error=False
    [回答] 子代理 `case-counter` 已在后台运行，正在执行 `wc -l cases/07_hooks.py`。我会在它完成后收到通知并汇报结果（按要求，我没有自己执行该命令）。
    [结果] subtype=success session_id=01a1c3ef-a39c-7e7c-93d3-d094d3aee9b6 is_error=False errors=None
    [判据] ToolUseBlock=3 其中 Agent 工具=1
    [判据] (b) 委派到 case-counter：通过 ✓  命中=1

=== C：不注册 agents（对照） ===
    [init] keys=['__timestamp', 'apiKeySource', 'cwd', 'mcp_servers', 'model', 'output_style', 'permissionMode', 'session_id', 'slash_commands', 'subtype', 'tools', 'type', 'uuid']
    [流] 工具调用 Read {'file_path': '/Users/sunqi/projects/blenderModel/cases/01_hello_query.py'}
    [流] 工具调用 Glob {'pattern': 'cases/**'}
    [流] 工具结果 [{'type': 'text', 'text': '   1→"""\n   2→案例 01 · Hello, query()\n   3→\n   4→难度：★☆☆☆☆\n   5→目标：跑通一次最简单的 SDK 查询，看懂消息流里到底…(共 3074 字符) is_error=False
    [流] 工具结果 [{'type': 'text', 'text': '["/Users/sunqi/projects/blenderModel/cases/01_hello_query.py","/Users/sunqi/projects/blenderM…(共 606 字符) is_error=False
    [流] 工具调用 Glob {'pattern': '**/*.md'}
    [流] 工具调用 Read {'file_path': '/Users/sunqi/projects/blenderModel/cases/_common/sdk_helpers.py'}
    [流] 工具结果 [{'type': 'text', 'text': '["/Users/sunqi/projects/blenderModel/README.md","/Users/sunqi/projects/blenderModel/docs/code…(共 152 字符) is_error=False
    [流] 工具结果 [{'type': 'text', 'text': '   1→"""SDK 消息流调试／展示公共函数。\n   2→\n   3→放在 cases/_common/ 下，与编号案例分开。案例按路径运行时 cases/ 会进入\n   4→…(共 2474 字符) is_error=False
    [流] 工具调用 Read {'file_path': '/Users/sunqi/projects/blenderModel/README.md'}
    [流] 工具调用 Grep {'pattern': '难度', 'path': '/Users/sunqi/projects/blenderModel', 'output_mode': 'content', '-n': True}
    [流] 工具结果 [{'type': 'text', 'text': '   1→# blenderModel\n   2→\n   3→CodeBuddy Agent SDK 的调研笔记与由浅入深的 Python 教学案例。\n   4→\n   5→> …(共 2856 字符) is_error=False
    [流] 工具结果 [{'type': 'text', 'text': '["/Users/sunqi/projects/blenderModel/docs/codebuddy-agent-sdk-tutorial.md:57:难度：★☆☆☆☆","/User…(共 1687 字符) is_error=False
    [流] 工具调用 Read {'file_path': '/Users/sunqi/projects/blenderModel/cases/08_subagents.py'}
    [流] 工具结果 [{'type': 'text', 'text': '   1→"""\n   2→案例 08 · 自定义子 Agent：AgentDefinition\n   3→\n   4→难度：★★★★☆\n   5→目标：\n   6→  1. …(共 9772 字符) is_error=False
    [流] 工具调用 Read {'file_path': '/Users/sunqi/projects/blenderModel/docs/codebuddy-agent-sdk-tutorial.md', 'offset': 40, 'limit': 50}
    [流] 工具结果 [{'type': 'text', 'text': '  40→## 三、课程大纲（由浅入深）\n  41→\n  42→1. **Hello, query()** — 消息流、3 类消息、`CodeBuddyAgentOptions` 初…(共 1706 字符) is_error=False
    [回答] **难度：★☆☆☆☆（1/5 星，最低档）**，见 `cases/01_hello_query.py:4`，教程文档 `docs/codebuddy-agent-sdk-tutorial.md:57` 也一致。\n\n为什么是这个星级：\n\n- 它是课程大纲 10 步里的第 1 步（"Hello, query()"），目标只是跑通一次最…(共 539 字符)
    [结果] subtype=success session_id=01a1c3ef-d6e9-77cb-ad77-b62d14ece801 is_error=False errors=None
    [判据] ToolUseBlock=8 其中 Agent 工具=0
    [判据] (c) 未注册时不会委派到自定义子代理：通过 ✓  命中=0

=== 要点 ===
  · agents: dict[str, AgentDefinition] | None；key 是子代理名，
    主 Agent 用 Agent 工具的 subagent_type 指定要委派给谁。
  · AgentDefinition(description, prompt, tools, disallowed_tools, model)：
    description 里写 'MUST BE USED' 能提高被主动选用的概率。
  · tools 省略 → 继承主线程全部工具；指定 → 白名单。
    disallowed_tools 在线上被映射成 disallowedTools（_protocol.py）。
  · model 省略 / 'inherit' / 'default' 都不强制具体模型。
  · agents 与 hooks 一样走 initialize 控制协议（_internal/query.py:107），
    不是 CLI 参数；setting_sources=None 关不掉它。
  · 与案例 02 的对照：文件型子代理放在 .codebuddy/agents/ 下，
    需要 setting_sources 才会加载；程序化 agents 始终生效。
  · 坑：不提供 can_use_tool 时 SDK 一律回 allowed=False（案例 06）。
    子代理的工具请求也走同一个回调，所以本例挂了放行型 allow_all。
```

### 五个实测结论

1. **注册是否生效，判据是 `Agent` 工具的 `subagent_type`，不是 `init.data`**：实测 `SystemMessage(init).data` 的 keys 里根本没有 `agents`（只有 `__timestamp` / `apiKeySource` / `cwd` / `mcp_servers` / `model` / `output_style` / `permissionMode` / `session_id` / `slash_commands` / `subtype` / `tools` / `type` / `uuid`），所以代码里 `if "agents" in data` 一次也没打印。A/B 场景各出现 1 次 `Agent` 工具调用，入参 `{"description", "prompt", "subagent_type": "case-reader", "name": "case-reader"}`，判据 (a)(b) 都通过。
2. **显式委派能稳定命中指定子代理**：`description` 里写 `MUST BE USED`，配合 prompt 点名 `subagent_type`，两个不同的 key 分别被选中，说明 `dict` 里多个 `AgentDefinition` 是各自独立生效的。
3. **子代理默认后台 spawn，主 `query()` 可能在它完成前就返回**：`Agent` 工具返回 `Spawned successfully. agent_id: case-reader@_auto_...`，模型随后用 `TaskOutput(block=True)` 只拿到 `Status: running`，主流程就返回 `subtype=success`，最终回答是「正在后台…我会在收到结果后向你汇报」。**不能把 `ResultMessage` 当成「子代理已完成」**——要拿最终报告得继续 `TaskOutput` 轮询或接后台任务通知。这是本例最容易踩的坑。
4. **`tools` 白名单划分了能力边界，且子代理的工具调用会出现在父消息流里**：`case-counter` 定义成 `tools=["Bash"]`，实测主流里出现 `[流] 工具调用 Bash {'command': 'wc -l cases/07_hooks.py'}`、`[权限] 放行 Bash`，随后 `299 cases/07_hooks.py` 的结果块也回来了。案例 06 的 `can_use_tool` 对子代理同样生效，所以本例挂了放行型回调。另外 A/B 场景流里出现多条 `SystemMessage(init)`，是子代理独立会话的痕迹。
5. **不注册 `agents` 时无法委派到自定义子代理**：C 场景问同样的问题，`Agent 工具=0`，主 Agent 自己用 Read / Glob / Grep 完成，判据 (c) 通过。程序化 `agents` 来自 `options` 而非文件配置，与案例 02 的 `setting_sources` 正好对照。

### 验证陷阱

- **不要用 `init.data` 判断注册**（见结论 1），也不要靠模型「有没有答对」当判据（案例 04/05 的教训）。本例 `verify()` 只读本地收集的 `ToolUseBlock`，找 `name == "Agent"` 且 `subagent_type` 命中注册名。
- **不要把 `ResultMessage(subtype=success)` 当成子代理已完成**（见结论 3）。
- **对照场景不是严格同 prompt**：C 为了不把自定义子代理名喂给模型，改成了不点名的问法；它证明的是「未注册时不会出现 `case-reader` / `case-counter` 的委派」，不是「同 prompt 下的行为差异」。
- **`tools` 省略会继承主线程全部工具**，别误以为是白名单；`model` 省略 / `inherit` / `default` 也都不强制具体模型。
- **记得挂 `can_use_tool`**：案例 06 的坑在这里同样适用，而且子代理的工具请求也走同一个回调。

### 思考题

- 把 `AgentDefinition.tools` 整个去掉，观察子代理是否继承主线程全部工具。
- 用 `model="lite"` / `"inherit"` 观察子代理的模型解析链。
- 改用 `disallowed_tools` 做黑名单，对照线上 key `disallowedTools`。
- 针对结论 3：用 `TaskOutput` 轮询到 `completed`，或接后台任务通知，真正把子代理的最终报告取回来。
- 在 `setting_sources=["project"]` 下放一个 `.codebuddy/agents/*.md` 文件型子代理，与 `options.agents` 对比优先级（案例 02 的延伸）。

---

## 案例 09 · 自定义工具：@tool + create_sdk_mcp_server

难度：★★★★☆
目标：认识 `@tool` / `create_sdk_mcp_server` / `mcp_servers` 三个 API 与 `CallToolResult` 返回格式、定义进程内自定义工具并让模型调用、用 `input_schema` 的两种写法定义参数、用「不注册 `mcp_servers`」作对照。

可运行文件：[`cases/09_custom_tools.py`](../cases/09_custom_tools.py)。本例发起 3 次真实模型调用；自定义工具只做加法和只读行数统计，不启动任何外部进程。

### 知识点：进程内 MCP 与外部 MCP

三个 API（`codebuddy_agent_sdk` 顶层导出）：

| API | 签名 | 作用 |
|---|---|---|
| `@tool` | `tool(name, description, input_schema)` | 装饰 `async def f(args: dict)`，给函数挂上 `_tool_definition` |
| `create_sdk_mcp_server` | `(name, version="1.0.0", tools=None)` | 返回 `McpSdkServerConfig`，即 `{"type": "sdk", "name", "server": SdkMcpServer}` |
| `mcp_servers` | `dict[str, McpServerConfig]` 或 `str` 或 `Path`（`types.py:609`） | 注册到 `options`；传字符串/路径时表示外部 `--mcp-config` 文件 |

`input_schema` 两种写法（`@tool` 内部由 `_convert_schema` 统一成 JSON Schema）：

| 写法 | 例子 | 效果 |
|---|---|---|
| 简单类型映射 | `{"a": int, "b": int}` | 自动转 `{"type":"object","properties":{"a":{"type":"integer"},...}}`，**所有参数自动 required** |
| JSON Schema | `{"properties": {"filename": {"type":"string","description":"..."}}, "required":["filename"]}` | 可加 `description` / `enum` / `default` 等 |

工具函数必须返回 `CallToolResult`，**不是裸字符串**：

```python
{"content": [{"type": "text", "text": "42"}], "isError": False}
```

注意是驼峰 **`isError`**，不是消息流 `ToolResultBlock` 的 `is_error`。

**链路**：

```
@tool(...) 装饰 async 函数
  → create_sdk_mcp_server(name, tools=[...])
      得到 {"type":"sdk","name":...,"server": SdkMcpServer 对象}
  → options.mcp_servers = {"case-tools": config}
  → transport 把 type=="sdk" 的项从 --mcp-config 里剥离（subprocess.py:113-145）
  → initialize 控制请求带上 sdkMcpServers: ["case-tools"]
  → CLI 用 mcp_message 控制请求回调本地 server.handle_message（:173-204）
  → 我们的 async 函数在本进程里执行
```

`McpSdkServerConfig` 里含一个 Python 对象，**无法 JSON 序列化**，所以它不可能走 `--mcp-config`。这是与案例 07 `hooks`、案例 08 `agents` 一脉相承的第三种「走控制协议」的配置，同样不受 `setting_sources` 影响。

| 维度 | 进程内 SDK MCP（本例） | 外部 MCP |
|---|---|---|
| 配置 | `create_sdk_mcp_server(...)` 的返回值 | `{"type":"stdio","command":...}` / `http` / `sse` / `remote` |
| 子进程 | 不起 | 需要 `command` + `args` 起服务 |
| 通道 | `initialize` 的 `sdkMcpServers` + `mcp_message` 控制请求 | `--mcp-config` JSON |
| 额外依赖 | 无 | 需要可用的 MCP server 程序 |
| 配置文件 | 不需要 | 传 `str` / `Path` 指向配置文件 |

**工具全名**是 `mcp__<server>__<tool>`。实测有个容易踩的细节：server 名 `case-tools` 里的连字符会变成下划线，注册出来的是 **`mcp__case_tools__add`**。`allowed_tools` / `can_use_tool` 里必须用这个全名，写短名 `add` 匹配不上。

**坑速查**：

| 坑 | 表现 | 正确做法 |
|---|---|---|
| 工具函数返回裸字符串 | CLI 收到非法 `CallToolResult` | `{"content":[{"type":"text","text":...}]}` |
| 把 `isError` 写成 `is_error` | 错误分支不生效 | 驼峰 `isError` |
| `allowed_tools` 用短名 | 匹配不上，权限仍被问 | 用全名 `mcp__case_tools__add` |
| 忘了 `can_use_tool` | MCP 工具被 SDK 一律拒绝 | 提供放行型回调（案例 06） |
| 多个 query 复用同一个 server 实例 | transport 被覆盖 | 每次 `build_server()` 新建（案例 04） |
| 以为要写 MCP 配置文件 | 白费功夫 | 程序化 `mcp_servers` 直接生效 |

### 代码

完整可运行代码见 [`cases/09_custom_tools.py`](../cases/09_custom_tools.py)。这里只放最核心的几行示意（省略了本地打点、消息流收集与 `verify()`）：

```python
@tool("add", "把两个整数相加，返回它们的和。", {"a": int, "b": int})
async def add(args: dict) -> dict:
    return {"content": [{"type": "text", "text": str(int(args["a"]) + int(args["b"]))}]}

server = create_sdk_mcp_server(name="case-tools", tools=[add])
options = make_options(mcp_servers={"case-tools": server})
```

第二个工具 `count_case_lines` 用 JSON Schema 写法、并做了防目录穿越；两个工具都在函数内部往 `TOOL_HITS` 打点，这是本例的确定性判据。三个场景与 `explain()` 要点都在代码文件里。

### 运行与实测输出

```bash
uv run python cases/09_custom_tools.py
```

```
=== 工具类型自省（不消耗模型调用）===
  tool(name: 'str', description: 'str', input_schema: 'dict[str, Any]') -> 'Callable[[F], F]'
  create_sdk_mcp_server(name: 'str', version: 'str' = '1.0.0', tools: 'list[Callable[..., Any]] | None' = None) -> 'McpSdkServerConfig'
  mcp_servers: dict[str, McpServerConfig] | str | Path（types.py:609）
  CallToolResult 键 = content, isError（注意是 isError，不是 is_error）
  McpSdkServerConfig 键 = type, name, server, description, defer_loading
  · @tool 的 input_schema 支持简单类型映射与 JSON Schema 两种写法。
  · 返回必须是 {"content": [{"type":"text","text": ...}]}，不是裸字符串。
  · create_sdk_mcp_server 返回的 dict 里含 SdkMcpServer 对象，不能 JSON 序列化；
    SDK 把它从 --mcp-config 剥离，改走 initialize 的 sdkMcpServers。
  已注册 SDK MCP server = case-tools  tools=['add', 'count_case_lines']

=== A：用 add 工具计算 17 + 25 ===
    [init] mcp_servers=[{'name': 'case-tools', 'status': 'connected'}]
    [流] 工具调用 mcp__case_tools__add {'a': 17, 'b': 25}
    [权限] 放行 mcp__case_tools__add
    [init] mcp_servers=[{'name': 'case-tools', 'status': 'connected'}]
    [流] 工具结果 [{'type': 'text', 'text': '[{"type":"text","text":"42"}]'}] is_error=False
    [回答] 使用 add 工具计算结果：**17 + 25 = 42**
    [结果] subtype=success session_id=01a1c41a-3812-7567-9f87-4b10e9b2fda2 is_error=False errors=None
    [判据] 本地工具被调用=1 ToolUseBlock=1
    [判据] (a) add(17, 25) 在本地执行并返回 42：通过 ✓  hits=[{'tool': 'add', 'args': {'a': 17, 'b': 25}, 'result': 42}]
    [判据] 本轮工具名=['mcp__case_tools__add']

=== B：用 count_case_lines 工具统计行数 ===
    [init] mcp_servers=[{'name': 'case-tools', 'status': 'connected'}]
    [流] 工具调用 mcp__case_tools__count_case_lines {'filename': '05_session_persistence.py'}
    [权限] 放行 mcp__case_tools__count_case_lines
    [init] mcp_servers=[{'name': 'case-tools', 'status': 'connected'}]
    [流] 工具结果 [{'type': 'text', 'text': '[{"type":"text","text":"05_session_persistence.py: 119 行"}]'}] is_error=False
    [回答] 使用 `count_case_lines` 工具统计结果：`05_session_persistence.py` 共 **119 行**。
    [结果] subtype=success session_id=01a1c41a-5cf0-78bd-840a-94768afceef7 is_error=False errors=None
    [判据] 本地工具被调用=1 ToolUseBlock=1
    [判据] (b) count_case_lines 在本地执行：通过 ✓  hits=[{'tool': 'count_case_lines', 'args': {'filename': '05_session_persistence.py'}, 'result': 119}]
    [判据] 本轮工具名=['mcp__case_tools__count_case_lines']

=== C：不注册 mcp_servers（对照） ===
    [init] mcp_servers=[]
    [回答] 42
    [结果] subtype=success session_id=01a1c41a-90eb-772e-a3d1-4182e236342f is_error=False errors=None
    [判据] 本地工具被调用=0 ToolUseBlock=0
    [判据] (c) 未注册时自定义工具从未被调用：通过 ✓  hits=0

=== 要点 ===
  · @tool(name, description, input_schema) 装饰 async def f(args: dict)。
    input_schema 两种写法：{a: int} 简单映射，或 {"properties":..., "required":...}。
  · create_sdk_mcp_server(name, version, tools) 返回 McpSdkServerConfig；
    把它放进 options.mcp_servers = {server_name: config}。
  · CallToolResult = {"content": [{"type":"text","text": ...}], "isError": bool}；
    注意是驼峰 isError，不是 ToolResultBlock 的 is_error。
  · 进程内 SDK MCP vs 外部 MCP：外部要 stdio/http/sse/remote 配置和子进程；
    SDK 内嵌不需要起进程，走 initialize 的 sdkMcpServers + mcp_message 控制请求
    （transport/subprocess.py:113-204），所以也没法用 --mcp-config 传。
  · 工具全名是 mcp__<server>__<tool>；allowed_tools / can_use_tool 用全名。
  · 坑：不提供 can_use_tool 时 SDK 一律回 allowed=False（案例 06），
    MCP 工具也逃不掉，所以本例挂了放行型 allow_all。
  · 对照案例 07/08：hooks / agents / SDK MCP 都走控制协议，
    setting_sources=None 关不掉它们。
```

### 五个实测结论

1. **`init.data["mcp_servers"]` 会报告 SDK server 的连接状态**：注册时是 `[{'name': 'case-tools', 'status': 'connected'}]`，对照场景 C 是 `[]`。这点和案例 08 的 `agents` 不同（那里 `init` 里根本没有 `agents` 字段），是判断 MCP 注册是否生效的现成凭据。
2. **工具全名是 `mcp__case_tools__add`，连字符会变下划线**：server 名 `case-tools` 在工具名里成了 `case_tools`，格式为 `mcp__<server>__<tool>`。实测 `[权限] 放行 mcp__case_tools__add` 说明权限回调拿到的也是这个全名；`allowed_tools` 里必须写全名，写 `add` 匹配不上。
3. **判据来自工具函数内部的本地打点**：`TOOL_HITS` 记下 `add(17,25)=42` 与 `count_case_lines("05_session_persistence.py")=119`，比消息流或模型回答都确定。三个场景全通过：A/B 各 1 次本地调用，C 为 0 次且模型自己算出 42。
4. **工具结果被包了一层字符串**：函数返回 `{"content":[{"type":"text","text":"42"}]}`，但 `ToolResultBlock.content` 是 `[{'type':'text','text':'[{"type":"text","text":"42"}]'}]`——`CallToolResult.content` 被序列化成 JSON 字符串再包一层 text。模型仍能正确读出 42，但自己解析结果块时别假设里面是结构化对象。
5. **`can_use_tool` 对 MCP 工具同样生效**：案例 06 的坑在这里照样成立，不提供回调 SDK 会一律回 `allowed=False`；本例的放行型 `allow_all` 接住了两次调用。`init.mcp_servers` 在每个场景出现两条，是 MCP 握手后再次发出的 init 快照。

### 验证陷阱

- **不要靠模型有没有答对当判据**（案例 04/05 的教训），也不要只依赖消息流；本例在工具函数内部打点 `TOOL_HITS`，函数被本地执行了就是被本地执行了。
- **`CallToolResult` 的键是驼峰 `isError`**，`content` 必须是列表；返回裸字符串不行。
- **`input_schema` 简单类型映射时所有参数自动 required**，想给参数加 `description` 得用 JSON Schema 写法。
- **工具全名含下划线转换**，且每次 `query()` 要新建 server 实例（案例 04 的「不要共享对象」同样适用）。
- **对照场景不是严格同 prompt**：C 为了不把工具名喂给模型，改成了「请计算 17 + 25 等于多少」；它证明的是「未注册时自定义工具不会被调用」，不是同 prompt 下的行为差异。

### 思考题

- 用 `allowed_tools=["mcp__case_tools__add"]` 精确放行，再去掉 `can_use_tool`，看是否还需要权限回调。
- 把 `isError` 写成 `is_error`，观察错误分支是否还生效。
- 用 `{"type":"stdio","command":...,"args":...}` 配一个外部 MCP server，对比 `init.mcp_servers` 与工具全名。
- 手动给 `create_sdk_mcp_server` 返回的 dict 补 `defer_loading`，观察工具发现方式的变化。
- 返回 `ImageContent` 或 `EmbeddedResource`，观察 `ToolResultBlock` 的形态（对应结论 4 的包装行为）。

---

## 案例 10 · 综合实战：批量代码审查 CLI

难度：★★★★★
目标：用 `AsyncIterable[dict]` 做流式输入并认识它「合并成一轮」的行为、用逐文件多轮实现真正的批量审查、用 `receive_messages()` 自己控制停止时机并演示 `interrupt()`、汇总 `num_turns` / `duration_ms` / `total_cost_usd` / token 用量。

可运行文件：[`cases/10_batch_review.py`](../cases/10_batch_review.py)。本例发起 4 次真实模型调用 + 1 个零成本错误演示；可用命令行参数指定待审查文件：`uv run python cases/10_batch_review.py cases/01_hello_query.py ...`。

### 知识点：四个主题与分层

| 主题 | 用到的 API | 落点 |
|---|---|---|
| 流式输入 | `query(AsyncIterable[dict], session_id=...)` | `review_stream()` |
| 中断 | `client.interrupt()` | `collect(..., interrupt_after=1)` |
| 错误处理 | `CodeBuddySDKError` 异常树 / `ResultMessage.is_error` / 文件级跳过 | `scene_errors()` / `scene_batch()` |
| 成本统计 | `num_turns` / `duration_ms` / `total_cost_usd` / `usage` | `summarize()` |

**流式输入的 envelope**（`client.py:88-105`、`_internal/query.py:146-169`）：每个 dict 是一条 stream-json 的 user 消息，`session_id` 由 `query(..., session_id=...)` 统一补齐，不用自己填。

```json
{
  "type": "user",
  "session_id": "...",
  "message": {"role": "user", "content": "..."},
  "parent_tool_use_id": null
}
```

| | `receive_messages()` | `receive_response()` |
|---|---|---|
| 停止 | **不自动停**，必须自己 break | 到 `ResultMessage` / `ErrorMessage` 自动返回 |
| 错误 | 只给一条 `ErrorMessage` | `is_error` 时抛 `ExecutionError` |
| 适用 | 后台任务通知、需要精细控制 | 常规一轮对话 |

所以 `collect()` 准备了**三层停止兜底**：① 遇 `ResultMessage` / `ErrorMessage` break；② 消息上限 `limit`（A/B 80、C 40）；③ `asyncio.timeout(90)` 墙钟超时——中断后流可能一直挂着，光有上限不够。

**错误处理三层**：文件级 `resolve_files()` 跳过不存在的路径 → 每轮 `try/except CodeBuddySDKError` 让单文件失败不打断整批 → 汇总里展示 `ResultMessage.is_error` / `errors`。

| 成本字段 | 含义 |
|---|---|
| `num_turns` | 本轮对话轮数 |
| `duration_ms` / `duration_api_ms` | 墙钟耗时 / API 耗时 |
| `total_cost_usd` | 费用（**本环境实测恒为 0.0**） |
| `usage.input_tokens` / `output_tokens` | token 用量 |
| `is_error` / `errors` | 失败判定 |

**坑速查**：

| 坑 | 表现 | 正确做法 |
|---|---|---|
| 用流式输入做逐个独立审查 | 连续多条 user message 被合并成一轮，只处理了一个 | 逐文件 `query(str)` 多轮 |
| `receive_messages()` 不 break | 流一直挂着 | 三层兜底 |
| 中断后立刻 `disconnect()` | 收不到收尾消息与 `ResultMessage` | 继续收到 `ResultMessage` 再退出 |
| 只看 `total_cost_usd` | 本环境全 0，无法区分任务 | 看 turns / tokens / duration |
| 既没 `allowed_tools` 也没 `can_use_tool` | 工具被一律拒绝（案例 06） | `allowed_tools` 静态放行或挂回调 |
| 单文件异常没兜住 | 整批中断 | 每轮单独 try/except |

### 代码

完整可运行代码见 [`cases/10_batch_review.py`](../cases/10_batch_review.py)。这里只放最核心的两处（省略了 `collect()` 的三层兜底、汇总与 `explain()`）：

```python
# ① 流式输入：一次投递 N 条 user message（注意会被合并成一轮）
async def review_stream(paths):
    for i, path in enumerate(paths, 1):
        yield {"type": "user",
               "message": {"role": "user", "content": f"【审查任务 {i}】{review_prompt(path)}"},
               "parent_tool_use_id": None}

await client.query(review_stream(files), session_id="batch-review")

# ② 真正批量：同一个 Client 内逐文件多轮，各轮独立收 ResultMessage
for path in files:
    await client.query(review_prompt(path))
    stats = await collect(client)     # collect 用 receive_messages() 自己 break
```

`collect()` 的三层停止兜底、`interrupt()` 的触发时机、四条 `ResultMessage` 的汇总与零成本错误演示都在代码文件里。

### 运行与实测输出

```bash
uv run python cases/10_batch_review.py
```

```
=== API 自省（不消耗模型调用）===
  CodeBuddySDKClient: connect / query / receive_messages /
    receive_response / interrupt / set_model / disconnect
  query(prompt: str | AsyncIterable[dict], session_id='default')
    → 传异步可迭代对象就是「流式输入」，逐条写 stdin。
  receive_messages() 不自动停，必须自己 break（案例 04 :534）。
  receive_response() 到 ResultMessage 自动停；is_error 时抛 ExecutionError。
  ResultMessage 统计字段 = num_turns, duration_ms, duration_api_ms,
    total_cost_usd, usage(input_tokens/output_tokens), is_error, errors
  异常树 = CodeBuddySDKError → CLIConnectionError / CLINotFoundError /
    CLIStartupError / CLIJSONDecodeError / ProcessError / ExecutionError /
    AuthenticationError

=== A：流式输入（AsyncIterable[dict]）===
  一次投递 2 条审查任务
    [流] 工具调用 Read {'file_path': '/Users/sunqi/projects/blenderModel/cases/03_readonly_analysis.py'}
    [回答] 最严重的问题在第 91–94 行：白名单校验只比对模型实际调用的工具名，一旦 Agent 未调用任何工具（或调用被拦截/报错）导致 `used` 为空时，`set(used) <= WHITELIST` 恒成立而误报「通过 ✓」，且校验依据是硬编码的 `WHITELIST` 而非 `options`…(共 174 字符)
    [判据] 投递=2 工具调用=1 收到消息=10
    [判据] (a) 流式输入全部送达且拿到 ResultMessage：通过 ✓

=== B：逐文件批量审查 ===
  -- 审查 01_hello_query.py --
    [流] 工具调用 Read {'file_path': '/Users/sunqi/projects/blenderModel/cases/01_hello_query.py'}
    [回答] 最严重的问题是 `permission_mode="plan"`——plan 并非注释所称的「只读模式」，而是让模型只输出计划、不直接作答，会使这个无需任何工具的纯问答拿不到预期的「一句话解释」文本，令演示 `TextBlock` 的分支形同虚设、直接违背案例目标。
  -- 审查 03_readonly_analysis.py --
    [流] 工具调用 Read {'file_path': '/Users/sunqi/projects/blenderModel/cases/03_readonly_analysis.py'}
    [回答] 最严重的是 `permission_mode="plan"`：它与本例「让 Agent 真正调用工具完成任务」的核心目标正面冲突——plan 是让模型只做规划、不执行任务的模式（并非注释误称的「只读模式、双保险」），一次性 `query()` 中模型给出计划后便因无人批准而结束，三项只读分析与汇总不…(共 211 字符)
    [判据] (b) 2/2 个文件独立完成审查：通过 ✓

=== C：中途中断 ===
    [中断] 已调用 client.interrupt()
    [回答] I'll start by exploring the `cases/` directory. Since I need to use the Read tool, let me first try reading the directory path directly.
    [流] 工具调用 Read {'file_path': '/Users/sunqi/projects/blenderModel/cases'}
    [回答] Interrupted by user
    [判据] 收到消息=8 工具调用=1 已中断=True
    [判据] (c) 主动中断被执行：通过 ✓

=== D：错误处理（零成本） ===
    [异常] CLIConnectionError: Not connected. Call connect() first.
    [判据] (d) 未连接调用被异常树兜住：通过 ✓

=== 汇总 ===
  A 流式: turns=6 耗时=29338ms 费用=$0.000000 tokens=10232/2142 is_error=False
  B/01_hello_query.py: turns=6 耗时=62201ms 费用=$0.000000 tokens=10034/4912 is_error=False
  B/03_readonly_analysis.py: turns=12 耗时=77433ms 费用=$0.000000 tokens=32304/11482 is_error=False
  C 中断: turns=5 耗时=14900ms 费用=$0.000000 tokens=4471/1169 is_error=False
  ---- 合计: turns=29 耗时=183872ms 费用=$0.000000 tokens=57041/19705
  跳过的不存在文件 = 无
  · 单文件失败只记入跳过列表，不影响其余文件；成本从各 ResultMessage 累加。
  D 错误演示捕获 = CLIConnectionError: Not connected. Call connect() first.

=== 要点 ===
  · 流式输入：query(AsyncIterable[dict])，每个 dict 是一条 stream-json user 消息；
    连续多条会被 CLI 合并成同一轮，适合「一次投递」，不适合逐个独立审查。
  · 真正的批量：同一个 Client 内逐文件 query(str) 多轮，每轮各自收 ResultMessage；
    单文件 try/except CodeBuddySDKError 兜住，失败不打断整批。
  · receive_messages() 不自动停：自己 break（ResultMessage / ErrorMessage），
    再加消息上限与墙钟超时，否则中断后流会一直挂着。
  · receive_response() 到 ResultMessage 自动停，但 is_error 时会抛 ExecutionError。
  · interrupt() 发控制请求打断当前回合，不靠模型自己停。
  · 成本口径：total_cost_usd / num_turns / duration_ms / usage；逐条累加，
    本环境 total_cost_usd 恒为 0，实际看 turns 与 tokens 更靠谱。
  · 错误处理三层：文件级跳过 → SDK 异常树兜底 → ResultMessage.is_error 检查。
  · tools 限定可见工具，allowed_tools 静态放行，can_use_tool 运行时兜底（案例 03/06）。
```

### 五个实测结论

1. **流式输入把连续多条 user message 合并成一轮**：A 场景本地 `SENT` 记录投递了 2 条，但模型只调用了 1 次 `Read`（`03_readonly_analysis.py`）、只给出 1 个文件的结论，`turns=6`。所以 `AsyncIterable[dict]` 适合「一次投递」，**不适合逐个独立审查**——这是本例第一版实现的真实缺陷，改成逐文件多轮后才修好。
2. **真正的批量要用同一个 Client 内逐文件多轮**：B 场景 2 个文件各自触发 1 次 `Read`、给出不同结论、各自拿到 `ResultMessage`（`turns=6` 与 `turns=12`），判据 (b) `2/2` 通过。这是案例 04「`query()` 每次都是新会话，多轮靠 Client」的直接应用。
3. **`receive_messages()` 不自动停，中断后还会继续来消息**：C 场景 `[中断]` 打印后，流里仍出现 `[回答]`、`[流] 工具调用 Read`、`[回答] Interrupted by user`，最后才到 `ResultMessage`。所以 `collect()` 必须同时具备三个兜底：遇 `ResultMessage`/`ErrorMessage` break、消息上限、`asyncio.timeout(90)` 墙钟超时。
4. **`total_cost_usd` 在本环境恒为 0，成本要看 turns / tokens / 耗时**：四条 `ResultMessage` 的 `total_cost_usd` 全是 `0.0`，汇总 `$0.000000`；真正有区分度的是 `num_turns`（合计 29）、`duration_ms`（合计 183872ms）、`usage`（57041 / 19705 tokens）。批量统计必须逐条累加，不能只看最后一次。
5. **三层错误处理都落地，且 `allowed_tools` 绕开了案例 06 的坑**：文件级 `resolve_files()` 跳过不存在的路径、`scene_batch()` 里 `try/except CodeBuddySDKError` 单文件失败继续、汇总展示 `ResultMessage.is_error`；D 场景零成本用未连接调用触发 `CLIConnectionError: Not connected. Call connect() first.` 验证异常树。全程没有 `[权限]` 打印，说明 `allowed_tools=["Read"]` 静态放行生效，`can_use_tool` 只是没被触发的兜底。

### 验证陷阱

- **别把流式输入当成「批量」**：多条连续 user message 会合并成一轮（结论 1），要逐个独立审查必须用逐文件 `query(str)` 多轮。
- **`receive_messages()` 不自动停**；`receive_response()` 会自动停，但 `is_error` 时抛 `ExecutionError`，两种停止语义别混用。
- **中断后不要立刻 `disconnect()`**，否则收不到 `Interrupted by user` 与收尾的 `ResultMessage`（结论 3）。
- **成本别只看 `total_cost_usd`**（本环境为 0）；批量任务逐条累加 turns / tokens / duration。
- **批量耗时不短**：本例 4 次调用合计约 184 秒，跑之前确认认证可用与预算。
- 模型给出的审查结论只是演示输出，不是本教程对这些文件的定论；判据一律来自本地记录（`SENT`、`stats`、异常对象）。

### 思考题

- 把 B 场景的 `collect()` 换成 `receive_response()`，对比停止行为与异常处理差异。
- 给 `review_prompt` 加结构化输出要求（JSON），把审查结论落成报告文件。
- 去掉 `asyncio.timeout(90)` 只留消息上限，观察中断场景下会不会挂住。
- 用 `set_model()` / `set_permission_mode()` 在批量中途动态切换（案例 04 / 10 的 Client API 延伸）。
- 把案例 06 的 `can_use_tool` 拦截、案例 07 的 Hook 审计加进流水线，做带审计的批量审查。

---

## 环境信息

| 项 | 值 |
|---|---|
| Python | 3.12（由 `.python-version` 指定） |
| 包管理 | UV，`uv sync` / `uv run` |
| SDK | 项目约束 `>=0.3.299`，`uv.lock` 锁定 0.3.299 |
| CLI | `/usr/local/bin/codebuddy` |

## 小结与延伸

案例 01–10 已全部完成，覆盖消息流、Options 与环境隔离、工具白名单、多轮对话、会话持久化、权限回调、Hook、子 Agent、自定义工具（SDK MCP）与批量审查 CLI。

后续可延伸的方向：

- 把案例 10 的审查结论落成结构化报告（JSON / Markdown），接进 CI。
- 用 `CodeBuddySDKClient.set_model()` / `set_permission_mode()` 做运行时切换（案例 04 / 10 的 Client API 还有一半没实跑）。
- 把案例 06 的 `can_use_tool` 拦截、案例 07 的 Hook 审计、案例 08 的子 Agent 组合成带审计的自动化流水线。
- 补上外部 MCP（stdio / http）、`mcp_server_status()`、后台任务通知与 `resume` 的错误分支（见各课思考题）。
