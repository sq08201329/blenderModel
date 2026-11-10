"""
案例 08 · 自定义子 Agent：AgentDefinition

难度：★★★★☆
目标：
  1. 认识 AgentDefinition 五个字段与 agents 的注册方式
  2. 定义多个专用子代理并让主 Agent 显式委派，观察 Agent 工具的 ToolUseBlock
  3. 用 tools 白名单给不同子代理划分能力边界
  4. 用「不注册 agents」作对照，确认程序化子代理来自 options 而非文件配置

本例涉及的 API：
    CodeBuddyAgentOptions(agents=..., can_use_tool=..., permission_mode=...)
    AgentDefinition(description, prompt, tools, disallowed_tools, model)
    query() / SystemMessage / AssistantMessage / ToolUseBlock / ToolResultBlock / ResultMessage

前置条件：同案例 01。本例发起 3 次真实模型调用。

运行：
    uv run python cases/08_subagents.py
"""

from __future__ import annotations

import asyncio
from dataclasses import fields
from pathlib import Path
from typing import Any

from codebuddy_agent_sdk import (
    AgentDefinition,
    AssistantMessage,
    CanUseToolOptions,
    CodeBuddyAgentOptions,
    CodeBuddySDKError,
    PermissionResultAllow,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)
from _common.sdk_helpers import brief

PROJECT_DIR = Path(__file__).resolve().parent.parent
CALLS: list[dict[str, Any]] = []


def show_agent_types() -> None:
    """零成本自省：直接打印类型定义，不消耗模型调用（案例 02/07 的做法）。"""
    print("=== Agent 类型自省（不消耗模型调用）===")
    print("  AgentDefinition 字段 = " + ", ".join(f.name for f in fields(AgentDefinition)))
    print("  agents: dict[str, AgentDefinition] | None（types.py:642）")
    print("  · key 是子代理名；主 Agent 通过 Agent 工具的 subagent_type 指定。")
    print("  · tools 省略 → 继承主线程全部工具；指定则成为白名单。")
    print("  · disallowed_tools 在线上叫 disallowedTools（_protocol.py:34-36）。")
    print("  · agents 与 hooks 一样走 initialize 控制协议，setting_sources 不影响。")


def build_agents() -> dict[str, AgentDefinition]:
    """两个能力边界不同的专用子代理：一个只读、一个只能跑 Bash。"""
    return {
        "case-reader": AgentDefinition(
            description="只读分析助手。MUST BE USED when asked to inspect case files.",
            prompt="你是只读分析助手。只读取文件并给出简短结论，不要修改文件，"
                   "不要执行 Bash 命令。回答控制在三句以内。",
            tools=["Read", "Glob", "Grep"],
        ),
        "case-counter": AgentDefinition(
            description="计数助手。MUST BE USED when asked to count lines of a file.",
            prompt="你是计数助手。用 Bash 的 wc -l 统计指定文件行数，只回报数字。",
            tools=["Bash"],
        ),
    }


async def allow_all(
    tool_name: str,
    input_data: dict[str, Any],
    options: CanUseToolOptions,
):
    """放行型权限回调：避开案例 06「不提供回调 → SDK 一律拒绝」的坑。"""
    print(f"    [权限] 放行 {tool_name}")
    return PermissionResultAllow(updated_input=input_data)


def make_options(**overrides: Any) -> CodeBuddyAgentOptions:
    """每次新建 options，避免多个 query 共享同一个对象（案例 04）。"""
    base: dict[str, Any] = dict(
        cwd=str(PROJECT_DIR),
        permission_mode="default",   # 需要确认 → 才会走 can_use_tool
        max_turns=10,                # 委派子代理会占多个轮次，放宽一点
        can_use_tool=allow_all,      # 不提供 → SDK 一律回 allowed=False（案例 06 的坑）
    )
    # 不设 tools 白名单：让主 Agent 能看到 Agent 工具并自行委派，
    # 子代理自己的工具集由 AgentDefinition.tools 决定。
    # agents 走进程内控制协议的 initialize 请求，不是 CLI 参数，
    # 所以 setting_sources=None 也关不掉（对照案例 02/07）。
    base.update(overrides)
    return CodeBuddyAgentOptions(**base)


def blocks_of(message: Any) -> list[Any]:
    content = getattr(message, "content", None)
    return content if isinstance(content, list) else []


