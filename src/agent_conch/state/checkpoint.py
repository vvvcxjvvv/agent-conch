"""S 层: 快照/恢复管理 — Checkpoint / Pause / Resume.

设计文档要求:
- 完整状态序列化到 SQLite: GraphRuntimeState + generate_entity
- 支持长时间暂停后恢复 (等待人工审批)
- 序列化 → 恢复时反序列化重建

P2: 完整实现 Pause/Resume 状态持久化.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from agent_conch.state.session_db import SessionDB


@dataclass
class Checkpoint:
    """检查点: Agent 运行状态快照."""

    id: int | None = None
    session_id: str = ""
    turn_index: int = 0
    status: str = "checkpoint"  # checkpoint | paused | suspended
    messages_snapshot: list[dict] = field(default_factory=list)
    agent_state: dict[str, Any] = field(default_factory=dict)
    context_state: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


# Checkpoint 表 DDL
_CHECKPOINT_SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoints (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id        TEXT NOT NULL,
    turn_index        INTEGER NOT NULL,
    status            TEXT NOT NULL DEFAULT 'checkpoint',
    messages_snapshot TEXT NOT NULL DEFAULT '[]',
    agent_state       TEXT NOT NULL DEFAULT '{}',
    context_state     TEXT NOT NULL DEFAULT '{}',
    created_at        REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
CREATE INDEX IF NOT EXISTS idx_checkpoints_session ON checkpoints(session_id);
"""


class CheckpointManager:
    """检查点管理器.

    职责:
    1. save_checkpoint: 保存 Agent 运行状态快照到 SQLite
    2. load_checkpoint: 加载最新检查点
    3. restore: 从检查点恢复会话
    4. pause / resume: 暂停/恢复 Agent 执行

    使用场景:
    - 长时间任务暂停后恢复
    - 等待人工审批后继续执行
    - 崩溃后恢复
    """

    def __init__(self, db: SessionDB):
        self.db = db
        self._init_table()

    def _init_table(self) -> None:
        """初始化 checkpoints 表."""
        self.db.conn.executescript(_CHECKPOINT_SCHEMA)
        self.db.conn.commit()

    async def save_checkpoint(
        self,
        session_id: str,
        turn_index: int,
        messages: list[dict[str, Any]] | None = None,
        agent_state: dict[str, Any] | None = None,
        context_state: dict[str, Any] | None = None,
        status: str = "checkpoint",
    ) -> int:
        """保存检查点.

        Args:
            session_id: 会话 ID
            turn_index: 当前轮次
            messages: 消息快照 (从 DB 加载或传入)
            agent_state: Agent 运行时状态
            context_state: Context Engine 状态
            status: checkpoint | paused | suspended

        Returns:
            checkpoint id
        """
        # 如果未提供 messages, 从 DB 加载
        if messages is None:
            messages = self.db.get_messages_as_dicts(session_id)

        cursor = self.db.conn.execute(
            "INSERT INTO checkpoints "
            "(session_id, turn_index, status, messages_snapshot, agent_state, context_state, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                turn_index,
                status,
                json.dumps(messages, ensure_ascii=False),
                json.dumps(agent_state or {}, ensure_ascii=False),
                json.dumps(context_state or {}, ensure_ascii=False),
                time.time(),
            ),
        )
        self.db.conn.commit()
        return cursor.lastrowid  # type: ignore

    async def load_checkpoint(
        self, session_id: str, checkpoint_id: int | None = None
    ) -> Checkpoint | None:
        """加载检查点.

        Args:
            session_id: 会话 ID
            checkpoint_id: 指定检查点 ID (None = 最新)

        Returns:
            Checkpoint 或 None
        """
        if checkpoint_id is not None:
            row = self.db.conn.execute(
                "SELECT * FROM checkpoints WHERE id = ?",
                (checkpoint_id,),
            ).fetchone()
        else:
            row = self.db.conn.execute(
                "SELECT * FROM checkpoints WHERE session_id = ? ORDER BY created_at DESC LIMIT 1",
                (session_id,),
            ).fetchone()

        if row is None:
            return None

        return Checkpoint(
            id=row["id"],
            session_id=row["session_id"],
            turn_index=row["turn_index"],
            status=row["status"],
            messages_snapshot=json.loads(row["messages_snapshot"]),
            agent_state=json.loads(row["agent_state"]),
            context_state=json.loads(row["context_state"]),
            created_at=row["created_at"],
        )

    async def list_checkpoints(
        self, session_id: str
    ) -> list[Checkpoint]:
        """列出会话的所有检查点."""
        rows = self.db.conn.execute(
            "SELECT * FROM checkpoints WHERE session_id = ? ORDER BY created_at DESC",
            (session_id,),
        ).fetchall()

        return [
            Checkpoint(
                id=row["id"],
                session_id=row["session_id"],
                turn_index=row["turn_index"],
                status=row["status"],
                messages_snapshot=json.loads(row["messages_snapshot"]),
                agent_state=json.loads(row["agent_state"]),
                context_state=json.loads(row["context_state"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    async def restore(self, session_id: str) -> bool:
        """从最新检查点恢复会话.

        恢复流程:
        1. 加载最新检查点
        2. 清空当前会话消息
        3. 从快照重建消息
        4. 更新会话状态为 active

        Returns:
            True 表示恢复成功
        """
        checkpoint = await self.load_checkpoint(session_id)
        if checkpoint is None:
            return False

        # 清空当前消息 (保留 system prompt)
        self.db.conn.execute(
            "DELETE FROM messages WHERE session_id = ?",
            (session_id,),
        )

        # 从快照重建消息
        for msg in checkpoint.messages_snapshot:
            self.db.add_message(
                session_id=session_id,
                role=msg.get("role", "user"),
                content=msg.get("content", ""),
                tool_calls=msg.get("tool_calls"),
                tool_call_id=msg.get("tool_call_id"),
                turn_index=checkpoint.turn_index,
            )

        # 更新会话状态
        self.db.update_session_status(session_id, "active")

        return True

    async def pause(
        self,
        session_id: str,
        turn_index: int,
        messages: list[dict[str, Any]] | None = None,
        agent_state: dict[str, Any] | None = None,
    ) -> int:
        """暂停 Agent 执行, 保存检查点.

        Args:
            session_id: 会话 ID
            turn_index: 当前轮次
            messages: 消息快照
            agent_state: Agent 状态

        Returns:
            checkpoint id
        """
        checkpoint_id = await self.save_checkpoint(
            session_id=session_id,
            turn_index=turn_index,
            messages=messages,
            agent_state=agent_state,
            status="paused",
        )
        self.db.update_session_status(session_id, "paused")
        return checkpoint_id

    async def resume(self, session_id: str) -> Checkpoint | None:
        """恢复暂停的 Agent 执行.

        Returns:
            恢复的 Checkpoint, 或 None 如果没有暂停状态
        """
        checkpoint = await self.load_checkpoint(session_id)
        if checkpoint is None or checkpoint.status != "paused":
            return None

        success = await self.restore(session_id)
        if not success:
            return None

        return checkpoint

    async def delete_checkpoint(self, checkpoint_id: int) -> None:
        """删除检查点."""
        self.db.conn.execute(
            "DELETE FROM checkpoints WHERE id = ?",
            (checkpoint_id,),
        )
        self.db.conn.commit()

    async def delete_all(self, session_id: str) -> None:
        """删除会话的所有检查点."""
        self.db.conn.execute(
            "DELETE FROM checkpoints WHERE session_id = ?",
            (session_id,),
        )
        self.db.conn.commit()
