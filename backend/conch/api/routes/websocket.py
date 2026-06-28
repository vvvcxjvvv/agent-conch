"""HITL WebSocket 路由。"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from conch.api.deps import (
    get_approval_manager,
    get_pending_resume,
    get_session_store,
    get_websocket_hub,
    pop_pending_resume,
)

router = APIRouter()


@router.websocket("/sessions/{session_id}/ws")
async def session_hitl_ws(websocket: WebSocket, session_id: str):
    """会话级 WebSocket：审批请求推送与 approve/deny 回写。"""
    store = get_session_store()
    if session_id not in store:
        await websocket.close(code=4404)
        return

    hub = get_websocket_hub()
    approval_manager = get_approval_manager()
    await hub.connect(session_id, websocket)

    try:
        for request in approval_manager.list_pending(session_id):
            await websocket.send_json(approval_manager.request_payload(request))

        while True:
            payload = await websocket.receive_json()
            action = payload.get("action")
            if action == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            if action not in {"approve", "deny"}:
                await websocket.send_json({"type": "error", "message": "Unsupported action"})
                continue

            request_id = str(payload.get("request_id", ""))
            if not request_id:
                await websocket.send_json({"type": "error", "message": "request_id is required"})
                continue

            decision = "approved" if action == "approve" else "denied"
            request = approval_manager.decide(request_id, decision)
            if decision == "denied":
                pop_pending_resume(session_id, request_id)
            message = approval_manager.decision_payload(request)
            pending = get_pending_resume(session_id, request_id)
            if pending is not None:
                message["resume_available"] = decision == "approved"
            await hub.broadcast(session_id, message)
    except WebSocketDisconnect:
        hub.disconnect(session_id, websocket)
    except Exception:
        hub.disconnect(session_id, websocket)
        raise
