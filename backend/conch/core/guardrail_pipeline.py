"""护栏管道 — 六层纵深防御的编排引擎。

基于 middleware.Pipeline 实现 input/output 两路管道。
Hook 在 pre_model_call / post_model_call 节点调用本管道。

六层护栏映射（参考 technical-design-v2.md 第 3 章）:
    1. 输入筛查   → run_input()  ← pre_model_call Hook
    2. LLM 推理   → 模型内置 safety（litellm Provider 参数）
    3. 工具护栏   → check_tool() ← pre_tool Hook
    4. 检索护栏   → 记忆 Pipeline 中间件（记忆域实现）
    5. 输出筛查   → run_output() ← post_model_call Hook
    6. 监控审计   → on_tool_error/post_tool Hook → 审计日志
"""

from __future__ import annotations

import logging
from typing import Any

from conch.core.cost_guard import State
from conch.core.extension import GuardrailProvider, GuardrailResult
from conch.core.middleware import Middleware, Pipeline

logger = logging.getLogger(__name__)


class GuardrailBlocked(Exception):
    """护栏拦截异常。"""

    def __init__(self, result: GuardrailResult):
        self.result = result
        super().__init__(f"Guardrail blocked: {result.reason}")


class GuardrailMiddleware(Middleware[str]):
    """单层护栏中间件 — 调用 GuardrailProvider 做检查。

    作为 Pipeline 的一环，对文本做检查/清洗。
    blocked 则抛 GuardrailBlocked（由上层捕获）。
    """

    def __init__(self, provider: GuardrailProvider, state: State, mode: str = "input"):
        self.provider = provider
        self.state = state
        self.mode = mode  # "input" / "output"

    def process(self, text: str) -> str:
        if self.mode == "input":
            result = self.provider.check_input(text, self.state)
        else:
            result = self.provider.check_output(text, self.state)

        if result.blocked:
            logger.info("Guardrail blocked (%s): %s", self.mode, result.reason)
            raise GuardrailBlocked(result)

        if result.sanitized is not None:
            return result.sanitized
        return text


class GuardrailPipeline:
    """护栏管道 — 持 input/output 两路 Pipeline。

    用法:
        gp = GuardrailPipeline(guardrail_provider, state)
        safe_input = gp.run_input(user_text)      # pre_model_call Hook 调
        safe_output = gp.run_output(llm_text)     # post_model_call Hook 调
        tool_check = gp.check_tool(tool, args)    # pre_tool Hook 调
    """

    def __init__(self, provider: GuardrailProvider | None, state: State):
        self.provider = provider
        self.state = state
        self.input_pipeline: Pipeline[str] = Pipeline()
        self.output_pipeline: Pipeline[str] = Pipeline()
        if provider is not None:
            self.input_pipeline.add(GuardrailMiddleware(provider, state, "input"))
            self.output_pipeline.add(GuardrailMiddleware(provider, state, "output"))

    def run_input(self, text: str) -> str:
        """输入筛查管道 — pre_model_call Hook 调用。"""
        if self.provider is None:
            return text
        try:
            return self.input_pipeline.run(text)
        except GuardrailBlocked:
            raise

    def run_output(self, text: str) -> str:
        """输出筛查管道 — post_model_call Hook 调用。"""
        if self.provider is None:
            return text
        try:
            return self.output_pipeline.run(text)
        except GuardrailBlocked:
            raise

    def check_tool(self, tool: str, args: dict) -> GuardrailResult:
        """工具护栏检查 — pre_tool Hook 调用。返回结果由调用方决定是否中断。"""
        if self.provider is None:
            return GuardrailResult()
        return self.provider.check_tool(tool, args, self.state)
