"""L 层: ExecutionLimitsLayer — 步骤/时间限制."""
from __future__ import annotations

import time

from agent_conch.engine.layers.base import GraphContext, Layer, NodeContext


class ExecutionLimitsLayer(Layer):
    """执行限制 Layer.

    检查:
    - max_turns: 最大轮次
    - max_time: 最大执行时间(秒)
    超限时设置 should_abort 中止 Agent run.
    """

    name = "execution_limits"

    def __init__(self, max_turns: int = 50, max_time: int = 600):
        self.max_turns = max_turns
        self.max_time = max_time

    async def on_graph_start(self, ctx: GraphContext) -> None:
        ctx.start_time = time.time()
        ctx.max_turns = self.max_turns
        ctx.max_time = self.max_time

    async def on_node_run_start(self, ctx: NodeContext) -> None:
        # 检查轮次限制
        if ctx.turn_index >= self.max_turns:
            # 通过 GraphContext 检查 (NodeContext 不直接持有 GraphContext)
            pass  # AgentLoop 中检查

    def check_limits(self, turn_count: int, start_time: float) -> tuple[bool, str]:
        """检查是否超限.

        Returns:
            (should_abort, reason)
        """
        if turn_count >= self.max_turns:
            return True, f"Max turns ({self.max_turns}) reached"
        elapsed = time.time() - start_time
        if elapsed >= self.max_time:
            return True, f"Max time ({self.max_time}s) reached"
        return False, ""
