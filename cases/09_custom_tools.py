"""
案例 09 · 自定义工具：@tool + create_sdk_mcp_server

难度：★★★★☆
目标：
  1. 认识 @tool / create_sdk_mcp_server / mcp_servers 三个 API 与 CallToolResult 返回格式
  2. 定义进程内自定义工具，让模型调用，验证「工具函数真的被本地执行」
  3. 用 input_schema 的简单类型映射与 JSON Schema 两种写法定义参数
  4. 用「不注册 mcp_servers」作对照，理解 SDK MCP 走进程内控制协议

本例涉及的 API：
    @tool(name, description, input_schema)
    create_sdk_mcp_server(name, version, tools) -> McpSdkServerConfig
    CodeBuddyAgentOptions(mcp_servers=..., can_use_tool=..., permission_mode=...)
    query() / SystemMessage / AssistantMessage / ToolUseBlock / ToolResultBlock / ResultMessage

前置条件：同案例 01。本例发起 3 次真实模型调用；自定义工具只做加法和只读行数统计。

运行：
    uv run python cases/09_custom_tools.py
"""

from __future__ import annotations

import asyncio
from inspect import signature
from pathlib import Path
from typing import Any

from codebuddy_agent_sdk import (
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
    create_sdk_mcp_server,
    query,
    tool,
)
from _common.sdk_helpers import brief

PROJECT_DIR = Path(__file__).resolve().parent.parent
CASES_DIR = PROJECT_DIR / "cases"
SERVER_NAME = "case-tools"
CALLS: list[dict[str, Any]] = []
TOOL_HITS: list[dict[str, Any]] = []


@tool("add", "把两个整数相加，返回它们的和。", {"a": int, "b": int})
async def add(args: dict[str, Any]) -> dict[str, Any]:
    """① input_schema 用简单类型映射：{"a": int, "b": int}，两个参数都会变成 required。"""
    a, b = int(args["a"]), int(args["b"])
    TOOL_HITS.append({"tool": "add", "args": dict(args), "result": a + b})
    return {"content": [{"type": "text", "text": str(a + b)}]}


@tool(
    "count_case_lines",
    "统计 cases/ 目录下某个 Python 文件的行数。",
    {
        "properties": {
            "filename": {
                "type": "string",
                "description": "文件名，如 01_hello_query.py",
            },
        },
        "required": ["filename"],
    },
)
async def count_case_lines(args: dict[str, Any]) -> dict[str, Any]:
    """② input_schema 用 JSON Schema 写法，可以给参数加 description。"""
    name = str(args["filename"])
    path = (CASES_DIR / name).resolve()
    # 防目录穿越：只允许读 cases/ 下的文件
    if not str(path).startswith(str(CASES_DIR.resolve())):
        return {"content": [{"type": "text", "text": "非法路径"}], "isError": True}
    try:
        lines = len(path.read_text().splitlines())
    except OSError as exc:
        return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    TOOL_HITS.append({"tool": "count_case_lines", "args": dict(args), "result": lines})
    return {"content": [{"type": "text", "text": f"{name}: {lines} 行"}]}


def build_server() -> dict[str, Any]:
    """每次新建 server 实例，避免多个 query 共享同一个 SdkMcpServer 对象（案例 04）。"""
    return create_sdk_mcp_server(
        name=SERVER_NAME,
        version="1.0.0",
        tools=[add, count_case_lines],
    )


def show_tool_types() -> None:
    """零成本自省：直接打印签名与结构，不消耗模型调用（案例 02/07/08 的做法）。"""
    print("=== 工具类型自省（不消耗模型调用）===")
    print(f"  tool{signature(tool)}")
    print(f"  create_sdk_mcp_server{signature(create_sdk_mcp_server)}")
    print("  mcp_servers: dict[str, McpServerConfig] | str | Path（types.py:609）")
    print("  CallToolResult 键 = content, isError（注意是 isError，不是 is_error）")
    print("  McpSdkServerConfig 键 = type, name, server, description, defer_loading")
    print("  · @tool 的 input_schema 支持简单类型映射与 JSON Schema 两种写法。")
    print("  · 返回必须是 {\"content\": [{\"type\":\"text\",\"text\": ...}]}，不是裸字符串。")
    print("  · create_sdk_mcp_server 返回的 dict 里含 SdkMcpServer 对象，不能 JSON 序列化；")
    print("    SDK 把它从 --mcp-config 剥离，改走 initialize 的 sdkMcpServers。")


async def allow_all(
    tool_name: str,
    input_data: dict[str, Any],
    options: CanUseToolOptions,
):
    """放行型权限回调：MCP 工具调用同样会走它（案例 06 的坑）。"""
    print(f"    [权限] 放行 {tool_name}")
    return PermissionResultAllow(updated_input=input_data)


def make_options(**overrides: Any) -> CodeBuddyAgentOptions:
    base: dict[str, Any] = dict(
        cwd=str(PROJECT_DIR),
        permission_mode="default",
        max_turns=8,
        can_use_tool=allow_all,   # 不提供 → SDK 一律回 allowed=False（案例 06 的坑）
    )
    base.update(overrides)
    return CodeBuddyAgentOptions(**base)


