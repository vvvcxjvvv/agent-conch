"""S 层: SQLite 会话状态存储.

设计文档要求:
- SQLite 优先, 所有运行时状态外置到 DB, 不依赖模型记忆
- 不用 JSON/JSONL/sidecar 文件做运行时状态
- 支持结构化查询和恢复能力

P1 阶段基础表: sessions / messages / turns / trajectories
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Session:
    """会话记录."""

    id: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    status: str = "active"  # active | completed | error | paused
    cwd: str = ""
    model_name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Message:
    """消息记录."""

    id: str | None = None
    session_id: str = ""
    role: str = ""  # system | user | assistant | tool
    content: str = ""
    tool_calls: list[dict] | None = None  # assistant 发起的 tool_call
    tool_call_id: str | None = None  # tool 响应对应的 call_id
    turn_index: int = 0
    created_at: float = field(default_factory=time.time)


@dataclass
class Turn:
    """轮次记录."""

    id: str | None = None
    session_id: str = ""
    turn_index: int = 0
    status: str = "pending"  # pending | running | completed | error
    error: str | None = None
    duration_ms: int = 0
    created_at: float = field(default_factory=time.time)


# === DDL ===

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active',
    cwd         TEXT NOT NULL DEFAULT '',
    model_name  TEXT NOT NULL DEFAULT '',
    metadata    TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL,
    role          TEXT NOT NULL,
    content       TEXT NOT NULL DEFAULT '',
    tool_calls    TEXT,          -- JSON array or NULL
    tool_call_id  TEXT,          -- tool response 的关联 id
    turn_index    INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_turn ON messages(session_id, turn_index);

CREATE TABLE IF NOT EXISTS turns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    turn_index  INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    error       TEXT,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);

CREATE TABLE IF NOT EXISTS trajectories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    turn_id     INTEGER,
    step_data   TEXT NOT NULL,    -- JSON: {tool_name, input, output, duration, status}
    created_at  REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
CREATE INDEX IF NOT EXISTS idx_traj_session ON trajectories(session_id);
"""


class SessionDB:
    """SQLite 会话存储.

    所有方法都是同步的 (sqlite3 stdlib), 在异步上下文中通过
    asyncio.to_thread 调用。这样设计的理由:
    1. sqlite3 stdlib 零依赖, 部署简单
    2. SQLite 单写者模型, 无需复杂并发控制
    3. P2/P3 可平滑切换到 aiosqlite
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._init_lock = asyncio.Lock()

    def _connect(self) -> sqlite3.Connection:
        """获取/创建连接 (同步)."""
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,  # 允许跨线程 (配合 to_thread)
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        return self._conn

    @property
    def conn(self) -> sqlite3.Connection:
        return self._connect()

    # === Session ===

    def create_session(
        self,
        session_id: str,
        cwd: str = "",
        model_name: str = "",
        metadata: dict | None = None,
    ) -> Session:
        now = time.time()
        self.conn.execute(
            "INSERT INTO sessions (id, created_at, updated_at, status, cwd, model_name, metadata) "
            "VALUES (?, ?, ?, 'active', ?, ?, ?)",
            (session_id, now, now, cwd, model_name, json.dumps(metadata or {})),
        )
        self.conn.commit()
        return Session(
            id=session_id,
            created_at=now,
            updated_at=now,
            cwd=cwd,
            model_name=model_name,
            metadata=metadata or {},
        )

    def get_session(self, session_id: str) -> Session | None:
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        return Session(
            id=row["id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            status=row["status"],
            cwd=row["cwd"],
            model_name=row["model_name"],
            metadata=json.loads(row["metadata"]),
        )

    def update_session_status(self, session_id: str, status: str) -> None:
        self.conn.execute(
            "UPDATE sessions SET status = ?, updated_at = ? WHERE id = ?",
            (status, time.time(), session_id),
        )
        self.conn.commit()

    # === Messages ===

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str = "",
        tool_calls: list[dict] | None = None,
        tool_call_id: str | None = None,
        turn_index: int = 0,
    ) -> int:
        """添加消息, 返回 message id."""
        cursor = self.conn.execute(
            "INSERT INTO messages (session_id, role, content, tool_calls, tool_call_id, turn_index, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                role,
                content,
                json.dumps(tool_calls) if tool_calls else None,
                tool_call_id,
                turn_index,
                time.time(),
            ),
        )
        self.conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (time.time(), session_id),
        )
        self.conn.commit()
        return cursor.lastrowid  # type: ignore

    def get_messages(
        self, session_id: str, limit: int = 0
    ) -> list[Message]:
        """获取会话消息列表. limit=0 表示全部."""
        query = "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC"
        params: tuple = (session_id,)
        if limit > 0:
            query += " LIMIT ?"
            params = (session_id, limit)
        rows = self.conn.execute(query, params).fetchall()
        return [
            Message(
                id=row["id"],
                session_id=row["session_id"],
                role=row["role"],
                content=row["content"],
                tool_calls=json.loads(row["tool_calls"]) if row["tool_calls"] else None,
                tool_call_id=row["tool_call_id"],
                turn_index=row["turn_index"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def get_messages_as_dicts(self, session_id: str, limit: int = 0) -> list[dict]:
        """获取消息并转为 LLM API 格式的 dict 列表."""
        msgs = self.get_messages(session_id, limit)
        result: list[dict] = []
        for m in msgs:
            entry: dict[str, Any] = {"role": m.role}
            if m.content:
                entry["content"] = m.content
            if m.tool_calls:
                entry["tool_calls"] = m.tool_calls
            if m.tool_call_id:
                entry["tool_call_id"] = m.tool_call_id
            result.append(entry)
        return result

    # === Turns ===

    def start_turn(self, session_id: str, turn_index: int) -> int:
        cursor = self.conn.execute(
            "INSERT INTO turns (session_id, turn_index, status, created_at) VALUES (?, ?, 'running', ?)",
            (session_id, turn_index, time.time()),
        )
        self.conn.commit()
        return cursor.lastrowid  # type: ignore

    def finish_turn(
        self,
        turn_id: int,
        status: str = "completed",
        error: str | None = None,
        duration_ms: int = 0,
    ) -> None:
        self.conn.execute(
            "UPDATE turns SET status = ?, error = ?, duration_ms = ? WHERE id = ?",
            (status, error, duration_ms, turn_id),
        )
        self.conn.commit()

    # === Trajectory (简化版, 完整实现在 trajectory.py) ===

    def save_trajectory_step(
        self,
        session_id: str,
        turn_id: int | None,
        step_data: dict,
    ) -> int:
        cursor = self.conn.execute(
            "INSERT INTO trajectories (session_id, turn_id, step_data, created_at) "
            "VALUES (?, ?, ?, ?)",
            (session_id, turn_id, json.dumps(step_data), time.time()),
        )
        self.conn.commit()
        return cursor.lastrowid  # type: ignore

    def get_trajectory(self, session_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM trajectories WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        return [json.loads(row["step_data"]) for row in rows]

    # === 统计 ===

    def count_messages(self, session_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return row["cnt"]

    def count_turns(self, session_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM turns WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return row["cnt"]

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
