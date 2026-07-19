"""V/S 层：失败报告自动沉淀与确定性回归门禁。"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Any

from agent_conch.sandbox.local import CommandResult
from agent_conch.state.session_db import SessionDB
from agent_conch.verification.report import VerificationReport

RegressionCommandRunner = Callable[[str, str | None, int], Awaitable[CommandResult]]


@dataclass(frozen=True)
class RegressionCase:
    case_id: str
    fingerprint: str
    task: str
    source_session_id: str
    commands: list[str]
    failure_excerpt: str
    enabled: bool
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class RegressionResult:
    run_id: str
    case_id: str
    passed: bool
    output: str
    duration_ms: int
    created_at: float


class RegressionStore:
    def __init__(self, db: SessionDB) -> None:
        self.db = db
        self.db.conn.executescript("""
            CREATE TABLE IF NOT EXISTS regression_cases (
                case_id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL UNIQUE,
                task TEXT NOT NULL,
                source_session_id TEXT NOT NULL,
                commands TEXT NOT NULL,
                failure_excerpt TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_regression_enabled
            ON regression_cases(enabled, created_at);
            CREATE TABLE IF NOT EXISTS regression_runs (
                run_id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL,
                passed INTEGER NOT NULL,
                output TEXT NOT NULL,
                duration_ms INTEGER NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_regression_runs_case
            ON regression_runs(case_id, created_at);
        """)
        self.db.conn.commit()

    def capture(self, report: VerificationReport) -> RegressionCase | None:
        failed = [check for check in report.checks if not check.passed]
        if report.passed or not failed:
            return None
        commands = [check.command for check in report.checks]
        signature = json.dumps(
            {"commands": commands, "failure": failed[0].output[-1000:]},
            sort_keys=True,
            ensure_ascii=False,
        )
        fingerprint = hashlib.sha256(signature.encode()).hexdigest()
        now = time.time()
        existing = self.get_by_fingerprint(fingerprint)
        if existing is not None:
            self.db.conn.execute(
                "UPDATE regression_cases SET updated_at = ?, source_session_id = ? WHERE case_id = ?",
                (now, report.session_id, existing.case_id),
            )
            self.db.conn.commit()
            return self.get(existing.case_id)
        case = RegressionCase(
            case_id=uuid.uuid4().hex,
            fingerprint=fingerprint,
            task=report.agent_claim or f"Verification failure in {report.session_id}",
            source_session_id=report.session_id,
            commands=commands,
            failure_excerpt=failed[0].output[-2000:],
            enabled=True,
            created_at=now,
            updated_at=now,
        )
        self.db.conn.execute(
            "INSERT INTO regression_cases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                case.case_id,
                case.fingerprint,
                case.task,
                case.source_session_id,
                json.dumps(case.commands, ensure_ascii=False),
                case.failure_excerpt,
                int(case.enabled),
                case.created_at,
                case.updated_at,
            ),
        )
        self.db.conn.commit()
        return case

    def get(self, case_id: str) -> RegressionCase | None:
        row = self.db.conn.execute(
            "SELECT * FROM regression_cases WHERE case_id = ?", (case_id,)
        ).fetchone()
        return self._row_to_case(row) if row is not None else None

    def get_by_fingerprint(self, fingerprint: str) -> RegressionCase | None:
        row = self.db.conn.execute(
            "SELECT * FROM regression_cases WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()
        return self._row_to_case(row) if row is not None else None

    def list_cases(self, enabled_only: bool = False) -> list[RegressionCase]:
        query = "SELECT * FROM regression_cases"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY created_at ASC"
        return [self._row_to_case(row) for row in self.db.conn.execute(query).fetchall()]

    def set_enabled(self, case_id: str, enabled: bool) -> bool:
        cursor = self.db.conn.execute(
            "UPDATE regression_cases SET enabled = ?, updated_at = ? WHERE case_id = ?",
            (int(enabled), time.time(), case_id),
        )
        self.db.conn.commit()
        return cursor.rowcount == 1

    def save_result(self, result: RegressionResult) -> None:
        self.db.conn.execute(
            "INSERT INTO regression_runs VALUES (?, ?, ?, ?, ?, ?)",
            (
                result.run_id,
                result.case_id,
                int(result.passed),
                result.output,
                result.duration_ms,
                result.created_at,
            ),
        )
        self.db.conn.commit()

    def latest_results(self) -> list[dict[str, Any]]:
        rows = self.db.conn.execute("""
            SELECT r.* FROM regression_runs r
            JOIN (
                SELECT case_id, MAX(created_at) AS latest
                FROM regression_runs GROUP BY case_id
            ) x ON x.case_id = r.case_id AND x.latest = r.created_at
            ORDER BY r.created_at DESC
        """).fetchall()
        return [dict(row) | {"passed": bool(row["passed"])} for row in rows]

    @staticmethod
    def _row_to_case(row: Any) -> RegressionCase:
        return RegressionCase(
            case_id=str(row["case_id"]),
            fingerprint=str(row["fingerprint"]),
            task=str(row["task"]),
            source_session_id=str(row["source_session_id"]),
            commands=[str(item) for item in json.loads(row["commands"])],
            failure_excerpt=str(row["failure_excerpt"]),
            enabled=bool(row["enabled"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )


class RegressionRunner:
    def __init__(
        self,
        store: RegressionStore,
        runner: RegressionCommandRunner,
        cwd: str | None = None,
        timeout: int = 180,
        minimum_pass_rate: float = 1.0,
    ) -> None:
        self.store = store
        self.runner = runner
        self.cwd = cwd
        self.timeout = timeout
        self.minimum_pass_rate = minimum_pass_rate

    async def run_case(self, case: RegressionCase) -> RegressionResult:
        started = time.time()
        outputs: list[str] = []
        passed = True
        for command in case.commands:
            command_result = await self.runner(command, self.cwd, self.timeout)
            outputs.append(
                f"$ {command}\n{command_result.stdout}{command_result.stderr}"[-4000:]
            )
            if command_result.exit_code != 0:
                passed = False
                break
        result = RegressionResult(
            run_id=uuid.uuid4().hex,
            case_id=case.case_id,
            passed=passed,
            output="\n".join(outputs)[-8000:],
            duration_ms=int((time.time() - started) * 1000),
            created_at=time.time(),
        )
        self.store.save_result(result)
        return result

    async def run_all(self) -> dict[str, Any]:
        cases = self.store.list_cases(enabled_only=True)
        results = [await self.run_case(case) for case in cases]
        pass_rate = sum(result.passed for result in results) / len(results) if results else 1.0
        return {
            "total": len(results),
            "passed": sum(result.passed for result in results),
            "pass_rate": pass_rate,
            "minimum_pass_rate": self.minimum_pass_rate,
            "gate_passed": pass_rate >= self.minimum_pass_rate,
            "results": [asdict(result) for result in results],
        }
