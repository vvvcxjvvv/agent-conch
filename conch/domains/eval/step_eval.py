"""域6：最小单步评测 — 检查 action 是否有错误。

三层评测中 MVP 先实现单步评测（step-level），
回合评测与多轮评测延后到阶段二。
"""
from __future__ import annotations

from typing import Any

from conch.core.extension import Plugin
from conch.core.registry import registry


@registry.register("eval", "step_eval", "1.0")
class StepEvaluator(Plugin):
    """单步评测：检查最后一个 action 是否出错。

    Args:
        eval_interval: 每隔多少步评测一次（默认每步都评）
    """

    domain = "eval"
    name = "step_eval"
    version = "1.0"
    metadata = {
        "cost": "low",
        "context_save": "low",
        "capabilities": ["step_eval"],
        "description": "最小单步评测：检查 action 是否有错误",
    }

    def __init__(self, eval_interval: int = 1):
        self.eval_interval = max(1, eval_interval)

    def should_eval(self, state: Any) -> bool:
        """判断当前是否需要评测（按间隔）。"""
        if not state or not getattr(state, "actions", None):
            return False
        return state.steps % self.eval_interval == 0

    async def eval(self, state: Any) -> Any:
        """执行单步评测：检查最后一步 action 是否出错。"""
        if not state.actions:
            return {"pass": True, "message": "no actions yet"}

        action = state.actions[-1]
        result = action.get("result")

        # 工具调用结果检查
        if isinstance(result, dict) and result.get("error"):
            return {
                "pass": False,
                "message": f"last action error: {result['error']}",
                "action_type": action.get("type"),
                "step": state.steps,
            }

        return {
            "pass": True,
            "message": "ok",
            "action_type": action.get("type"),
            "step": state.steps,
        }
