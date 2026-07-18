"""T/C 层：FTS5 跨会话搜索工具。"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from agent_conch.context.memory.manager import MetaMemory
from agent_conch.tools.base import BaseTool, ToolResult


class SessionSearchInput(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(10, ge=1, le=50)


class SessionSearchTool(BaseTool):
    name = "session_search"
    description = "Search summaries of previous Agent-Conch sessions using SQLite FTS5."
    input_model = SessionSearchInput
    is_core = False
    tags = ["search", "session", "memory"]

    def __init__(self, memory: MetaMemory) -> None:
        self.memory = memory

    async def execute(self, **kwargs: Any) -> ToolResult:
        validated = SessionSearchInput(**kwargs)
        results = self.memory.search(validated.query, validated.limit)
        return ToolResult(
            content=json.dumps(results, ensure_ascii=False, indent=2),
            metadata={"results_count": len(results), "query": validated.query},
        )
