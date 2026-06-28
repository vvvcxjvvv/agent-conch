"""HITL 审批管理与 WebSocket 推送。"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import asdict, dataclass
from typing import Any

from fastapi import WebSocket


@dataclass
class HitlRequest:
    request_id: str
    session_id: str
    tool: str
    args: dict[str, Any]
    reason: str
    signature: str
    status: str = "pending"


class ApprovalManager:
    """会话级审批管理。

    当前实现为一次性审批令牌：
    - 首次命中需要审批的工具调用时创建 pending request
    - 用户批准后生成一次性 grant
    - 下次完全相同的 tool+args 命中时消费 grant 放行
    """

    def __init__(self):
        self._requests: dict[str, HitlRequest] = {}
        self._pending_by_session: dict[str, dict[str, str]] = {}
        self._approved_signatures: dict[str, set[str]] = {}

    def signature(self, tool: str, args: dict[str, Any]) -> str:
        payload = {"tool": tool, "args": args}
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def create_request(
        self, session_id: str, tool: str, args: dict[str, Any], reason: str
    ) -> HitlRequest:
        signature = self.signature(tool, args)
        pending = self._pending_by_session.setdefault(session_id, {})
        existing_request_id = pending.get(signature)
        if existing_request_id:
            return self._requests[existing_request_id]

        request = HitlRequest(
            request_id=str(uuid.uuid4()),
            session_id=session_id,
            tool=tool,
            args=args,
            reason=reason,
            signature=signature,
        )
        self._requests[request.request_id] = request
        pending[signature] = request.request_id
        return request

    def list_pending(self, session_id: str) -> list[HitlRequest]:
        request_ids = self._pending_by_session.get(session_id, {}).values()
        return [self._requests[rid] for rid in request_ids if self._requests[rid].status == "pending"]

    def consume_approval(self, session_id: str, tool: str, args: dict[str, Any]) -> bool:
        signature = self.signature(tool, args)
        approved = self._approved_signatures.get(session_id, set())
        if signature not in approved:
            return False
        approved.remove(signature)
        if not approved:
            self._approved_signatures.pop(session_id, None)
        return True

    def decide(self, request_id: str, decision: str) -> HitlRequest:
        if request_id not in self._requests:
            raise KeyError(f"Unknown HITL request: {request_id}")

        request = self._requests[request_id]
        if request.status != "pending":
            return request

        if decision not in {"approved", "denied"}:
            raise ValueError(f"Unsupported decision: {decision}")

        request.status = decision
        pending = self._pending_by_session.get(request.session_id, {})
        pending.pop(request.signature, None)
        if not pending:
            self._pending_by_session.pop(request.session_id, None)

        if decision == "approved":
            self._approved_signatures.setdefault(request.session_id, set()).add(request.signature)
        return request

    def request_payload(self, request: HitlRequest) -> dict[str, Any]:
        payload = asdict(request)
        payload["type"] = "hitl_request"
        return payload

    def decision_payload(self, request: HitlRequest) -> dict[str, Any]:
        return {
            "type": "hitl_decision",
            "request_id": request.request_id,
            "status": request.status,
            "tool": request.tool,
            "args": request.args,
            "reason": request.reason,
        }


class WebSocketHub:
    """会话级 WebSocket 广播。"""

    def __init__(self):
        self._connections: dict[str, set[WebSocket]] = {}

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.setdefault(session_id, set()).add(websocket)

    def disconnect(self, session_id: str, websocket: WebSocket) -> None:
        connections = self._connections.get(session_id)
        if not connections:
            return
        connections.discard(websocket)
        if not connections:
            self._connections.pop(session_id, None)

    async def broadcast(self, session_id: str, payload: dict[str, Any]) -> None:
        for websocket in list(self._connections.get(session_id, set())):
            try:
                await websocket.send_json(payload)
            except Exception:
                self.disconnect(session_id, websocket)

    def emit(self, session_id: str, payload: dict[str, Any]) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.broadcast(session_id, payload))