def blocks_of(message: Any) -> list[Any]:
    content = getattr(message, "content", None)
    return content if isinstance(content, list) else []


async def run(
    label: str,
    prompt: str,
    scene: str,
    mcp_servers: dict[str, Any] | None = None,
) -> None:
    print(f"\n=== {label} ===")
    h0 = len(TOOL_HITS)
    start = len(CALLS)
    overrides: dict[str, Any] = {}
    if mcp_servers is not None:
        overrides["mcp_servers"] = mcp_servers
    options = make_options(**overrides)
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, SystemMessage) and message.subtype == "init":
                print(f"    [init] mcp_servers="
                      f"{brief(message.data.get('mcp_servers'), 220)}")
            elif isinstance(message, (AssistantMessage, UserMessage)):
                for block in blocks_of(message):
                    if isinstance(block, ToolUseBlock):
                        CALLS.append({
                            "scene": scene, "block": "ToolUseBlock",
                            "name": block.name, "id": block.id, "input": block.input,
                        })
                        print(f"    [流] 工具调用 {block.name} {brief(block.input, 140)}")
                    elif isinstance(block, ToolResultBlock):
                        CALLS.append({
                            "scene": scene, "block": "ToolResultBlock",
                            "tool_use_id": block.tool_use_id,
                            "is_error": block.is_error,
                        })
                        print(f"    [流] 工具结果 {brief(block.content, 140)} "
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
    verify(scene, TOOL_HITS[h0:], CALLS[start:])


def verify(
    scene: str,
    hits: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> None:
    """判据来自「工具函数内部的本地打点」，比消息流更确定。

    自定义工具是我们自己的 Python 函数：它被调用了就会被记录，
    不依赖模型有没有答对、也不依赖 ToolUseBlock 的名字长什么样。
    """
    uses = [e for e in events if e["block"] == "ToolUseBlock"]
    print(f"    [判据] 本地工具被调用={len(hits)} ToolUseBlock={len(uses)}")
    if scene == "a":
        ok = any(h["tool"] == "add" and h["result"] == 42 for h in hits)
        print(f"    [判据] (a) add(17, 25) 在本地执行并返回 42："
              f"{'通过 ✓' if ok else '未通过 ✗'}  hits={hits}")
    elif scene == "b":
        ok = any(h["tool"] == "count_case_lines" for h in hits)
        print(f"    [判据] (b) count_case_lines 在本地执行："
              f"{'通过 ✓' if ok else '未通过 ✗'}  hits={hits}")
    else:
        ok = not hits
        print(f"    [判据] (c) 未注册时自定义工具从未被调用："
              f"{'通过 ✓' if ok else '未通过 ✗'}  hits={len(hits)}")
    if uses:
        print(f"    [判据] 本轮工具名={[e['name'] for e in uses]}")


def explain() -> None:
    print("\n=== 要点 ===")
    print("  · @tool(name, description, input_schema) 装饰 async def f(args: dict)。")
    print("    input_schema 两种写法：{a: int} 简单映射，或 {\"properties\":..., \"required\":...}。")
    print("  · create_sdk_mcp_server(name, version, tools) 返回 McpSdkServerConfig；")
    print("    把它放进 options.mcp_servers = {server_name: config}。")
    print("  · CallToolResult = {\"content\": [{\"type\":\"text\",\"text\": ...}], \"isError\": bool}；")
    print("    注意是驼峰 isError，不是 ToolResultBlock 的 is_error。")
    print("  · 进程内 SDK MCP vs 外部 MCP：外部要 stdio/http/sse/remote 配置和子进程；")
    print("    SDK 内嵌不需要起进程，走 initialize 的 sdkMcpServers + mcp_message 控制请求")
    print("    （transport/subprocess.py:113-204），所以也没法用 --mcp-config 传。")
    print("  · 工具全名是 mcp__<server>__<tool>；allowed_tools / can_use_tool 用全名。")
    print("  · 坑：不提供 can_use_tool 时 SDK 一律回 allowed=False（案例 06），")
    print("    MCP 工具也逃不掉，所以本例挂了放行型 allow_all。")
    print("  · 对照案例 07/08：hooks / agents / SDK MCP 都走控制协议，")
    print("    setting_sources=None 关不掉它们。")


async def main() -> None:
    show_tool_types()
    print(f"  已注册 SDK MCP server = {SERVER_NAME}  tools=['add', 'count_case_lines']")

    await run(
        "A：用 add 工具计算 17 + 25",
        "请使用 add 工具计算 17 + 25，必须使用工具，不要自己心算。",
        scene="a",
        mcp_servers={SERVER_NAME: build_server()},
    )
    await run(
        "B：用 count_case_lines 工具统计行数",
        "请使用 count_case_lines 工具统计 05_session_persistence.py 的行数，"
        "必须使用工具，不要自己读文件。",
        scene="b",
        mcp_servers={SERVER_NAME: build_server()},
    )
    await run(
        "C：不注册 mcp_servers（对照）",
        "请计算 17 + 25 等于多少。",
        scene="c",
    )
    explain()


if __name__ == "__main__":
    asyncio.run(main())
