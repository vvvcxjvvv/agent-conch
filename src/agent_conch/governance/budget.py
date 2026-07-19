"""G/S 层：单任务 Token、时间、工具与资源预算熔断。"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any

from agent_conch.engine.layers.base import Event, GraphContext, Layer
from agent_conch.state.session_db import SessionDB


@dataclass(frozen=True)
class BudgetLimits:
    max_tokens: int = 200_000
    max_seconds: int = 600
    max_tool_calls: int = 500
    max_resource_units: int = 1_000


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    reason: str = ""


class BudgetManager:
    def __init__(self, db: SessionDB, default_limits: BudgetLimits | None = None) -> None:
        self.db = db
        self.default_limits = default_limits or BudgetLimits()
        self.db.conn.executescript("""
            CREATE TABLE IF NOT EXISTS run_budgets (
                session_id TEXT PRIMARY KEY,
                max_tokens INTEGER NOT NULL,
                max_seconds INTEGER NOT NULL,
                max_tool_calls INTEGER NOT NULL,
                max_resource_units INTEGER NOT NULL,
                used_tokens INTEGER NOT NULL DEFAULT 0,
                used_tool_calls INTEGER NOT NULL DEFAULT 0,
                used_resource_units INTEGER NOT NULL DEFAULT 0,
                started_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                breach_reason TEXT NOT NULL DEFAULT ''
            );
        """)
        self.db.conn.commit()

    def start(self, session_id: str, limits: BudgetLimits | None = None) -> None:
        current = limits or self.default_limits
        now = time.time()
        self.db.conn.execute(
            "INSERT INTO run_budgets VALUES (?, ?, ?, ?, ?, 0, 0, 0, ?, ?, 'active', '') "
            "ON CONFLICT(session_id) DO UPDATE SET "
            "max_tokens=excluded.max_tokens, max_seconds=excluded.max_seconds, "
            "max_tool_calls=excluded.max_tool_calls, max_resource_units=excluded.max_resource_units, "
            "used_tokens=0, used_tool_calls=0, used_resource_units=0, "
            "started_at=excluded.started_at, updated_at=excluded.updated_at, "
            "status='active', breach_reason=''",
            (
                session_id,
                current.max_tokens,
                current.max_seconds,
                current.max_tool_calls,
                current.max_resource_units,
                now,
                now,
            ),
        )
        self.db.conn.commit()

    def record_llm(self, session_id: str, tokens: int) -> BudgetDecision:
        row = self._ensure(session_id)
        used = int(row["used_tokens"]) + max(tokens, 0)
        self.db.conn.execute(
            "UPDATE run_budgets SET used_tokens = ?, updated_at = ? WHERE session_id = ?",
            (used, time.time(), session_id),
        )
        self.db.conn.commit()
        if used > int(row["max_tokens"]):
            return self._breach(session_id, f"Token budget exceeded: {used} > {row['max_tokens']}")
        return self.check(session_id)

    def consume_tool(self, session_id: str, resource_units: int = 1) -> BudgetDecision:
        row = self._ensure(session_id)
        time_decision = self._check_time(row)
        if not time_decision.allowed:
            return self._breach(session_id, time_decision.reason)
        next_calls = int(row["used_tool_calls"]) + 1
        next_units = int(row["used_resource_units"]) + max(resource_units, 0)
        if next_calls > int(row["max_tool_calls"]):
            return self._breach(
                session_id, f"Tool call budget exceeded: {next_calls} > {row['max_tool_calls']}"
            )
        if next_units > int(row["max_resource_units"]):
            return self._breach(
                session_id,
                f"Resource budget exceeded: {next_units} > {row['max_resource_units']}",
            )
        self.db.conn.execute(
            "UPDATE run_budgets SET used_tool_calls = ?, used_resource_units = ?, updated_at = ? "
            "WHERE session_id = ?",
            (next_calls, next_units, time.time(), session_id),
        )
        self.db.conn.commit()
        return BudgetDecision(True)

    def check(self, session_id: str) -> BudgetDecision:
        row = self._ensure(session_id)
        if str(row["status"]) == "breached":
            return BudgetDecision(False, str(row["breach_reason"]))
        decision = self._check_time(row)
        if not decision.allowed:
            return self._breach(session_id, decision.reason)
        return BudgetDecision(True)

    def finish(self, session_id: str) -> None:
        self.db.conn.execute(
            "UPDATE run_budgets SET status = CASE WHEN status = 'active' THEN 'completed' ELSE status END, "
            "updated_at = ? WHERE session_id = ?",
            (time.time(), session_id),
        )
        self.db.conn.commit()

    def summary(self, session_id: str) -> dict[str, Any]:
        row = self.db.conn.execute(
            "SELECT * FROM run_budgets WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return {"session_id": session_id, "status": "not_started"}
        result = dict(row)
        result["elapsed_seconds"] = max(0.0, time.time() - float(row["started_at"]))
        return result

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.conn.execute(
            "SELECT * FROM run_budgets ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

    def _ensure(self, session_id: str) -> Any:
        row = self.db.conn.execute(
            "SELECT * FROM run_budgets WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            self.start(session_id)
            row = self.db.conn.execute(
                "SELECT * FROM run_budgets WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            raise RuntimeError("Failed to initialize run budget")
        return row

    @staticmethod
    def _check_time(row: Any) -> BudgetDecision:
        elapsed = time.time() - float(row["started_at"])
        maximum = int(row["max_seconds"])
        if elapsed > maximum:
            return BudgetDecision(False, f"Time budget exceeded: {elapsed:.1f}s > {maximum}s")
        return BudgetDecision(True)

    def _breach(self, session_id: str, reason: str) -> BudgetDecision:
        self.db.conn.execute(
            "UPDATE run_budgets SET status = 'breached', breach_reason = ?, updated_at = ? "
            "WHERE session_id = ?",
            (reason, time.time(), session_id),
        )
        self.db.conn.commit()
        return BudgetDecision(False, reason)


class CostBudgetLayer(Layer):
    name = "cost_budget"

    def __init__(self, manager: BudgetManager, limits: BudgetLimits) -> None:
        self.manager = manager
        self.limits = limits

    async def on_graph_start(self, ctx: GraphContext) -> None:
        self.manager.start(ctx.session_id, self.limits)
        ctx.metadata["budget_limits"] = asdict(self.limits)

    async def on_event(self, event: Event) -> None:
        if event.type != "llm_usage":
            return
        session_id = str(event.data.get("session_id", ""))
        usage = event.data.get("usage") or {}
        decision = self.manager.record_llm(session_id, int(usage.get("total", 0)))
        graph_ctx = event.data.get("graph_context")
        if not decision.allowed and isinstance(graph_ctx, GraphContext):
            graph_ctx.should_abort = True
            graph_ctx.abort_reason = decision.reason

    async def on_graph_end(self, ctx: GraphContext) -> None:
        self.manager.finish(ctx.session_id)
        ctx.metadata["budget"] = self.manager.summary(ctx.session_id)
