"""L/S 层：可配置生命周期 HookExecutor。"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from agent_conch.engine.layers.base import Event, GraphContext, Layer, NodeContext
from agent_conch.sandbox.local import CommandResult
from agent_conch.state.session_db import SessionDB

HookRunner = Callable[[str, str | None, int, dict[str, str]], Awaitable[CommandResult]]


@dataclass(frozen=True)
class HookSpec:
    name: str
    event: str
    command: str
    timeout: int = 30
    fail_closed: bool = False
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HookSpec:
        return cls(
            name=str(data["name"]),
            event=str(data["event"]),
            command=str(data["command"]),
            timeout=max(1, min(int(data.get("timeout", 30)), 180)),
            fail_closed=bool(data.get("fail_closed", False)),
            cwd=str(data["cwd"]) if data.get("cwd") else None,
            env={str(key): str(value) for key, value in dict(data.get("env", {})).items()},
        )


@dataclass(frozen=True)
class HookExecution:
    execution_id: str
    hook_name: str
    event: str
    session_id: str
    status: str
    exit_code: int
    output: str
    duration_ms: int
    created_at: float


class HookExecutor:
    def __init__(self, db: SessionDB, runner: HookRunner, specs: list[HookSpec] | None = None) -> None:
        self.db = db
        self.runner = runner
        self.specs = list(specs or [])
        self.db.conn.executescript("""
            CREATE TABLE IF NOT EXISTS hook_executions (
                execution_id TEXT PRIMARY KEY,
                hook_name TEXT NOT NULL,
                event TEXT NOT NULL,
                session_id TEXT NOT NULL,
                status TEXT NOT NULL,
                exit_code INTEGER NOT NULL,
                output TEXT NOT NULL,
                duration_ms INTEGER NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_hook_executions_session
            ON hook_executions(session_id, created_at);
        """)
        self.db.conn.commit()

    async def run_event(
        self, event: str, session_id: str, context: dict[str, str] | None = None
    ) -> list[tuple[HookSpec, HookExecution]]:
        results: list[tuple[HookSpec, HookExecution]] = []
        for spec in [item for item in self.specs if item.event == event]:
            env = {
                **spec.env,
                **(context or {}),
                "CONCH_EVENT": event,
                "CONCH_SESSION_ID": session_id,
            }
            result = await self.runner(spec.command, spec.cwd, spec.timeout, env)
            execution = HookExecution(
                uuid.uuid4().hex,
                spec.name,
                event,
                session_id,
                "passed" if result.exit_code == 0 else "failed",
                result.exit_code,
                (result.stdout + result.stderr)[-4000:],
                result.duration_ms,
                time.time(),
            )
            self._save(execution)
            results.append((spec, execution))
            if execution.status == "failed" and spec.fail_closed:
                break
        return results

    def list_executions(self, session_id: str = "", limit: int = 100) -> list[HookExecution]:
        if session_id:
            rows = self.db.conn.execute(
                "SELECT * FROM hook_executions WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        else:
            rows = self.db.conn.execute(
                "SELECT * FROM hook_executions ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [HookExecution(**dict(row)) for row in rows]

    def _save(self, execution: HookExecution) -> None:
        self.db.conn.execute(
            "INSERT INTO hook_executions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                execution.execution_id,
                execution.hook_name,
                execution.event,
                execution.session_id,
                execution.status,
                execution.exit_code,
                execution.output,
                execution.duration_ms,
                execution.created_at,
            ),
        )
        self.db.conn.commit()


class HookExecutorLayer(Layer):
    name = "hooks"

    def __init__(self, executor: HookExecutor):
        self.executor = executor

    async def on_graph_start(self, ctx: GraphContext) -> None:
        failures = await self._run("graph_start", ctx.session_id)
        if failures:
            ctx.should_abort = True
            ctx.abort_reason = failures[0]

    async def on_node_run_start(self, ctx: NodeContext) -> None:
        failures = await self._run(
            "node_start", ctx.session_id, {"CONCH_TURN_INDEX": str(ctx.turn_index)}
        )
        if failures:
            ctx.block_progress(failures[0])

    async def on_node_run_end(self, ctx: NodeContext, result: Any) -> None:
        failures = await self._run(
            "node_end", ctx.session_id, {"CONCH_TURN_INDEX": str(ctx.turn_index)}
        )
        if failures:
            ctx.block_progress(failures[0])

    async def on_event(self, event: Event) -> None:
        await self._run(event.type, str(event.data.get("session_id", "")))

    async def on_graph_end(self, ctx: GraphContext) -> None:
        await self._run("graph_end", ctx.session_id)

    async def _run(
        self, event: str, session_id: str, context: dict[str, str] | None = None
    ) -> list[str]:
        executions = await self.executor.run_event(event, session_id, context)
        return [
            f"Hook '{spec.name}' failed with exit code {execution.exit_code}"
            for spec, execution in executions
            if spec.fail_closed and execution.status == "failed"
        ]
