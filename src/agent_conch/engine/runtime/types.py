"""L 层: Agent Runtime 可插拔抽象.

运行时策略:
- AgentRuntime: 允许不同类型的 Agent 执行器接入统一控制面
- RuntimeRegistry: 注册和选择 runtime
- 通用 Harness 不绑定单一 Agent 循环
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentResult:
    """Agent 执行结果."""

    session_id: str
    status: str = "completed"  # completed | error | aborted | max_turns
    final_response: str = ""
    turn_count: int = 0
    total_duration_ms: int = 0
    tool_calls_count: int = 0
    error: str | None = None
    trajectory_summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class RuntimeConfig:
    """Runtime 配置."""

    name: str = "builtin"
    max_turns: int = 50
    max_time: int = 600
    parallel_tools: bool = True
    model_name: str = "gpt-4o"
    temperature: float = 0.0
    max_tokens: int = 4096


class AgentRuntime(ABC):
    """Agent Runtime 抽象基类.

    不同 runtime (编码/研究/工作流/远程) 共享工具、状态、验证和治理能力,
    但可以有各自的执行循环.
    """

    @abstractmethod
    async def run(self, session_id: str, user_input: str) -> AgentResult:
        """执行 Agent run."""
        ...

    @abstractmethod
    def supported_tools(self) -> list[str]:
        """该 runtime 支持的核心工具列表."""
        ...

    @abstractmethod
    def supported_layers(self) -> list[str]:
        """该 runtime 需要启用的 Layer."""
        ...


class RuntimeRegistry:
    """Runtime 注册表."""

    def __init__(self) -> None:
        self._runtimes: dict[str, Callable[..., AgentRuntime]] = {}

    def register(self, name: str, runtime_factory: Callable[..., AgentRuntime]) -> None:
        self._runtimes[name] = runtime_factory

    def select(self, config: RuntimeConfig, **dependencies: Any) -> AgentRuntime:
        """根据配置选择并实例化 runtime."""
        name = config.name
        if name not in self._runtimes:
            # fallback to builtin
            name = "builtin"
        runtime_factory = self._runtimes.get(name)
        if runtime_factory is None:
            raise ValueError(f"No runtime registered for '{name}'")
        return runtime_factory(config, **dependencies)

    def list_runtimes(self) -> list[str]:
        return list(self._runtimes.keys())
