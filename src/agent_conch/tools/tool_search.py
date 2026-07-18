"""T 层: 渐进式工具发现.

设计文档要求:
- ToolSearch: 渐进发现 + 自动阈值
- 非核心工具 schema 超过 context window 10% 时启用
- 核心工具始终暴露, 非核心工具按需发现
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_conch.tools.registry import ToolRegistry


@dataclass
class ToolSearchResult:
    """工具搜索结果."""

    query: str
    matches: list[dict[str, Any]] = field(default_factory=list)
    total_searched: int = 0


class ToolSearch:
    """渐进式工具发现.

    策略:
    1. 核心工具 (is_core=True) 始终暴露给 LLM
    2. 非核心工具默认隐藏, 通过 tool_search 工具发现
    3. 自动阈值: 非核心工具 schema 总 token 超过 context window 10% 时启用搜索
    """

    def __init__(
        self,
        registry: ToolRegistry,
        auto_threshold: float = 0.10,
        context_window: int = 128000,
    ):
        self.registry = registry
        self.auto_threshold = auto_threshold
        self.context_window = context_window

    def should_enable_search(self) -> bool:
        """判断是否需要启用 ToolSearch.

        当非核心工具 schema 的总 token 估算超过 context window 的阈值时启用.
        """
        non_core_schemas = []
        for name in self.registry.list_names():
            tool = self.registry.get(name)
            if tool and not tool.is_core:
                non_core_schemas.append(tool.to_schema())

        if not non_core_schemas:
            return False

        # 粗略估算 token: schema JSON 字符数 / 4
        import json

        total_chars = sum(len(json.dumps(s)) for s in non_core_schemas)
        estimated_tokens = total_chars // 4
        threshold_tokens = int(self.context_window * self.auto_threshold)

        return estimated_tokens > threshold_tokens

    def search(self, query: str, limit: int = 10) -> ToolSearchResult:
        """搜索工具.

        基于工具 name/description/tags 做关键词匹配.
        """
        query_lower = query.lower()
        keywords = query_lower.split()
        matches: list[tuple[int, dict[str, Any]]] = []

        for name in self.registry.list_names():
            tool = self.registry.get(name)
            if tool is None or tool.is_core:
                continue  # 核心工具不需要搜索

            # 计算匹配分数
            score = 0
            name_lower = tool.name.lower()
            desc_lower = tool.description.lower()
            tags_lower = [t.lower() for t in tool.tags]

            for kw in keywords:
                if kw in name_lower:
                    score += 3
                if kw in desc_lower:
                    score += 2
                for tag in tags_lower:
                    if kw in tag:
                        score += 1

            if score > 0:
                schema = tool.to_schema()
                matches.append((score, schema))

        # 按分数排序
        matches.sort(key=lambda x: x[0], reverse=True)
        top_matches = [m[1] for m in matches[:limit]]

        return ToolSearchResult(
            query=query,
            matches=top_matches,
            total_searched=len(self.registry.list_names()),
        )

    def get_search_tool_schema(self) -> dict[str, Any]:
        """返回 tool_search 工具自身的 schema."""
        return {
            "name": "tool_search",
            "description": (
                "Search for available tools by keyword. "
                "Use this when you need a tool that is not in the core set. "
                "Returns matching tool schemas with usage instructions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search keywords for finding tools",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (default 10)",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
        }
