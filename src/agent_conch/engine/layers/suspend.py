"""L/S 层：暂停、恢复与状态持久化 Layer。"""

from __future__ import annotations

from agent_conch.engine.layers.base import Event, GraphContext, Layer
from agent_conch.state.checkpoint import CheckpointManager


class SuspendLayer(Layer):
    name = "suspend"

    def __init__(self) -> None:
        self._suspended: set[str] = set()

    async def on_graph_start(self, ctx: GraphContext) -> None:
        if ctx.session_id in self._suspended:
            ctx.should_abort = True
            ctx.abort_reason = "Session is suspended"

    async def on_event(self, event: Event) -> None:
        session_id = str(event.data.get("session_id", ""))
        if event.type == "pause" and session_id:
            self._suspended.add(session_id)
        elif event.type == "resume" and session_id:
            self._suspended.discard(session_id)

    def is_suspended(self, session_id: str) -> bool:
        return session_id in self._suspended


class PauseStatePersistLayer(Layer):
    name = "pause_state_persist"

    def __init__(self, checkpoints: CheckpointManager) -> None:
        self.checkpoints = checkpoints

    async def on_event(self, event: Event) -> None:
        session_id = str(event.data.get("session_id", ""))
        if not session_id:
            return
        if event.type == "pause":
            await self.checkpoints.pause(
                session_id,
                int(event.data.get("turn_index", 0)),
                agent_state=dict(event.data.get("agent_state") or {}),
            )
        elif event.type == "resume":
            await self.checkpoints.resume(session_id)
