"""Hook 桥接层 — 框架原生事件 → conch 语义 Hook 总线。

这是 v2 的核心创新：让框架无关的语义 Hook（pre_model_call / pre_tool / ...）
能在任何编排引擎上工作。换编排引擎只需新写一个桥接类，已有 Hook 零改动复用。

当前实现：
- LangGraphHookBridge：桥接 LangGraph/LangChain 的 Callback Handler 接口

预留（阶段四）：
- AutoGenHookBridge：桥接 AutoGen GroupChat 事件
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from langchain_core.callbacks.base import AsyncCallbackHandler

from conch.core.hooks import HookBus

if TYPE_CHECKING:
    from conch.core.cost_guard import State

logger = logging.getLogger(__name__)


class LangGraphHookBridge(AsyncCallbackHandler):
    """将 LangGraph/LangChain 回调事件桥接到 conch Hook 语义节点。

    用法（在编排 Plugin 中）:
        bridge = LangGraphHookBridge(state.hook_bus, state)
        config = {"callbacks": [bridge], "recursion_limit": 25}
        async for event in graph.astream_events(input, config=config, version="v2"):
            ...

    事件映射:
        on_llm_start    → pre_model_call
        on_llm_end      → post_model_call
        on_tool_start   → pre_tool
        on_tool_end     → post_tool
        on_tool_error   → on_tool_error
    """

    def __init__(self, hook_bus: HookBus, state: "State"):
        self.raise_error = True
        self.run_inline = True
        self.hook_bus = hook_bus
        self.state = state

    # ── LangChain BaseCallbackHandler 接口实现 ──────────────────

    async def on_chat_model_start(
        self, serialized: dict[str, Any], messages: list[list[Any]], **kwargs: Any
    ) -> None:
        """ChatModel 开始推理 → 触发 pre_model_call。"""
        self.hook_bus.fire("pre_model_call", self.state)

    async def on_llm_start(
        self, serialized: dict[str, Any], prompts: list[str], **kwargs: Any
    ) -> None:
        """LLM 开始推理 → 触发 pre_model_call。"""
        self.hook_bus.fire("pre_model_call", self.state)

    async def on_llm_end(self, response, **kwargs: Any) -> None:
        """LLM 推理结束 → 触发 post_model_call。"""
        action = self._parse_llm_result(response)
        self.hook_bus.fire("post_model_call", self.state, action=action)

    async def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        """流式 token — 不触发 Hook，由编排 Plugin 直接 yield 给 SSE。"""
        pass

    async def on_tool_start(
        self, serialized: dict[str, Any], input_str: str, **kwargs: Any
    ) -> None:
        """工具开始执行 → 触发 pre_tool（中断白名单，可拦截高危工具）。"""
        tool_name = serialized.get("name", "unknown")
        self.hook_bus.fire(
            "pre_tool",
            self.state,
            tool=tool_name,
            args=self._normalize_tool_args(input_str),
        )

    async def on_tool_end(self, output: str, **kwargs: Any) -> None:
        """工具执行结束 → 触发 post_tool。"""
        self.hook_bus.fire("post_tool", self.state, result=output)

    async def on_tool_error(self, error: BaseException, **kwargs: Any) -> None:
        """工具执行出错 → 触发 on_tool_error。"""
        self.hook_bus.fire("on_tool_error", self.state, error=error)

    async def on_chain_start(self, serialized, inputs, **kwargs):
        """链开始 — 映射到 pre_step（一个 LangGraph step 约等于一次 chain 调用）。"""
        self.hook_bus.fire("pre_step", self.state)

    async def on_chain_end(self, outputs, **kwargs):
        """链结束 → post_step。"""
        self.hook_bus.fire("post_step", self.state)

    # ── 内部工具 ────────────────────────────────────────────────

    def _parse_llm_result(self, response: Any) -> dict[str, Any]:
        """从 LLM 响应解析出 action 结构（供 post_model_call Hook 使用）。"""
        action: dict[str, Any] = {"type": "text", "content": "", "usage": {}}
        try:
            # LangChain AIMessageChuck / AIMessage
            if hasattr(response, "llm_output") and response.llm_output:
                usage = response.llm_output.get("token_usage", {})
                action["usage"] = {
                    "total_tokens": usage.get("total_tokens", 0),
                    "cost": 0.0,
                }
            # 取最后一条消息的内容
            if hasattr(response, "generations") and response.generations:
                last_gen = response.generations[-1][-1]
                msg = last_gen.message if hasattr(last_gen, "message") else last_gen
                content = getattr(msg, "content", "")
                action["content"] = content
                tool_calls = getattr(msg, "tool_calls", None)
                if tool_calls:
                    tc = tool_calls[-1]
                    action = {
                        "type": "tool_call",
                        "tool": tc.get("name", ""),
                        "args": tc.get("args", {}),
                        "content": content,
                        "usage": action["usage"],
                    }
        except Exception:
            logger.debug("Failed to parse LLM result for hook", exc_info=True)
        return action

    def _normalize_tool_args(self, raw_args: Any) -> dict[str, Any]:
        if isinstance(raw_args, dict):
            return raw_args
        if isinstance(raw_args, str):
            stripped = raw_args.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    logger.debug("Failed to parse tool args JSON", exc_info=True)
            return {"input": raw_args}
        if raw_args is None:
            return {}
        return {"input": raw_args}


# 预留：AutoGen 桥接（阶段四实现）
class AutoGenHookBridge:
    """桥接 AutoGen GroupChat 事件到 conch Hook 总线。

    阶段四多 Agent 时实现。接口预留，当前 raise NotImplementedError。
    """

    def __init__(self, hook_bus: HookBus, state: "State"):
        raise NotImplementedError("AutoGenHookBridge will be implemented in phase 4")
