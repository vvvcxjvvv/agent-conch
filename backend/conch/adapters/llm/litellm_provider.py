"""LLM Provider — 基于 litellm 统一接入多模型。

支持本地/国内模型（OpenAI 兼容 API / Ollama / 通义/智谱等）。
litellm 用 "model:provider" 格式路由，如 "openai/gpt-4o"、"ollama/llama3"。
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from conch.core.extension import Plugin
from conch.core.registry import registry

logger = logging.getLogger(__name__)


@registry.register("llm", "litellm", "1.0")
class LiteLLMProvider(Plugin):
    """litellm 多模型统一接入。

    用 litellm.acompletion 统一调用 OpenAI/Claude/Ollama/通义/智谱等。
    支持流式输出与 tool_calls 解析。

    Args:
        default_model: 默认模型（如 "openai/gpt-4o"、"ollama/llama3"）
        api_base: 自定义 API 端点（本地模型用）
        api_key: API key（环境变量 LITELLM_API_KEY 也可）
        temperature: 采样温度
    """

    domain = "llm"
    name = "litellm"
    version = "1.0"
    metadata = {
        "capabilities": ["streaming", "tool_calls", "multi_model"],
        "description": "litellm 统一多模型接入",
    }

    def __init__(
        self,
        default_model: str = "openai/gpt-4o-mini",
        api_base: str | None = None,
        api_key: str | None = None,
        temperature: float = 0.7,
    ):
        self.default_model = default_model
        self.api_base = api_base
        self.api_key = api_key
        self.temperature = temperature

    async def stream(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """流式调用 LLM，yield 分块。

        Yields:
            {"type": "text", "content": "..."}        — 文本片段
            {"type": "tool_call", "tool": "...", "args": {...}} — 工具调用
            {"type": "usage", "total_tokens": N, "cost": F}     — 用量（末尾）
        """
        import litellm

        kwargs: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": messages,
            "stream": True,
            "temperature": self.temperature,
        }
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if tools:
            kwargs["tools"] = tools

        collected_tool_calls: dict[int, dict[str, Any]] = {}

        response = await litellm.acompletion(**kwargs)
        async for chunk in response:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            # 文本内容
            if delta.content:
                yield {"type": "text", "content": delta.content}

            # 工具调用（累积，OpenAI 格式）
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in collected_tool_calls:
                        collected_tool_calls[idx] = {
                            "name": "",
                            "args_str": "",
                        }
                    if tc.function:
                        if tc.function.name:
                            collected_tool_calls[idx]["name"] += tc.function.name
                        if tc.function.arguments:
                            collected_tool_calls[idx]["args_str"] += tc.function.arguments

            # 用量（末尾 chunk 可能带）
            if hasattr(chunk, "usage") and chunk.usage:
                yield {
                    "type": "usage",
                    "total_tokens": chunk.usage.total_tokens or 0,
                    "cost": 0.0,
                }

        # 流结束后 yield 完整的 tool_calls
        import json
        for idx in sorted(collected_tool_calls):
            tc = collected_tool_calls[idx]
            args = {}
            if tc["args_str"]:
                try:
                    args = json.loads(tc["args_str"])
                except json.JSONDecodeError:
                    args = {"_raw": tc["args_str"]}
            yield {"type": "tool_call", "tool": tc["name"], "args": args}

    async def call(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        tools: list[dict] | None = None,
    ) -> dict[str, Any]:
        """非流式调用，返回完整结果。"""
        import litellm

        kwargs: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if tools:
            kwargs["tools"] = tools

        response = await litellm.acompletion(**kwargs)
        msg = response.choices[0].message
        result: dict[str, Any] = {
            "content": msg.content or "",
            "usage": {
                "total_tokens": response.usage.total_tokens if response.usage else 0,
                "cost": 0.0,
            },
        }
        if msg.tool_calls:
            import json
            result["tool_calls"] = [
                {
                    "name": tc.function.name,
                    "args": json.loads(tc.function.arguments) if tc.function.arguments else {},
                }
                for tc in msg.tool_calls
            ]
        return result
