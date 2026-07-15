"""L 层: Subagent 管理 + 孤儿恢复.

设计文档要求:
- SQLite 持久化注册表
- 父 Agent 崩溃后恢复子 Agent (孤儿恢复)
- Delegation: 子 Agent 委托执行
- DELEGATE_BLOCKED_TOOLS: 禁止子 Agent 使用的工具列表

模式:
- Coordinator/Worker: 主 Agent 仅持有 spawn/send_message/stop 工具
- 子 Agent 上下文隔离
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from agent_conch.state.session_db import SessionDB


class SubagentStatus(str, Enum):
    """子 Agent 状态."""

    PENDING = "pending"      # 已创建但未启动
    RUNNING = "running"      # 运行中
    COMPLETED = "completed"  # 正常完成
    FAILED = "failed"        # 执行失败
    ORPHANED = "orphaned"    # 父 Agent 崩溃, 成为孤儿
    CANCELLED = "cancelled"  # 被父 Agent 取消


# 子 Agent 禁止使用的工具 (安全限制)
DELEGATE_BLOCKED_TOOLS: list[str] = [
    "task_manage",  # 不允许子 Agent 创建后台任务
    # "bash",       # 可根据策略禁止子 Agent 执行命令
]


# Subagent 表 DDL
_SUBAGENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS subagents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    subagent_id     TEXT NOT NULL UNIQUE,
    parent_id       TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    task            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    result          TEXT,
    error           TEXT,
    created_at      REAL NOT NULL,
    started_at      REAL,
    finished_at     REAL,
    metadata        TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_subagents_parent ON subagents(parent_id);
CREATE INDEX IF NOT EXISTS idx_subagents_session ON subagents(session_id);
CREATE INDEX IF NOT EXISTS idx_subagents_status ON subagents(status);
"""


