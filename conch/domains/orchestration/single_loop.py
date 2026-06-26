"""域5：单 Agent 循环编排模式。

最小编排模式 — 直接调用注入的 AgentLoop.run()。
task_split / state_sync / conflict_resolve 为空实现，
L3 多 Agent 协作时才需要覆写。
"""
from __future__ import annotations

from typing import Any

from conch.core.extension import Plugin
from conch.core.registry import registry


@registry.register("orchestration", "single_loop", "1.0")
class SingleLoopOrchestration(Plugin):
    """单 Agent 循环编排 — 直接调用注入的 AgentLoop。

    Args:
        max_steps: 单次循环最大步数（兜底，实际由 Profile.max_steps 控制）
    """

    domain = "orchestration"
    name = "single_loop"
    version = "1.0"
    metadata = {
        "cost": "low",
        "context_save": "low",
        "capabilities": ["single_agent"],
        "description": "单 Agent 循环编排模式（默认）",
    }

    def __init__(self, max_steps: int = 50):
        self.max_steps = max_steps

    async def run(self, task: Any, agents: list[Any], state: Any) -> Any:
        """执行单 Agent 循环。

        Args:
            task: 任务描述
            agents: Agent 列表，单 Loop 模式只用第一个（应为 AgentLoop 实例）
            state: 共享状态

        Returns:
            执行结果 State
        """
        if not agents:
            return {"error": "No agents provided"}
        loop = agents[0]
        if hasattr(loop, "run"):
            return await loop.run(task)
        return {"error": "Agent has no run() method"}

    async def task_split(self, task: Any, state: Any) -> list[Any]:
        """单 Agent 模式不拆分任务，原样返回。"""
        return [task]

    async def state_sync(self, agents: list[Any], state: Any) -> None:
        """单 Agent 无需状态同步。"""
        return None

    async def conflict_resolve(self, results: list[Any], state: Any) -> Any:
        """单 Agent 无冲突，取首个结果。"""
        return results[0] if results else None
