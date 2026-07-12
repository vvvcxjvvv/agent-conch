"""T 层核心工具: glob — 文件模式匹配."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from agent_conch.sandbox.path_validator import PathValidator
from agent_conch.tools.base import BaseTool, ToolResult


class GlobInput(BaseModel):
    pattern: str = Field(..., description="Glob pattern (e.g. '**/*.py', 'src/**/*.ts')")
    path: str = Field(".", description="Base directory to search from")


class GlobTool(BaseTool):
    """文件模式匹配工具.

    使用 pathlib 的 glob 语法.
    """

    name = "glob"
    description = (
        "Find files matching a glob pattern. "
        "Returns a list of matching file paths, sorted by modification time (newest first)."
    )
    input_model = GlobInput
    is_write_tool = False
    is_core = True
    tags = ["file", "search", "pattern"]

    def __init__(self, validator: PathValidator):
        self.validator = validator

    async def execute(self, **kwargs: Any) -> ToolResult:
        validated = GlobInput(**kwargs)
        try:
            base = self.validator.validate_or_raise(validated.path, "read")
            base_path = Path(base)
            if not base_path.is_dir():
                return ToolResult.error(f"Not a directory: {validated.path}")

            matches = sorted(
                base_path.glob(validated.pattern),
                key=lambda p: p.stat().st_mtime if p.exists() else 0,
                reverse=True,
            )

            # 限制结果数量
            max_results = 200
            truncated = len(matches) > max_results
            result_list = [str(m.relative_to(base_path)) for m in matches[:max_results]]

            content = "\n".join(result_list) if result_list else "No matches found."
            if truncated:
                content += f"\n... [showing {max_results} of {len(matches)} matches]"

            return ToolResult(
                content=content,
                metadata={
                    "pattern": validated.pattern,
                    "path": validated.path,
                    "total_matches": len(matches),
                    "truncated": truncated,
                },
            )
        except PermissionError as e:
            return ToolResult.error(f"Permission denied: {e!s}")
        except Exception as e:
            return ToolResult.error(f"Glob error: {e!s}")
