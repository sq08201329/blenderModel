"""
案例 07 · Hook 系统：PreToolUse 审计与阻断

难度：★★★★☆
目标：
  1. 认识 HookEvent 的 11 种事件与 HookMatcher / HookCallback 类型签名
  2. 用 PreToolUse 做执行前审计，证明它先于工具执行
  3. 用 decision="block" 拦截危险命令，验证被拦命令从未执行
  4. 用 matcher 证明 Hook 只作用于指定工具，分清 Hook 层与 can_use_tool 权限层

本例涉及的 API：
    CodeBuddyAgentOptions(hooks=..., can_use_tool=..., permission_mode=...)
    HookEvent / HookMatcher / HookCallback / HookContext / HookJSONOutput
    PermissionResultAllow / CanUseToolOptions（对照案例 06）
    query() / AssistantMessage / UserMessage / ToolUseBlock / ToolResultBlock / ResultMessage

前置条件：同案例 01。本例发起 3 次真实模型调用；所有 Bash 命令均为无害的 echo，
危险命令在工具执行前被 PreToolUse 拦截，不会真正运行。

运行：
    uv run python cases/07_hooks.py
"""

from __future__ import annotations

import asyncio
import itertools
from dataclasses import fields
from pathlib import Path
from typing import Any, get_args

from codebuddy_agent_sdk import (
    AssistantMessage,
    CanUseToolOptions,
    CodeBuddyAgentOptions,
    CodeBuddySDKError,
    HookCallback,
    HookContext,
    HookEvent,
    HookJSONOutput,
    HookMatcher,
    PermissionResultAllow,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)
from _common.sdk_helpers import brief

PROJECT_DIR = Path(__file__).resolve().parent.parent
DANGEROUS = ("rm -rf", "sudo", "chmod 777")
_SEQ = itertools.count(1)
TRACE: list[dict[str, Any]] = []
_SEEN_RAW = False


def record(src: str, **data: Any) -> None:
    """全局有序日志：hook（回调内）/ perm（权限回调内）/ stream（消息流）。

    这是本例的确定性判据来源——Hook 是本地 Python 回调，记录到什么就是什么，
    不需要靠模型「有没有答对」来判断（案例 04/05 的验证陷阱）。
    """
    TRACE.append({"seq": next(_SEQ), "src": src, **data})


def hook_command(hook_input: Any) -> tuple[str, str]:
    """兼容 hook_input 的两种形状。

    CLI 文档的 JSON schema 是嵌套的 {"tool_name", "tool_input": {"command"}}，
    但同一文档里的 Python 示例却用扁平的 input_data.get("command")。
    HookCallback 首参类型是 Any，真实形状以首次调用的 raw 打印为准。
    """
    if not isinstance(hook_input, dict):
        return "?", ""
    tool = str(hook_input.get("tool_name", "?"))
    nested = hook_input.get("tool_input")
    if isinstance(nested, dict) and "command" in nested:
        command = str(nested.get("command", ""))
    else:
        command = str(hook_input.get("command", ""))
    return tool, command


def show_hook_types() -> None:
    """零成本自省：直接打印 Hook 相关类型，不消耗模型调用（案例 02 的做法）。"""
    events: list[str] = []
    for arg in get_args(HookEvent):
        # HookEvent 是 Literal[...] | Literal[...] | ...，需要再展开一层
        inner = get_args(arg)
        events.extend(str(v) for v in inner) if inner else events.append(str(arg))
    print("=== Hook 类型自省（不消耗模型调用）===")
    print(f"  HookEvent（{len(events)} 种）= {', '.join(events)}")
    print("  HookMatcher 字段 = " + ", ".join(f.name for f in fields(HookMatcher)))
    print("  HookJSONOutput 键 = " + ", ".join(HookJSONOutput.__annotations__))
    print("  HookCallback = async (hook_input: Any, tool_use_id, context: HookContext)")
    print("    -> HookJSONOutput；HookContext 键 = " + ", ".join(HookContext.__annotations__))
    print("  · Python 里没有 HOOK_EVENTS 常量（那是 TypeScript 的），事件名就是字符串。")
    print("  · 键名是 continue_ 不是 continue；_execute_hook 会改写成线上的 continue。")
    print("  · HookMatcher.timeout 单位是秒（TypeScript 是毫秒）。")


async def allow_all(
    tool_name: str,
    input_data: dict[str, Any],
    options: CanUseToolOptions,
):
    """放行型权限回调：避开案例 06「不提供回调 → SDK 一律拒绝」的坑。"""
    record("perm", tool=tool_name, tool_use_id=options.tool_use_id)
    print(f"    [权限] 放行 {tool_name}（Hook 之后、执行之前）")
    return PermissionResultAllow(updated_input=input_data)


