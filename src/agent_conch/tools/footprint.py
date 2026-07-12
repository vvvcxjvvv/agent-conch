"""T 层: Footprint Ladder 六级扩展阶梯.

设计文档要求:
- 控制核心工具膨胀
- 扩展优先级: 扩展现有代码 → CLI+Skill → service-gated → plugin → MCP → 新核心工具
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any


class FootprintLevel(IntEnum):
    """扩展阶梯级别 (数字越小优先级越高)."""

    EXTEND_EXISTING = 1  # 扩展现有工具代码 (零成本, 首选)
    CLI_WITH_SKILL = 2  # CLI 命令 + SKILL.md (知识注入, 不增加工具数)
    SERVICE_GATED = 3  # service-gated tool (check_fn 条件加载)
    PLUGIN = 4  # plugin tool (隔离运行)
    MCP_SERVER = 5  # MCP server tool (外部 MCP 工具)
    NEW_CORE = 6  # 新核心工具 (最后手段, 需架构评审)


@dataclass
class FootprintSuggestion:
    """扩展建议."""

    needed_capability: str
    suggested_level: FootprintLevel
    rationale: str
    action: str


FOOTPRINT_DESCRIPTIONS: dict[FootprintLevel, str] = {
    FootprintLevel.EXTEND_EXISTING: "扩展现有工具代码 — 零成本, 首选. 在现有工具中增加参数或分支.",
    FootprintLevel.CLI_WITH_SKILL: "CLI 命令 + SKILL.md — 知识注入, 不增加工具数. 通过 bash 工具 + Skill 指导.",
    FootprintLevel.SERVICE_GATED: "service-gated tool — 条件加载工具, 通过 check_fn 控制可用性.",
    FootprintLevel.PLUGIN: "plugin tool — 插件工具, 隔离运行, 不影响核心.",
    FootprintLevel.MCP_SERVER: "MCP server tool — 外部 MCP 工具, 通过 MCP 协议接入.",
    FootprintLevel.NEW_CORE: "新核心工具 — 最后手段, 需架构评审. 仅在以上方案均不可行时.",
}


class FootprintLadder:
    """Footprint Ladder 评估器.

    当需要新能力时, 按 Ladder 从低到高评估:
    能否扩展现有工具? 能否用 CLI+Skill? 是否需要 service-gated?
    以此类推, 尽量保持核心工具集精简.
    """

    def evaluate(self, needed_capability: str, existing_tools: list[str] | None = None) -> FootprintSuggestion:
        """评估新能力的扩展建议."""
        # P1: 简化逻辑, 实际应根据能力描述做语义匹配
        capability_lower = needed_capability.lower()

        # 如果现有工具能覆盖 (文件/搜索/执行相关)
        file_keywords = ["file", "read", "write", "edit", "文件", "读取", "写入"]
        search_keywords = ["search", "find", "grep", "glob", "搜索", "查找"]

        if any(kw in capability_lower for kw in file_keywords + search_keywords):
            return FootprintSuggestion(
                needed_capability=needed_capability,
                suggested_level=FootprintLevel.EXTEND_EXISTING,
                rationale="现有工具 (read_file/write_file/grep/glob) 可能已覆盖此能力",
                action="检查现有工具参数, 尝试通过参数组合实现",
            )

        # 如果是 CLI 能力
        cli_keywords = ["run", "execute", "command", "shell", "运行", "执行"]
        if any(kw in capability_lower for kw in cli_keywords):
            return FootprintSuggestion(
                needed_capability=needed_capability,
                suggested_level=FootprintLevel.CLI_WITH_SKILL,
                rationale="通过 bash 工具 + SKILL.md 指导可实现",
                action="编写 SKILL.md 描述命令用法, 用 bash 工具执行",
            )

        # 默认: service-gated
        return FootprintSuggestion(
            needed_capability=needed_capability,
            suggested_level=FootprintLevel.SERVICE_GATED,
            rationale="需要条件加载的工具能力",
            action="实现 BaseTool 子类, 设置 check_fn 控制可用性",
        )

    def describe_levels(self) -> list[str]:
        """返回所有级别的描述."""
        return [
            f"Level {level.value}: {FOOTPRINT_DESCRIPTIONS[level]}"
            for level in FootprintLevel
        ]
