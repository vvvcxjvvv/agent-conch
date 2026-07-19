"""P4 治理、回归、自改进、调度与多 Agent 闭环测试。"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from agent_conch.api.approvals import WriteApprovalStore
from agent_conch.api.server import create_app
from agent_conch.config import ConchConfig
from agent_conch.context.skills.curator import CuratorAction, SkillCurator
from agent_conch.context.skills.registry import Skill, SkillFrontmatter
from agent_conch.engine.conch_engine import ConchEngine
from agent_conch.governance.budget import BudgetLimits, BudgetManager
from agent_conch.governance.scheduler import CronScheduler
from agent_conch.multiagent.coordinator import Coordinator, CoordinatorTask
from agent_conch.multiagent.subagent import SubagentManager
from agent_conch.observability.events import EventBus
from agent_conch.observability.exit_status import ExitStatus, classify_exit_status
from agent_conch.sandbox.local import CommandResult
from agent_conch.sandbox.registry import SandboxMode, SandboxRegistry
from agent_conch.sandbox.snapshots import SnapshotManager
from agent_conch.security.credentials import CredentialPool, CredentialRef
from agent_conch.security.permissions import ALL_PERMISSIONS, RBAC, ActionLevel, Permission
from agent_conch.security.policy_engine import PolicyEffect, PolicyEngine, PolicyRequest
from agent_conch.state.session_db import SessionDB
from agent_conch.tools.base import BaseTool, ToolCall, ToolResult
from agent_conch.tools.registry import ToolRegistry
from agent_conch.verification.regression import RegressionRunner, RegressionStore
from agent_conch.verification.report import VerificationCheck, VerificationReport


class _WriteInput(BaseModel):
    path: str
    content: str


class _WriteTool(BaseTool):
    name = "write_test"
    description = "test write"
    input_model = _WriteInput
    is_write_tool = True
    is_core = True

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, **kwargs: Any) -> ToolResult:
        self.calls += 1
        return ToolResult.success(str(kwargs["content"]))


def test_rbac_has_more_than_forty_permissions_and_denies_unknown_role() -> None:
    assert len(ALL_PERMISSIONS) >= 40
    rbac = RBAC()
    assert rbac.authorize("admin", Permission.SYSTEM_ADMIN).allowed
    assert not rbac.authorize("viewer", Permission.TOOL_WRITE).allowed
    assert not rbac.authorize("unknown", Permission.RUN_READ).allowed


def test_policy_engine_requires_memory_and_skill_write_approval() -> None:
    result = PolicyEngine().evaluate(
        PolicyRequest(
            principal="alice",
            role="admin",
            permission=Permission.TOOL_WRITE,
            action_level=ActionLevel.WRITE,
            tool_name="write_file",
            action="write",
            arguments={"path": "/project/skills/demo/SKILL.md"},
        )
    )
    assert result.effect is PolicyEffect.REQUIRE_APPROVAL
    assert result.matched_rule == "memory_skill_write_approval"


def test_policy_engine_enforces_rbac_before_explicit_rules() -> None:
    result = PolicyEngine().evaluate(
        PolicyRequest(
            principal="guest",
            role="viewer",
            permission=Permission.TOOL_WRITE,
            action_level=ActionLevel.WRITE,
        )
    )
    assert result.effect is PolicyEffect.DENY
    assert result.matched_rule == "rbac"


def test_write_approval_is_idempotent_and_consumed_once(tmp_db: SessionDB) -> None:
    store = WriteApprovalStore(tmp_db)
    payload = {"path": "MEMORY.md", "content": "fact"}
    first = store.create("s1", "write_file", "memory write", payload, "alice", "admin", 4)
    duplicate = store.create("s1", "write_file", "memory write", payload, "alice", "admin", 4)
    assert duplicate.approval_id == first.approval_id
    approved = store.decide(first.approval_id, "approved", "reviewer")
    assert approved is not None and approved.decided_by == "reviewer"
    allowed, consumed = store.authorize_or_request(
        "s1", "write_file", "memory write", payload, "alice", "admin", 4
    )
    assert allowed and consumed.consumed_at is not None
    allowed_again, pending = store.authorize_or_request(
        "s1", "write_file", "memory write", payload, "alice", "admin", 4
    )
    assert not allowed_again and pending.status == "pending"


@pytest.mark.asyncio
async def test_tool_registry_blocks_then_executes_exact_approved_request(tmp_db: SessionDB) -> None:
    approvals = WriteApprovalStore(tmp_db)
    policy = PolicyEngine(approval_level=ActionLevel.WRITE)
    registry = ToolRegistry(governance=policy, approvals=approvals, default_role="admin")
    tool = _WriteTool()
    registry.register(tool)
    call = ToolCall("c1", "write_test", {"path": "file.txt", "content": "value"})
    blocked = await registry.execute_tool_call(call, session_id="s1")
    assert blocked.status == "approval_required" and tool.calls == 0
    approval = approvals.list_pending()[0]
    approvals.decide(approval.approval_id, "approved")
    executed = await registry.execute_tool_call(call, session_id="s1")
    assert executed.status == "success" and tool.calls == 1
    replay = await registry.execute_tool_call(call, session_id="s1")
    assert replay.status == "approval_required" and tool.calls == 1


def test_budget_enforces_tokens_tools_resources_and_status(tmp_db: SessionDB) -> None:
    manager = BudgetManager(tmp_db, BudgetLimits(10, 60, 1, 2))
    manager.start("s1")
    assert manager.record_llm("s1", 10).allowed
    assert manager.consume_tool("s1", 2).allowed
    decision = manager.consume_tool("s1", 1)
    assert not decision.allowed and "Tool call budget exceeded" in decision.reason
    assert manager.summary("s1")["status"] == "breached"


def test_budget_exit_status_is_distinct() -> None:
    assert classify_exit_status("aborted", "Token budget exceeded") is ExitStatus.BUDGET_EXCEEDED


def test_credential_pool_rotates_and_never_exposes_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KEY_ONE", "secret-one")
    monkeypatch.setenv("KEY_TWO", "secret-two")
    pool = CredentialPool(
        [
            CredentialRef("one", "model", "KEY_ONE"),
            CredentialRef("two", "model", "KEY_TWO"),
        ],
        failure_cooldown=60,
    )
    first = pool.acquire("model")
    second = pool.acquire("model")
    assert first is not None and second is not None and first.alias != second.alias
    assert all("secret" not in str(item) for item in pool.metadata())
    pool.record_failure(first.alias)
    assert pool.acquire("model") is not None


def test_credential_pool_resolves_bitwarden_and_one_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert kwargs["timeout"] == 10 and kwargs["check"] is False
        return subprocess.CompletedProcess(command, 0, stdout="vault-secret\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    pool = CredentialPool(
        [
            CredentialRef("bw", "one", "item-id", backend="bitwarden"),
            CredentialRef("op", "two", "op://vault/item/password", backend="1password"),
        ]
    )
    assert pool.acquire("one").secret == "vault-secret"  # type: ignore[union-attr]
    assert pool.acquire("two").secret == "vault-secret"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_failed_verification_is_deduplicated_and_becomes_regression_gate(
    tmp_db: SessionDB,
) -> None:
    store = RegressionStore(tmp_db)
    report = VerificationReport.create(
        "s1",
        1,
        "fix lint",
        [VerificationCheck("ruff", "ruff check", False, 1, "failure", 10)],
    )
    first = store.capture(report)
    second = store.capture(report)
    assert first is not None and second is not None and first.case_id == second.case_id

    async def runner(command: str, cwd: str | None, timeout: int) -> CommandResult:
        return CommandResult(command=command, stdout="ok", stderr="", exit_code=0, duration_ms=1)

    summary = await RegressionRunner(store, runner).run_all()
    assert summary["gate_passed"] and summary["pass_rate"] == 1.0


def test_curator_archives_only_after_approval(tmp_db: SessionDB, tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "old"
    skill_dir.mkdir(parents=True)
    path = skill_dir / "SKILL.md"
    path.write_text("deprecated", encoding="utf-8")
    skill = Skill(
        SkillFrontmatter(
            name="old",
            description="old",
            agent_created=True,
            metadata={"deprecated": True},
        ),
        "deprecated",
        str(path),
    )
    curator = SkillCurator(tmp_db, tmp_path / "archive")
    proposal = curator.analyze({"old": skill})[0]
    assert proposal.action is CuratorAction.ARCHIVE
    with pytest.raises(PermissionError):
        curator.apply(proposal.proposal_id)
    applied = curator.apply(proposal.proposal_id, approved=True)
    assert applied.status == "applied"
    assert not skill_dir.exists() and (tmp_path / "archive" / "old").exists()


def test_cron_parser_computes_next_minute() -> None:
    assert CronScheduler.next_run_after("* * * * *", 0) == 60
    with pytest.raises(ValueError):
        CronScheduler.validate_cron("invalid")


@pytest.mark.asyncio
async def test_scheduler_runs_due_task_and_persists_result(tmp_db: SessionDB) -> None:
    async def runner(task: str, session_id: str) -> dict[str, str]:
        return {"task": task, "session": session_id}

    scheduler = CronScheduler(tmp_db, runner)
    schedule = scheduler.create("minute", "* * * * *", "health", now=0)
    runs = await scheduler.run_due(now=60)
    assert len(runs) == 1 and runs[0].status == "completed"
    assert scheduler.list_schedules()[0].next_run_at > schedule.next_run_at


@pytest.mark.asyncio
async def test_coordinator_isolates_workers_and_preserves_result_order(tmp_db: SessionDB) -> None:
    tmp_db.create_session("parent")
    manager = SubagentManager(tmp_db)

    async def runner(record: Any, role: str, metadata: dict[str, Any]) -> str:
        assert metadata["context_isolated"] is True
        return f"{record.task}:{role}"

    coordinator = Coordinator(tmp_db, manager, runner, max_workers=2)
    result = await coordinator.execute(
        "parent",
        [CoordinatorTask("one"), CoordinatorTask("two")],
    )
    assert result.status == "completed"
    assert [item["result"] for item in result.summary["workers"]] == [
        "one:worker",
        "two:worker",
    ]
    assert len(manager.list_by_parent("parent")) == 2


@pytest.mark.asyncio
async def test_snapshot_manager_tracks_create_restore_delete(tmp_db: SessionDB) -> None:
    class Backend:
        async def snapshot(self, session_id: str, tag: str = "") -> str:
            return f"snapshot:{session_id}:{tag}"

        async def restore_snapshot(self, session_id: str, snapshot_tag: str) -> bool:
            return snapshot_tag.startswith("snapshot:")

        async def remove_snapshot(self, snapshot_tag: str) -> bool:
            return snapshot_tag.startswith("snapshot:")

    registry = SandboxRegistry(SandboxMode.ALWAYS)
    registry.register("fake", Backend())  # type: ignore[arg-type]
    registry.set_default("fake")
    manager = SnapshotManager(tmp_db, registry)
    created = await manager.create("s1", "before")
    assert (await manager.restore(created.snapshot_id)).status == "restored"
    assert await manager.delete(created.snapshot_id)
    assert manager.get(created.snapshot_id).status == "deleted"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_sqlite_event_bus_delivers_across_instances(tmp_db: SessionDB) -> None:
    subscriber = EventBus(tmp_db, poll_interval=0.001)
    publisher = EventBus(tmp_db, poll_interval=0.001)
    iterator = subscriber.subscribe("s1").__aiter__()
    pending = asyncio.create_task(iterator.__anext__())
    await asyncio.sleep(0.01)
    await publisher.publish("s1", {"type": "shared"})
    assert await asyncio.wait_for(pending, timeout=1) == {"type": "shared"}
    await iterator.aclose()


def test_p4_config_loads_governance_budget_and_scheduler(tmp_path: Path) -> None:
    path = tmp_path / "conch.yaml"
    path.write_text(
        "governance:\n  default_role: maintainer\n  approval_level: 5\n"
        "budget:\n  max_tokens: 42\n  max_seconds: 7\n"
        "scheduler:\n  hard_timeout: 120\n",
        encoding="utf-8",
    )
    config = ConchConfig.load(path)
    assert config.governance.default_role == "maintainer"
    assert config.budget.max_tokens == 42
    assert config.scheduler.hard_timeout == 120


def test_api_enforces_rbac_before_starting_run(tmp_db: SessionDB) -> None:
    engine = SimpleNamespace(
        session_db=tmp_db,
        config=ConchConfig(),
        rbac=RBAC(),
        get_tool_health=lambda: {},
    )
    response = TestClient(create_app(engine)).post(
        "/runs",
        headers={"X-Conch-Role": "viewer"},
        json={"input": "test"},
    )
    assert response.status_code == 403


def test_desktop_terminal_uses_rbac_policy_budget_and_audit(tmp_path: Path) -> None:
    config = ConchConfig()
    config.state.storage_dir = str(tmp_path / "state")
    engine = ConchEngine(config, cwd=str(tmp_path))
    client = TestClient(create_app(engine))
    payload = {
        "session_id": "desktop-session",
        "command": "printf desktop > terminal-result.txt",
        "cwd": str(tmp_path),
        "timeout": 10,
    }
    try:
        denied = client.post(
            "/desktop/terminal",
            headers={"X-Conch-Role": "viewer"},
            json=payload,
        )
        assert denied.status_code == 403

        executed = client.post(
            "/desktop/terminal",
            headers={"X-Conch-Principal": "desktop", "X-Conch-Role": "developer"},
            json=payload,
        )
        assert executed.status_code == 200
        assert executed.json()["status"] == "success"
        assert (tmp_path / "terminal-result.txt").read_text(encoding="utf-8") == "desktop"
        steps = engine.trajectory_store.get_steps("desktop-session")
        assert steps[-1].metadata["source"] == "desktop_terminal"
        assert engine.budget_manager.summary("desktop-session")["used_tool_calls"] == 1
    finally:
        engine.close()
