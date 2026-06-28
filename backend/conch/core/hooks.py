"""Hook 总线 — 可扩展性的逃生口。

在 Agent Loop 关键节点注入横切逻辑，对核心零侵入。

三大约束（v0.3 固化）：
1. 职责隔离：Hook 仅触发副作用（日志/告警/统计/中断），禁止修改主流程核心数据；
   中间件仅处理数据流变换，禁止中断执行流程。
2. 优先级：priority 数值越小越先执行（默认 100），同节点 Hook 按优先级顺序串行。
3. 中断白名单：仅 INTERRUPTIBLE_HOOKS 中的节点允许中断主流程，其余禁止终止。
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Hook 挂载点 — Agent Loop 的所有关键节点
HOOK_POINTS = [
    "on_task_start",
    "pre_step",
    "post_step",
    "pre_tool",
    "post_tool",
    "on_tool_error",
    "pre_model_call",
    "post_model_call",
    "on_compaction",
    "on_context_reset",
    "on_eval",
    "on_cost_exceeded",
    "on_task_end",
    "on_error",
]

# 仅以下节点允许中断主流程，其余节点禁止终止
INTERRUPTIBLE_HOOKS = {
    "on_tool_error",
    "pre_step",
    "pre_tool",
    "pre_model_call",
    "on_cost_exceeded",
    "on_error",
}


class HookAction(Enum):
    """Hook 返回的动作指令。"""

    CONTINUE = "continue"  # 继续（默认）
    INTERRUPT = "interrupt"  # 中断主流程（仅中断白名单节点有效）


@dataclass
class HookResult:
    """Hook 执行结果。"""

    action: HookAction = HookAction.CONTINUE
    reason: str = ""


@dataclass(order=True)
class HookRegistration:
    """一个已注册的 Hook。"""

    priority: int  # 越小越先执行
    callback: Callable = field(compare=False)
    name: str = field(default="", compare=False)


class HookInterrupted(Exception):
    """Hook 中断了主流程。"""

    def __init__(self, hook_name: str, reason: str):
        self.hook_name = hook_name
        self.reason = reason
        super().__init__(f"Hook '{hook_name}' interrupted: {reason}")


class HookBus:
    """Hook 总线 — 管理所有 Hook 的注册与触发。

    用法:
        bus = HookBus()
        bus.register("post_step", my_hook, priority=10)
        bus.fire("post_step", state)
    """

    def __init__(self):
        self._hooks: dict[str, list[HookRegistration]] = defaultdict(list)

    def register(
        self, point: str, callback: Callable, priority: int = 100, name: str = ""
    ) -> None:
        """注册一个 Hook 到指定节点。

        Args:
            point: 挂载点名称（见 HOOK_POINTS）
            callback: 回调函数，签名为 (*args, **kwargs) -> HookResult | None
            priority: 优先级，越小越先执行（默认 100）
            name: Hook 名称（用于调试）
        """
        if point not in HOOK_POINTS:
            raise ValueError(
                f"Unknown hook point '{point}'. Valid: {HOOK_POINTS}"
            )
        reg = HookRegistration(priority=priority, callback=callback, name=name or callback.__name__)
        self._hooks[point].append(reg)
        # 按 priority 排序
        self._hooks[point].sort()

    def fire(self, point: str, *args, **kwargs) -> None:
        """触发某节点的所有 Hook（按优先级顺序）。

        如果 Hook 返回 INTERRUPT 且该节点在中断白名单中，抛出 HookInterrupted。
        """
        for reg in self._hooks.get(point, []):
            try:
                result = reg.callback(*args, **kwargs)
                if isinstance(result, HookResult) and result.action == HookAction.INTERRUPT:
                    if point not in INTERRUPTIBLE_HOOKS:
                        logger.warning(
                            "Hook '%s' tried to interrupt at non-interruptible point '%s', ignored",
                            reg.name, point,
                        )
                        continue
                    raise HookInterrupted(reg.name, result.reason)
            except HookInterrupted:
                raise
            except Exception:
                logger.exception("Hook '%s' at '%s' raised exception", reg.name, point)

    def has_hooks(self, point: str) -> bool:
        return bool(self._hooks.get(point))


# 全局 Hook 总线实例
hook_bus = HookBus()


def hook(point: str, priority: int = 100, name: str = "") -> Callable:
    """装饰器：注册一个函数为 Hook。

    Example:
        @hook("post_step", priority=10)
        def entropy_guard(state):
            if detect_drift(state):
                return HookResult(action=HookAction.INTERRUPT, reason="entropy too high")
    """

    def deco(func: Callable) -> Callable:
        hook_bus.register(point, func, priority=priority, name=name or func.__name__)
        return func

    return deco
