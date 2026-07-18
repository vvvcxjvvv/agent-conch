"""T 层核心工具: ask_user — 用户提问."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field

from agent_conch.tools.base import BaseTool, ToolResult


class AskUserInput(BaseModel):
    question: str = Field(..., description="Question to ask the user")
    context: str | None = Field(None, description="Additional context for the question")
    options: list[str] | None = Field(
        None, description="Optional list of choices for the user to pick from"
    )


# 回调类型: 接收 question + options, 返回用户回答
AskUserCallback = Callable[[str, list[str] | None], Awaitable[str]]


class AskUserTool(BaseTool):
    """用户提问工具.

    Agent 通过此工具向用户提问并等待回答.
    在 CLI 模式下通过 input() 获取用户输入;
    在 Web 模式下通过 SSE/WebSocket 推送问题并等待回答.
    """

    name = "ask_user"
    description = (
        "Ask the user a question and wait for their response. "
        "Use when you need clarification, confirmation, or user input. "
        "Optionally provide a list of choices."
    )
    input_model = AskUserInput
    is_write_tool = False
    is_core = True
    tags = ["user", "interaction", "input"]

    def __init__(self, callback: AskUserCallback | None = None):
        self._callback = callback or self._default_callback

    def set_callback(self, callback: AskUserCallback) -> None:
        self._callback = callback

    async def execute(self, **kwargs: Any) -> ToolResult:
        validated = AskUserInput(**kwargs)
        try:
            answer = await self._callback(validated.question, validated.options)
            return ToolResult(
                content=f"User response: {answer}",
                metadata={
                    "question": validated.question,
                    "answer": answer,
                    "had_options": validated.options is not None,
                },
            )
        except Exception as e:
            return ToolResult.error(f"Failed to get user input: {e!s}")

    @staticmethod
    async def _default_callback(question: str, options: list[str] | None) -> str:
        """默认回调: 通过标准输入获取用户回答."""
        print(f"\n[Agent asks]: {question}")
        if options:
            for i, opt in enumerate(options, 1):
                print(f"  {i}. {opt}")
            print("  (enter number or type your answer)")

        # 在事件循环中运行同步 input
        answer = await asyncio.to_thread(input, "> ")
        if options:
            try:
                idx = int(answer) - 1
                if 0 <= idx < len(options):
                    return options[idx]
            except (ValueError, IndexError):
                pass
        return answer
