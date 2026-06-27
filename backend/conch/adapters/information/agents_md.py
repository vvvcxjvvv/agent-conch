"""AGENTS.md 信息边界 — 读取项目指令文件作系统提示。

v2 重写：从 conch/domains/information/agents_md.py 迁移，
适配新接口，读取 AGENTS.md 作为 Agent 的系统提示。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from conch.core.extension import Plugin
from conch.core.registry import registry

logger = logging.getLogger(__name__)


@registry.register("information", "agents_md", "1.0")
class AgentsMdProvider(Plugin):
    """AGENTS.md 信息边界 — 读取指令文件作系统提示。

    Args:
        file: AGENTS.md 文件路径（默认项目根目录）
    """

    domain = "information"
    name = "agents_md"
    version = "1.0"
    metadata = {
        "capabilities": ["system_prompt"],
        "description": "读取 AGENTS.md 作系统提示",
    }

    def __init__(self, file: str = "AGENTS.md"):
        self.file = Path(file)
        self._content: str | None = None

    def on_load(self) -> None:
        if self.file.exists():
            self._content = self.file.read_text(encoding="utf-8")
            logger.info("AgentsMdProvider loaded: %s (%d chars)", self.file, len(self._content))
        else:
            logger.warning("AgentsMdProvider: file not found: %s", self.file)
            self._content = ""

    def assemble(self, task: Any, state: Any) -> Any:
        """组装系统提示。"""
        return self._content or ""

    def reload(self) -> None:
        """热重载（AGENTS.md 修改后）。"""
        self.on_load()
