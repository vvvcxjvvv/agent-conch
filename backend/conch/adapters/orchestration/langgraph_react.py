"""LangGraph ReAct 编排 — v2 默认编排引擎。

包装 langgraph.prebuilt.create_react_agent，通过 Hook 桥接层
把 LangGraph callback 事件桥接到 conch 语义 Hook 总线。

数据流:
    task → build_graph(tools, system_prompt) → astream_events(v2)
         → LangGraphHookBridge 触发 pre_model_call/pre_tool/...
         → yield SSE 事件（text_delta/tool_call/tool_result）
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from conch.core.extension import Plugin
from conch.core.hook_bridge import LangGraphHookBridge
from conch.core.registry import registry

logger = logging.getLogger(__name__)


@registry.register("orchestration", "langgraph_react", "1.0")
class LangGraphReActOrchestrator(Plugin):
    """LangGraph ReAct 编排 — 包装 create_react_agent。

    Args:
        model: litellm 模型名（如 "openai/gpt-4o"、"ollama/llama3"）
        recursion_limit: 最大递归步数（兜底，实际由 CostGuard/Profile 控制）
        api_base: 自定义 API 端点（本地模型用）
    """

    domain = "orchestration"
    name = "langgraph_react"
    version = "1.0"
    metadata = {
        "capabilities": ["react", "tool_use", "streaming", "single_agent"],
        "framework": "langgraph",
        "description": "LangGraph ReAct 编排（默认）",
    }

    def __init__(
        self,
        model: str = "openai/gpt-4o-mini",
        recursion_limit: int = 25,
        api_base: str | None = None,
        api_key: str | None = None,
        temperature: float = 0.7,
    ):
        self.model_name = model
        self.recursion_limit = recursion_limit
        self.api_base = api_base
        self.api_key = api_key
        self.temperature = temperature
        self._graph = None

    def _build_llm(self):
        """构建 LangChain Chat 模型（通过 langchain_openai 兼容 litellm 模型）。"""
        from langchain_openai import ChatOpenAI

        # litellm 的 "provider/model" 格式 → langchain_openai 的 model 名
        model_name = self.model_name
        if "/" in model_name:
            model_name = model_name.split("/", 1)[1]

        kwargs: dict[str, Any] = {
            "model": model_name,
            "streaming": True,
            "temperature": self.temperature,
        }
        if self.api_base:
            kwargs["base_url"] = self.api_base
        if self.api_key:
            kwargs["api_key"] = self.api_key
        return ChatOpenAI(**kwargs)

    def build_graph(self, tools: list, system_prompt: str | None = None):
        """构建 LangGraph ReAct 图。

        Args:
            tools: LangChain Tool 列表（由 ToolProvider 提供）
            system_prompt: 系统提示（由 InformationProvider 提供）
        """
        from langgraph.prebuilt import create_react_agent

        llm = self._build_llm()
        kwargs: dict[str, Any] = {"model": llm, "tools": tools}
        if system_prompt:
            kwargs["prompt"] = system_prompt
        self._graph = create_react_agent(**kwargs)
        return self._graph

    async def run(
        self, task: Any, agents: list[Any], state: Any
    ) -> AsyncIterator[dict[str, Any]]:
        """执行 ReAct 编排，流式 yield SSE 事件。

        Args:
            task: 用户任务文本
            agents: 未使用（单 Agent 模式）
            state: conch State（含 hook_bus、profile）

        Yields:
            {"type": "text_delta", "content": "..."}
            {"type": "tool_call", "tool": "...", "args": {...}}
            {"type": "tool_result", "tool": "...", "result": "..."}
            {"type": "done", "success": bool}
        """
        if self._graph is None:
            yield {"type": "done", "success": False, "error": "Graph not built. Call build_graph() first."}
            return

        # 构建 Hook 桥接
        bridge = None
        if state and getattr(state, "hook_bus", None):
            bridge = LangGraphHookBridge(state.hook_bus, state)

        config: dict[str, Any] = {"recursion_limit": self.recursion_limit}
        if bridge:
            config["callbacks"] = [bridge]

        task_text = task if isinstance(task, str) else str(task)
        inputs = {"messages": [{"role": "user", "content": task_text}]}

        current_tool: str | None = None
        try:
            async for event in self._graph.astream_events(inputs, config=config, version="v2"):
                evt_type = event.get("event", "")
                name = event.get("name", "")
                data = event.get("data", {})

                # LLM 流式 token
                if evt_type == "on_chat_model_stream":
                    chunk = data.get("chunk")
                    if chunk and chunk.content:
                        yield {"type": "text_delta", "content": chunk.content}

                # 工具开始
                elif evt_type == "on_tool_start":
                    current_tool = name
                    input_str = data.get("input", "")
                    args = input_str if isinstance(input_str, dict) else {}
                    yield {"type": "tool_call", "tool": name, "args": args}

                # 工具结束
                elif evt_type == "on_tool_end":
                    output = data.get("output", "")
                    out_str = str(output.content) if hasattr(output, "content") else str(output)
                    yield {"type": "tool_result", "tool": current_tool or name, "result": out_str}
                    current_tool = None

            yield {"type": "done", "success": True}

        except Exception as e:
            logger.exception("LangGraph ReAct orchestration failed")
            yield {"type": "done", "success": False, "error": str(e)}

    async def task_split(self, task: Any, state: Any) -> list[Any]:
        return [task]

    async def state_sync(self, agents: list[Any], state: Any) -> None:
        return None

    async def conflict_resolve(self, results: list[Any], state: Any) -> Any:
        return results[0] if results else None
