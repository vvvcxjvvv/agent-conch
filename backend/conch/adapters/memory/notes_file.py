"""域4：基于 NOTES.md 文件的结构化记忆。

五分法中 MVP 先实现：
- short-term（短期）：内存工作记忆
- episodic（情景）：NOTES.md 文件，跨 step 恢复

语义/长期/程序性记忆延后到阶段三。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from conch.core.extension import Plugin
from conch.core.registry import registry


@registry.register("memory", "notes_file", "1.0")
class NotesFileMemory(Plugin):
    """基于 NOTES.md 的结构化记忆 — short + episodic。

    Args:
        path: NOTES.md 文件路径
    """

    domain = "memory"
    name = "notes_file"
    version = "1.0"
    metadata = {
        "cost": "low",
        "context_save": "medium",
        "capabilities": ["short_term", "episodic"],
        "description": "NOTES.md 文件记忆系统（short + episodic）",
    }

    def __init__(self, path: str = "NOTES.md"):
        self.path = Path(path)
        # short-term: 内存
        self._short: dict[str, Any] = {}
        # episodic: 文件持久化
        self._episodic_cache: list[str] = []

    def on_load(self) -> None:
        # 加载时预读 episodic 文件
        if self.path.exists():
            try:
                self._episodic_cache = self.path.read_text(encoding="utf-8").splitlines()
            except Exception:
                self._episodic_cache = []

    def store(self, key: str, value: Any, mem_type: str = "short") -> None:
        """存储记忆。

        Args:
            key: 记忆键
            value: 记忆值
            mem_type: 记忆类型，"short" / "episodic"
                      （semantic/long_term/procedural MVP 不实现）
        """
        if mem_type == "short":
            self._short[key] = value
        elif mem_type == "episodic":
            entry = self._format_episodic(key, value)
            self._episodic_cache.append(entry)
            self._flush()
        else:
            # 其他类型 MVP 不实现，暂存到 short
            self._short[f"{mem_type}:{key}"] = value

    def recall(self, query: str, mem_type: str = "short", limit: int = 5) -> list[Any]:
        """检索记忆（简单子串匹配）。"""
        if mem_type == "short":
            results = []
            q = query.lower()
            for k, v in self._short.items():
                if q in str(k).lower() or q in str(v).lower():
                    results.append({"key": k, "value": v})
                if len(results) >= limit:
                    break
            return results
        if mem_type == "episodic":
            results = []
            q = query.lower()
            # 从最新到最旧检索
            for entry in reversed(self._episodic_cache):
                if q in entry.lower():
                    results.append(entry)
                if len(results) >= limit:
                    break
            return results
        return []

    def _format_episodic(self, key: str, value: Any) -> str:
        """格式化 episodic 记忆条目。"""
        if isinstance(value, str):
            return f"- [{key}] {value}"
        return f"- [{key}] {json.dumps(value, ensure_ascii=False)}"

    def _flush(self) -> None:
        """将 episodic 记忆写回文件。"""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                "\n".join(self._episodic_cache),
                encoding="utf-8",
            )
        except Exception:
            pass
