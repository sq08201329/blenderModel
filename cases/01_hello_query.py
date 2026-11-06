"""
案例 01 · Hello, query()

难度：★☆☆☆☆
目标：跑通一次最简单的 SDK 查询，看懂消息流里到底流过了什么。

本例涉及的 API：
    query(prompt=..., options=...)   -> AsyncIterator[Message]
    CodeBuddyAgentOptions
    SystemMessage / AssistantMessage / UserMessage / ResultMessage
    TextBlock / ToolUseBlock / ToolResultBlock

公共函数：
    _common.sdk_helpers.dump_stream() —— 完整打印每条消息并原样 yield，供所有案例复用

前置条件：
    uv add codebuddy-agent-sdk
    codebuddy 已完成登录，或已设置 CODEBUDDY_API_KEY

运行：
    uv run python cases/01_hello_query.py
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
        #model="deepseek-v4.1-flash",
        permission_mode="plan",  # 只读模式：本例不需要任何写操作，最安全
        max_turns=5,             # 限制最大轮数，防止跑飞
    )

    # query() 返回的不是「一个最终结果」，而是一条条的异步消息流。
    # dump_stream 给出「完整视图」：每条消息的 type + 全部字段；
    # 下面的分支给出「按需提取」：只挑出教学关注的几个值。两者互不干扰。
    async for message in dump_stream(query(prompt=prompt, options=options)):

        # ① 会话初始化：data 里带 session_id、可用工具列表等
        if isinstance(message, SystemMessage):
            print(f"  → [system] subtype={message.subtype} "
                  f"session_id={message.data.get('session_id')}")

        # ② 助手输出：content 是「内容块」列表，文本 / 思考 / 工具调用在这里
        elif isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(f"  → [文本] {block.text}")
                elif isinstance(block, ToolUseBlock):
                    print(f"  → [工具调用] {block.name}({block.input})")

        # ③ 工具结果走 UserMessage：Anthropic 消息格式里 tool_result 属于 user 角色
        elif isinstance(message, UserMessage):
            if isinstance(message.content, list):
                for block in message.content:
                    if isinstance(block, ToolResultBlock):
                        print(f"  → [工具结果] {block.content}")

        # ④ 收尾统计：耗时、轮数、费用、错误
        elif isinstance(message, ResultMessage):
            print(f"  → [结果] subtype={message.subtype} turns={message.num_turns} "
                  f"耗时={message.duration_ms}ms 费用={message.total_cost_usd}")
            if message.is_error:
                print(f"  → [错误] {message.errors}")


if __name__ == "__main__":
    asyncio.run(main())
