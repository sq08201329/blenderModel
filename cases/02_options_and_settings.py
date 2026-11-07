"""
案例 02 · Options 全景与环境隔离（setting_sources）

难度：★★☆☆☆
目标：
  1. 认识 CodeBuddyAgentOptions —— SDK 行为的唯一入口
  2. 掌握全部字段的分组与典型取值（尤其 tools vs allowed_tools）
  3. 通过 SystemMessage(init) 快照，看到 options 真的生效
  4. 理解 setting_sources 的环境隔离设计与 --setting-sources 映射

本例涉及的 API：
    CodeBuddyAgentOptions / AppendSystemPrompt
    query()
    SystemMessage / ResultMessage

前置条件：同案例 01。本例只发起 1 次真实模型调用。

运行：
    uv run python cases/02_options_and_settings.py
"""

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
