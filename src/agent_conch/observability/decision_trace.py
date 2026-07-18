"""O 层：可审计的决策轨迹，不保存模型原始思维链。"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from agent_conch.state.session_db import SessionDB


@dataclass
class DecisionTraceStep:
    """一次可解释的执行决策摘要。"""

    decision_id: str
    session_id: str
    turn_index: int
    phase: str
    title: str
    summary: str
    evidence: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    @classmethod
    def create(
        cls,
        session_id: str,
        turn_index: int,
        phase: str,
        title: str,
        summary: str,
        evidence: dict[str, Any] | None = None,
    ) -> DecisionTraceStep:
        return cls(
            decision_id=uuid.uuid4().hex,
            session_id=session_id,
            turn_index=turn_index,
            phase=phase,
            title=title,
            summary=summary,
            evidence=evidence or {},
        )


class DecisionTraceStore:
    """SQLite 决策轨迹存储，按产生顺序稳定回放。"""

    def __init__(self, db: SessionDB) -> None:
        self.db = db
        self.db.conn.executescript("""
            CREATE TABLE IF NOT EXISTS decision_traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id TEXT NOT NULL UNIQUE,
                session_id TEXT NOT NULL,
                turn_index INTEGER NOT NULL,
                phase TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                evidence TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_decision_trace_session
            ON decision_traces(session_id, id);
        """)
        self.db.conn.commit()

    def save(self, step: DecisionTraceStep) -> None:
        self.db.conn.execute(
            "INSERT INTO decision_traces "
            "(decision_id, session_id, turn_index, phase, title, summary, evidence, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                step.decision_id,
                step.session_id,
                step.turn_index,
                step.phase,
                step.title,
                step.summary,
                json.dumps(step.evidence, ensure_ascii=False),
                step.created_at,
            ),
        )
        self.db.conn.commit()

    def list_for_session(self, session_id: str) -> list[DecisionTraceStep]:
        rows = self.db.conn.execute(
            "SELECT * FROM decision_traces WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        return [
            DecisionTraceStep(
                decision_id=row["decision_id"],
                session_id=row["session_id"],
                turn_index=row["turn_index"],
                phase=row["phase"],
                title=row["title"],
                summary=row["summary"],
                evidence=json.loads(row["evidence"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]
