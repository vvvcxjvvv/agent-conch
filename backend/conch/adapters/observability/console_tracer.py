"""域7：控制台轨迹输出。

每个 step 打印 step 数/动作/工具/token/cost。
维护四级指标集，MVP 先实现执行类与成本类：
- 执行类：step 数、工具调用成功率、Context Reset 次数
- 成本类：token 消耗、模型费用
效果类随域6补齐，健康类随域9补齐。
"""
from __future__ import annotations

import sys
from typing import Any, TextIO

from conch.core.extension import Plugin
from conch.core.registry import registry


@registry.register("observability", "console_tracer", "1.0")
class ConsoleTracer(Plugin):
    """控制台轨迹输出 — MVP 实现。

    Args:
        verbose: 是否打印每步轨迹
        stream: 输出流（默认 stderr）
    """

    domain = "observability"
    name = "console_tracer"
    version = "1.0"
    metadata = {
        "cost": "low",
        "context_save": "low",
        "capabilities": ["trace", "metrics"],
        "description": "控制台轨迹输出（执行类+成本类指标）",
    }

    def __init__(self, verbose: bool = True, stream: TextIO | None = None):
        self.verbose = verbose
        self.stream = stream or sys.stderr
        # 四级指标集 — MVP 先做执行类 + 成本类
        self._metrics = {
            # 执行类
            "steps": 0,
            "tool_calls": 0,
            "tool_successes": 0,
            "tool_failures": 0,
            "context_resets": 0,
            # 成本类
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_cost": 0.0,
            # 效果类（占位，随域6 补齐）
            "task_success": None,
            # 健康类（占位，随域9 补齐）
            "permission_denials": 0,
            "sandbox_errors": 0,
        }

    def trace(self, state: Any) -> None:
        """记录一个 step 的轨迹。"""
        if not state or not getattr(state, "actions", None):
            return

        # 只处理最后一个 action（避免重复累计）
        action = state.actions[-1]
        self._metrics["steps"] = state.steps

        action_type = action.get("type", "unknown")
        usage = action.get("usage", {}) or {}
        tokens = usage.get("total_tokens", 0)
        cost = usage.get("cost", 0.0)

        # 成本类累计
        self._metrics["total_tokens"] += tokens
        self._metrics["total_cost"] += cost
        self._metrics["prompt_tokens"] += usage.get("prompt_tokens", 0)
        self._metrics["completion_tokens"] += usage.get("completion_tokens", 0)

        # 执行类：工具调用统计
        if action_type == "tool_call":
            self._metrics["tool_calls"] += 1
            result = action.get("result")
            if isinstance(result, dict) and result.get("error"):
                self._metrics["tool_failures"] += 1
            else:
                self._metrics["tool_successes"] += 1

        # 降级标记
        degrade = getattr(state, "degrade_level", None)
        degrade_val = degrade.value if hasattr(degrade, "value") else 0
        if degrade_val == 1:  # L1_COMPACT
            self._metrics["context_resets"] += 1

        # 控制台输出
        if self.verbose:
            tool_name = action.get("tool", "-")
            self._print(
                f"[step {state.steps:>3}] action={action_type:<10} "
                f"tool={tool_name:<15} "
                f"tokens={tokens:<6} cost=${cost:.4f} | "
                f"cum_tokens={state.total_tokens} "
                f"cum_cost=${state.total_cost:.4f}"
            )

    def _print(self, msg: str) -> None:
        try:
            self.stream.write(msg + "\n")
            self.stream.flush()
        except Exception:
            pass

    def metrics(self) -> dict[str, Any]:
        """返回当前累计指标。"""
        m = dict(self._metrics)
        # 计算工具成功率
        total = m["tool_successes"] + m["tool_failures"]
        m["tool_success_rate"] = (m["tool_successes"] / total) if total > 0 else 0.0
        return m
