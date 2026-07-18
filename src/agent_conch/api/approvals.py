"""P3 Web Console 审批面板使用的 SQLite pending store。"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from agent_conch.state.session_db import SessionDB


@dataclass
class Approval:
    approval_id: str
    session_id: str
    operation: str
    reason: str
    status: str = "pending"
    created_at: float = 0.0
    decided_at: float | None = None


class ApprovalStore:
    def __init__(self, db: SessionDB) -> None:
        self.db = db
        self.db.conn.executescript("""
            CREATE TABLE IF NOT EXISTS approvals (
                approval_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at REAL NOT NULL,
                decided_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_approvals_status
            ON approvals(status, created_at);
        """)
        self.db.conn.commit()

    def create(self, session_id: str, operation: str, reason: str) -> Approval:
        approval = Approval(uuid.uuid4().hex, session_id, operation, reason, created_at=time.time())
        self.db.conn.execute(
            "INSERT INTO approvals VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                approval.approval_id,
                approval.session_id,
                approval.operation,
                approval.reason,
                approval.status,
                approval.created_at,
                approval.decided_at,
            ),
        )
        self.db.conn.commit()
        return approval

    def decide(self, approval_id: str, status: str) -> Approval | None:
        if status not in {"approved", "rejected"}:
            raise ValueError("Approval status must be approved or rejected")
        self.db.conn.execute(
            "UPDATE approvals SET status = ?, decided_at = ? "
            "WHERE approval_id = ? AND status = 'pending'",
            (status, time.time(), approval_id),
        )
        self.db.conn.commit()
        return self.get(approval_id)

    def get(self, approval_id: str) -> Approval | None:
        row = self.db.conn.execute(
            "SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)
        ).fetchone()
        return Approval(**dict(row)) if row is not None else None

    def list_pending(self) -> list[Approval]:
        rows = self.db.conn.execute(
            "SELECT * FROM approvals WHERE status = 'pending' ORDER BY created_at ASC"
        ).fetchall()
        return [Approval(**dict(row)) for row in rows]
