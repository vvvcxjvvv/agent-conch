"""V 层：Agent 自述与服务级验证分离报告。"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from agent_conch.state.session_db import SessionDB


@dataclass
class VerificationCheck:
    name: str
    command: str
    passed: bool
    exit_code: int
    output: str
    duration_ms: int


@dataclass
class VerificationReport:
    report_id: str
    session_id: str
    turn_index: int
    passed: bool
    agent_claim: str = ""
    checks: list[VerificationCheck] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    @classmethod
    def create(
        cls,
        session_id: str,
        turn_index: int,
        agent_claim: str,
        checks: list[VerificationCheck],
    ) -> VerificationReport:
        return cls(
            report_id=uuid.uuid4().hex,
            session_id=session_id,
            turn_index=turn_index,
            passed=all(check.passed for check in checks),
            agent_claim=agent_claim,
            checks=checks,
        )


class VerificationStore:
    def __init__(self, db: SessionDB) -> None:
        self.db = db
        self.db.conn.executescript("""
            CREATE TABLE IF NOT EXISTS verification_reports (
                report_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                turn_index INTEGER NOT NULL,
                passed INTEGER NOT NULL,
                agent_claim TEXT NOT NULL,
                checks TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_verification_session
            ON verification_reports(session_id, created_at);
        """)
        self.db.conn.commit()

    def save(self, report: VerificationReport) -> None:
        self.db.conn.execute(
            "INSERT INTO verification_reports VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                report.report_id,
                report.session_id,
                report.turn_index,
                int(report.passed),
                report.agent_claim,
                json.dumps([asdict(check) for check in report.checks], ensure_ascii=False),
                report.created_at,
            ),
        )
        self.db.conn.commit()

    def list_for_session(self, session_id: str) -> list[VerificationReport]:
        rows = self.db.conn.execute(
            "SELECT * FROM verification_reports WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        ).fetchall()
        return [
            VerificationReport(
                report_id=row["report_id"],
                session_id=row["session_id"],
                turn_index=row["turn_index"],
                passed=bool(row["passed"]),
                agent_claim=row["agent_claim"],
                checks=[VerificationCheck(**item) for item in json.loads(row["checks"])],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def latest(self, session_id: str) -> VerificationReport | None:
        reports = self.list_for_session(session_id)
        return reports[-1] if reports else None

    def as_dict(self, report: VerificationReport) -> dict[str, Any]:
        return asdict(report)