async def run(
    label: str,
    prompt: str,
    scene: str,
    agents: dict[str, AgentDefinition] | None = None,
) -> None:
    print(f"\n=== {label} ===")
    start = len(CALLS)
    overrides: dict[str, Any] = {}
    if agents is not None:
        overrides["agents"] = agents
    options = make_options(**overrides)
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, SystemMessage) and message.subtype == "init":
                data = message.data
                print(f"    [init] keys={sorted(data)}")
                if "agents" in data:
                    print(f"    [init] agents={brief(data['agents'], 200)}")
            elif isinstance(message, (AssistantMessage, UserMessage)):
                for block in blocks_of(message):
                    if isinstance(block, ToolUseBlock):
                        CALLS.append({
                            "scene": scene, "block": "ToolUseBlock",
                            "name": block.name, "id": block.id, "input": block.input,
                        })
                        print(f"    [流] 工具调用 {block.name} {brief(block.input, 160)}")
                    elif isinstance(block, ToolResultBlock):
                        CALLS.append({
                            "scene": scene, "block": "ToolResultBlock",
                            "tool_use_id": block.tool_use_id,
                            "is_error": block.is_error,
                        })
                        print(f"    [流] 工具结果 {brief(block.content, 120)} "
                              f"is_error={block.is_error}")
                    elif (isinstance(block, TextBlock)
                          and isinstance(message, AssistantMessage)
                          and block.text.strip()):
                        print(f"    [回答] {brief(block.text.strip(), 170)}")
            elif isinstance(message, ResultMessage):
                print(f"    [结果] subtype={message.subtype} "
                      f"session_id={message.session_id} "
                      f"is_error={message.is_error} errors={message.errors}")
    except CodeBuddySDKError as exc:
        print(f"    [异常] {type(exc).__name__}: {exc}")
    verify(scene, CALLS[start:])


def verify(scene: str, events: list[dict[str, Any]]) -> None:
    """只依赖本地收集到的 ToolUseBlock，不看模型回答（案例 04/05 的教训）。"""
    uses = [e for e in events if e["block"] == "ToolUseBlock"]
    agent_calls = [e for e in uses if e["name"] == "Agent"]
    print(f"    [判据] ToolUseBlock={len(uses)} 其中 Agent 工具={len(agent_calls)}")
    if not uses:
        print("    [判据] 未观察到工具调用，跳过断言。")
        return

    if scene in ("a", "b"):
        want = "case-reader" if scene == "a" else "case-counter"
        hit = [e for e in agent_calls if want in str(e["input"])]
        ok = bool(hit)
        print(f"    [判据] ({scene}) 委派到 {want}：{'通过 ✓' if ok else '未通过 ✗'}"
              f"  命中={len(hit)}")
        if not ok:
            print(f"    [判据] 实际工具序列={[e['name'] for e in uses]}")
    else:
        names = ("case-reader", "case-counter")
        hit = [e for e in agent_calls if any(n in str(e["input"]) for n in names)]
        ok = not hit
        print(f"    [判据] (c) 未注册时不会委派到自定义子代理："
              f"{'通过 ✓' if ok else '未通过 ✗'}  命中={len(hit)}")


def explain() -> None:
    print("\n=== 要点 ===")
    print("  · agents: dict[str, AgentDefinition] | None；key 是子代理名，")
    print("    主 Agent 用 Agent 工具的 subagent_type 指定要委派给谁。")
    print("  · AgentDefinition(description, prompt, tools, disallowed_tools, model)：")
    print("    description 里写 'MUST BE USED' 能提高被主动选用的概率。")
    print("  · tools 省略 → 继承主线程全部工具；指定 → 白名单。")
    print("    disallowed_tools 在线上被映射成 disallowedTools（_protocol.py）。")
    print("  · model 省略 / 'inherit' / 'default' 都不强制具体模型。")
    print("  · agents 与 hooks 一样走 initialize 控制协议（_internal/query.py:107），")
    print("    不是 CLI 参数；setting_sources=None 关不掉它。")
    print("  · 与案例 02 的对照：文件型子代理放在 .codebuddy/agents/ 下，")
    print("    需要 setting_sources 才会加载；程序化 agents 始终生效。")
    print("  · 坑：不提供 can_use_tool 时 SDK 一律回 allowed=False（案例 06）。")
    print("    子代理的工具请求也走同一个回调，所以本例挂了放行型 allow_all。")


async def main() -> None:
    show_agent_types()
    agents = build_agents()
    print(f"  已注册子代理 = {sorted(agents)}")

    await run(
        "A：注册并显式委派 case-reader",
        "请使用 Agent 工具，把下面的任务委派给名为 case-reader 的子代理"
        "（subagent_type 填 case-reader）：读取 cases/01_hello_query.py，"
        "说明它的难度星级。请只委派，不要自己读文件。",
        scene="a",
        agents=agents,
    )
    await run(
        "B：委派 case-counter（tools 白名单只给 Bash）",
        "请使用 Agent 工具，把下面的任务委派给名为 case-counter 的子代理"
        "（subagent_type 填 case-counter）：用 wc -l 统计 cases/07_hooks.py 的行数。"
        "请只委派，不要自己执行命令。",
        scene="b",
        agents=agents,
    )
    await run(
        "C：不注册 agents（对照）",
        "请读取 cases/01_hello_query.py，说明它的难度星级。"
        "如果需要，可以使用 Agent 工具委派给合适的子代理。",
        scene="c",
    )
    explain()


if __name__ == "__main__":
    asyncio.run(main())
