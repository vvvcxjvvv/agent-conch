"""聊天路由 — SSE 流式对话端点。"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from conch.api.deps import build_runtime, get_profile_loader, get_session_store
from conch.api.sse import EventType, sse_event

logger = logging.getLogger(__name__)
router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    profile: str = "user-chat-v1"


class SessionCreate(BaseModel):
    profile: str = "user-chat-v1"


def _build_orchestrator_graph(rt):
    """为 LangGraph 编排构建图（注入 tools + system_prompt）。"""
    orch = rt.orchestrator
    if orch is None:
        return None

    # 收集工具
    tools: list[Any] = []
    if rt.tools:
        try:
            tools = rt.tools.tools_for("", rt.state)
        except Exception:
            logger.exception("Failed to get tools")

    # 系统提示
    system_prompt = None
    if rt.info_provider:
        try:
            system_prompt = rt.info_provider.assemble("", rt.state)
        except Exception:
            logger.exception("Failed to assemble system prompt")

    # 构建图
    if hasattr(orch, "build_graph"):
        orch.build_graph(tools, system_prompt)
    return orch


@router.post("/sessions/{session_id}/stream")
async def stream_chat(session_id: str, req: ChatRequest):
    """SSE 流式对话 — 用户发消息，Agent 流式响应。"""
    from fastapi.responses import StreamingResponse

    store = get_session_store()
    if session_id not in store:
        raise HTTPException(status_code=404, detail="Session not found")

    # 加载 Profile 并构建运行时
    loader = get_profile_loader()
    try:
        profile = loader.load(req.profile)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Profile '{req.profile}' not found")

    rt = build_runtime(profile)
    rt.state.task = req.message

    # 构建编排图
    orch = _build_orchestrator_graph(rt)
    if orch is None:
        raise HTTPException(status_code=500, detail="No orchestrator configured")

    async def event_generator():
        """SSE 事件生成器。"""
        try:
            # LangGraph 编排
            if hasattr(orch, "run"):
                async for event in orch.run(req.message, [], rt.state):
                    evt_type = event.get("type", "")
                    if evt_type == "text_delta":
                        yield sse_event(EventType.TEXT_DELTA, {"content": event["content"]})
                    elif evt_type == "tool_call":
                        yield sse_event(EventType.TOOL_CALL, {
                            "tool": event["tool"], "args": event.get("args", {}),
                            "call_id": str(uuid.uuid4())[:8],
                        })
                    elif evt_type == "tool_result":
                        yield sse_event(EventType.TOOL_RESULT, {
                            "tool": event["tool"], "result": event.get("result", ""),
                        })
                    elif evt_type == "guardrail":
                        yield sse_event(EventType.GUARDRAIL, {
                            "action": event.get("action", "blocked"),
                            "reason": event.get("reason", ""),
                        })
                    elif evt_type == "done":
                        success = event.get("success", True)
                        yield sse_event(EventType.DONE, {
                            "success": success,
                            "error": event.get("error") if not success else None,
                        })

            # 成本更新
            yield sse_event(EventType.COST_UPDATE, {
                "tokens": rt.state.total_tokens,
                "cost": rt.state.total_cost,
                "steps": rt.state.steps,
            })

        except Exception as e:
            logger.exception("Stream chat failed")
            yield sse_event(EventType.DONE, {"success": False, "error": str(e)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