def make_options(**overrides: Any) -> CodeBuddyAgentOptions:
    """每次新建 options，避免多个 query 共享同一个对象（案例 04）。"""
    base: dict[str, Any] = dict(
        cwd=str(PROJECT_DIR),
        permission_mode="default",  # 需要确认 → 才会走 can_use_tool；对照案例 06
        max_turns=5,                # 限制最大轮数，防止跑飞
        tools=["Bash"],             # 只暴露 Bash，让流程可控
        can_use_tool=allow_all,     # 不提供 → SDK 一律回 allowed=False（案例 06 的坑）
    )
    # hooks 走进程内控制协议的 initialize 请求，不是 CLI 参数：
    # transport/subprocess.py 完全不序列化 opts.hooks，
    # 所以 setting_sources=None 也关不掉程序化 Hook。
    base.update(overrides)
    return CodeBuddyAgentOptions(**base)


async def audit_cb(
    hook_input: Any, tool_use_id: str | None, context: HookContext
) -> HookJSONOutput:
    """场景 A：执行前审计并放行；首次调用打印原始 hook_input 定稿真实形状。"""
    global _SEEN_RAW
    tool, command = hook_command(hook_input)
    record("hook", event="PreToolUse", tool=tool, tool_use_id=tool_use_id,
           decision="allow", cmd=command)
    print(f"    [Hook/PRE] 审计 {tool}: {brief(command, 70)}")
    if not _SEEN_RAW:
        _SEEN_RAW = True
        print(f"    [Hook/PRE] raw hook_input = {brief(hook_input, 240)}")
    return {"continue_": True}


async def guard_cb(
    hook_input: Any, tool_use_id: str | None, context: HookContext
) -> HookJSONOutput:
    """场景 B：命中危险关键词就 block，命令根本不会执行。"""
    tool, command = hook_command(hook_input)
    blocked = any(word in command for word in DANGEROUS)
    record("hook", event="PreToolUse", tool=tool, tool_use_id=tool_use_id,
           decision="block" if blocked else "allow", cmd=command)
    if blocked:
        print(f"    [Hook/PRE] 拦截 {brief(command, 70)}")
        return {"decision": "block", "reason": f"危险命令被 PreToolUse 拦截：{command}"}
    print(f"    [Hook/PRE] 放行 {brief(command, 70)}")
    return {"continue_": True}


async def matcher_cb(
    hook_input: Any, tool_use_id: str | None, context: HookContext
) -> HookJSONOutput:
    """场景 C：matcher="Bash" 时，非 Bash 工具不该触发这个回调。"""
    tool, command = hook_command(hook_input)
    record("hook", event="PreToolUse", matcher="Bash", tool=tool,
           tool_use_id=tool_use_id, decision="allow", cmd=command)
    print(f"    [Hook/PRE] 命中 matcher=Bash 的回调，tool_name={tool}")
    return {"continue_": True}


def blocks_of(message: Any) -> list[Any]:
    content = getattr(message, "content", None)
    return content if isinstance(content, list) else []


