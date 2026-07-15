"""L 层: Agent Loop — Observe-Think-Act 循环.

设计文档要求:
- AgentLoop: 核心执行循环
- forward_with_handling: 错误降级
- 并行工具执行: asyncio.gather
- Layer 钩子集成
- 轨迹记录

P1 简化:
- 上下文直接从 SessionDB 加载 (P2 接入 Context Engine)
- 不做 Prompt Caching (P2)
- 不做 auto-compact (P2)
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from agent_conch.engine.error_classifier import (
    ClassifiedError,
    ErrorClassifier,
    RecoveryStrategy,
)
from agent_conch.engine.layers.base import GraphContext, LayerManager, NodeContext
from agent_conch.engine.runtime.types import AgentResult, RuntimeConfig
from agent_conch.state.session_db import SessionDB
from agent_conch.state.trajectory import TrajectoryStep, TrajectoryStore
from agent_conch.tools.base import ToolCall
from agent_conch.tools.registry import ToolRegistry


@dataclass
class LLMResponse:
    """LLM 响应封装."""

    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str = "stop"  # stop | tool_calls | length
    usage: dict[str, int] = field(default_factory=dict)
    raw: dict[str, Any] | None = None


class AgentLoop:
    """Agent 执行循环.

    Observe-Think-Act:
    - Observe: 从 SessionDB 加载消息历史 + system prompt
    - Think: 调用 LLM 获取响应
    - Act: 执行工具调用 (并行)
    循环直到 LLM 不再发起工具调用或达到限制.
    """

    def __init__(
        self,
        config: RuntimeConfig,
        session_db: SessionDB,
        tool_registry: ToolRegistry,
        trajectory_store: TrajectoryStore,
        layers: LayerManager,
        system_prompt: str = "",
        sandbox_mode: str = "non-main",
        context_engine: Any = None,
        prompt_caching: Any = None,
    ):
        self.config = config
        self.db = session_db
        self.tools = tool_registry
        self.trajectory = trajectory_store
        self.layers = layers
        self.system_prompt = system_prompt
        self.sandbox_mode = sandbox_mode
        self.error_classifier = ErrorClassifier()
        # P2: Context Engine + Prompt Caching
        self.context_engine = context_engine
        self.prompt_caching = prompt_caching

    async def run(self, session_id: str, user_input: str) -> AgentResult:
        """执行 Agent run.

        流程:
        1. 创建 session (如果不存在)
        2. 添加用户消息
        3. 循环: Think → Act → Record
        4. 返回结果
        """
        run_start = time.time()
        turn_count = 0
        tool_calls_count = 0

        # 确保 session 存在
        session = self.db.get_session(session_id)
        if session is None:
            self.db.create_session(
                session_id=session_id,
                cwd="",
                model_name=self.config.model_name,
            )

        # P2: Context Engine bootstrap
        if self.context_engine is not None:
            await self.context_engine.bootstrap(session_id)

        # 添加用户消息
        self.db.add_message(session_id, "user", user_input, turn_index=0)

        # Graph context
        graph_ctx = GraphContext(
            session_id=session_id,
            user_input=user_input,
            max_turns=self.config.max_turns,
            max_time=self.config.max_time,
            start_time=run_start,
        )

        # Layer: on_graph_start
        await self.layers.on_graph_start(graph_ctx)

        if graph_ctx.should_abort:
            return AgentResult(
                session_id=session_id,
                status="aborted",
                error=graph_ctx.abort_reason,
                total_duration_ms=int((time.time() - run_start) * 1000),
            )

        last_response = ""

        while turn_count < self.config.max_turns:
            # 检查时间限制
            elapsed = time.time() - run_start
            if elapsed >= self.config.max_time:
                return AgentResult(
                    session_id=session_id,
                    status="max_turns",
                    error=f"Max time ({self.config.max_time}s) exceeded",
                    turn_count=turn_count,
                    tool_calls_count=tool_calls_count,
                    total_duration_ms=int((time.time() - run_start) * 1000),
                )

            turn_count += 1
            turn_id = self.db.start_turn(session_id, turn_count)
            turn_start = time.time()

            # P2: Context Engine maintain (auto-compact check)
            if self.context_engine is not None:
                await self.context_engine.maintain(session_id)

            try:
                # === Think: 调用 LLM ===
                llm_response = await self.forward_with_handling(session_id)

                if llm_response is None:
                    # 所有重试都失败
                    self.db.finish_turn(
                        turn_id, "error", "LLM call failed after retries"
                    )
                    return AgentResult(
                        session_id=session_id,
                        status="error",
                        error="LLM call failed after all retries",
                        turn_count=turn_count,
                        tool_calls_count=tool_calls_count,
                        total_duration_ms=int((time.time() - run_start) * 1000),
                    )

                # 保存 assistant 消息
                self.db.add_message(
                    session_id,
                    "assistant",
                    content=llm_response.content,
                    tool_calls=llm_response.tool_calls if llm_response.tool_calls else None,
                    turn_index=turn_count,
                )

                # 记录 LLM 调用轨迹
                self.trajectory.save_step(
                    TrajectoryStep(
                        session_id=session_id,
                        turn_index=turn_count,
                        step_type="llm_call",
                        tool_output=llm_response.content[:500] if llm_response.content else "",
                        duration_ms=int((time.time() - turn_start) * 1000),
                        token_usage=llm_response.usage,
                    )
                )

                # === 判断是否结束 ===
                if not llm_response.tool_calls:
                    last_response = llm_response.content
                    self.db.finish_turn(turn_id, "completed", duration_ms=int((time.time() - turn_start) * 1000))
                    break

                # === Act: 执行工具调用 ===
                node_ctx = NodeContext(
                    session_id=session_id,
                    turn_index=turn_count,
                    response={"content": llm_response.content},
                    tool_calls=llm_response.tool_calls,
                )

                await self.layers.on_node_run_start(node_ctx)

                # 解析工具调用
                tool_calls = [ToolCall.from_llm(tc) for tc in llm_response.tool_calls]
                tool_calls_count += len(tool_calls)

                # 并行执行工具
                if self.config.parallel_tools and len(tool_calls) > 1:
                    results = await self._execute_tools_parallel(tool_calls, session_id)
                else:
                    results = []
                    for tc in tool_calls:
                        record = await self.tools.execute_tool_call(
                            tc, sandbox_mode=self.sandbox_mode
                        )
                        results.append(record)

                node_ctx.tool_results = results

                # Layer: on_node_run_end
                await self.layers.on_node_run_end(node_ctx, results)

                # 保存工具结果消息
                for record in results:
                    self.db.add_message(
                        session_id,
                        "tool",
                        content=record.result.content,
                        tool_call_id=record.tool_call_id,
                        turn_index=turn_count,
                    )
                    # 记录工具调用轨迹
                    self.trajectory.save_step(
                        TrajectoryStep(
                            session_id=session_id,
                            turn_index=turn_count,
                            step_type="tool_call",
                            tool_name=record.tool_name,
                            tool_input=record.arguments,
                            tool_output=record.result.content[:2000],
                            tool_status=record.status,
                            duration_ms=record.duration_ms,
                        )
                    )

                # 处理注入消息 (VerificationLayer 等)
                for msg in node_ctx.inject_messages:
                    self.db.add_message(session_id, msg["role"], msg["content"], turn_index=turn_count)

                self.db.finish_turn(turn_id, "completed", duration_ms=int((time.time() - turn_start) * 1000))

            except Exception as e:
                error_msg = f"Turn {turn_count} error: {e!s}"
                self.db.finish_turn(turn_id, "error", error_msg, int((time.time() - turn_start) * 1000))
                # 记录错误并继续 (除非是致命错误)
                classified = self.error_classifier.classify(e)
                if classified.strategy == RecoveryStrategy.ABORT:
                    return AgentResult(
                        session_id=session_id,
                        status="error",
                        error=error_msg,
                        turn_count=turn_count,
                        tool_calls_count=tool_calls_count,
                        total_duration_ms=int((time.time() - run_start) * 1000),
                    )
                # 否则继续下一轮

            # P2: Context Engine after_turn
            if self.context_engine is not None:
                await self.context_engine.after_turn(
                    session_id,
                    {"turn_index": turn_count, "tool_calls": tool_calls_count},
                )

        # Layer: on_graph_end
        await self.layers.on_graph_end(graph_ctx)

        # 更新 session 状态
        self.db.update_session_status(session_id, "completed")

        return AgentResult(
            session_id=session_id,
            status="completed" if turn_count < self.config.max_turns else "max_turns",
            final_response=last_response,
            turn_count=turn_count,
            tool_calls_count=tool_calls_count,
            total_duration_ms=int((time.time() - run_start) * 1000),
        )

    async def forward_with_handling(self, session_id: str) -> LLMResponse | None:
        """LLM 调用 + 错误降级.

        设计文档要求: forward_with_handling 错误降级.
        流程:
        1. 尝试调用 LLM
        2. 失败 → ErrorClassifier 分类
        3. 根据 strategy: retry / requery / compact / abort
        4. 最多重试 max_retries 次
        """
        max_retries = 3
        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                return await self._call_model(session_id)
            except Exception as e:
                last_error = e
                classified = self.error_classifier.classify(e)

                if classified.strategy == RecoveryStrategy.ABORT:
                    return None
                elif classified.strategy == RecoveryStrategy.RETRY:
                    if attempt < max_retries:
                        # 指数退避
                        await asyncio.sleep(2 ** attempt)
                        continue
                elif classified.strategy == RecoveryStrategy.REQUERY:
                    # 重新查询: 可能去掉最后一条消息后重试
                    if attempt < max_retries:
                        continue
                elif classified.strategy == RecoveryStrategy.COMPACT:
                    # P2: 触发上下文压缩
                    # P1: 直接重试
                    if attempt < max_retries:
                        continue
                # CONTINUE: 忽略错误, 返回空响应
                return LLMResponse(content=f"[Error recovered: {classified.message}]", finish_reason="error")

        return None

    async def _call_model(self, session_id: str) -> LLMResponse:
        """调用 LLM (通过 litellm).

        P2: 通过 Context Engine 组装上下文 + Prompt Caching.
        P1 fallback: 直接从 DB 加载消息.
        """
        # P2: 使用 Context Engine 组装上下文
        if self.context_engine is not None:
            from agent_conch.context.engine import TokenBudget

            budget = TokenBudget(
                total=128000,
                reserved_for_response=self.config.max_tokens,
            )
            assembled = await self.context_engine.assemble(session_id, budget)
            messages = assembled.messages
        else:
            # P1 fallback: 直接从 DB 加载
            messages: list[dict[str, Any]] = []
            if self.system_prompt:
                messages.append({"role": "system", "content": self.system_prompt})
            db_messages = self.db.get_messages_as_dicts(session_id)
            messages.extend(db_messages)

        # P2: 应用 Prompt Caching
        if self.prompt_caching is not None:
            messages = self.prompt_caching.apply(messages)

        # 获取工具 schema
        tool_schemas = await self.tools.get_available_schemas(include_core_only=True)

        # 调用 litellm
        import litellm

        kwargs: dict[str, Any] = {
            "model": self.config.model_name,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if tool_schemas:
            kwargs["tools"] = [
                {"type": "function", "function": s} for s in tool_schemas
            ]

        response = await litellm.acompletion(**kwargs)

        # 解析响应
        choice = response.choices[0]
        message = choice.message

        tool_calls: list[dict[str, Any]] = []
        if message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append(
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                )

        usage = {}
        if response.usage:
            usage = {
                "prompt": response.usage.prompt_tokens,
                "completion": response.usage.completion_tokens,
                "total": response.usage.total_tokens,
            }

        return LLMResponse(
            content=message.content or "",
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage=usage,
            raw=response.model_dump() if hasattr(response, "model_dump") else None,
        )

    async def _execute_tools_parallel(
        self, tool_calls: list[ToolCall], session_id: str
    ) -> list:
        """并行执行工具调用.

        设计文档要求: asyncio.gather(return_exceptions=True) 并行.
        只用于互不依赖的操作; 写操作和危险操作仍需串行或进入审批.
        """
        # 分离写操作和读操作
        write_calls: list[ToolCall] = []
        read_calls: list[ToolCall] = []
        for tc in tool_calls:
            tool = self.tools.get(tc.name)
            if tool and tool.is_write_tool:
                write_calls.append(tc)
            else:
                read_calls.append(tc)

        results: list = []

        # 读操作并行
        if read_calls:
            read_results = await asyncio.gather(
                *[
                    self.tools.execute_tool_call(tc, sandbox_mode=self.sandbox_mode)
                    for tc in read_calls
                ],
                return_exceptions=True,
            )
            for r in read_results:
                if isinstance(r, Exception):
                    # 创建错误记录
                    from agent_conch.tools.base import ToolExecutionRecord, ToolResult
                    results.append(
                        ToolExecutionRecord(
                            tool_name="unknown",
                            tool_call_id="",
                            arguments={},
                            result=ToolResult.error(f"Parallel execution error: {r!s}"),
                            duration_ms=0,
                            status="error",
                        )
                    )
                else:
                    results.append(r)

        # 写操作串行
        for tc in write_calls:
            record = await self.tools.execute_tool_call(tc, sandbox_mode=self.sandbox_mode)
            results.append(record)

        # 按原始顺序排序
        order_map = {tc.id: i for i, tc in enumerate(tool_calls)}
        results.sort(key=lambda r: order_map.get(r.tool_call_id, 999))
        return results
