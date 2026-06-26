"""ScriptedProvider — 按预设脚本返回响应的 Provider。

用于端到端测试：模拟一个完整的 Agent 行为序列
（读文件 → 分析 → 修复 → 写文件），
无需真实 LLM API 即可验证 Loop + Tool + Governance 全链路。
"""

from __future__ import annotations

from typing import Any

from conch.runtime.model.base import Provider


class ScriptedProvider(Provider):
    """按预设脚本返回响应。

    Example:
        provider = ScriptedProvider([
            {"tool_call": {"name": "read_file", "args": {"path": "hello.py"}}},
            {"content": "Found syntax error: missing closing paren"},
            {"tool_call": {"name": "write_file", "args": {"path": "hello.py", "content": "print('hello')\\n"}}},
            {"content": "Fixed! The file has been updated."},
        ])
    """

    def __init__(self, script: list[dict]):
        self.script = script
        self._index = 0
        self._call_count = 0

    async def call(self, context: Any, model: str = "gpt-4o", **kwargs) -> dict:
        self._call_count += 1
        if self._index >= len(self.script):
            # 脚本播完，返回空内容（Loop 会因 max_steps 或无工具调用而终止）
            return {"content": "[done]", "tool_call": None, "usage": {"total_tokens": 5, "cost": 0.0001}}

        response = self.script[self._index]
        self._index += 1

        return {
            "content": response.get("content", ""),
            "tool_call": response.get("tool_call"),
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "cost": 0.0001,
            },
        }

    async def stream(self, context: Any, model: str = "gpt-4o", **kwargs):
        result = await self.call(context, model, **kwargs)
        yield result
