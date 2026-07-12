"""L 层: BuiltinConchRuntime — 内置 Agent Runtime."""
from __future__ import annotations

from agent_conch.engine.agent_loop import AgentLoop
from agent_conch.engine.runtime.types import AgentResult, AgentRuntime, RuntimeConfig


class BuiltinConchRuntime(AgentRuntime):
    """内置 Conch Runtime.

    使用 AgentLoop 的标准 Observe-Think-Act 循环.
    所有 P1 核心工具都可用.
    """

    def __init__(self, config: RuntimeConfig, agent_loop: AgentLoop):
        self.config = config
        self.agent_loop = agent_loop

    async def run(self, session_id: str, user_input: str) -> AgentResult:
        return await self.agent_loop.run(session_id, user_input)

    def supported_tools(self) -> list[str]:
        return [
            "bash",
            "read_file",
            "write_file",
            "edit_file",
            "glob",
            "grep",
            "web_search",
            "web_fetch",
            "skill",
            "ask_user",
            "task_manage",
            "tool_search",
        ]

    def supported_layers(self) -> list[str]:
        return ["execution_limits"]
