"""LlamaGuard 风格护栏分类器。

当前实现不强依赖真实 LlamaGuard 模型，先用类别规则完成二级分类；
后续可替换为本地模型或远程推理服务，接口不变。
"""

from __future__ import annotations

from typing import Any

from conch.core.extension import GuardrailProvider, GuardrailResult, Plugin
from conch.core.registry import registry


_CATEGORY_PATTERNS: dict[str, list[str]] = {
    "destructive_code": [
        "rm -rf",
        "删除所有文件",
        "删除全部文件",
        "格式化磁盘",
        "format c:",
        "drop table",
        "drop database",
        "销毁数据",
    ],
    "data_exfiltration": [
        "导出所有密钥",
        "泄露 api key",
        "打印所有密码",
        "读取 /etc/passwd",
        "复制 ssh 私钥",
        "导出 token",
    ],
    "violence": [
        "制造炸弹",
        "如何杀人",
        "恐怖袭击",
        "shoot school",
        "build a bomb",
    ],
    "self_harm": [
        "自杀",
        "伤害自己",
        "结束生命",
        "kill myself",
        "self harm",
    ],
}


@registry.register("guardrail", "llamaguard_only", "1.0")
class LlamaGuardClassifier(Plugin, GuardrailProvider):
    """LlamaGuard 风格二级分类器。"""

    domain = "guardrail"
    name = "llamaguard_only"
    version = "1.0"
    metadata = {
        "capabilities": ["input_filter", "output_filter", "tool_guard", "category_classification"],
        "framework": "llamaguard",
        "description": "LlamaGuard 风格安全分类器",
    }

    def __init__(self, blocked_categories: list[str] | None = None):
        self.blocked_categories = blocked_categories or list(_CATEGORY_PATTERNS.keys())

    def check_input(self, text: str, state: Any) -> GuardrailResult:
        return self._classify(text)

    def check_output(self, text: str, state: Any) -> GuardrailResult:
        return self._classify(text)

    def check_tool(self, tool: str, args: dict, state: Any) -> GuardrailResult:
        return self._classify(f"{tool}\n{args}")

    def _classify(self, text: str) -> GuardrailResult:
        normalized = text.lower()
        for category in self.blocked_categories:
            patterns = _CATEGORY_PATTERNS.get(category, [])
            for pattern in patterns:
                if pattern.lower() in normalized:
                    return GuardrailResult(
                        blocked=True,
                        reason=f"LlamaGuard blocked category: {category}",
                        action="block",
                    )
        return GuardrailResult(action="pass")
