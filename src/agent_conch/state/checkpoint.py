"""S 层: 快照/恢复管理.

设计文档要求:
- 完整状态序列化到 SQLite: GraphRuntimeState + generate_entity
- 支持长时间暂停后恢复

P1: 占位实现, 提供接口骨架
P2: 完整实现 Pause/Resume 状态持久化
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_conch.state.session_db import SessionDB


@dataclass
class Checkpoint:
    """检查点: Agent 运行状态快照."""

    session_id: str
    turn_index: int
    status: str = "checkpoint"  # checkpoint | paused | suspended
    messages_snapshot: list[dict] = field(default_factory=list)
    agent_state: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0


class CheckpointManager:
    """检查点管理器.

    P1 阶段仅提供接口骨架, 不实际使用.
    P2 阶段完整实现 Pause/Resume 的状态序列化与恢复.
    """

    def __init__(self, db: SessionDB):
        self.db = db

    async def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        """保存检查点 (P2 实现)."""
        # P2: 序列化 messages_snapshot + agent_state 到 SQLite
        raise NotImplementedError("Checkpoint save will be implemented in P2")

    async def load_checkpoint(self, session_id: str) -> Checkpoint | None:
        """加载最新检查点 (P2 实现)."""
        raise NotImplementedError("Checkpoint load will be implemented in P2")

    async def restore(self, session_id: str) -> bool:
        """从检查点恢复会话 (P2 实现)."""
        raise NotImplementedError("Checkpoint restore will be implemented in P2")
