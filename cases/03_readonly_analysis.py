"""
案例 03 · 让 Agent 干活：工具白名单与只读分析

难度：★★★☆☆
目标：
  1. 让 Agent 真正调用工具完成一个任务，而不只是聊天
  2. 看清 ToolUseBlock -> ToolResultBlock 的完整轨迹
  3. 用 tools / allowed_tools / disallowed_tools 控制可用工具集
  4. 用实际调用的工具名验证白名单是否生效

本例涉及的 API：
    CodeBuddyAgentOptions(tools=..., allowed_tools=..., disallowed_tools=...)
    query()
    AssistantMessage / ToolUseBlock
    UserMessage / ToolResultBlock
    SystemMessage / ResultMessage

前置条件：同案例 01。本例发起 1 次真实模型调用（内部含若干工具轮次）。

运行：
    uv run python cases/03_readonly_analysis.py
"""

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
