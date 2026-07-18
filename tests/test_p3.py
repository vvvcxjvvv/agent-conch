"""P3 可观测、验证、治理、检索与 API 闭环测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agent_conch.api.approvals import ApprovalStore
from agent_conch.api.server import create_app
from agent_conch.config import ConchConfig
from agent_conch.context.memory.manager import MetaMemory
from agent_conch.engine.layers.base import Event, GraphContext, LayerManager, NodeContext
from agent_conch.engine.layers.llm_quota import LLMQuotaLayer
from agent_conch.engine.layers.suspend import PauseStatePersistLayer, SuspendLayer
from agent_conch.observability.decision_trace import DecisionTraceStep, DecisionTraceStore
from agent_conch.observability.events import EventBus
from agent_conch.observability.exit_status import ExitStatus, classify_exit_status
from agent_conch.observability.insights import InsightsEngine
from agent_conch.observability.otel import ObservabilityLayer, OTelTracer
from agent_conch.observability.trace_store import TraceStore
from agent_conch.sandbox.local import CommandResult
from agent_conch.security.audit import SecurityAudit
from agent_conch.state.checkpoint import CheckpointManager
from agent_conch.state.session_db import SessionDB
from agent_conch.tools.base import ToolExecutionRecord, ToolResult
from agent_conch.tools.core.session_search import SessionSearchTool
from agent_conch.verification.layer import VerificationLayer
from agent_conch.verification.report import VerificationStore
from agent_conch.verification.reviewer import Reviewer
from agent_conch.verification.self_review import SelfReview


@pytest.mark.asyncio
async def test_observability_layer_persists_graph_and_node_spans(tmp_db: SessionDB) -> None:
    layer = ObservabilityLayer(OTelTracer(TraceStore(tmp_db)))
    graph = GraphContext(session_id="s1", max_turns=2, max_time=10)
    node = NodeContext(session_id="s1", turn_index=1)

    await layer.on_graph_start(graph)
    await layer.on_node_run_start(node)
    await layer.on_node_run_end(node, [])
    await layer.on_graph_end(graph)

    spans = layer.tracer.store.get_spans("s1")
    assert [span.name for span in spans] == ["agent.run", "agent.node"]
    assert all(span.status == "ok" and span.ended_at is not None for span in spans)


@pytest.mark.asyncio
async def test_llm_quota_aborts_graph() -> None:
    layer = LLMQuotaLayer(max_tokens=10)
    graph = GraphContext(session_id="s1")
    await layer.on_graph_start(graph)
    await layer.on_event(
        Event(
            "llm_usage",
            {"session_id": "s1", "usage": {"total": 11}, "graph_context": graph},
        )
    )
    assert graph.should_abort
    assert "quota exceeded" in graph.abort_reason


@pytest.mark.asyncio
async def test_pause_resume_persists_checkpoint(tmp_db: SessionDB) -> None:
    tmp_db.create_session("s1", cwd="", model_name="test")
    manager = LayerManager()
    suspend = SuspendLayer()
    checkpoints = CheckpointManager(tmp_db)
    manager.add(suspend)
    manager.add(PauseStatePersistLayer(checkpoints))

    await manager.on_event(Event("pause", {"session_id": "s1", "turn_index": 3}))
    checkpoint = await checkpoints.load_checkpoint("s1")
    assert suspend.is_suspended("s1")
    assert checkpoint is not None and checkpoint.status == "paused"

    await manager.on_event(Event("resume", {"session_id": "s1"}))
    assert not suspend.is_suspended("s1")
    assert tmp_db.get_session("s1") is not None
    assert tmp_db.get_session("s1").status == "active"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_verification_runs_after_successful_write(tmp_db: SessionDB) -> None:
    async def runner(command: str, cwd: str | None, timeout: int) -> CommandResult:
        return CommandResult(command, "ok", "", 0, 1, cwd=cwd or "")

    store = VerificationStore(tmp_db)
    layer = VerificationLayer(store, runner, ["ruff check"], "/tmp")
    context = NodeContext(session_id="s1", turn_index=1, response={"content": "done"})
    record = ToolExecutionRecord(
        tool_name="write_file",
        tool_call_id="t1",
        arguments={},
        result=ToolResult.success("written"),
        duration_ms=1,
        status="success",
    )
    await layer.on_node_run_end(context, [record])

    report = store.latest("s1")
    assert report is not None and report.passed
    assert report.agent_claim == "done"
    assert context.metadata["verification_passed"] is True


@pytest.mark.asyncio
async def test_verification_failure_blocks_and_injects_fix_request(tmp_db: SessionDB) -> None:
    async def runner(command: str, cwd: str | None, timeout: int) -> CommandResult:
        return CommandResult(command, "", "broken", 1, 1, cwd=cwd or "")

    layer = VerificationLayer(VerificationStore(tmp_db), runner, ["pytest -q"])
    context = NodeContext(session_id="s1", turn_index=1)
    record = ToolExecutionRecord(
        tool_name="edit_file",
        tool_call_id="t1",
        arguments={},
        result=ToolResult.success("edited"),
        duration_ms=1,
        status="success",
    )
    await layer.on_node_run_end(context, [record])
    assert context.should_block
    assert "pytest -q" in context.inject_messages[0]["content"]


@pytest.mark.asyncio
async def test_reviewer_and_self_review_have_deterministic_fallbacks() -> None:
    selected = await Reviewer().select("task", ["short", "tested answer with 验证"])
    review = await SelfReview().run("task", "answer", verification_passed=True)
    assert selected.selected_index == 1
    assert review.passed


@pytest.mark.asyncio
async def test_session_search_tool_uses_fts(tmp_db: SessionDB) -> None:
    memory = MetaMemory(tmp_db)
    memory.index_session("s1", "implemented observability spans", 3)
    tool = SessionSearchTool(memory)
    result = await tool.execute(query="observability", limit=5)
    assert not result.is_error
    assert "s1" in result.content


def test_security_audit_detects_inline_secret_and_disabled_sandbox() -> None:
    findings = SecurityAudit().scan(
        {"model": {"api_key": "plain-text"}, "sandbox": {"mode": "never"}}
    )
    assert {finding.code for finding in findings} == {"INLINE_SECRET", "SANDBOX_DISABLED"}


def test_insights_aggregates_session_status(tmp_db: SessionDB) -> None:
    tmp_db.create_session("s1", cwd="", model_name="test")
    tmp_db.update_session_status("s1", "completed")
    summary = InsightsEngine(tmp_db).summary()
    assert summary["sessions"] == 1
    assert summary["success_rate"] == 1.0
    assert summary["failure_reasons"] == {}


def test_exit_status_classifies_failure_reason() -> None:
    assert classify_exit_status("aborted", "LLM quota exceeded") is ExitStatus.QUOTA_EXCEEDED


@pytest.mark.asyncio
async def test_event_bus_delivers_sse_payload() -> None:
    bus = EventBus()
    iterator = bus.subscribe("s1").__aiter__()
    pending = asyncio.create_task(iterator.__anext__())
    await asyncio.sleep(0)
    await bus.publish("s1", {"type": "tool_call"})
    assert await pending == {"type": "tool_call"}
    await iterator.aclose()


def test_approval_store_round_trip(tmp_db: SessionDB) -> None:
    store = ApprovalStore(tmp_db)
    approval = store.create("s1", "write memory", "persist knowledge")
    assert len(store.list_pending()) == 1
    decided = store.decide(approval.approval_id, "approved")
    assert decided is not None and decided.status == "approved"
    assert store.list_pending() == []


def test_decision_trace_store_and_api_are_auditable(tmp_db: SessionDB) -> None:
    store = DecisionTraceStore(tmp_db)
    store.save(
        DecisionTraceStep.create(
            "s1",
            1,
            "decide",
            "选择执行工具",
            "选择 read_file 获取任务证据。",
            {"tools": ["read_file"]},
        )
    )
    engine = SimpleNamespace(
        session_db=tmp_db,
        decision_trace_store=store,
        get_tool_health=lambda: {},
    )
    payload = TestClient(create_app(engine)).get("/runs/s1/decisions").json()
    assert payload[0]["phase"] == "decide"
    assert payload[0]["evidence"] == {"tools": ["read_file"]}


def test_http_api_exposes_health_and_approval_flow(tmp_db: SessionDB) -> None:
    engine = SimpleNamespace(
        session_db=tmp_db,
        get_tool_health=lambda: {"bash": {"available": True}},
    )
    client = TestClient(create_app(engine))
    assert client.get("/health").status_code == 200
    created = client.post(
        "/approvals",
        json={"session_id": "s1", "operation": "write", "reason": "test"},
    ).json()
    decided = client.post(
        f"/approvals/{created['approval_id']}/decision", json={"status": "approved"}
    )
    assert decided.status_code == 200
    assert decided.json()["status"] == "approved"


def test_p3_config_loads_from_yaml(tmp_path: Path) -> None:
    path = tmp_path / "conch.yaml"
    path.write_text(
        "layers:\n  enabled: [llm_quota, verification]\n"
        "quota:\n  max_tokens: 123\n"
        "verification:\n  commands: ['pytest -q']\n  review_on_submit: false\n",
        encoding="utf-8",
    )
    config = ConchConfig.load(path)
    assert config.quota.max_tokens == 123
    assert config.verification.commands == ["pytest -q"]
    assert config.verification.review_on_submit is False
