"""L/S 层：SQLite Cron 调度与三分钟硬中断。"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from agent_conch.state.session_db import SessionDB

ScheduleRunner = Callable[[str, str], Awaitable[Any]]


@dataclass(frozen=True)
class Schedule:
    schedule_id: str
    name: str
    cron: str
    task: str
    enabled: bool
    timeout_seconds: int
    next_run_at: float
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class ScheduleRun:
    run_id: str
    schedule_id: str
    session_id: str
    status: str
    result: str
    error: str
    started_at: float
    finished_at: float


class CronScheduler:
    """支持标准五字段 cron 的 *, */n、逗号、范围与整数语法，按 UTC 计算。"""

    def __init__(self, db: SessionDB, runner: ScheduleRunner, hard_timeout: int = 180) -> None:
        self.db = db
        self.runner = runner
        self.hard_timeout = min(max(hard_timeout, 1), 180)
        self.db.conn.executescript("""
            CREATE TABLE IF NOT EXISTS schedules (
                schedule_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                cron TEXT NOT NULL,
                task TEXT NOT NULL,
                enabled INTEGER NOT NULL,
                timeout_seconds INTEGER NOT NULL,
                next_run_at REAL NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_schedules_due
            ON schedules(enabled, next_run_at);
            CREATE TABLE IF NOT EXISTS schedule_runs (
                run_id TEXT PRIMARY KEY,
                schedule_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                status TEXT NOT NULL,
                result TEXT NOT NULL,
                error TEXT NOT NULL,
                started_at REAL NOT NULL,
                finished_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_schedule_runs
            ON schedule_runs(schedule_id, started_at);
        """)
        self.db.conn.commit()

    def create(
        self,
        name: str,
        cron: str,
        task: str,
        timeout_seconds: int = 180,
        enabled: bool = True,
        now: float | None = None,
    ) -> Schedule:
        self.validate_cron(cron)
        current = now if now is not None else time.time()
        schedule = Schedule(
            schedule_id=uuid.uuid4().hex,
            name=name,
            cron=cron,
            task=task,
            enabled=enabled,
            timeout_seconds=min(max(timeout_seconds, 1), self.hard_timeout),
            next_run_at=self.next_run_after(cron, current),
            created_at=current,
            updated_at=current,
        )
        self.db.conn.execute(
            "INSERT INTO schedules VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                schedule.schedule_id,
                schedule.name,
                schedule.cron,
                schedule.task,
                int(schedule.enabled),
                schedule.timeout_seconds,
                schedule.next_run_at,
                schedule.created_at,
                schedule.updated_at,
            ),
        )
        self.db.conn.commit()
        return schedule

    def list_schedules(self) -> list[Schedule]:
        rows = self.db.conn.execute(
            "SELECT * FROM schedules ORDER BY created_at ASC"
        ).fetchall()
        return [self._row_to_schedule(row) for row in rows]

    def set_enabled(self, schedule_id: str, enabled: bool) -> bool:
        cursor = self.db.conn.execute(
            "UPDATE schedules SET enabled = ?, updated_at = ? WHERE schedule_id = ?",
            (int(enabled), time.time(), schedule_id),
        )
        self.db.conn.commit()
        return cursor.rowcount == 1

    async def run_due(self, now: float | None = None) -> list[ScheduleRun]:
        current = now if now is not None else time.time()
        rows = self.db.conn.execute(
            "SELECT * FROM schedules WHERE enabled = 1 AND next_run_at <= ? "
            "ORDER BY next_run_at ASC, schedule_id ASC",
            (current,),
        ).fetchall()
        results: list[ScheduleRun] = []
        for row in rows:
            schedule = self._row_to_schedule(row)
            results.append(await self._run_schedule(schedule))
            next_run = self.next_run_after(schedule.cron, current)
            self.db.conn.execute(
                "UPDATE schedules SET next_run_at = ?, updated_at = ? WHERE schedule_id = ?",
                (next_run, time.time(), schedule.schedule_id),
            )
            self.db.conn.commit()
        return results

    def list_runs(self, limit: int = 100) -> list[ScheduleRun]:
        rows = self.db.conn.execute(
            "SELECT * FROM schedule_runs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [ScheduleRun(**dict(row)) for row in rows]

    async def _run_schedule(self, schedule: Schedule) -> ScheduleRun:
        started = time.time()
        session_id = f"cron-{schedule.schedule_id[:8]}-{int(started)}"
        status = "completed"
        result_text = ""
        error = ""
        try:
            result = await asyncio.wait_for(
                self.runner(schedule.task, session_id), timeout=schedule.timeout_seconds
            )
            if hasattr(result, "__dataclass_fields__"):
                result_text = json.dumps(asdict(result), ensure_ascii=False, default=str)
            else:
                result_text = json.dumps(result, ensure_ascii=False, default=str)
        except TimeoutError:
            status = "timeout"
            error = f"Schedule exceeded hard timeout of {schedule.timeout_seconds}s"
        except Exception as exc:
            status = "error"
            error = str(exc)
        run = ScheduleRun(
            run_id=uuid.uuid4().hex,
            schedule_id=schedule.schedule_id,
            session_id=session_id,
            status=status,
            result=result_text[-8000:],
            error=error[-4000:],
            started_at=started,
            finished_at=time.time(),
        )
        self.db.conn.execute(
            "INSERT INTO schedule_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run.run_id,
                run.schedule_id,
                run.session_id,
                run.status,
                run.result,
                run.error,
                run.started_at,
                run.finished_at,
            ),
        )
        self.db.conn.commit()
        return run

    @classmethod
    def validate_cron(cls, expression: str) -> None:
        parts = expression.split()
        if len(parts) != 5:
            raise ValueError("Cron expression must contain five fields")
        ranges = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))
        for value, bounds in zip(parts, ranges, strict=True):
            cls._parse_field(value, *bounds)

    @classmethod
    def next_run_after(cls, expression: str, after: float) -> float:
        cls.validate_cron(expression)
        parts = expression.split()
        candidate = (int(after) // 60 + 1) * 60
        for _ in range(527_040):
            moment = datetime.fromtimestamp(candidate, tz=timezone.utc)
            values = (moment.minute, moment.hour, moment.day, moment.month, moment.weekday())
            ranges = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))
            if all(
                value in cls._parse_field(field, *bounds)
                for field, value, bounds in zip(parts, values, ranges, strict=True)
            ):
                return float(candidate)
            candidate += 60
        raise ValueError("Cron expression has no run time within one year")

    @staticmethod
    def _parse_field(field: str, minimum: int, maximum: int) -> set[int]:
        values: set[int] = set()
        for part in field.split(","):
            if part == "*":
                values.update(range(minimum, maximum + 1))
            elif part.startswith("*/"):
                step = int(part[2:])
                if step <= 0:
                    raise ValueError("Cron step must be positive")
                values.update(range(minimum, maximum + 1, step))
            elif "-" in part:
                start, end = (int(value) for value in part.split("-", 1))
                if start > end:
                    raise ValueError("Cron range start must not exceed end")
                values.update(range(start, end + 1))
            else:
                values.add(int(part))
        if not values or min(values) < minimum or max(values) > maximum:
            raise ValueError(f"Cron field '{field}' outside {minimum}-{maximum}")
        return values

    @staticmethod
    def _row_to_schedule(row: Any) -> Schedule:
        return Schedule(
            schedule_id=str(row["schedule_id"]),
            name=str(row["name"]),
            cron=str(row["cron"]),
            task=str(row["task"]),
            enabled=bool(row["enabled"]),
            timeout_seconds=int(row["timeout_seconds"]),
            next_run_at=float(row["next_run_at"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )
