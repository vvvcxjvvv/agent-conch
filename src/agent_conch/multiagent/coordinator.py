"""L/O/S 层：Coordinator 主从编排、决策表与上下文隔离。"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from agent_conch.multiagent.subagent import SubagentManager, SubagentRecord
from agent_conch.state.session_db import SessionDB

WorkerRunner = Callable[[SubagentRecord, str, dict[str, Any]], Awaitable[str]]


@dataclass(frozen=True)
class CoordinatorTask:
    task: str
    capability: str = "general"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CoordinatorRun:
    coordinator_id: str
    parent_session_id: str
    strategy: str
    status: str
    tasks: list[CoordinatorTask]
    summary: dict[str, Any]
    created_at: float
    finished_at: float | None = None


class DecisionTable:
    def __init__(self, routes: dict[str, str] | None = None, default_role: str = "worker") -> None:
        self.routes = dict(routes or {})
        self.default_role = default_role

    def select_role(self, capability: str) -> str:
        return self.routes.get(capability, self.default_role)

    def describe(self) -> dict[str, Any]:
        return {"default_role": self.default_role, "routes": dict(sorted(self.routes.items()))}


class Coordinator:
    def __init__(
        self,
        db: SessionDB,
        subagents: SubagentManager,
        runner: WorkerRunner,
        decision_table: DecisionTable | None = None,
        max_workers: int = 4,
    ) -> None:
        self.db = db
        self.subagents = subagents
        self.runner = runner
        self.decision_table = decision_table or DecisionTable()
        self.max_workers = max(1, max_workers)
        self.db.conn.executescript("""
            CREATE TABLE IF NOT EXISTS coordinator_runs (
                coordinator_id TEXT PRIMARY KEY,
                parent_session_id TEXT NOT NULL,
                strategy TEXT NOT NULL,
                status TEXT NOT NULL,
                tasks TEXT NOT NULL,
                summary TEXT NOT NULL,
                created_at REAL NOT NULL,
                finished_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_coordinator_parent
            ON coordinator_runs(parent_session_id, created_at);
        """)
        self.db.conn.commit()

    async def execute(
        self,
        parent_session_id: str,
        tasks: list[CoordinatorTask],
        strategy: str = "parallel",
    ) -> CoordinatorRun:
        if strategy not in {"parallel", "sequential"}:
            raise ValueError("Coordinator strategy must be parallel or sequential")
        if not tasks:
            raise ValueError("Coordinator requires at least one task")
        coordinator_id = uuid.uuid4().hex
        created_at = time.time()
        self._insert_run(coordinator_id, parent_session_id, strategy, tasks, created_at)
        workers = [
            self.subagents.spawn(
                parent_session_id,
                task.task,
                {
                    **task.metadata,
                    "coordinator_id": coordinator_id,
                    "capability": task.capability,
                    "trace_parent": parent_session_id,
                    "context_isolated": True,
                },
            )
            for task in tasks
        ]

        if strategy == "parallel":
            semaphore = asyncio.Semaphore(self.max_workers)

            async def limited(record: SubagentRecord, task: CoordinatorTask) -> dict[str, Any]:
                async with semaphore:
                    return await self._run_worker(record, task)

            results = await asyncio.gather(
                *(limited(record, task) for record, task in zip(workers, tasks, strict=True))
            )
        else:
            results = []
            for record, task in zip(workers, tasks, strict=True):
                results.append(await self._run_worker(record, task))

        failed = [result for result in results if result["status"] != "completed"]
        status = "failed" if failed else "completed"
        summary = {
            "workers": results,
            "completed": len(results) - len(failed),
            "failed": len(failed),
            "decision_table": self.decision_table.describe(),
        }
        finished_at = time.time()
        self.db.conn.execute(
            "UPDATE coordinator_runs SET status = ?, summary = ?, finished_at = ? "
            "WHERE coordinator_id = ?",
            (status, json.dumps(summary, ensure_ascii=False), finished_at, coordinator_id),
        )
        self.db.conn.commit()
        return CoordinatorRun(
            coordinator_id,
            parent_session_id,
            strategy,
            status,
            tasks,
            summary,
            created_at,
            finished_at,
        )

    def list_runs(self, limit: int = 100) -> list[CoordinatorRun]:
        rows = self.db.conn.execute(
            "SELECT * FROM coordinator_runs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row_to_run(row) for row in rows]

    async def _run_worker(
        self, record: SubagentRecord, task: CoordinatorTask
    ) -> dict[str, Any]:
        role = self.decision_table.select_role(task.capability)
        self.subagents.start(record.subagent_id)
        metadata = {
            **record.metadata,
            "role": role,
            "worker_session_id": record.session_id,
        }
        try:
            result = await self.runner(record, role, metadata)
            self.subagents.complete(record.subagent_id, result)
            return {
                "subagent_id": record.subagent_id,
                "session_id": record.session_id,
                "role": role,
                "status": "completed",
                "result": result,
            }
        except Exception as exc:
            self.subagents.fail(record.subagent_id, str(exc))
            return {
                "subagent_id": record.subagent_id,
                "session_id": record.session_id,
                "role": role,
                "status": "failed",
                "error": str(exc),
            }

    def _insert_run(
        self,
        coordinator_id: str,
        parent_session_id: str,
        strategy: str,
        tasks: list[CoordinatorTask],
        created_at: float,
    ) -> None:
        self.db.conn.execute(
            "INSERT INTO coordinator_runs VALUES (?, ?, ?, 'running', ?, '{}', ?, NULL)",
            (
                coordinator_id,
                parent_session_id,
                strategy,
                json.dumps([asdict(task) for task in tasks], ensure_ascii=False),
                created_at,
            ),
        )
        self.db.conn.commit()

    @staticmethod
    def _row_to_run(row: Any) -> CoordinatorRun:
        return CoordinatorRun(
            coordinator_id=str(row["coordinator_id"]),
            parent_session_id=str(row["parent_session_id"]),
            strategy=str(row["strategy"]),
            status=str(row["status"]),
            tasks=[CoordinatorTask(**item) for item in json.loads(row["tasks"])],
            summary=dict(json.loads(row["summary"])),
            created_at=float(row["created_at"]),
            finished_at=float(row["finished_at"]) if row["finished_at"] is not None else None,
        )
