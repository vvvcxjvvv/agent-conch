"""会话管理路由。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from conch.api.deps import get_session_store

router = APIRouter()


class SessionCreate(BaseModel):
    profile: str = "user-chat-v1"
    title: str | None = None


class SessionOut(BaseModel):
    id: str
    profile: str
    title: str
    created_at: str
    messages: list[dict] = []


@router.post("", response_model=SessionOut)
async def create_session(req: SessionCreate):
    """创建新会话。"""
    store = get_session_store()
    session_id = str(uuid.uuid4())
    session = {
        "id": session_id,
        "profile": req.profile,
        "title": req.title or "New Session",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "messages": [],
    }
    store[session_id] = session
    return SessionOut(**session)


@router.get("", response_model=list[SessionOut])
async def list_sessions():
    """列出所有会话。"""
    store = get_session_store()
    return [SessionOut(**s) for s in store.values()]


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(session_id: str):
    """获取会话详情。"""
    store = get_session_store()
    if session_id not in store:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionOut(**store[session_id])


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """删除会话。"""
    store = get_session_store()
    if session_id not in store:
        raise HTTPException(status_code=404, detail="Session not found")
    del store[session_id]
    return {"deleted": session_id}
