"""
案例 05 · 会话持久化：session_id / resume / continue_conversation

难度：★★★☆☆
目标：
  1. 从 SystemMessage(init) 与 ResultMessage 拿到 session_id，并确认会话落盘
  2. 用 resume=<sid> 恢复指定会话
  3. 用 continue_conversation=True 继续当前目录最近的会话
  4. 用「不带任何恢复」的调用作对照，看上下文是否真的被带回

本例涉及的 API：
    CodeBuddyAgentOptions(resume=..., continue_conversation=...,
                          fork_session=..., persist_session=..., session_id=...)
    query()
    SystemMessage / AssistantMessage / TextBlock / ResultMessage

前置条件：同案例 01。本例发起 4 次真实模型调用。

运行：
    uv run python cases/05_session_persistence.py
"""

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
