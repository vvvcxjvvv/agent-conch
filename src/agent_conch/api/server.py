"""P3 Webhook / HTTP API / SSE 服务。"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import asdict
from typing import Any, cast

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agent_conch.api.approvals import ApprovalStore
from agent_conch.config import ConchConfig
from agent_conch.multiagent.coordinator import CoordinatorTask
from agent_conch.security.permissions import RBAC, Permission
from agent_conch.state.trajectory import TrajectoryStep
from agent_conch.tools.base import ToolCall


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


class RegressionStateRequest(BaseModel):
    enabled: bool


class ScheduleRequest(BaseModel):
    name: str = Field(..., min_length=1)
    cron: str = Field(..., min_length=1)
    task: str = Field(..., min_length=1)
    timeout_seconds: int = Field(default=180, ge=1, le=180)
    enabled: bool = True


class ScheduleStateRequest(BaseModel):
    enabled: bool


class CoordinatorTaskRequest(BaseModel):
    task: str = Field(..., min_length=1)
    capability: str = "general"
    metadata: dict[str, Any] = Field(default_factory=dict)


class CoordinatorRequest(BaseModel):
    parent_session_id: str
    tasks: list[CoordinatorTaskRequest] = Field(..., min_length=1)
    strategy: str = "parallel"


class CuratorApplyRequest(BaseModel):
    session_id: str


class SnapshotRequest(BaseModel):
    session_id: str
    tag: str = ""


class DesktopTerminalRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    command: str = Field(..., min_length=1)
    cwd: str | None = None
    timeout: int = Field(default=120, ge=1, le=180)


def create_app(engine: Any) -> FastAPI:
    app = FastAPI(title="Agent-Conch API", version="0.4.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    approvals = getattr(engine, "approval_store", None) or ApprovalStore(engine.session_db)
    config = getattr(engine, "config", None) or ConchConfig()
    rbac = getattr(engine, "rbac", None) or RBAC()

    def identity(principal: str | None, role: str | None) -> tuple[str, str]:
        return principal or "local", role or config.governance.default_role

    def require(role: str, permission: Permission) -> None:
        authorization = rbac.authorize(role, permission)
        if not authorization.allowed:
            raise HTTPException(status_code=403, detail=authorization.reason)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "tools": engine.get_tool_health()}

    @app.post("/runs")
    @app.post("/webhooks/run")
    async def run_agent(
        request: RunRequest,
        x_conch_principal: str | None = Header(default=None),
        x_conch_role: str | None = Header(default=None),
    ) -> dict[str, Any]:
        session_id = request.session_id or uuid.uuid4().hex[:12]
        principal, role = identity(x_conch_principal, x_conch_role)
        require(role, Permission.RUN_CREATE)
        result = await engine.run(request.input, session_id, principal=principal, role=role)
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
    async def list_approvals(
        x_conch_role: str | None = Header(default=None),
    ) -> list[dict[str, Any]]:
        _, role = identity(None, x_conch_role)
        require(role, Permission.APPROVAL_READ)
        return [asdict(item) for item in approvals.list_pending()]

    @app.post("/approvals")
    async def create_approval(
        request: ApprovalRequest,
        x_conch_principal: str | None = Header(default=None),
        x_conch_role: str | None = Header(default=None),
    ) -> dict[str, Any]:
        principal, role = identity(x_conch_principal, x_conch_role)
        require(role, Permission.APPROVAL_CREATE)
        return asdict(approvals.create(request.session_id, request.operation, request.reason))

    @app.post("/approvals/{approval_id}/decision")
    async def decide_approval(
        approval_id: str,
        request: ApprovalDecision,
        x_conch_principal: str | None = Header(default=None),
        x_conch_role: str | None = Header(default=None),
    ) -> dict[str, Any]:
        principal, role = identity(x_conch_principal, x_conch_role)
        require(role, Permission.APPROVAL_DECIDE)
        try:
            approval = approvals.decide(approval_id, request.status, principal)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if approval is None:
            raise HTTPException(status_code=404, detail="Approval not found")
        if (
            approval.status == "approved"
            and approval.payload
            and engine.tool_registry.get(approval.operation) is not None
        ):
            await engine.resume_approval(approval)
        return asdict(approval)

    @app.get("/governance/overview")
    async def governance_overview(
        x_conch_role: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _, role = identity(None, x_conch_role)
        require(role, Permission.POLICY_READ)
        return cast(dict[str, Any], engine.governance_overview())

    @app.get("/governance/policy")
    async def governance_policy(
        x_conch_role: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _, role = identity(None, x_conch_role)
        require(role, Permission.POLICY_READ)
        return cast(dict[str, Any], engine.policy_engine.describe())

    @app.get("/governance/roles")
    async def governance_roles(
        x_conch_role: str | None = Header(default=None),
    ) -> dict[str, list[str]]:
        _, role = identity(None, x_conch_role)
        require(role, Permission.ROLE_READ)
        return rbac.roles()

    @app.get("/budgets/{session_id}")
    async def budget(
        session_id: str,
        x_conch_role: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _, role = identity(None, x_conch_role)
        require(role, Permission.BUDGET_READ)
        return cast(dict[str, Any], engine.budget_manager.summary(session_id))

    @app.get("/credentials")
    async def credentials(
        x_conch_role: str | None = Header(default=None),
    ) -> list[dict[str, object]]:
        _, role = identity(None, x_conch_role)
        require(role, Permission.CREDENTIAL_READ)
        return cast(list[dict[str, object]], engine.credential_pool.metadata())

    @app.get("/regressions")
    async def regressions(
        x_conch_role: str | None = Header(default=None),
    ) -> list[dict[str, Any]]:
        _, role = identity(None, x_conch_role)
        require(role, Permission.REGRESSION_READ)
        return [asdict(case) for case in engine.regression_store.list_cases()]

    @app.post("/regressions/run")
    async def run_regressions(
        x_conch_role: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _, role = identity(None, x_conch_role)
        require(role, Permission.REGRESSION_RUN)
        return cast(dict[str, Any], await engine.regression_runner.run_all())

    @app.post("/regressions/{case_id}/enabled")
    async def set_regression_state(
        case_id: str,
        request: RegressionStateRequest,
        x_conch_role: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _, role = identity(None, x_conch_role)
        require(role, Permission.REGRESSION_WRITE)
        if not engine.regression_store.set_enabled(case_id, request.enabled):
            raise HTTPException(status_code=404, detail="Regression case not found")
        return {"case_id": case_id, "enabled": request.enabled}

    @app.get("/curator/proposals")
    async def curator_proposals(
        x_conch_role: str | None = Header(default=None),
    ) -> list[dict[str, Any]]:
        _, role = identity(None, x_conch_role)
        require(role, Permission.SKILL_READ)
        return [asdict(item) for item in engine.skill_curator.list_proposals()]

    @app.post("/curator/analyze")
    async def analyze_skills(
        x_conch_role: str | None = Header(default=None),
    ) -> list[dict[str, Any]]:
        _, role = identity(None, x_conch_role)
        require(role, Permission.SKILL_READ)
        engine.skills = engine.skill_loader.load_all()
        return [asdict(item) for item in engine.skill_curator.analyze(engine.skills)]

    @app.post("/curator/proposals/{proposal_id}/apply")
    async def apply_curator_proposal(
        proposal_id: str,
        request: CuratorApplyRequest,
        x_conch_principal: str | None = Header(default=None),
        x_conch_role: str | None = Header(default=None),
    ) -> dict[str, Any]:
        principal, role = identity(x_conch_principal, x_conch_role)
        require(role, Permission.SKILL_WRITE)
        payload = {"proposal_id": proposal_id}
        authorized, approval = approvals.authorize_or_request(
            request.session_id,
            "curator_apply",
            "Skill Curator changes require approval",
            payload,
            principal,
            role,
            4,
        )
        if not authorized:
            return {"status": "approval_required", "approval": asdict(approval)}
        return asdict(engine.skill_curator.apply(proposal_id, approved=True))

    @app.get("/schedules")
    async def schedules(
        x_conch_role: str | None = Header(default=None),
    ) -> list[dict[str, Any]]:
        _, role = identity(None, x_conch_role)
        require(role, Permission.SCHEDULE_READ)
        return [asdict(item) for item in engine.scheduler.list_schedules()]

    @app.post("/schedules")
    async def create_schedule(
        request: ScheduleRequest,
        x_conch_role: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _, role = identity(None, x_conch_role)
        require(role, Permission.SCHEDULE_WRITE)
        try:
            schedule = engine.scheduler.create(
                request.name,
                request.cron,
                request.task,
                request.timeout_seconds,
                request.enabled,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(schedule)

    @app.post("/schedules/{schedule_id}/enabled")
    async def set_schedule_state(
        schedule_id: str,
        request: ScheduleStateRequest,
        x_conch_role: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _, role = identity(None, x_conch_role)
        require(role, Permission.SCHEDULE_WRITE)
        if not engine.scheduler.set_enabled(schedule_id, request.enabled):
            raise HTTPException(status_code=404, detail="Schedule not found")
        return {"schedule_id": schedule_id, "enabled": request.enabled}

    @app.post("/schedules/run-due")
    async def run_due_schedules(
        x_conch_role: str | None = Header(default=None),
    ) -> list[dict[str, Any]]:
        _, role = identity(None, x_conch_role)
        require(role, Permission.SCHEDULE_RUN)
        return [asdict(item) for item in await engine.scheduler.run_due()]

    @app.get("/coordinator/runs")
    async def coordinator_runs(
        x_conch_role: str | None = Header(default=None),
    ) -> list[dict[str, Any]]:
        _, role = identity(None, x_conch_role)
        require(role, Permission.COORDINATOR_READ)
        return [asdict(item) for item in engine.coordinator.list_runs()]

    @app.post("/coordinator/runs")
    async def run_coordinator(
        request: CoordinatorRequest,
        x_conch_role: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _, role = identity(None, x_conch_role)
        require(role, Permission.COORDINATOR_RUN)
        try:
            result = await engine.coordinator.execute(
                request.parent_session_id,
                [CoordinatorTask(**item.model_dump()) for item in request.tasks],
                request.strategy,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(result)

    @app.get("/snapshots/{session_id}")
    async def snapshots(
        session_id: str,
        x_conch_role: str | None = Header(default=None),
    ) -> list[dict[str, Any]]:
        _, role = identity(None, x_conch_role)
        require(role, Permission.SNAPSHOT_READ)
        return [asdict(item) for item in engine.snapshot_manager.list_for_session(session_id)]

    @app.post("/snapshots")
    async def create_snapshot(
        request: SnapshotRequest,
        x_conch_role: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _, role = identity(None, x_conch_role)
        require(role, Permission.SNAPSHOT_CREATE)
        try:
            return asdict(await engine.snapshot_manager.create(request.session_id, request.tag))
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/snapshots/{snapshot_id}/restore")
    async def restore_snapshot(
        snapshot_id: str,
        x_conch_role: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _, role = identity(None, x_conch_role)
        require(role, Permission.SNAPSHOT_RESTORE)
        try:
            return asdict(await engine.snapshot_manager.restore(snapshot_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.delete("/snapshots/{snapshot_id}")
    async def delete_snapshot(
        snapshot_id: str,
        x_conch_role: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _, role = identity(None, x_conch_role)
        require(role, Permission.SNAPSHOT_DELETE)
        if not await engine.snapshot_manager.delete(snapshot_id):
            raise HTTPException(status_code=404, detail="Snapshot not found or deletion failed")
        return {"snapshot_id": snapshot_id, "status": "deleted"}

    @app.post("/desktop/terminal")
    async def desktop_terminal(
        request: DesktopTerminalRequest,
        x_conch_principal: str | None = Header(default=None),
        x_conch_role: str | None = Header(default=None),
    ) -> dict[str, Any]:
        principal, role = identity(x_conch_principal, x_conch_role)
        require(role, Permission.TOOL_EXECUTE)
        if engine.session_db.get_session(request.session_id) is None:
            engine.session_db.create_session(
                request.session_id,
                cwd=request.cwd or getattr(engine, "cwd", ""),
                metadata={"source": "desktop_terminal", "principal": principal},
            )
        engine.tool_registry.set_session_identity(request.session_id, principal, role)
        try:
            record = await engine.tool_registry.execute_tool_call(
                ToolCall(
                    id=f"desktop-{uuid.uuid4().hex[:12]}",
                    name="bash",
                    arguments={
                        "command": request.command,
                        "cwd": request.cwd,
                        "timeout": request.timeout,
                    },
                ),
                session_id=request.session_id,
                principal=principal,
                role=role,
                sandbox_mode="main",
            )
        finally:
            engine.tool_registry.clear_session_identity(request.session_id)
        engine.trajectory_store.save_step(
            TrajectoryStep(
                session_id=request.session_id,
                turn_index=0,
                step_type="tool_call",
                tool_name=record.tool_name,
                tool_input=record.arguments,
                tool_output=record.result.content[:2000],
                tool_status=record.status,
                duration_ms=record.duration_ms,
                metadata={"source": "desktop_terminal", "principal": principal},
            )
        )
        await engine.event_bus.publish(
            request.session_id,
            {
                "type": "desktop_terminal",
                "tool_name": record.tool_name,
                "status": record.status,
            },
        )
        return asdict(record)

    return app
