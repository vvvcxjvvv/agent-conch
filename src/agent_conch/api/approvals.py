"""G/S 层：WriteApproval 持久化、决策与一次性恢复。"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

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
    payload: dict[str, Any] = field(default_factory=dict)
    request_hash: str = ""
    principal: str = "local"
    role: str = "admin"
    action_level: int = 2
    decided_by: str | None = None
    consumed_at: float | None = None


class WriteApprovalStore:
    """相同请求复用 pending 记录；批准后只能消费一次。"""

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
                decided_at REAL,
                payload TEXT NOT NULL DEFAULT '{}',
                request_hash TEXT NOT NULL DEFAULT '',
                principal TEXT NOT NULL DEFAULT 'local',
                role TEXT NOT NULL DEFAULT 'admin',
                action_level INTEGER NOT NULL DEFAULT 2,
                decided_by TEXT,
                consumed_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_approvals_status
            ON approvals(status, created_at);
        """)
        self._migrate_existing_table()
        self.db.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_approvals_request "
            "ON approvals(session_id, request_hash, status, consumed_at)"
        )
        self.db.conn.commit()

    def _migrate_existing_table(self) -> None:
        columns = {
            str(row["name"])
            for row in self.db.conn.execute("PRAGMA table_info(approvals)").fetchall()
        }
        additions = {
            "payload": "TEXT NOT NULL DEFAULT '{}'",
            "request_hash": "TEXT NOT NULL DEFAULT ''",
            "principal": "TEXT NOT NULL DEFAULT 'local'",
            "role": "TEXT NOT NULL DEFAULT 'admin'",
            "action_level": "INTEGER NOT NULL DEFAULT 2",
            "decided_by": "TEXT",
            "consumed_at": "REAL",
        }
        for name, ddl in additions.items():
            if name not in columns:
                self.db.conn.execute(f"ALTER TABLE approvals ADD COLUMN {name} {ddl}")

    @staticmethod
    def fingerprint(session_id: str, operation: str, payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            {"session_id": session_id, "operation": operation, "payload": payload},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def create(
        self,
        session_id: str,
        operation: str,
        reason: str,
        payload: dict[str, Any] | None = None,
        principal: str = "local",
        role: str = "admin",
        action_level: int = 2,
    ) -> Approval:
        data = payload or {}
        request_hash = self.fingerprint(session_id, operation, data)
        existing = self._find_reusable(session_id, request_hash, statuses=("pending",))
        if existing is not None:
            return existing
        approval = Approval(
            uuid.uuid4().hex,
            session_id,
            operation,
            reason,
            created_at=time.time(),
            payload=data,
            request_hash=request_hash,
            principal=principal,
            role=role,
            action_level=action_level,
        )
        self.db.conn.execute(
            "INSERT INTO approvals "
            "(approval_id, session_id, operation, reason, status, created_at, decided_at, "
            "payload, request_hash, principal, role, action_level, decided_by, consumed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                approval.approval_id,
                approval.session_id,
                approval.operation,
                approval.reason,
                approval.status,
                approval.created_at,
                approval.decided_at,
                json.dumps(approval.payload, ensure_ascii=False, default=str),
                approval.request_hash,
                approval.principal,
                approval.role,
                approval.action_level,
                approval.decided_by,
                approval.consumed_at,
            ),
        )
        self.db.conn.commit()
        return approval

    def decide(self, approval_id: str, status: str, decided_by: str = "local") -> Approval | None:
        if status not in {"approved", "rejected"}:
            raise ValueError("Approval status must be approved or rejected")
        self.db.conn.execute(
            "UPDATE approvals SET status = ?, decided_at = ?, decided_by = ? "
            "WHERE approval_id = ? AND status = 'pending'",
            (status, time.time(), decided_by, approval_id),
        )
        self.db.conn.commit()
        return self.get(approval_id)

    def authorize_or_request(
        self,
        session_id: str,
        operation: str,
        reason: str,
        payload: dict[str, Any],
        principal: str,
        role: str,
        action_level: int,
    ) -> tuple[bool, Approval]:
        request_hash = self.fingerprint(session_id, operation, payload)
        approved = self._find_reusable(session_id, request_hash, statuses=("approved",))
        if approved is not None and self.consume(approved.approval_id):
            consumed = self.get(approved.approval_id)
            if consumed is not None:
                return True, consumed
        return False, self.create(
            session_id,
            operation,
            reason,
            payload,
            principal,
            role,
            action_level,
        )

    def consume(self, approval_id: str) -> bool:
        cursor = self.db.conn.execute(
            "UPDATE approvals SET consumed_at = ? "
            "WHERE approval_id = ? AND status = 'approved' AND consumed_at IS NULL",
            (time.time(), approval_id),
        )
        self.db.conn.commit()
        return cursor.rowcount == 1

    def get(self, approval_id: str) -> Approval | None:
        row = self.db.conn.execute(
            "SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)
        ).fetchone()
        return self._row_to_approval(row) if row is not None else None

    def list_pending(self) -> list[Approval]:
        rows = self.db.conn.execute(
            "SELECT * FROM approvals WHERE status = 'pending' ORDER BY created_at ASC"
        ).fetchall()
        return [self._row_to_approval(row) for row in rows]

    def list_all(self, limit: int = 100) -> list[Approval]:
        rows = self.db.conn.execute(
            "SELECT * FROM approvals ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row_to_approval(row) for row in rows]

    def _find_reusable(
        self,
        session_id: str,
        request_hash: str,
        statuses: tuple[str, ...],
    ) -> Approval | None:
        placeholders = ",".join("?" for _ in statuses)
        row = self.db.conn.execute(
            "SELECT * FROM approvals WHERE session_id = ? AND request_hash = ? "
            f"AND status IN ({placeholders}) AND consumed_at IS NULL ORDER BY created_at DESC LIMIT 1",
            (session_id, request_hash, *statuses),
        ).fetchone()
        return self._row_to_approval(row) if row is not None else None

    @staticmethod
    def _row_to_approval(row: Any) -> Approval:
        data = dict(row)
        data["payload"] = json.loads(data.get("payload") or "{}")
        return Approval(**data)


class ApprovalStore(WriteApprovalStore):
    """兼容旧 API 名称；实现使用 WriteApproval。"""
