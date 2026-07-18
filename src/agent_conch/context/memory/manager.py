"""C 层: 分层记忆 — ShortTerm + Session + LongTerm + Meta.

设计文档要求:
| 层级   | 实现                            | 存储              | 生命周期 |
| 短期   | 工作记忆 (当前对话 + carryover) | 进程内存          | 单次会话 |
| 中期   | 会话记忆 (ContextEngine)        | SQLite + 内存     | 跨轮次   |
| 长期   | 持久记忆 (MEMORY.md + 向量检索) | 文件系统 + SQLite | 跨会话   |
| 元记忆 | 跨会话搜索 (FTS5 + LLM 摘要)    | SQLite FTS5       | 跨会话   |

记忆自动提取: 每轮结束后异步触发 LLM 提取可持久化知识
写权限限制 + 去重签名
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_conch.state.session_db import SessionDB


@dataclass
class MemoryEntry:
    """记忆条目."""

    id: int | None = None
    session_id: str = ""
    content: str = ""
    memory_type: str = "fact"  # fact | preference | decision | error_lesson
    signature: str = ""  # 去重签名
    created_at: float = field(default_factory=time.time)
    pinned: bool = False


class ShortTermMemory:
    """短期记忆 — 工作记忆 (进程内存).

    存储当前对话的工具 carryover、临时变量、上下文片段.
    生命周期: 单次会话.
    """

    def __init__(self) -> None:
        self._carryover: dict[str, Any] = {}
        self._temp_facts: list[str] = []
        self._context_snippets: dict[str, str] = {}

    def set(self, key: str, value: Any) -> None:
        self._carryover[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._carryover.get(key, default)

    def add_temp_fact(self, fact: str) -> None:
        self._temp_facts.append(fact)

    def get_temp_facts(self) -> list[str]:
        return list(self._temp_facts)

    def add_snippet(self, key: str, content: str) -> None:
        self._context_snippets[key] = content

    def get_snippet(self, key: str) -> str | None:
        return self._context_snippets.get(key)

    def clear(self) -> None:
        self._carryover.clear()
        self._temp_facts.clear()
        self._context_snippets.clear()


class SessionMemory:
    """中期记忆 — 会话记忆 (SQLite + 内存).

    存储跨轮次但限于当前会话的记忆.
    生命周期: 跨轮次, 单会话.
    """

    def __init__(self, db: SessionDB):
        self.db = db
        self._cache: dict[str, list[MemoryEntry]] = {}  # session_id → entries

    def add(self, session_id: str, content: str, memory_type: str = "fact") -> None:
        """添加会话记忆."""
        entry = MemoryEntry(
            session_id=session_id,
            content=content,
            memory_type=memory_type,
            signature=self._sign(content),
        )
        if session_id not in self._cache:
            self._cache[session_id] = []
        self._cache[session_id].append(entry)

    def get(self, session_id: str) -> list[MemoryEntry]:
        """获取会话记忆."""
        return self._cache.get(session_id, [])

    def clear(self, session_id: str) -> None:
        self._cache.pop(session_id, None)

    @staticmethod
    def _sign(content: str) -> str:
        """生成内容签名 (用于去重)."""
        return hashlib.md5(content.encode("utf-8")).hexdigest()


class LongTermMemory:
    """长期记忆 — 持久记忆 (MEMORY.md + SQLite).

    存储跨会话的持久知识.
    存储格式: MEMORY.md (人类可读) + SQLite (结构化查询).
    生命周期: 跨会话.

    记忆自动提取: 每轮结束后异步触发, 带写权限限制 + 去重签名.
    """

    def __init__(self, db: SessionDB, memory_dir: str = ""):
        self.db = db
        self.memory_dir = Path(memory_dir or os.path.expanduser("~/.agent-conch/memory"))
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.memory_file = self.memory_dir / "MEMORY.md"
        self._init_db()
        self._load_memory_file()

    def _init_db(self) -> None:
        """初始化长期记忆表."""
        self.db.conn.executescript("""
            CREATE TABLE IF NOT EXISTS long_term_memory (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT,
                content     TEXT NOT NULL,
                memory_type TEXT NOT NULL DEFAULT 'fact',
                signature   TEXT NOT NULL,
                created_at  REAL NOT NULL,
                pinned      INTEGER NOT NULL DEFAULT 0,
                UNIQUE(signature)
            );
            CREATE INDEX IF NOT EXISTS idx_ltm_type ON long_term_memory(memory_type);
        """)
        self.db.conn.commit()

    def _load_memory_file(self) -> None:
        """加载 MEMORY.md 文件内容到 SQLite (如果文件存在)."""
        if not self.memory_file.exists():
            return

        content = self.memory_file.read_text(encoding="utf-8")
        # 简单解析: 每行一个记忆条目
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            self._add_to_db("", line, "fact")

    def add(
        self,
        content: str,
        memory_type: str = "fact",
        session_id: str = "",
    ) -> bool:
        """添加长期记忆.

        带去重签名: 如果签名已存在则不重复添加.
        Returns: True 表示新增, False 表示重复.
        """
        signature = SessionMemory._sign(content)
        return self._add_to_db(session_id, content, memory_type, signature)

    def _add_to_db(
        self,
        session_id: str,
        content: str,
        memory_type: str,
        signature: str = "",
    ) -> bool:
        """添加到数据库 (去重)."""
        if not signature:
            signature = SessionMemory._sign(content)

        try:
            self.db.conn.execute(
                "INSERT INTO long_term_memory (session_id, content, memory_type, signature, created_at, pinned) "
                "VALUES (?, ?, ?, ?, ?, 0)",
                (session_id, content, memory_type, signature, time.time()),
            )
            self.db.conn.commit()
            return True
        except sqlite3.IntegrityError:
            # 签名重复, 不添加
            return False

    def get_all(self, memory_type: str = "") -> list[MemoryEntry]:
        """获取所有长期记忆."""
        if memory_type:
            rows = self.db.conn.execute(
                "SELECT * FROM long_term_memory WHERE memory_type = ? ORDER BY created_at DESC",
                (memory_type,),
            ).fetchall()
        else:
            rows = self.db.conn.execute(
                "SELECT * FROM long_term_memory ORDER BY created_at DESC"
            ).fetchall()

        return [
            MemoryEntry(
                id=row["id"],
                session_id=row["session_id"],
                content=row["content"],
                memory_type=row["memory_type"],
                signature=row["signature"],
                created_at=row["created_at"],
                pinned=bool(row["pinned"]),
            )
            for row in rows
        ]

    def search(self, query: str, limit: int = 10) -> list[MemoryEntry]:
        """搜索长期记忆 (LIKE 模糊匹配, P3 替换为向量检索)."""
        rows = self.db.conn.execute(
            "SELECT * FROM long_term_memory WHERE content LIKE ? ORDER BY pinned DESC, created_at DESC LIMIT ?",
            (f"%{query}%", limit),
        ).fetchall()

        return [
            MemoryEntry(
                id=row["id"],
                session_id=row["session_id"],
                content=row["content"],
                memory_type=row["memory_type"],
                signature=row["signature"],
                created_at=row["created_at"],
                pinned=bool(row["pinned"]),
            )
            for row in rows
        ]

    def persist_to_file(self) -> None:
        """将 SQLite 中的长期记忆持久化到 MEMORY.md 文件."""
        entries = self.get_all()
        lines = ["# Agent-Conch Long-Term Memory", ""]

        for entry in entries:
            prefix = "📌 " if entry.pinned else "- "
            lines.append(f"{prefix}[{entry.memory_type}] {entry.content}")

        self.memory_file.write_text("\n".join(lines), encoding="utf-8")

    def pin(self, entry_id: int) -> None:
        """置顶记忆条目."""
        self.db.conn.execute(
            "UPDATE long_term_memory SET pinned = 1 WHERE id = ?",
            (entry_id,),
        )
        self.db.conn.commit()


class MetaMemory:
    """元记忆 — 跨会话搜索 (FTS5).

    存储会话摘要, 支持全文搜索.
    生命周期: 跨会话.
    """

    def __init__(self, db: SessionDB):
        self.db = db
        self._init_fts()

    def _init_fts(self) -> None:
        """初始化 FTS5 全文搜索表."""
        try:
            self.db.conn.executescript("""
                CREATE VIRTUAL TABLE IF NOT EXISTS session_search
                USING fts5(
                    session_id,
                    summary,
                    turn_count,
                    created_at,
                    tokenize='unicode61'
                );
            """)
            self.db.conn.commit()
        except Exception:
            # FTS5 可能不可用 (SQLite 编译选项), 降级为普通表
            self.db.conn.executescript("""
                CREATE TABLE IF NOT EXISTS session_search (
                    session_id TEXT,
                    summary TEXT,
                    turn_count INTEGER,
                    created_at REAL
                );
            """)
            self.db.conn.commit()

    def index_session(
        self,
        session_id: str,
        summary: str,
        turn_count: int = 0,
    ) -> None:
        """索引会话摘要."""
        self.db.conn.execute(
            "INSERT INTO session_search (session_id, summary, turn_count, created_at) VALUES (?, ?, ?, ?)",
            (session_id, summary, turn_count, time.time()),
        )
        self.db.conn.commit()

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """全文搜索历史会话."""
        try:
            rows = self.db.conn.execute(
                "SELECT session_id, summary, turn_count, created_at FROM session_search "
                "WHERE session_search MATCH ? ORDER BY rank LIMIT ?",
                (query, limit),
            ).fetchall()
        except Exception:
            # FTS5 不可用, 降级为 LIKE
            rows = self.db.conn.execute(
                "SELECT session_id, summary, turn_count, created_at FROM session_search "
                "WHERE summary LIKE ? ORDER BY created_at DESC LIMIT ?",
                (f"%{query}%", limit),
            ).fetchall()

        return [
            {
                "session_id": row["session_id"],
                "summary": row["summary"],
                "turn_count": row["turn_count"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]


class MemoryManager:
    """记忆管理器 — 统一管理四层记忆.

    职责:
    1. 管理短期/中期/长期/元记忆
    2. 每轮结束后自动提取可持久化知识
    3. 去重签名防止重复
    """

    def __init__(self, db: SessionDB, memory_dir: str = ""):
        self.short_term = ShortTermMemory()
        self.session_memory = SessionMemory(db)
        self.long_term = LongTermMemory(db, memory_dir)
        self.meta_memory = MetaMemory(db)

    async def extract_and_persist(
        self,
        session_id: str,
        turn_content: str,
        llm_caller: Any | None = None,
    ) -> list[str]:
        """从回合内容中提取可持久化知识.

        Args:
            session_id: 会话 ID
            turn_content: 本轮对话内容
            llm_caller: LLM 调用函数 (async, messages → str)
                        如果为 None 则使用规则提取

        Returns:
            新增的记忆条目列表
        """
        if llm_caller:
            memories = await self._llm_extract(turn_content, llm_caller)
        else:
            memories = self._rule_extract(turn_content)

        added: list[str] = []
        for mem in memories:
            if self.long_term.add(mem["content"], mem["type"], session_id):
                added.append(mem["content"])

        return added

    async def _llm_extract(self, content: str, llm_caller: Any) -> list[dict[str, str]]:
        """使用 LLM 提取记忆."""
        prompt = (
            "Extract persistent knowledge from the following conversation that "
            "would be useful in future sessions. Focus on:\n"
            "1. User preferences and conventions\n"
            "2. Important decisions and their rationale\n"
            "3. Error lessons and solutions\n"
            "4. Project-specific knowledge\n\n"
            'Return as JSON array: [{"content": "...", "type": "fact|preference|decision|error_lesson"}]\n\n'
            f"Conversation:\n{content[:3000]}"
        )
        try:
            result = await llm_caller([{"role": "user", "content": prompt}])
            extracted = json.loads(result)
            if not isinstance(extracted, list):
                return []
            return [
                {"content": item["content"], "type": item["type"]}
                for item in extracted
                if isinstance(item, dict)
                and isinstance(item.get("content"), str)
                and item.get("type") in {"fact", "preference", "decision", "error_lesson"}
            ]
        except Exception:
            return []

    def _rule_extract(self, content: str) -> list[dict[str, str]]:
        """规则提取记忆 (无 LLM 时的 fallback).

        简化规则: 提取包含特定关键词的句子.
        """
        keywords = [
            ("remember", "preference"),
            ("always", "preference"),
            ("never", "preference"),
            ("decided", "decision"),
            ("error", "error_lesson"),
            ("fix", "error_lesson"),
        ]

        memories: list[dict[str, str]] = []
        sentences = content.replace("\n", " ").split(".")

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 10:
                continue
            for kw, mem_type in keywords:
                if kw in sentence.lower():
                    memories.append({"content": sentence, "type": mem_type})
                    break

        return memories[:5]  # 最多 5 条
