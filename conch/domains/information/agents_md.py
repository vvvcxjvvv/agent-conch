"""域1：AGENTS.md 指令文件加载器。

遵循"只当目录不当超级 Prompt"理念（约 100 行，指向深层文档）。
加载 AGENTS.md 文件内容作为系统指令注入上下文。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from conch.core.extension import Plugin
from conch.core.registry import registry


@registry.register("information", "agents_md", "1.0")
class AgentsMdLoader(Plugin):
    """加载 AGENTS.md 文件，作为系统指令注入上下文。

    Args:
        file: AGENTS.md 文件路径
        extra_instructions: 额外指令片段（追加在 AGENTS.md 之后）
        reload: 每次 assemble 是否重新读文件（默认 False，预读缓存）
    """

    domain = "information"
    name = "agents_md"
    version = "1.0"
    metadata = {
        "cost": "low",
        "context_save": "low",
        "capabilities": ["instruction_loading"],
        "description": "加载 AGENTS.md 指令文件作为系统提示",
    }

    def __init__(
        self,
        file: str = "AGENTS.md",
        extra_instructions: str = "",
        reload: bool = False,
    ):
        self.file = Path(file)
        self.extra_instructions = extra_instructions
        self.reload = reload
        self._cache: str | None = None

    def on_load(self) -> None:
        # 加载时预读一次文件，缓存内容
        self._cache = self._read_file()

    def on_reload(self) -> None:
        # 热重载时清缓存，重新读取
        self._cache = None
        super().on_reload()

    def _read_file(self) -> str:
        if not self.file.exists():
            return ""
        try:
            return self.file.read_text(encoding="utf-8")
        except Exception:
            return ""

    def assemble(self, task: Any, state: Any) -> Any:
        """组装指令上下文：系统提示(AGENTS.md) + 额外指令 + 任务描述。

        返回消息列表，供 Provider 层使用。
        """
        if self.reload:
            content = self._read_file()
        else:
            content = self._cache if self._cache is not None else self._read_file()

        parts: list[dict] = []
        if content:
            parts.append({"role": "system", "content": content})
        if self.extra_instructions:
            parts.append({"role": "system", "content": self.extra_instructions})
        parts.append({
            "role": "user",
            "content": str(task) if task is not None else "",
        })
        return parts
