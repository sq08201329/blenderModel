"""
案例 06 · 权限控制：can_use_tool 白名单与危险命令拦截

难度：★★★★☆
目标：
  1. 掌握 can_use_tool 回调签名与三种返回结果
  2. 用 PermissionResultAllow(updated_input=...) 改写工具入参
  3. 用 PermissionResultDeny(interrupt=True) 拦截危险命令并中断会话
  4. 验证「不提供回调 → 权限请求被自动拒绝」这个坑

本例涉及的 API：
    CodeBuddyAgentOptions(permission_mode=..., can_use_tool=...)
    CanUseToolOptions / PermissionResultAllow / PermissionResultDeny
    query()

前置条件：同案例 01。本例发起 3 次真实模型调用；所有 Bash 命令均为无害的 echo，
且危险命令在工具执行前就被拦截，不会真正运行。

运行：
    uv run python cases/06_permission_control.py
"""

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
