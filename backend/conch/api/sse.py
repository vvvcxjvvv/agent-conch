"""SSE 流式工具 — 格式化 Server-Sent Events。"""

from __future__ import annotations

import json
from typing import Any


def sse_event(event: str, data: dict[str, Any]) -> str:
    """格式化一条 SSE 事件。

    Args:
        event: 事件类型（text_delta / tool_call / tool_result / guardrail / cost_update / done）
        data: 事件数据

    Returns:
        SSE 格式字符串: "event: xxx\\ndata: {json}\\n\\n"
    """
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# 事件类型常量
class EventType:
    TEXT_DELTA = "text_delta"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    GUARDRAIL = "guardrail"
    COST_UPDATE = "cost_update"
    HITL_REQUEST = "hitl_request"
    DONE = "done"
