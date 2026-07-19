"""L 层: Layer 插件体系基础框架.

接口策略:
- Layer 接口: on_graph_start / on_node_run_start / on_node_run_end / on_event / on_graph_end
- 横切能力: 配额/可观测/暂停恢复/验证/策略
- 不同部署场景按需启用不同 Layer
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GraphContext:
    """Agent 执行图上下文 (整个 run 生命周期)."""

    session_id: str
    user_input: str = ""
    turn_count: int = 0
    max_turns: int = 50
    max_time: int = 600
    start_time: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    # 控制信号
    should_abort: bool = False
    abort_reason: str = ""


@dataclass
class NodeContext:
    """单轮执行节点上下文 (单次 LLM 调用 + 工具执行)."""

    session_id: str
    turn_index: int
    # 当前轮的 LLM 响应
    response: dict[str, Any] | None = None
    # 当前轮的工具调用
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    # 当前轮的工具执行结果
    tool_results: list[Any] = field(default_factory=list)
    # 控制信号
    should_block: bool = False
    block_reason: str = ""
    # 注入消息 (让模型修复错误)
    inject_messages: list[dict[str, str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def inject_message(self, content: str, role: str = "user") -> None:
        """注入消息到下一轮上下文."""
        self.inject_messages.append({"role": role, "content": content})

    def block_progress(self, reason: str) -> None:
        """阻止进入下一步 (质量门禁)."""
        self.should_block = True
        self.block_reason = reason


@dataclass
class Event:
    """生命周期事件."""

    type: str  # "pause" | "resume" | "error" | "approval_request" | ...
    data: dict[str, Any] = field(default_factory=dict)


class Layer:
    """Layer 抽象基类.

    子类按需覆盖生命周期钩子. 默认实现为空操作.
    """

    name: str = "base"

    async def on_graph_start(self, ctx: GraphContext) -> None:
        """Agent run 开始时调用."""
        pass

    async def on_node_run_start(self, ctx: NodeContext) -> None:
        """单轮执行开始时调用."""
        pass

    async def on_node_run_end(self, ctx: NodeContext, result: Any) -> None:
        """单轮执行结束后调用 (工具执行完毕)."""
        pass

    async def on_event(self, event: Event) -> None:
        """事件发生时调用."""
        pass

    async def on_graph_end(self, ctx: GraphContext) -> None:
        """Agent run 结束时调用."""
        pass


class LayerManager:
    """Layer 管理器.

    按注册顺序执行各 Layer 的钩子.
    """

    def __init__(self) -> None:
        self._layers: list[Layer] = []

    def add(self, layer: Layer) -> None:
        """添加 Layer."""
        self._layers.append(layer)

    def remove(self, name: str) -> None:
        """移除 Layer."""
        self._layers = [layer for layer in self._layers if layer.name != name]

    @property
    def layers(self) -> list[Layer]:
        return list(self._layers)

    async def on_graph_start(self, ctx: GraphContext) -> None:
        for layer in self._layers:
            await layer.on_graph_start(ctx)
            if ctx.should_abort:
                return

    async def on_node_run_start(self, ctx: NodeContext) -> None:
        for layer in self._layers:
            await layer.on_node_run_start(ctx)

    async def on_node_run_end(self, ctx: NodeContext, result: Any) -> None:
        for layer in self._layers:
            await layer.on_node_run_end(ctx, result)

    async def on_event(self, event: Event) -> None:
        for layer in self._layers:
            await layer.on_event(event)

    async def on_graph_end(self, ctx: GraphContext) -> None:
        for layer in self._layers:
            await layer.on_graph_end(ctx)
