"""E/S 层：沙箱快照目录、恢复与删除闭环。"""

from __future__ import annotations

import inspect
import time
import uuid
from dataclasses import dataclass
from typing import Any

from agent_conch.sandbox.registry import SandboxRegistry
from agent_conch.state.session_db import SessionDB


@dataclass(frozen=True)
class SnapshotRecord:
    snapshot_id: str
    session_id: str
    backend: str
    external_ref: str
    status: str
    created_at: float
    restored_at: float | None = None


class SnapshotManager:
    def __init__(self, db: SessionDB, registry: SandboxRegistry) -> None:
        self.db = db
        self.registry = registry
        self.db.conn.executescript("""
            CREATE TABLE IF NOT EXISTS sandbox_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                backend TEXT NOT NULL,
                external_ref TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at REAL NOT NULL,
                restored_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_snapshots_session
            ON sandbox_snapshots(session_id, created_at);
        """)
        self.db.conn.commit()

    async def create(self, session_id: str, tag: str = "") -> SnapshotRecord:
        backend = self.registry.get_backend(session_id=session_id, is_main=False)
        snapshot = getattr(backend, "snapshot", None)
        if not callable(snapshot):
            raise RuntimeError("Selected sandbox backend does not support snapshots")
        external_ref = snapshot(session_id, tag)
        if inspect.isawaitable(external_ref):
            external_ref = await external_ref
        if not external_ref:
            raise RuntimeError("Sandbox snapshot creation failed")
        record = SnapshotRecord(
            uuid.uuid4().hex,
            session_id,
            type(backend).__name__,
            str(external_ref),
            "available",
            time.time(),
        )
        self.db.conn.execute(
            "INSERT INTO sandbox_snapshots VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                record.snapshot_id,
                record.session_id,
                record.backend,
                record.external_ref,
                record.status,
                record.created_at,
                record.restored_at,
            ),
        )
        self.db.conn.commit()
        return record

    async def restore(self, snapshot_id: str) -> SnapshotRecord:
        record = self.get(snapshot_id)
        if record is None:
            raise KeyError(f"Snapshot not found: {snapshot_id}")
        if record.status == "deleted":
            raise ValueError("Deleted snapshot cannot be restored")
        backend = self.registry.get_backend(session_id=record.session_id, is_main=False)
        restore = getattr(backend, "restore_snapshot", None)
        if not callable(restore):
            raise RuntimeError("Sandbox snapshot restore failed")
        restored = restore(record.session_id, record.external_ref)
        if inspect.isawaitable(restored):
            restored = await restored
        if not bool(restored):
            raise RuntimeError("Sandbox snapshot restore failed")
        restored_at = time.time()
        self.db.conn.execute(
            "UPDATE sandbox_snapshots SET status = 'restored', restored_at = ? "
            "WHERE snapshot_id = ?",
            (restored_at, snapshot_id),
        )
        self.db.conn.commit()
        updated = self.get(snapshot_id)
        if updated is None:
            raise RuntimeError("Snapshot disappeared after restore")
        return updated

    async def delete(self, snapshot_id: str) -> bool:
        record = self.get(snapshot_id)
        if record is None:
            return False
        backend = self.registry.get_backend(session_id=record.session_id, is_main=False)
        remove = getattr(backend, "remove_snapshot", None)
        if not callable(remove):
            return False
        removed = remove(record.external_ref)
        if inspect.isawaitable(removed):
            removed = await removed
        if not bool(removed):
            return False
        self.db.conn.execute(
            "UPDATE sandbox_snapshots SET status = 'deleted' WHERE snapshot_id = ?",
            (snapshot_id,),
        )
        self.db.conn.commit()
        return True

    def get(self, snapshot_id: str) -> SnapshotRecord | None:
        row = self.db.conn.execute(
            "SELECT * FROM sandbox_snapshots WHERE snapshot_id = ?", (snapshot_id,)
        ).fetchone()
        return SnapshotRecord(**dict(row)) if row is not None else None

    def list_for_session(self, session_id: str) -> list[SnapshotRecord]:
        rows = self.db.conn.execute(
            "SELECT * FROM sandbox_snapshots WHERE session_id = ? ORDER BY created_at DESC",
            (session_id,),
        ).fetchall()
        return [SnapshotRecord(**dict(row)) for row in rows]

    def overview(self) -> list[dict[str, Any]]:
        rows = self.db.conn.execute(
            "SELECT status, COUNT(*) AS count FROM sandbox_snapshots GROUP BY status ORDER BY status"
        ).fetchall()
        return [dict(row) for row in rows]
