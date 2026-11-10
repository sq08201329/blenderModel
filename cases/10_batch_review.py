"""
案例 10 · 综合实战：批量代码审查 CLI

难度：★★★★★
目标：
  1. 用 AsyncIterable[dict] 做流式输入，并认识它「合并成一轮」的行为
  2. 用逐文件多轮实现真正的批量审查，单文件失败不影响整批
  3. 用 receive_messages() 自己控制停止时机，并演示 interrupt() 中断
  4. 汇总 num_turns / duration_ms / total_cost_usd / token 用量

本例涉及的 API：
    CodeBuddySDKClient(connect/query/receive_messages/receive_response/interrupt)
    ResultMessage(num_turns, duration_ms, total_cost_usd, usage, is_error, errors)
    CodeBuddySDKError -> CLIConnectionError / ExecutionError / ...
    CodeBuddyAgentOptions(tools, allowed_tools, can_use_tool, max_turns)

前置条件：同案例 01。本例发起 4 次真实模型调用 + 1 个零成本错误演示。

运行：
    uv run python cases/10_batch_review.py
    uv run python cases/10_batch_review.py cases/01_hello_query.py cases/05_session_persistence.py
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any

from codebuddy_agent_sdk import (
    AssistantMessage,
    CanUseToolOptions,
    CodeBuddyAgentOptions,
    CodeBuddySDKClient,
    CodeBuddySDKError,
    ErrorMessage,
    PermissionResultAllow,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    UserMessage,
)
from _common.sdk_helpers import brief

PROJECT_DIR = Path(__file__).resolve().parent.parent
SENT: list[dict[str, Any]] = []


def parse_args() -> list[Path]:
    parser = argparse.ArgumentParser(description="批量代码审查 CLI（案例 10）")
    parser.add_argument("files", nargs="*", help="待审查文件；默认审查两个小案例")
    args = parser.parse_args()
    if args.files:
        return [Path(f) for f in args.files]
    return [
        PROJECT_DIR / "cases" / "01_hello_query.py",
        PROJECT_DIR / "cases" / "03_readonly_analysis.py",
    ]


def resolve_files(paths: list[Path]) -> tuple[list[Path], list[str]]:
    """批量容错：单个文件不存在不能让整批崩掉。"""
    valid, missing = [], []
    for path in paths:
        if path.is_file():
            valid.append(path)
        else:
            missing.append(str(path))
    return valid, missing


def review_prompt(path: Path) -> str:
    try:
        rel = path.relative_to(PROJECT_DIR)
    except ValueError:
        rel = path
    return (f"请用 Read 工具读取 {rel}，只指出最严重的一个问题；"
            "一句话回答，不要修改文件。")


async def review_stream(paths: list[Path]):
    """流式输入：把 N 个审查任务变成 AsyncIterable[dict]，逐条写进 CLI stdin。

    每条 dict 是 stream-json 的 user message envelope；session_id 由
    client.query(..., session_id=...) 统一补齐，这里不用管。
    """
    for i, path in enumerate(paths, 1):
        yield {
            "type": "user",
            "message": {"role": "user", "content": f"【审查任务 {i}/{len(paths)}】{review_prompt(path)}"},
            "parent_tool_use_id": None,
        }
        SENT.append({"index": i, "file": path.name})


def show_api_types() -> None:
    """零成本自省：打印本例用到的 API 与字段，不消耗模型调用。"""
    print("=== API 自省（不消耗模型调用）===")
    print("  CodeBuddySDKClient: connect / query / receive_messages /")
    print("    receive_response / interrupt / set_model / disconnect")
    print("  query(prompt: str | AsyncIterable[dict], session_id='default')")
    print("    → 传异步可迭代对象就是「流式输入」，逐条写 stdin。")
    print("  receive_messages() 不自动停，必须自己 break（案例 04 :534）。")
    print("  receive_response() 到 ResultMessage 自动停；is_error 时抛 ExecutionError。")
    print("  ResultMessage 统计字段 = num_turns, duration_ms, duration_api_ms,")
    print("    total_cost_usd, usage(input_tokens/output_tokens), is_error, errors")
    print("  异常树 = CodeBuddySDKError → CLIConnectionError / CLINotFoundError /")
    print("    CLIStartupError / CLIJSONDecodeError / ProcessError / ExecutionError /")
    print("    AuthenticationError")


async def allow_all(
    tool_name: str,
    input_data: dict[str, Any],
    options: CanUseToolOptions,
):
    """兜底放行：allowed_tools 没覆盖到时也不至于被 SDK 一律拒绝（案例 06 坑）。"""
    print(f"    [权限] 放行 {tool_name}（allowed_tools 未覆盖的兜底）")
    return PermissionResultAllow(updated_input=input_data)


def make_options(**overrides: Any) -> CodeBuddyAgentOptions:
    base: dict[str, Any] = dict(
        cwd=str(PROJECT_DIR),
        permission_mode="default",
        max_turns=12,
        tools=["Read"],             # 模型只能看到 Read
        allowed_tools=["Read"],     # Read 静态放行，正常不触发 can_use_tool
        can_use_tool=allow_all,     # 兜底，演示案例 06 的坑
    )
    base.update(overrides)
    return CodeBuddyAgentOptions(**base)


def blocks_of(message: Any) -> list[Any]:
    content = getattr(message, "content", None)
    return content if isinstance(content, list) else []


async def collect(
    client: CodeBuddySDKClient,
    *,
    limit: int = 80,
    interrupt_after: int | None = None,
) -> dict[str, Any]:
    """用 receive_messages() 收消息，自己判断何时停（本例的核心）。

    receive_messages() 不会像 receive_response() 那样在 ResultMessage 处自动返回，
    所以必须：① 遇 ResultMessage / ErrorMessage break；② 设消息上限兜底；
    ③ 套墙钟超时，防止被中断后流一直挂着。
    """
    stats: dict[str, Any] = {
        "messages": 0, "texts": 0, "tool_calls": 0, "tool_names": [],
        "result": None, "interrupted": False, "errors": [],
    }
    try:
        async with asyncio.timeout(90):
            async for message in client.receive_messages():
                stats["messages"] += 1
                if isinstance(message, ResultMessage):
                    stats["result"] = {
                        "subtype": message.subtype,
                        "session_id": message.session_id,
                        "num_turns": message.num_turns,
                        "duration_ms": message.duration_ms,
                        "total_cost_usd": message.total_cost_usd,
                        "is_error": message.is_error,
                        "errors": message.errors,
                        "input_tokens": message.usage.input_tokens if message.usage else None,
                        "output_tokens": message.usage.output_tokens if message.usage else None,
                    }
                    break
                if isinstance(message, ErrorMessage):
                    stats["errors"].append(message.error)
                    break
                if isinstance(message, (AssistantMessage, UserMessage)):
                    for block in blocks_of(message):
                        if isinstance(block, ToolUseBlock):
                            stats["tool_calls"] += 1
                            stats["tool_names"].append(block.name)
                            print(f"    [流] 工具调用 {block.name} {brief(block.input, 90)}")
                        elif (isinstance(block, TextBlock)
                              and isinstance(message, AssistantMessage)
                              and block.text.strip()):
                            stats["texts"] += 1
                            print(f"    [回答] {brief(block.text.strip(), 150)}")

                if (interrupt_after is not None
                        and not stats["interrupted"]
                        and (stats["tool_calls"] >= interrupt_after
                             or stats["messages"] >= 3)):
                    # 主动中断：不靠模型自己停下来
                    await client.interrupt()
                    stats["interrupted"] = True
                    print("    [中断] 已调用 client.interrupt()")
                if stats["messages"] >= limit:
                    stats["errors"].append("达到消息上限，主动停止")
                    break
    except TimeoutError:
        stats["errors"].append("收消息超时（90s），主动放弃")
    return stats


async def scene_stream(paths: list[Path]) -> dict[str, Any]:
    """A：流式输入演示（一次投递 N 条 user message）。"""
    print("\n=== A：流式输入（AsyncIterable[dict]）===")
    s0 = len(SENT)
    print(f"  一次投递 {len(paths)} 条审查任务")
    async with CodeBuddySDKClient(options=make_options()) as client:
        await client.query(review_stream(paths), session_id="batch-review")
        stats = await collect(client)
    stats["sent"] = SENT[s0:]
    print(f"    [判据] 投递={len(stats['sent'])} 工具调用={stats['tool_calls']} "
          f"收到消息={stats['messages']}")
    ok = len(stats["sent"]) == len(paths) and stats["result"] is not None
    print(f"    [判据] (a) 流式输入全部送达且拿到 ResultMessage："
          f"{'通过 ✓' if ok else '未通过 ✗'}")
    return stats


async def scene_batch(paths: list[Path]) -> list[dict[str, Any]]:
    """B：逐文件多轮 —— 真正的批量审查，单文件失败不影响整批。"""
    print("\n=== B：逐文件批量审查 ===")
    results: list[dict[str, Any]] = []
    async with CodeBuddySDKClient(options=make_options()) as client:
        for path in paths:
            print(f"  -- 审查 {path.name} --")
            try:
                await client.query(review_prompt(path))
                stats = await collect(client)
            except CodeBuddySDKError as exc:
                # 单文件失败只记一笔，继续下一个（文件级容错）
                stats = {"result": None, "errors": [f"{type(exc).__name__}: {exc}"]}
                print(f"    [失败] {stats['errors'][0]}")
            results.append({"file": path.name, "stats": stats})
    done = sum(1 for r in results if r["stats"]["result"] is not None)
    print(f"    [判据] (b) {done}/{len(paths)} 个文件独立完成审查："
          f"{'通过 ✓' if done == len(paths) else '未通过 ✗'}")
    return results


async def scene_interrupt() -> dict[str, Any]:
    """C：流式消息中途主动 interrupt()。"""
    print("\n=== C：中途中断 ===")
    async with CodeBuddySDKClient(options=make_options()) as client:
        await client.query(
            "请逐个读取 cases/ 目录下所有 Python 文件，"
            "为每个文件写一段不少于五句的详细审查意见。必须使用 Read 工具。"
        )
        stats = await collect(client, interrupt_after=1, limit=40)
    print(f"    [判据] 收到消息={stats['messages']} 工具调用={stats['tool_calls']} "
          f"已中断={stats['interrupted']}")
    print(f"    [判据] (c) 主动中断被执行："
          f"{'通过 ✓' if stats['interrupted'] else '未通过 ✗'}")
    return stats


async def scene_errors() -> dict[str, Any]:
    """D：零成本错误演示 —— 未连接调用触发 CLIConnectionError。"""
    print("\n=== D：错误处理（零成本） ===")
    client = CodeBuddySDKClient()
    caught: str | None = None
    try:
        await client.query("这条消息发不出去")  # 没 connect
    except CodeBuddySDKError as exc:
        caught = f"{type(exc).__name__}: {exc}"
    print(f"    [异常] {caught}")
    print(f"    [判据] (d) 未连接调用被异常树兜住："
          f"{'通过 ✓' if caught else '未通过 ✗'}")
    return {"caught": caught}


def summarize(entries: list[tuple[str, dict[str, Any]]], missing: list[str]) -> None:
    """汇总：成本、轮次、耗时、token，以及被跳过的文件。"""
    print("\n=== 汇总 ===")
    total_cost = 0.0
    total_turns = 0
    total_ms = 0
    total_in = 0
    total_out = 0
    for label, stats in entries:
        result = stats.get("result")
        if not result:
            print(f"  {label}: 无 ResultMessage（中断/失败/未完成）")
            continue
        cost = result["total_cost_usd"] or 0.0
        total_cost += cost
        total_turns += result["num_turns"] or 0
        total_ms += result["duration_ms"] or 0
        total_in += result["input_tokens"] or 0
        total_out += result["output_tokens"] or 0
        print(f"  {label}: turns={result['num_turns']} "
              f"耗时={result['duration_ms']}ms 费用=${cost:.6f} "
              f"tokens={result['input_tokens']}/{result['output_tokens']} "
              f"is_error={result['is_error']}")
    print(f"  ---- 合计: turns={total_turns} 耗时={total_ms}ms "
          f"费用=${total_cost:.6f} tokens={total_in}/{total_out}")
    print(f"  跳过的不存在文件 = {missing or '无'}")
    print("  · 单文件失败只记入跳过列表，不影响其余文件；成本从各 ResultMessage 累加。")


def explain() -> None:
    print("\n=== 要点 ===")
    print("  · 流式输入：query(AsyncIterable[dict])，每个 dict 是一条 stream-json user 消息；")
    print("    连续多条会被 CLI 合并成同一轮，适合「一次投递」，不适合逐个独立审查。")
    print("  · 真正的批量：同一个 Client 内逐文件 query(str) 多轮，每轮各自收 ResultMessage；")
    print("    单文件 try/except CodeBuddySDKError 兜住，失败不打断整批。")
    print("  · receive_messages() 不自动停：自己 break（ResultMessage / ErrorMessage），")
    print("    再加消息上限与墙钟超时，否则中断后流会一直挂着。")
    print("  · receive_response() 到 ResultMessage 自动停，但 is_error 时会抛 ExecutionError。")
    print("  · interrupt() 发控制请求打断当前回合，不靠模型自己停。")
    print("  · 成本口径：total_cost_usd / num_turns / duration_ms / usage；逐条累加，")
    print("    本环境 total_cost_usd 恒为 0，实际看 turns 与 tokens 更靠谱。")
    print("  · 错误处理三层：文件级跳过 → SDK 异常树兜底 → ResultMessage.is_error 检查。")
    print("  · tools 限定可见工具，allowed_tools 静态放行，can_use_tool 运行时兜底（案例 03/06）。")


async def main() -> None:
    paths = parse_args()
    show_api_types()
    files, missing = resolve_files(paths)
    if missing:
        print(f"  [跳过] 文件不存在: {missing}")

    stream = await scene_stream(files) if files else {"result": None}
    batches = await scene_batch(files) if files else []
    interrupted = await scene_interrupt()
    errors = await scene_errors()

    entries: list[tuple[str, dict[str, Any]]] = [("A 流式", stream)]
    entries += [(f"B/{r['file']}", r["stats"]) for r in batches]
    entries.append(("C 中断", interrupted))
    summarize(entries, missing)
    print(f"  D 错误演示捕获 = {errors['caught']}")
    explain()


if __name__ == "__main__":
    asyncio.run(main())
