"""P3 Webhook / HTTP API / SSE 服务。"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import asdict
from typing import Any, cast

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agent_conch.api.approvals import ApprovalStore


class RunRequest(BaseModel):
    input: str = Field(..., min_length=1)
    session_id: str | None = None


class ApprovalRequest(BaseModel):
    session_id: str
    operation: str
    reason: str


class ApprovalDecision(BaseModel):
    status: str


class ReviewRequest(BaseModel):
    task: str
    candidates: list[str]


def create_app(engine: Any) -> FastAPI:
    app = FastAPI(title="Agent-Conch API", version="0.3.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    approvals = ApprovalStore(engine.session_db)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "tools": engine.get_tool_health()}

    @app.post("/runs")
    @app.post("/webhooks/run")
    async def run_agent(request: RunRequest) -> dict[str, Any]:
        session_id = request.session_id or uuid.uuid4().hex[:12]
        result = await engine.run(request.input, session_id)
        return asdict(result)

    @app.get("/runs/{session_id}/trajectory")
    async def trajectory(session_id: str) -> list[dict[str, Any]]:
        return [asdict(step) for step in engine.trajectory_store.get_steps(session_id)]

    @app.get("/runs/{session_id}/traces")
    async def traces(session_id: str) -> list[dict[str, Any]]:
        return [asdict(span) for span in engine.trace_store.get_spans(session_id)]

    @app.get("/runs/{session_id}/decisions")
    async def decisions(session_id: str) -> list[dict[str, Any]]:
        return [asdict(step) for step in engine.decision_trace_store.list_for_session(session_id)]

    @app.get("/runs/{session_id}/verification")
    async def verification(session_id: str) -> list[dict[str, Any]]:
        return [asdict(report) for report in engine.verification_store.list_for_session(session_id)]

    @app.get("/events/{session_id}")
    async def events(session_id: str) -> StreamingResponse:
        async def stream() -> Any:
            iterator = engine.event_bus.subscribe(session_id).__aiter__()
            while True:
                try:
                    event = await asyncio.wait_for(iterator.__anext__(), timeout=15)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except TimeoutError:
                    yield ": heartbeat\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/sessions/search")
    async def search_sessions(query: str, limit: int = 10) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], engine.memory_manager.meta_memory.search(query, limit))

    @app.get("/insights")
    async def insights() -> dict[str, Any]:
        return cast(dict[str, Any], engine.insights.summary())

    @app.get("/security/audit")
    async def security_audit() -> list[dict[str, Any]]:
        return [asdict(finding) for finding in engine.run_security_audit()]

    @app.post("/review")
    async def review(request: ReviewRequest) -> dict[str, Any]:
        return asdict(await engine.reviewer.select(request.task, request.candidates))

    @app.get("/approvals")
    async def list_approvals() -> list[dict[str, Any]]:
        return [asdict(item) for item in approvals.list_pending()]

    @app.post("/approvals")
    async def create_approval(request: ApprovalRequest) -> dict[str, Any]:
        return asdict(approvals.create(request.session_id, request.operation, request.reason))

    @app.post("/approvals/{approval_id}/decision")
    async def decide_approval(approval_id: str, request: ApprovalDecision) -> dict[str, Any]:
        try:
            approval = approvals.decide(approval_id, request.status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if approval is None:
            raise HTTPException(status_code=404, detail="Approval not found")
        return asdict(approval)

    return app
