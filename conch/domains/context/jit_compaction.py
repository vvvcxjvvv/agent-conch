"""域3：JIT + 40% 阈值守卫的最小上下文管理。

- assemble() 拼装上下文（指令 + 记忆摘要 + 即时检索）
- should_compact() 检查利用率是否超阈值
- compact() 摘要压缩（最小实现：保留首尾，中间摘要）
"""
from __future__ import annotations

from typing import Any

from conch.core.extension import Plugin
from conch.core.registry import registry


@registry.register("context", "jit_compaction", "1.0")
class JitCompaction(Plugin):
    """JIT 上下文管理 + 40% 利用率阈值压缩守卫。

    Args:
        threshold: 利用率阈值，超过则触发压缩（默认 0.4）
        max_context_tokens: 上下文窗口 token 上限（用于利用率计算）
    """

    domain = "context"
    name = "jit_compaction"
    version = "1.0"
    metadata = {
        "cost": "medium",
        "context_save": "high",
        "capabilities": ["jit", "compaction", "utilization_guard"],
        "description": "JIT 加载 + 40% 阈值守卫 + 摘要压缩",
    }

    def __init__(
        self,
        threshold: float = 0.4,
        max_context_tokens: int = 100000,
    ):
        self.threshold = threshold
        self.max_context_tokens = max_context_tokens

    def assemble(self, task: Any, state: Any) -> Any:
        """组装上下文：JIT 原则，不重复加载已有内容。

        若 state.context 已存在则保留（避免重复加载），
        否则构建最小上下文（任务描述）。
        """
        existing = getattr(state, "context", None)
        if existing is not None:
            # JIT 原则：已有上下文不重新加载
            return existing

        # 最小初始上下文
        return [
            {"role": "user", "content": str(task) if task is not None else ""},
        ]

    def should_compact(self, context: Any) -> bool:
        """检查上下文利用率是否超过阈值。"""
        if self.max_context_tokens <= 0:
            return False
        tokens = self._estimate_tokens(context)
        return (tokens / self.max_context_tokens) > self.threshold

    def compact(self, context: Any, strategy: str = "summary") -> Any:
        """上下文压缩/摘要蒸馏。

        Args:
            context: 当前上下文
            strategy: 压缩策略，"summary" 摘要蒸馏（MVP 唯一实现）
        """
        if strategy == "summary":
            return self._summarize(context)
        # 其他策略保留接口，MVP 不实现
        return context

    def _summarize(self, context: Any) -> Any:
        """最小摘要实现：保留首尾消息，中间消息合并为一条摘要。"""
        if not isinstance(context, list) or len(context) <= 2:
            return context

        head = context[0]
        tail = context[-1]
        middle = context[1:-1]

        # 把中间消息合并为一条摘要（截断防止过长）
        middle_text = " ".join(
            str(m.get("content", "")) if isinstance(m, dict) else str(m)
            for m in middle
        )
        summary = {
            "role": "system",
            "content": f"[compacted {len(middle)} messages] {middle_text[:500]}",
        }
        return [head, summary, tail]

    def _estimate_tokens(self, context: Any) -> int:
        """粗略估算 token 数（按 4 字符 ≈ 1 token）。"""
        if context is None:
            return 0
        if isinstance(context, list):
            total = 0
            for item in context:
                if isinstance(item, dict):
                    total += len(str(item.get("content", "")))
                else:
                    total += len(str(item))
            return total // 4
        return len(str(context)) // 4