@dataclass
class SubagentRecord:
    """子 Agent 记录."""

    id: int | None = None
    subagent_id: str = ""
    parent_id: str = ""  # 父 Agent 的 session_id
    session_id: str = ""  # 子 Agent 自己的 session_id
    task: str = ""
    status: SubagentStatus = SubagentStatus.PENDING
    result: str | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SubagentManager:
    """子 Agent 管理器.

    职责:
    1. 注册/注销子 Agent
    2. 追踪子 Agent 状态
    3. 孤儿恢复: 父 Agent 崩溃后恢复子 Agent
    4. Delegation: 任务委托与结果回收
    """

    def __init__(self, db: SessionDB):
        self.db = db
        self._init_table()

    def _init_table(self) -> None:
        """初始化 subagents 表."""
        self.db.conn.executescript(_SUBAGENT_SCHEMA)
        self.db.conn.commit()

    def spawn(
        self,
        parent_id: str,
        task: str,
        metadata: dict[str, Any] | None = None,
    ) -> SubagentRecord:
        """创建子 Agent.

        Args:
            parent_id: 父 Agent 的 session_id
            task: 委托给子 Agent 的任务描述
            metadata: 额外元数据

        Returns:
            SubagentRecord
        """
        import uuid

        subagent_id = str(uuid.uuid4())[:12]
        session_id = f"sub-{subagent_id}"

        record = SubagentRecord(
            subagent_id=subagent_id,
            parent_id=parent_id,
            session_id=session_id,
            task=task,
            status=SubagentStatus.PENDING,
            metadata=metadata or {},
        )

        cursor = self.db.conn.execute(
            "INSERT INTO subagents "
            "(subagent_id, parent_id, session_id, task, status, created_at, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                record.subagent_id,
                record.parent_id,
                record.session_id,
                record.task,
                record.status.value,
                record.created_at,
                json.dumps(record.metadata, ensure_ascii=False),
            ),
        )
        self.db.conn.commit()
        record.id = cursor.lastrowid
        return record

    def start(self, subagent_id: str) -> bool:
        """标记子 Agent 为运行中."""
        cursor = self.db.conn.execute(
            "UPDATE subagents SET status = ?, started_at = ? WHERE subagent_id = ? AND status = ?",
            (SubagentStatus.RUNNING.value, time.time(), subagent_id, SubagentStatus.PENDING.value),
        )
        self.db.conn.commit()
        return cursor.rowcount > 0

    def complete(
        self, subagent_id: str, result: str
    ) -> bool:
        """标记子 Agent 为已完成."""
        cursor = self.db.conn.execute(
            "UPDATE subagents SET status = ?, result = ?, finished_at = ? WHERE subagent_id = ?",
            (SubagentStatus.COMPLETED.value, result, time.time(), subagent_id),
        )
        self.db.conn.commit()
        return cursor.rowcount > 0

    def fail(
        self, subagent_id: str, error: str
    ) -> bool:
        """标记子 Agent 为失败."""
        cursor = self.db.conn.execute(
            "UPDATE subagents SET status = ?, error = ?, finished_at = ? WHERE subagent_id = ?",
            (SubagentStatus.FAILED.value, error, time.time(), subagent_id),
        )
        self.db.conn.commit()
        return cursor.rowcount > 0

    def cancel(self, subagent_id: str) -> bool:
        """取消子 Agent."""
        cursor = self.db.conn.execute(
            "UPDATE subagents SET status = ?, finished_at = ? WHERE subagent_id = ?",
            (SubagentStatus.CANCELLED.value, time.time(), subagent_id),
        )
        self.db.conn.commit()
        return cursor.rowcount > 0

    def get(self, subagent_id: str) -> SubagentRecord | None:
        """获取子 Agent 记录."""
        row = self.db.conn.execute(
            "SELECT * FROM subagents WHERE subagent_id = ?",
            (subagent_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def list_by_parent(self, parent_id: str) -> list[SubagentRecord]:
        """列出父 Agent 的所有子 Agent."""
        rows = self.db.conn.execute(
            "SELECT * FROM subagents WHERE parent_id = ? ORDER BY created_at ASC",
            (parent_id,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_by_status(self, status: SubagentStatus) -> list[SubagentRecord]:
        """按状态列出子 Agent."""
        rows = self.db.conn.execute(
            "SELECT * FROM subagents WHERE status = ? ORDER BY created_at ASC",
            (status.value,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def find_orphans(self) -> list[SubagentRecord]:
        """查找孤儿子 Agent.

        孤儿条件:
        - 状态为 RUNNING 或 PENDING
        - 父 Agent 的 session 已不存在或状态为 error/completed

        Returns:
            孤儿子 Agent 列表
        """
        # 查找所有运行中/待处理的子 Agent
        active_subagents = self.list_by_status(SubagentStatus.RUNNING)
        active_subagents.extend(self.list_by_status(SubagentStatus.PENDING))

        orphans: list[SubagentRecord] = []
        for sub in active_subagents:
            # 检查父 Agent 是否还存在
            parent_session = self.db.get_session(sub.parent_id)
            if parent_session is None:
                orphans.append(sub)
            elif parent_session.status in ("error", "completed"):
                orphans.append(sub)

        return orphans

    def recover_orphans(self) -> list[SubagentRecord]:
        """恢复孤儿子 Agent.

        恢复策略:
        - 标记为 ORPHANED
        - 可由新父 Agent 认领或终止

        Returns:
            被标记为 ORPHANED 的子 Agent 列表
        """
        orphans = self.find_orphans()
        for sub in orphans:
            self.db.conn.execute(
                "UPDATE subagents SET status = ? WHERE subagent_id = ?",
                (SubagentStatus.ORPHANED.value, sub.subagent_id),
            )
        self.db.conn.commit()
        return orphans

    def adopt_orphan(
        self, subagent_id: str, new_parent_id: str
    ) -> bool:
        """认领孤儿子 Agent.

        Args:
            subagent_id: 子 Agent ID
            new_parent_id: 新父 Agent 的 session_id
        """
        cursor = self.db.conn.execute(
            "UPDATE subagents SET parent_id = ?, status = ? WHERE subagent_id = ? AND status = ?",
            (new_parent_id, SubagentStatus.PENDING.value, subagent_id, SubagentStatus.ORPHANED.value),
        )
        self.db.conn.commit()
        return cursor.rowcount > 0

    def get_blocked_tools(self) -> list[str]:
        """获取子 Agent 禁止使用的工具列表."""
        return list(DELEGATE_BLOCKED_TOOLS)

    def _row_to_record(self, row) -> SubagentRecord:
        """将数据库行转为 SubagentRecord."""
        return SubagentRecord(
            id=row["id"],
            subagent_id=row["subagent_id"],
            parent_id=row["parent_id"],
            session_id=row["session_id"],
            task=row["task"],
            status=SubagentStatus(row["status"]),
            result=row["result"],
            error=row["error"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )
