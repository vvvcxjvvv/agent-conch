"""C 层: 可插拔 Context Engine.

设计文档要求:
- ContextEngine ABC: 统一管理上下文组装、压缩、记忆检索和回合后维护
- 不同任务可替换策略 (代码/研究/运维) 而不改 Agent 执行循环
- LegacyEngine: 内置 fallback 引擎, 始终可用

铁律: 不允许变更过去上下文、不允许切换 toolset、不允许重建 system prompt
唯一例外: context compression
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from agent_conch.state.session_db import SessionDB


@dataclass
class TokenBudget:
    """Token 预算."""

    total: int = 128000  # 模型上下文窗口
    reserved_for_response: int = 4096  # 预留给模型输出
    reserved_for_system: int = 2000  # 预留给 system prompt

    @property
    def available_for_context(self) -> int:
        """可用于对话上下文的 token 数."""
        return self.total - self.reserved_for_response - self.reserved_for_system


@dataclass
class AssembleResult:
    """上下文组装结果."""

    messages: list[dict[str, Any]]
    token_count: int = 0
    compacted: bool = False
    attachments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContextState:
    """上下文引擎运行时状态."""

    session_id: str
    turn_count: int = 0
    last_compact_turn: int = 0
    total_tokens_used: int = 0
    compact_count: int = 0
    recent_files: list[str] = field(default_factory=list)
    discovered_tools: list[str] = field(default_factory=list)
    async_tasks: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class ContextEngine(ABC):
    """Context Engine 抽象基类.

    职责:
    1. bootstrap: 初始化会话上下文
    2. assemble: 组装发送给 LLM 的消息列表 (含 system + history)
    3. maintain: 回合后维护 (auto-compact 检查等)
    4. compact: 执行上下文压缩
    5. after_turn: 回合后处理 (记忆提取等)
    """

    @abstractmethod
    async def bootstrap(self, session_id: str) -> ContextState:
        """初始化会话上下文状态."""
        ...

    @abstractmethod
    async def assemble(self, session_id: str, budget: TokenBudget) -> AssembleResult:
        """组装发送给 LLM 的消息列表.

        - 包含 system prompt + 历史消息 + 压缩后的上下文
        - 确保总 token 不超过 budget
        """
        ...

    @abstractmethod
    async def maintain(self, session_id: str) -> None:
        """回合后维护: auto-compact 检查、状态更新."""
        ...

    @abstractmethod
    async def compact(self, session_id: str) -> AssembleResult:
        """执行上下文压缩."""
        ...

    @abstractmethod
    async def after_turn(self, session_id: str, turn_result: dict[str, Any]) -> None:
        """回合后处理: 记忆提取、状态更新."""
        ...

    @abstractmethod
    def get_state(self, session_id: str) -> ContextState | None:
        """获取会话上下文状态."""
        ...


class LegacyEngine(ContextEngine):
    """内置 fallback Context Engine.

    P1 行为的封装: 直接从 SessionDB 加载消息, 不做压缩.
    作为所有自定义引擎的 fallback, 始终可用.
    """

    def __init__(
        self,
        db: SessionDB,
        system_prompt: str = "",
        token_counter: Any | None = None,
        compressor: Any | None = None,
        memory_manager: Any | None = None,
        llm_caller: Any | None = None,
        auto_compact: bool = True,
        token_budget: TokenBudget | None = None,
    ):
        self.db = db
        self.system_prompt = system_prompt
        self.token_counter = token_counter or SimpleTokenCounter()
        self.compressor = compressor
        self.memory_manager = memory_manager
        self.llm_caller = llm_caller
        self.auto_compact = auto_compact
        self.token_budget = token_budget or TokenBudget()
        self._states: dict[str, ContextState] = {}

    async def bootstrap(self, session_id: str) -> ContextState:
        state = ContextState(session_id=session_id)
        self._states[session_id] = state
        return state

    async def assemble(self, session_id: str, budget: TokenBudget) -> AssembleResult:
        """组装消息: system prompt + DB 历史消息."""
        db_messages = self.db.get_messages_as_dicts(session_id)
        state = self._states.get(session_id)
        compacted_messages = None
        if state is not None:
            compacted_messages = state.metadata.get("compacted_messages")
            source_count = state.metadata.get("compacted_source_count")

        if compacted_messages is not None and source_count == len(db_messages):
            messages = list(compacted_messages)
            compacted = True
        else:
            messages = self._assemble_full_messages(db_messages)
            compacted = False

        # token 计数
        token_count = self.token_counter.estimate(messages)

        # 更新状态
        if state:
            state.total_tokens_used = token_count

        return AssembleResult(
            messages=messages,
            token_count=token_count,
            compacted=compacted,
        )

    async def maintain(self, session_id: str) -> None:
        """执行自动压缩检查，并缓存当前轮可直接使用的压缩上下文。"""
        state = self._states.get(session_id)
        if state is None:
            state = await self.bootstrap(session_id)
        state.turn_count += 1

        if not self.auto_compact or self.compressor is None:
            return

        messages = self._assemble_full_messages(self.db.get_messages_as_dicts(session_id))
        if self.token_counter.estimate(messages) <= self.token_budget.available_for_context:
            state.metadata.pop("compacted_messages", None)
            state.metadata.pop("compacted_source_count", None)
            return

        await self._compact_messages(session_id, messages)

    async def compact(self, session_id: str) -> AssembleResult:
        """立即压缩当前会话；供上下文溢出恢复策略调用。"""
        messages = self._assemble_full_messages(self.db.get_messages_as_dicts(session_id))
        if self.compressor is None:
            return await self.assemble(session_id, self.token_budget)

        result = await self._compact_messages(session_id, messages)
        return AssembleResult(
            messages=result.messages,
            token_count=result.compacted_token_count,
            compacted=bool(result.steps_applied),
            attachments=result.attachments,
        )

    async def after_turn(self, session_id: str, turn_result: dict[str, Any]) -> None:
        """从本轮 Agent 输出提取长期记忆，LLM 失败时由规则提取降级。"""
        if self.memory_manager is None:
            return

        content = str(turn_result.get("content", "")).strip()
        if not content:
            return

        added = await self.memory_manager.extract_and_persist(session_id, content, self.llm_caller)
        if added:
            self.memory_manager.long_term.persist_to_file()

    def get_state(self, session_id: str) -> ContextState | None:
        return self._states.get(session_id)

    def _assemble_full_messages(self, db_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.extend(db_messages)
        return messages

    async def _compact_messages(self, session_id: str, messages: list[dict[str, Any]]) -> Any:
        compressor = self.compressor
        if compressor is None:
            raise RuntimeError("Context compressor is not configured")
        result = await compressor.compact(messages, self.token_budget.available_for_context)
        state = self._states.get(session_id)
        if state is None:
            state = await self.bootstrap(session_id)
        if result.steps_applied:
            state.compact_count += 1
            state.last_compact_turn = state.turn_count
            state.recent_files = result.attachments.get("recent_files", [])
            state.discovered_tools = result.attachments.get("discovered_tools", [])
            state.async_tasks = result.attachments.get("async_tasks", [])
            state.metadata["compacted_messages"] = result.messages
            state.metadata["compacted_source_count"] = len(
                self.db.get_messages_as_dicts(session_id)
            )
        return result


class SimpleTokenCounter:
    """简单 token 计数器.

    P1/P2 使用近似估算 (4 chars ≈ 1 token).
    P3 可替换为 tiktoken 精确计数.
    """

    CHARS_PER_TOKEN = 4

    def estimate(self, messages: list[dict[str, Any]]) -> int:
        """估算消息列表的 token 数."""
        total_chars = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        total_chars += len(str(part.get("text", "")))
            # tool_calls 的 token
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                import json

                total_chars += len(json.dumps(tool_calls))
        return total_chars // self.CHARS_PER_TOKEN

    def estimate_single(self, text: str) -> int:
        """估算单段文本的 token 数."""
        return len(text) // self.CHARS_PER_TOKEN
