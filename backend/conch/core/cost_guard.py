"""成本守卫与执行状态 — 从 v1 loop.py 拆出。

v2 改动：
- State 新增 hook_bus / profile 字段，供 Hook 桥接层与编排 Plugin 读取
- CostGuard 独立模块，编排 Plugin（LangGraph / single_loop）共用
- AgentLoop 编排逻辑降级到 adapters/orchestration/single_loop.py
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from conch.core.hooks import HookBus

if TYPE_CHECKING:
    from conch.core.profile import Profile

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    DEGRADED = "degraded"  # 成本降级后终止
    FAILED = "failed"


class DegradeLevel(Enum):
    """成本降级级别（v0.3 分级降级策略）。"""

    NONE = 0
    L1_COMPACT = 1      # 超 60% 阈值 → 触发 compaction
    L2_SWITCH_MODEL = 2  # 超 80% 阈值 → 切换廉价模型
    L3_DISABLE_TOOLS = 3  # 超 90% 阈值 → 禁用非核心工具（延后）
    L4_TERMINATE = 4     # 超 100% 预算 → 终止任务


@dataclass
class State:
    """Agent 执行状态 — 编排 Plugin 与 Hook 共享。

    v2 新增字段:
        hook_bus: Hook 总线引用，供编排 Plugin 的桥接层触发语义 Hook
        profile: 当前 Profile 引用，供 Hook 读取配置
    """

    task: Any
    status: TaskStatus = TaskStatus.PENDING
    steps: int = 0
    actions: list[dict] = field(default_factory=list)
    context: Any = None
    total_tokens: int = 0
    total_cost: float = 0.0
    result: Any = None
    error: Exception | None = None
    degrade_level: DegradeLevel = DegradeLevel.NONE
    # v2 新增
    hook_bus: HookBus | None = None
    profile: "Profile | None" = None
    session_id: str = ""
    runtime_events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def done(self) -> bool:
        return self.status in (TaskStatus.DONE, TaskStatus.DEGRADED, TaskStatus.FAILED)

    def record(self, action: dict) -> None:
        """记录一步动作，累计 token 与成本。"""
        self.actions.append(action)
        self.steps += 1
        usage = action.get("usage", {})
        self.total_tokens += usage.get("total_tokens", 0)
        self.total_cost += usage.get("cost", 0.0)

    def emit_event(self, event: dict[str, Any]) -> None:
        """缓存运行时事件，供 API/SSE 层转发。"""
        self.runtime_events.append(event)

    def drain_events(self) -> list[dict[str, Any]]:
        """取出并清空运行时事件队列。"""
        events = list(self.runtime_events)
        self.runtime_events.clear()
        return events


class CostGuard:
    """成本守卫 — token budget 分级降级。

    MVP 实现 L1(压缩) + L2(切模型) + L4(终止)，L3(禁工具)延后。
    编排 Plugin 在每步后调用 check()，根据返回级别执行降级。
    """

    def __init__(self, max_tokens: int | None = None):
        self.max_tokens = max_tokens

    def check(self, state: State) -> DegradeLevel:
        """检查当前状态，返回应触发的降级级别。"""
        if self.max_tokens is None:
            return DegradeLevel.NONE

        ratio = state.total_tokens / self.max_tokens
        if ratio >= 1.0:
            return DegradeLevel.L4_TERMINATE
        if ratio >= 0.9:
            return DegradeLevel.L3_DISABLE_TOOLS  # 延后，实际走 L2
        if ratio >= 0.8:
            return DegradeLevel.L2_SWITCH_MODEL
        if ratio >= 0.6:
            return DegradeLevel.L1_COMPACT
        return DegradeLevel.NONE

    def exceeded(self, state: State) -> bool:
        return self.check(state) == DegradeLevel.L4_TERMINATE

    def apply(self, state: State, level: DegradeLevel) -> None:
        """对 state 应用降级副作用（触发 Hook、改状态）。"""
        if level == DegradeLevel.NONE:
            return

        if level.value > state.degrade_level.value:
            state.degrade_level = level
        if state.hook_bus:
            state.hook_bus.fire("on_cost_exceeded", state, level=level)

        if level == DegradeLevel.L4_TERMINATE:
            logger.warning("Cost guard L4: budget exceeded, terminating task")
            state.status = TaskStatus.DEGRADED
