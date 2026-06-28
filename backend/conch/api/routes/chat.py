"""聊天路由 — SSE 流式对话端点。"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from conch.api.deps import (
    _record_guardrail_event,
    _record_observability_event,
    build_runtime,
    get_pending_resume,
    get_profile_loader,
    get_session_store,
    pop_pending_resume,
)
from conch.api.sse import EventType, sse_event

logger = logging.getLogger(__name__)
router = APIRouter()

_RETRIEVAL_SENSITIVE_PATTERNS = [
    "api key",
    "access token",
    "secret",
    "password",
    "private key",
    "ssh-rsa",
    "begin private key",
    "数据库密码",
    "私钥",
    "密钥",
]


class ChatRequest(BaseModel):
    message: str
    profile: str = "user-chat-v1"


class SessionCreate(BaseModel):
    profile: str = "user-chat-v1"


def _tokenize_text(text: str) -> set[str]:
    return {token for token in re.findall(r"[\w\u4e00-\u9fff]+", text.lower()) if token}


def _score_relevance(query: str, text: str) -> float:
    q_tokens = _tokenize_text(query)
    t_tokens = _tokenize_text(text)
    if not q_tokens or not t_tokens:
        return 0.0
    overlap = q_tokens & t_tokens
    if not overlap:
        return 0.0
    return len(overlap) / len(q_tokens)


def _format_memory_item(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        value = item.get("value")
        if isinstance(value, dict):
            role = value.get("role")
            content = value.get("content")
            if role and content:
                return f"{role}: {content}"
        if isinstance(value, str):
            return value
        text = item.get("text")
        if isinstance(text, str) and text:
            return text
    return str(item)


def _get_memory_item_score(item: Any, task: str) -> float:
    if isinstance(item, dict):
        raw_score = item.get("score")
        if isinstance(raw_score, (int, float)):
            return float(raw_score)
        return _score_relevance(task, _format_memory_item(item))
    return _score_relevance(task, _format_memory_item(item))


def _filter_recalled_memories(rt, task: str, recalled: list[Any]) -> list[Any]:
    filtered: list[tuple[float, Any]] = []
    blocked_count = 0
    low_relevance_count = 0

    for item in recalled:
        formatted = _format_memory_item(item)
        normalized = formatted.lower()
        if any(pattern in normalized for pattern in _RETRIEVAL_SENSITIVE_PATTERNS):
            blocked_count += 1
            continue

        score = _get_memory_item_score(item, task)
        if score <= 0.0:
            low_relevance_count += 1
            continue
        filtered.append((score, item))

    filtered.sort(key=lambda pair: pair[0], reverse=True)

    if blocked_count > 0:
        _record_guardrail_event(
            rt,
            rt.state,
            "retrieval",
            "blocked",
            f"Filtered {blocked_count} sensitive memory item(s)",
            extra={"blocked_items": blocked_count},
        )
    if low_relevance_count > 0:
        _record_guardrail_event(
            rt,
            rt.state,
            "retrieval",
            "filtered",
            f"Filtered {low_relevance_count} low-relevance memory item(s)",
            extra={"filtered_items": low_relevance_count},
        )

    _record_observability_event(
        rt,
        "retrieval_recall",
        {
            "session_id": rt.state.session_id if rt.state else "",
            "query": task,
            "recalled": len(recalled),
            "retained": len(filtered),
        },
    )
    return [item for _, item in filtered[:4]]


def _build_memory_context(rt, task: str) -> str | None:
    if rt.memory is None or not hasattr(rt.memory, "recall"):
        return None

    recalled: list[Any] = []
    try:
        for mem_type in ("episodic", "semantic", "long_term", "procedural"):
            recalled.extend(rt.memory.recall(task, mem_type=mem_type, limit=2))
    except Exception:
        logger.exception("Failed to recall memory")
        return None

    if not recalled:
        return None

    recalled = _filter_recalled_memories(rt, task, recalled)
    if not recalled:
        return None

    lines = [_format_memory_item(item) for item in recalled]
    lines = [line for line in lines if line]
    if not lines:
        return None

    return "Relevant memory:\n" + "\n".join(f"- {line}" for line in lines)


def _store_memory_exchange(rt, user_message: str, assistant_message: str) -> None:
    if rt.memory is None or not hasattr(rt.memory, "store"):
        return

    session_id = rt.state.session_id if rt.state else ""
    user_key = f"user:{session_id}:{uuid.uuid4().hex[:8]}"
    assistant_key = f"assistant:{session_id}:{uuid.uuid4().hex[:8]}"

    try:
        rt.memory.store(
            user_key,
            {"role": "user", "session_id": session_id, "content": user_message},
            mem_type="episodic",
        )
        if assistant_message.strip():
            rt.memory.store(
                assistant_key,
                {"role": "assistant", "session_id": session_id, "content": assistant_message},
                mem_type="episodic",
            )
    except Exception:
        logger.exception("Failed to persist conversation memory")


def _append_session_message(session_id: str, role: str, content: str) -> None:
    session = get_session_store().get(session_id)
    if session is None:
        return
    session.setdefault("messages", []).append(
        {"id": uuid.uuid4().hex[:8], "role": role, "content": content}
    )


def _build_agent_config(rt) -> dict[str, Any]:
    return {
        "llm": rt.llm,
        "tools": rt.tools,
        "context": rt.context_mgr,
        "information": rt.info_provider,
        "guardrail_pipeline": rt.guardrail_pipeline,
        "governance": rt.governance,
        "cost_guard": rt.cost_guard,
        "hook_bus": rt.hook_bus,
        "observability": rt.observability,
    }


def _iter_runtime_sse_events(rt):
    for event in rt.state.drain_events():
        evt_type = event.get("type")
        if evt_type == "guardrail":
            yield sse_event(
                EventType.GUARDRAIL,
                {
                    "layer": event.get("layer", "tool"),
                    "action": event.get("action", "blocked"),
                    "reason": event.get("reason", ""),
                    "tool": event.get("tool"),
                },
            )
        elif evt_type == "cost_update":
            yield sse_event(
                EventType.COST_UPDATE,
                {
                    "tokens": event.get("tokens", 0),
                    "cost": event.get("cost", 0.0),
                    "steps": event.get("steps", 0),
                    "degrade_level": event.get("degrade_level", "NONE"),
                },
            )
        elif evt_type == "hitl_request":
            yield sse_event(
                EventType.HITL_REQUEST,
                {
                    "request_id": event.get("request_id", ""),
                    "tool": event.get("tool"),
                    "args": event.get("args", {}),
                    "reason": event.get("reason", ""),
                },
            )


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

    memory_context = _build_memory_context(rt, rt.state.task if rt.state else "")
    if memory_context:
        system_prompt = f"{system_prompt}\n\n{memory_context}" if system_prompt else memory_context

    # 构建图
    if hasattr(orch, "build_graph"):
        orch.build_graph(tools, system_prompt)
    return orch


def _stream_response(session_id: str, message: str, profile_name: str, append_user_message: bool):
    from fastapi.responses import StreamingResponse

    store = get_session_store()
    if session_id not in store:
        raise HTTPException(status_code=404, detail="Session not found")

    # 加载 Profile 并构建运行时
    loader = get_profile_loader()
    try:
        profile = loader.load(profile_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_name}' not found")

    rt = build_runtime(profile, session_id=session_id)
    rt.state.task = message
    if append_user_message:
        _append_session_message(session_id, "user", message)

    # 构建编排图
    orch = _build_orchestrator_graph(rt)
    if orch is None:
        raise HTTPException(status_code=500, detail="No orchestrator configured")

    async def event_generator():
        """SSE 事件生成器。"""
        try:
            agent_config = _build_agent_config(rt)
            assistant_chunks: list[str] = []
            # LangGraph 编排
            if hasattr(orch, "run"):
                async for event in orch.run(message, [agent_config], rt.state):
                    evt_type = event.get("type", "")
                    if evt_type == "text_delta":
                        assistant_chunks.append(event["content"])
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
                        if success:
                            assistant_message = "".join(assistant_chunks)
                            _store_memory_exchange(rt, message, assistant_message)
                            if assistant_message.strip():
                                _append_session_message(session_id, "assistant", assistant_message)
                            pop_pending_resume(session_id)
                        for rt_event in _iter_runtime_sse_events(rt):
                            yield rt_event
                        yield sse_event(EventType.DONE, {
                            "success": success,
                            "error": event.get("error") if not success else None,
                        })
                    for rt_event in _iter_runtime_sse_events(rt):
                        yield rt_event

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


@router.post("/sessions/{session_id}/stream")
async def stream_chat(session_id: str, req: ChatRequest):
    """SSE 流式对话 — 用户发消息，Agent 流式响应。"""
    return _stream_response(session_id, req.message, req.profile, append_user_message=True)


@router.post("/sessions/{session_id}/resume/{request_id}/stream")
async def resume_chat(session_id: str, request_id: str):
    """审批后恢复同一任务，不重复提交用户消息。"""
    pending = get_pending_resume(session_id, request_id)
    if pending is None:
        raise HTTPException(status_code=404, detail="No pending resumable task")

    message = str(pending.get("message", ""))
    profile_name = str(pending.get("profile", "user-chat-v1"))
    if not message:
        raise HTTPException(status_code=400, detail="Pending resumable task is invalid")

    return _stream_response(session_id, message, profile_name, append_user_message=False)
