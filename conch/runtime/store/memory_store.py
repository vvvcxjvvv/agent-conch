"""内存 KV 存储 — 最小存储实现，用于记忆和状态。

MVP 不依赖外部数据库，纯内存字典。
阶段三接入向量库（Chroma）用于语义记忆检索。
"""

from __future__ import annotations

from typing import Any


class MemoryStore:
    """最小 KV 存储 — 纯内存字典实现。"""

    def __init__(self):
        self._data: dict[str, Any] = {}

    def put(self, key: str, value: Any) -> None:
        self._data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def keys(self) -> list[str]:
        return list(self._data.keys())

    def search(self, query: str, limit: int = 5) -> list[tuple[str, Any]]:
        """简单文本搜索（阶段三替换为向量检索）。"""
        results = []
        query_lower = query.lower()
        for key, value in self._data.items():
            text = str(value).lower()
            if query_lower in text or query_lower in key.lower():
                results.append((key, value))
                if len(results) >= limit:
                    break
        return results

    def clear(self) -> None:
        self._data.clear()
