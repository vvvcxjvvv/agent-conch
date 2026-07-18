"""O 层：SQLite Trace 持久化。"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from agent_conch.state.session_db import SessionDB


@dataclass
class SpanRecord:
    """单个可查询 Trace span。"""

    span_id: str
    trace_id: str
    session_id: str
    name: str
    kind: str
    parent_span_id: str | None = None
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    status: str = "running"
    attributes: dict[str, Any] = field(default_factory=dict)


class TraceStore:
    """将 span 外置到 SessionDB，支持审计与 API 查询。"""

    def __init__(self, db: SessionDB) -> None:
        self.db = db
        self.db.conn.executescript("""
            CREATE TABLE IF NOT EXISTS trace_spans (
                span_id TEXT PRIMARY KEY,
                trace_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                parent_span_id TEXT,
                started_at REAL NOT NULL,
                ended_at REAL,
                status TEXT NOT NULL,
                attributes TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_trace_session
            ON trace_spans(session_id, started_at);
        """)
        self.db.conn.commit()

    def start_span(
        self,
        session_id: str,
        name: str,
        kind: str,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> SpanRecord:
        record = SpanRecord(
            span_id=uuid.uuid4().hex,
            trace_id=trace_id or uuid.uuid4().hex,
            session_id=session_id,
            name=name,
            kind=kind,
            parent_span_id=parent_span_id,
            attributes=attributes or {},
        )
        self.db.conn.execute(
            "INSERT INTO trace_spans "
            "(span_id, trace_id, session_id, name, kind, parent_span_id, "
            "started_at, status, attributes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.span_id,
                record.trace_id,
                record.session_id,
                record.name,
                record.kind,
                record.parent_span_id,
                record.started_at,
                record.status,
                json.dumps(record.attributes, ensure_ascii=False),
            ),
        )
        self.db.conn.commit()
        return record

    def finish_span(
        self,
        span_id: str,
        status: str = "ok",
        attributes: dict[str, Any] | None = None,
    ) -> None:
        row = self.db.conn.execute(
            "SELECT attributes FROM trace_spans WHERE span_id = ?", (span_id,)
        ).fetchone()
        current = json.loads(row["attributes"]) if row is not None else {}
        current.update(attributes or {})
        self.db.conn.execute(
            "UPDATE trace_spans SET ended_at = ?, status = ?, attributes = ? WHERE span_id = ?",
            (time.time(), status, json.dumps(current, ensure_ascii=False), span_id),
        )
        self.db.conn.commit()

    def get_spans(self, session_id: str) -> list[SpanRecord]:
        rows = self.db.conn.execute(
            "SELECT * FROM trace_spans WHERE session_id = ? ORDER BY started_at ASC",
            (session_id,),
        ).fetchall()
        return [
            SpanRecord(
                span_id=row["span_id"],
                trace_id=row["trace_id"],
                session_id=row["session_id"],
                name=row["name"],
                kind=row["kind"],
                parent_span_id=row["parent_span_id"],
                started_at=row["started_at"],
                ended_at=row["ended_at"],
                status=row["status"],
                attributes=json.loads(row["attributes"]),
            )
            for row in rows
        ]
