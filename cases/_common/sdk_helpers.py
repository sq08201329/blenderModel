"""SDK 消息流调试／展示公共函数。

放在 cases/_common/ 下，与编号案例分开。案例按路径运行时 cases/ 会进入
sys.path，因此脚本里可直接 import：

    from _common.sdk_helpers import dump_message, dump_stream

三种用法：

    # ① 只打印一条
    dump_message(msg)

    # ② 拿到字符串自己处理（写日志、着色、断言）
    text = format_message(msg)

    # ③ 套在消息流上：逐条打印并原样 yield，不打断原有逻辑
    async for msg in dump_stream(query(prompt="...", options=opts)):
        ...

说明：所有 Message 都是 dataclass，`asdict()` 能递归展开嵌套的
content block，因此下面不会漏字段；`ensure_ascii=False` 保证中文可读。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import asdict, is_dataclass
from typing import Any, TypeVar

T = TypeVar("T")


def format_message(msg: Any, *, indent: int = 2) -> str:
    """把一条 Message 格式化成「[类型名] + 完整 JSON」字符串。

    非 dataclass 的兜底值用 repr 包一层；遇到不可 JSON 序列化的对象用 str 转换。
    """
    name = type(msg).__name__
    if is_dataclass(msg) and not isinstance(msg, type):
        data: Any = asdict(msg)
    else:
        data = {"raw": repr(msg)}
    body = json.dumps(data, ensure_ascii=False, indent=indent, default=str)
    return f"[{name}]\n{body}"


def dump_message(msg: Any, *, indent: int = 2, max_len: int | None = None) -> None:
    """打印一条 Message。max_len 用于截断超长的工具结果，None 表示完整打印。"""
    text = format_message(msg, indent=indent)
    if max_len is not None and len(text) > max_len:
        text = text[:max_len] + f"\n... (截断，共 {len(text)} 字符)"
    print(text)


async def dump_stream(
    stream: AsyncIterable[T],
    *,
    indent: int = 2,
    max_len: int | None = None,
) -> AsyncIterator[T]:
    """包装异步消息流：每条消息打印后原样 yield，可直接套在 query() 外面。"""
    async for msg in stream:
        dump_message(msg, indent=indent, max_len=max_len)
        yield msg
