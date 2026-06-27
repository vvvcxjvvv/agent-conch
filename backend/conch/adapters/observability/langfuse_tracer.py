"""Langfuse 可观测性 — trace/cost/指标记录。

包装 langfuse 的 LangfuseCallbackHandler，作为 LangChain callback 挂到 LangGraph config。
同时实现 ObservabilityProvider 接口，供 conch State 查询累计指标。

MVP 可选：未配置 Langfuse 时用 console_tracer 兜底。
"""

from __future__ import annotations

import logging
from typing import Any

from conch.core.extension import Plugin
from conch.core.registry import registry

logger = logging.getLogger(__name__)


@registry.register("observability", "langfuse_tracer", "1.0")
class LangfuseTracer(Plugin):
    """Langfuse 可观测性。

    Args:
        project: Langfuse 项目名
        host: Langfuse 服务地址（自托管或云）
        public_key / secret_key: Langfuse API 密钥
    """

    domain = "observability"
    name = "langfuse_tracer"
    version = "1.0"
    metadata = {
        "capabilities": ["trace", "cost", "metrics"],
        "framework": "langfuse",
        "description": "Langfuse 可观测性（trace/cost/指标）",
    }

    def __init__(
        self,
        project: str = "conch",
        host: str | None = None,
        public_key: str | None = None,
        secret_key: str | None = None,
    ):
        self.project = project
        self.host = host
        self.public_key = public_key
        self.secret_key = secret_key
        self._callback_handler = None
        self._total_tokens = 0
        self._total_cost = 0.0
        self._steps = 0

    def on_load(self) -> None:
        try:
            from langfuse.callback import CallbackHandler

            kwargs: dict[str, Any] = {}
            if self.public_key:
                kwargs["public_key"] = self.public_key
            if self.secret_key:
                kwargs["secret_key"] = self.secret_key
            if self.host:
                kwargs["host"] = self.host
            self._callback_handler = CallbackHandler(**kwargs)
            logger.info("LangfuseTracer initialized (project=%s)", self.project)
        except ImportError:
            logger.warning("langfuse not installed, tracer will be no-op")
        except Exception:
            logger.exception("Failed to init Langfuse, tracer will be no-op")

    @property
    def callback_handler(self):
        """返回 Langfuse callback handler，供 LangGraph config 使用。"""
        return self._callback_handler

    def trace(self, state: Any) -> None:
        """记录一个 step 的轨迹。"""
        self._steps += 1
        if state and hasattr(state, "total_tokens"):
            self._total_tokens = state.total_tokens
            self._total_cost = state.total_cost

    def metrics(self) -> dict[str, Any]:
        """返回当前累计指标。"""
        return {
            "steps": self._steps,
            "total_tokens": self._total_tokens,
            "total_cost": self._total_cost,
            "project": self.project,
        }
