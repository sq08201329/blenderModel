"""
案例 04 · 多轮对话：CodeBuddySDKClient

难度：★★★☆☆
目标：
  1. 理解 query() 是一次性单轮，多轮交互要用 CodeBuddySDKClient
  2. 用 A/B 对比看到「会话是否共享」（session_id 是确定性判据）
  3. 掌握上下文管理器、query() / receive_response() / disconnect()
  4. 区分 receive_response() 与 receive_messages()，并避开验证陷阱

本例涉及的 API：
    CodeBuddySDKClient / CodeBuddyAgentOptions
    client.query() / receive_response() / receive_messages() / interrupt()
    SystemMessage / AssistantMessage / TextBlock / ResultMessage

前置条件：同案例 01。本例发起 4 次真实模型调用。

运行：
    uv run python cases/04_multi_turn.py
"""

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
