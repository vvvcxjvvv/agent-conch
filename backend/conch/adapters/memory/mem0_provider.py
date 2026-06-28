"""域4：Mem0 记忆适配器。

优先接真实 Mem0；若本地未安装或初始化失败，则回退到 JSONL 持久化。

当前阶段能力：
- episodic 跨轮/跨会话持久化
- semantic 同路径复用简单文本检索兜底
- 兼容当前 MemoryProvider 的 store/recall 契约
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from conch.core.extension import Plugin
from conch.core.registry import registry

logger = logging.getLogger(__name__)


@registry.register("memory", "mem0", "1.0")
class Mem0MemoryProvider(Plugin):
    """Mem0 记忆层。

    Args:
        path: fallback 持久化路径；未安装 Mem0 时写入 JSONL
        user_id: Mem0 user_id；auto 时退化为全局 demo 用户
        agent_id: Mem0 agent_id
    """

    domain = "memory"
    name = "mem0"
    version = "1.0"
    metadata = {
        "cost": "medium",
        "context_save": "high",
        "capabilities": ["episodic", "semantic", "cross_session"],
        "description": "Mem0 记忆层（未安装时回退 JSONL）",
    }

    def __init__(
        self,
        path: str = "log/mem0-memory.jsonl",
        user_id: str = "auto",
        agent_id: str = "conch",
    ):
        self.path = Path(path)
        self.user_id = user_id
        self.agent_id = agent_id
        self._mem0 = None
        self._records: list[dict[str, Any]] = []

    def on_load(self) -> None:
        self._init_mem0()
        self._load_fallback_records()

    def store(self, key: str, value: Any, mem_type: str = "episodic") -> None:
        text = self._value_as_text(value)
        record = {
            "key": key,
            "mem_type": mem_type,
            "value": value,
            "text": text,
            "score": 1.0,
        }

        if self._mem0 is not None:
            try:
                payload = {
                    "role": self._detect_role(key, value),
                    "content": text,
                    "metadata": {
                        "key": key,
                        "mem_type": mem_type,
                        "raw_value": value,
                    },
                }
                self._mem0.add(
                    payload,
                    user_id=self._resolved_user_id(),
                    agent_id=self.agent_id,
                )
            except Exception:
                logger.exception("Mem0 add failed, fallback to JSONL store")

        self._records.append(record)
        self._flush_fallback_records()

    def recall(self, query: str, mem_type: str = "episodic", limit: int = 5) -> list[Any]:
        if self._mem0 is not None:
            try:
                result = self._mem0.search(
                    query,
                    user_id=self._resolved_user_id(),
                    limit=limit,
                )
                normalized = self._normalize_mem0_results(result)
                if normalized:
                    return normalized
            except Exception:
                logger.exception("Mem0 search failed, fallback to JSONL recall")

        return self._fallback_recall(query, mem_type=mem_type, limit=limit)

    def _init_mem0(self) -> None:
        try:
            from mem0 import Memory

            self._mem0 = Memory()
        except Exception:
            self._mem0 = None

    def _load_fallback_records(self) -> None:
        if not self.path.exists():
            return
        try:
            self._records = [
                json.loads(line)
                for line in self.path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except Exception:
            logger.exception("Failed to load fallback memory records")
            self._records = []

    def _flush_fallback_records(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                "\n".join(json.dumps(record, ensure_ascii=False) for record in self._records),
                encoding="utf-8",
            )
        except Exception:
            logger.exception("Failed to flush fallback memory records")

    def _fallback_recall(self, query: str, mem_type: str, limit: int) -> list[dict[str, Any]]:
        scored_results: list[tuple[float, int, dict[str, Any]]] = []
        accepted_types = self._accepted_types(mem_type)
        for record in reversed(self._records):
            if record.get("mem_type") not in accepted_types:
                continue
            score = self._score_record(query, record)
            if score <= 0.0:
                continue
            enriched = dict(record)
            enriched["score"] = score
            scored_results.append((score, len(scored_results), enriched))

        scored_results.sort(key=lambda item: (-item[0], item[1]))
        return [record for _, _, record in scored_results[:limit]]

    def _normalize_mem0_results(self, result: Any) -> list[dict[str, Any]]:
        if not isinstance(result, list):
            return []

        normalized: list[dict[str, Any]] = []
        for item in result:
            if isinstance(item, dict):
                metadata = item.get("metadata") or {}
                normalized.append(
                    {
                        "key": metadata.get("key", item.get("id", "")),
                        "mem_type": metadata.get("mem_type", "episodic"),
                        "value": metadata.get("raw_value") or item.get("memory") or item,
                        "text": item.get("memory") or item.get("text") or "",
                        "score": float(item.get("score", 1.0) or 1.0),
                    }
                )
            else:
                normalized.append(
                    {
                        "key": "",
                        "mem_type": "episodic",
                        "value": item,
                        "text": self._value_as_text(item),
                        "score": 1.0,
                    }
                )
        return normalized

    def _resolved_user_id(self) -> str:
        return "conch-demo-user" if self.user_id == "auto" else self.user_id

    def _detect_role(self, key: str, value: Any) -> str:
        if isinstance(value, dict) and value.get("role") in {"user", "assistant", "system"}:
            return str(value["role"])
        if key.startswith("assistant:"):
            return "assistant"
        return "user"

    def _value_as_text(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            if isinstance(value.get("content"), str):
                return value["content"]
            try:
                return json.dumps(value, ensure_ascii=False, sort_keys=True)
            except TypeError:
                return str(value)
        try:
            return json.dumps(value, ensure_ascii=False)
        except TypeError:
            return str(value)

    def _accepted_types(self, mem_type: str) -> set[str]:
        if mem_type == "episodic":
            return {"episodic", "semantic", "long_term", "procedural"}
        if mem_type == "semantic":
            return {"semantic", "episodic", "long_term"}
        if mem_type == "long_term":
            return {"long_term", "semantic"}
        if mem_type == "procedural":
            return {"procedural", "long_term"}
        return {mem_type}

    def _score_record(self, query: str, record: dict[str, Any]) -> float:
        text = f"{record.get('key', '')}\n{record.get('text', '')}"
        q_tokens = self._tokenize(query)
        t_tokens = self._tokenize(text)
        if not q_tokens or not t_tokens:
            return 0.0
        overlap = q_tokens & t_tokens
        if not overlap:
            return 0.0
        return len(overlap) / len(q_tokens)

    def _tokenize(self, text: str) -> set[str]:
        return {token for token in re.findall(r"[\w\u4e00-\u9fff]+", text.lower()) if token}
