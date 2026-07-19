"""T/S 层：工具长输出截断、offload 与预览引用。"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from agent_conch.tools.base import ToolResult


class ToolOutputManager:
    def __init__(self, output_dir: str | Path, max_chars: int = 20_000, preview_chars: int = 4_000):
        if max_chars <= 0 or preview_chars <= 0 or preview_chars > max_chars:
            raise ValueError("output limits must satisfy 0 < preview_chars <= max_chars")
        self.output_dir = Path(output_dir)
        self.max_chars = max_chars
        self.preview_chars = preview_chars

    def process(self, tool_name: str, session_id: str, result: ToolResult) -> ToolResult:
        if len(result.content) <= self.max_chars:
            return result
        session = self._safe_segment(session_id or "anonymous")
        destination = self.output_dir / session
        destination.mkdir(parents=True, exist_ok=True)
        path = destination / f"{self._safe_segment(tool_name)}-{uuid.uuid4().hex}.txt"
        path.write_text(result.content, encoding="utf-8")
        os.chmod(path, 0o600)
        metadata = {
            **result.metadata,
            "offloaded": True,
            "artifact_path": str(path),
            "total_chars": len(result.content),
            "preview_chars": self.preview_chars,
        }
        preview = result.content[: self.preview_chars]
        content = (
            f"{preview}\n\n... [output offloaded: {len(result.content)} chars; "
            f"artifact={path}]"
        )
        return ToolResult(content, result.is_error, metadata, result.structured)

    @staticmethod
    def _safe_segment(value: str) -> str:
        cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)
        return cleaned[:80] or "unknown"
