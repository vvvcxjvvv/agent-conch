"""LLM Provider 基类 — 统一暴露 call() 与 stream()。

Provider 层封装而非替代官方 SDK（OpenAI/Claude/litellm），
底层可接入官方 SDK 享受原生能力，也可接入 litellm 多模型切换。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class Provider(ABC):
    """LLM Provider 抽象基类。"""

    @abstractmethod
    async def call(self, context: Any, model: str = "gpt-4o", **kwargs) -> dict:
        """同步调用模型。

        Args:
            context: 上下文（消息列表）
            model: 模型名
        Returns:
            {"content": str, "tool_call": dict|None, "usage": dict}
        """
        ...

    async def stream(self, context: Any, model: str = "gpt-4o", **kwargs):
        """流式调用模型（异步生成器）。

        Yields:
            {"content": str, "tool_call": dict|None, "usage": dict}
        """
        # 默认实现：调用 call() 后一次性 yield（非真正流式）
        result = await self.call(context, model, **kwargs)
        yield result


class MockProvider(Provider):
    """Mock Provider — 测试用，返回固定响应。

    无需真实 API key，用于骨架验证和单元测试。
    """

    def __init__(self, response: str = "[mock response]", tool_call: dict | None = None):
        self.response = response
        self.tool_call = tool_call
        self._call_count = 0

    async def call(self, context, model="gpt-4o", **kwargs) -> dict:
        self._call_count += 1
        return {
            "content": self.response,
            "tool_call": self.tool_call,
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "cost": 0.0001,
            },
        }

    async def stream(self, context, model="gpt-4o", **kwargs):
        self._call_count += 1
        yield {
            "content": self.response,
            "tool_call": self.tool_call,
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "cost": 0.0001,
            },
        }
