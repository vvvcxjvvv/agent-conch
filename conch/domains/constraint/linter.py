"""域8：最小 Linter — 检查常见错误模式 + 简单恢复建议。

MVP 实现：
- validate() 对 action 内容做常见错误模式检测
- recover() 返回恢复建议（不强制）
"""
from __future__ import annotations

import re
from typing import Any

from conch.core.extension import Plugin
from conch.core.registry import registry


# 常见错误模式（pattern, 描述）
ERROR_PATTERNS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"^\s*print\s+[^\(]", re.MULTILINE),
        "print 应使用函数调用形式 print(...)",
    ),
    (
        re.compile(r"^\s*except\s*:", re.MULTILINE),
        "裸 except 不应使用，需指定异常类型",
    ),
    (
        re.compile(r"\bTODO\b", re.IGNORECASE),
        "存在 TODO 标记，未完成",
    ),
    (
        re.compile(r"^\s*import\s+\*", re.MULTILINE),
        "通配符 import 不推荐",
    ),
    (
        re.compile(r"\beval\s*\(", re.MULTILINE),
        "使用 eval() 存在安全风险",
    ),
]


@registry.register("constraint", "linter", "1.0")
class Linter(Plugin):
    """最小 Linter — 常见错误模式检测 + 恢复建议。

    Args:
        rules: 自定义规则列表（pattern, message），默认用 ERROR_PATTERNS
    """

    domain = "constraint"
    name = "linter"
    version = "1.0"
    metadata = {
        "cost": "low",
        "context_save": "low",
        "capabilities": ["lint", "validate", "recover"],
        "description": "最小 Linter — 常见错误模式检测 + 恢复建议",
    }

    def __init__(self, rules: list | None = None):
        self.rules = rules if rules is not None else ERROR_PATTERNS

    def validate(self, action: Any, state: Any) -> Any:
        """校验动作是否合规。

        支持：
        - dict action：对 content / result.content 做 lint
        - str action：直接 lint
        """
        if isinstance(action, dict):
            content = action.get("content", "") or ""
            result = action.get("result")
            if isinstance(result, dict):
                content += " " + str(result.get("content", ""))
            issues = self._lint(content)
            return {"valid": len(issues) == 0, "issues": issues}
        if isinstance(action, str):
            issues = self._lint(action)
            return {"valid": len(issues) == 0, "issues": issues}
        return {"valid": True, "issues": []}

    def recover(self, error: Exception, state: Any) -> Any:
        """故障恢复 — 返回建议，不强制执行。"""
        return {
            "recovered": False,
            "suggestion": (
                f"遇到异常 {type(error).__name__}: {error}。"
                "建议检查上下文或重试上一步。"
            ),
        }

    def _lint(self, content: str) -> list[str]:
        """对内容做模式匹配，返回问题列表。"""
        issues = []
        for pattern, msg in self.rules:
            if pattern.search(content):
                issues.append(msg)
        return issues