async def run(
    label: str,
    prompt: str,
    hooks: dict[HookEvent, list[HookMatcher]],
    scene: str,
    tools: list[str] | None = None,
) -> None:
    print(f"\n=== {label} ===")
    start = len(TRACE)
    overrides: dict[str, Any] = {"hooks": hooks}
    if tools:
        overrides["tools"] = tools
    options = make_options(**overrides)
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, (AssistantMessage, UserMessage)):
                for block in blocks_of(message):
                    if isinstance(block, ToolUseBlock):
                        record("stream", block="ToolUseBlock", tool=block.name,
                               tool_use_id=block.id)
                        print(f"    [流] 工具调用 {block.name} {brief(block.input, 90)}")
                    elif isinstance(block, ToolResultBlock):
                        record("stream", block="ToolResultBlock",
                               tool_use_id=block.tool_use_id,
                               is_error=block.is_error)
                        print(f"    [流] 工具结果 {brief(block.content, 90)} "
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
    verify(scene, TRACE[start:])


def verify(scene: str, events: list[dict[str, Any]]) -> None:
    """只依赖本地 TRACE 日志做确定性判据，绝不看模型回答。"""
    hooks = [e for e in events if e["src"] == "hook"]
    uses = [e for e in events if e["src"] == "stream" and e.get("block") == "ToolUseBlock"]
    results = [e for e in events if e["src"] == "stream" and e.get("block") == "ToolResultBlock"]
    print(f"    [判据] hook={len(hooks)} ToolUseBlock={len(uses)} "
          f"ToolResultBlock={len(results)}")
    if not uses:
        print("    [判据] 未观察到工具调用，跳过断言（模型本轮未使用工具）。")
        return
    if not hooks:
        print("    [判据] 工具被调用但 Hook 未触发（检查 matcher 匹配规则）。")
        return

    if scene == "a":
        first_hook = min(e["seq"] for e in hooks)
        first_result = min((e["seq"] for e in results), default=None)
        ok = first_result is not None and first_hook < first_result
        print(f"    [判据] (a) PreToolUse 先于工具执行：{'通过 ✓' if ok else '未通过 ✗'}"
              f"  hook_seq={first_hook} result_seq={first_result}")
    elif scene == "b":
        blocked = {e["tool_use_id"] for e in hooks if e.get("decision") == "block"}
        # 被拦的命令不会成功执行；CLI 可能把拦截原因作为 is_error=True 的
        # tool_result 回给模型，那种结果不算「执行过命令」。
        executed = {e["tool_use_id"] for e in results if not e.get("is_error")}
        ok = bool(blocked) and not (blocked & executed)
        print(f"    [判据] (b) 被拦命令从未执行：{'通过 ✓' if ok else '未通过 ✗'}"
              f"  blocked={sorted(map(str, blocked))} 成功执行={sorted(map(str, executed))}")
    else:
        hooked = {str(e["tool_use_id"]) for e in hooks}
        non_bash = {e["tool_use_id"] for e in uses if e.get("tool") != "Bash"}
        ok = all(e.get("tool") == "Bash" for e in hooks) and not (non_bash & hooked)
        print(f"    [判据] (c) matcher 只作用于 Bash：{'通过 ✓' if ok else '未通过 ✗'}"
              f"  非 Bash 工具调用={len(non_bash)} 其中命中 Hook={len(non_bash & hooked)}")


def explain() -> None:
    print("\n=== 要点 ===")
    print("  · hooks: dict[HookEvent, list[HookMatcher]]，事件名是字符串，")
    print("    Python 没有 HOOK_EVENTS 常量（那是 TypeScript 的）。")
    print("  · HookCallback 必须 async，签名 (hook_input, tool_use_id, context)；")
    print("    同步函数会被 _execute_hook 的 await 吞掉，异常也会被吞成 continue=False。")
    print("  · 返回 {'continue_': True} 放行；{'decision':'block','reason':...} 拦截 PreToolUse；")
    print("    'continue_' 由 _internal/query.py:490 改写成线上的 'continue'。")
    print("  · matcher 按工具名匹配（支持正则；None/'*'/'' 匹配全部）；timeout 单位是秒。")
    print("  · hooks 走进程内控制协议的 initialize 请求，不是 CLI 参数：")
    print("    transport/subprocess.py 完全不序列化 opts.hooks，所以 setting_sources=None")
    print("    也关不掉程序化 Hook（对照案例 02 的环境隔离）。")
    print("  · 分层：tool_use → PreToolUse Hook → can_use_tool 权限层 → 执行 → ToolResultBlock。")
    print("    Hook 能 block/改写入参；案例 06 的 can_use_tool 用 PermissionResultDeny/Allow。")
    print("  · 坑：不提供 can_use_tool 时 SDK 一律回 allowed=False（案例 06），")
    print("    三个场景都挂了放行型回调，工具才会真正执行、Hook 的先后才可观测。")


async def main() -> None:
    show_hook_types()

    await run(
        "A：PreToolUse 执行前审计",
        "请调用 Bash 工具执行命令 echo AUDIT_OK，然后把输出告诉我。必须使用工具，不要只回答文字。",
        hooks={"PreToolUse": [HookMatcher(hooks=[audit_cb])]},
        scene="a",
    )
    await run(
        "B：decision=block 拦截危险命令",
        '请调用 Bash 工具执行命令 echo "rm -rf /tmp/case07_nonexistent"，'
        "然后把输出告诉我。必须使用工具。",
        hooks={"PreToolUse": [HookMatcher(matcher="Bash", hooks=[guard_cb])]},
        scene="b",
    )
    await run(
        "C：matcher 只匹配 Bash",
        "请先用 Read 工具读取 cases/01_hello_query.py 的前几行，"
        "再调用 Bash 工具执行命令 echo MATCH_OK，最后把命令输出告诉我。两个工具都必须使用。",
        hooks={"PreToolUse": [HookMatcher(matcher="Bash", hooks=[matcher_cb])]},
        scene="c",
        tools=["Read", "Bash"],
    )
    explain()


if __name__ == "__main__":
    asyncio.run(main())
