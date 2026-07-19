"""O 层：API/SSE 使用的进程内实时事件总线。"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any

from agent_conch.state.session_db import SessionDB


class EventBus:
    """无 DB 时为进程内队列；传入 DB 后使用 SQLite 轮询支持多实例共享。"""

    def __init__(self, db: SessionDB | None = None, poll_interval: float = 0.1) -> None:
        self.db = db
        self.poll_interval = poll_interval
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
        if self.db is not None:
            self.db.conn.executescript("""
                CREATE TABLE IF NOT EXISTS event_stream (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_event_stream_session
                ON event_stream(session_id, id);
            """)
            self.db.conn.commit()

    async def publish(self, session_id: str, event: dict[str, Any]) -> None:
        if self.db is not None:
            self.db.conn.execute(
                "INSERT INTO event_stream (session_id, payload, created_at) VALUES (?, ?, ?)",
                (session_id, json.dumps(event, ensure_ascii=False, default=str), time.time()),
            )
            self.db.conn.commit()
            return
        for queue in tuple(self._subscribers.get(session_id, set())):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(dict(event))

    async def subscribe(self, session_id: str) -> AsyncIterator[dict[str, Any]]:
        if self.db is not None:
            row = self.db.conn.execute(
                "SELECT COALESCE(MAX(id), 0) AS id FROM event_stream WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            last_id = int(row["id"])
            while True:
                rows = self.db.conn.execute(
                    "SELECT id, payload FROM event_stream WHERE session_id = ? AND id > ? "
                    "ORDER BY id ASC",
                    (session_id, last_id),
                ).fetchall()
                if rows:
                    for item in rows:
                        last_id = int(item["id"])
                        yield dict(json.loads(item["payload"]))
                else:
                    await asyncio.sleep(self.poll_interval)
            return
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._subscribers.setdefault(session_id, set()).add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            subscribers = self._subscribers.get(session_id)
            if subscribers is not None:
                subscribers.discard(queue)
                if not subscribers:
                    self._subscribers.pop(session_id, None)
