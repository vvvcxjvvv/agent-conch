"""T 层核心工具: tool_search — 工具搜索 (延迟发现)."""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from agent_conch.tools.base import BaseTool, ToolResult
from agent_conch.tools.tool_search import ToolSearch


class ToolSearchInput(BaseModel):
    query: str = Field(..., description="Search keywords for finding tools")
    limit: int = Field(10, description="Max results to return")


class ToolSearchTool(BaseTool):
    """工具搜索工具.

    设计文档要求: ToolSearch 渐进发现.
    非核心工具通过此工具被 Agent 发现.
    """

    name = "tool_search"
    description = (
        "Search for available tools by keyword. "
        "Returns matching tool schemas with descriptions. "
        "Use this when you need a capability not in the core toolset."
    )
    input_model = ToolSearchInput
    is_write_tool = False
    is_core = True
    tags = ["tools", "search", "discovery"]

    def __init__(self, tool_search: ToolSearch):
        self.tool_search = tool_search

    async def execute(self, **kwargs: Any) -> ToolResult:
        validated = ToolSearchInput(**kwargs)
        result = self.tool_search.search(validated.query, validated.limit)

        if not result.matches:
            return ToolResult(
                content=f"No tools found matching '{validated.query}'.",
                metadata={
                    "query": validated.query,
                    "matches": 0,
                    "total_searched": result.total_searched,
                },
            )

        # 格式化结果
        formatted: list[str] = []
        for i, schema in enumerate(result.matches, 1):
            formatted.append(
                f"{i}. {schema.get('name', 'unknown')}\n"
                f"   {schema.get('description', 'no description')}"
            )

        return ToolResult(
            content=f"Found {len(result.matches)} tool(s) matching '{validated.query}':\n\n"
            + "\n\n".join(formatted),
            metadata={
                "query": validated.query,
                "matches": len(result.matches),
                "total_searched": result.total_searched,
                "schemas_json": json.dumps(result.matches),
            },
        )
