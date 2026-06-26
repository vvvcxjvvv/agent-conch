"""Agent Loop 引擎 — 编排核心。

最小可靠的单 Agent 循环，多 Agent 在其上组合（见 orchestration.py）。
内建 streaming 输出与 cost guard 分级降级。

数据流:
    任务输入 → [组装上下文 → 推理(streaming) → 工具执行 → 记录轨迹 → 评测 → cost guard] 循环
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from conch.core.hooks import HookBus, HookInterrupted

# Profile 依赖 pydantic+yaml，用 TYPE_CHECKING 避免运行时硬依赖
from typing import TYPE_CHECKING
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
    L1_COMPACT = 1  # 超 60% 阈值 → 触发 compaction
    L2_SWITCH_MODEL = 2  # 超 80% 阈值 → 切换廉价模型
    L3_DISABLE_TOOLS = 3  # 超 90% 阈值 → 禁用非核心工具（延后）
    L4_TERMINATE = 4  # 超 100% 预算 → 终止任务


@dataclass
class State:
    """Agent 执行状态。"""

    task: Any
    status: TaskStatus = TaskStatus.PENDING
    steps: int = 0
    actions: list[dict] = field(default_factory=list)  # 每步动作记录
    context: Any = None  # 当前上下文
    total_tokens: int = 0  # 累计 token
    total_cost: float = 0.0  # 累计成本（美元）
    result: Any = None  # 最终结果
    error: Exception | None = None
    degrade_level: DegradeLevel = DegradeLevel.NONE

    @property
    def done(self) -> bool:
        return self.status in (TaskStatus.DONE, TaskStatus.DEGRADED, TaskStatus.FAILED)

    def record(self, action: dict) -> None:
        self.actions.append(action)
        self.steps += 1
        # 累计 token
        usage = action.get("usage", {})
        self.total_tokens += usage.get("total_tokens", 0)
        self.total_cost += usage.get("cost", 0.0)


class CostGuard:
    """成本守卫 — token budget 分级降级。

    MVP 实现 L1(压缩) + L2(切模型) + L4(终止)，L3(禁工具)延后。
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


class AgentLoop:
    """Agent 循环引擎 — 核心编排。

    依赖注入：通过 Profile + Registry 构建各域插件实例。
    核心层不依赖任何具体能力域实现（依赖倒置）。
    """

    def __init__(
        self,
        profile: Profile,
        registry: "Registry",  # noqa: F821
        model: Any = None,  # LLM Provider
        hook_bus: HookBus | None = None,
    ):
        self.profile = profile
        self.registry = registry
        self.model = model
        self.hooks = hook_bus or HookBus()

        # 延迟构建各域插件（按 Profile 配置）
        self._ctx_mgr = None
        self._tool_mgr = None
        self._mem_mgr = None
        self._eval_mgr = None
        self._obs = None
        self._gov = None
        self._constraint = None
        self.cost_guard = CostGuard(profile.max_tokens)

    def _ensure_plugins(self):
        """延迟构建 Profile 中配置的插件实例。"""
        if self._ctx_mgr is None:
            p = self.profile.domains
            self._ctx_mgr = self._build_or_none("context", p)
            self._tool_mgr = self._build_or_none("tool", p)
            self._mem_mgr = self._build_or_none("memory", p)
            self._eval_mgr = self._build_or_none("eval", p)
            self._obs = self._build_or_none("observability", p)
            self._gov = self._build_or_none("governance", p)
            self._constraint = self._build_or_none("constraint", p)

    def _build_or_none(self, domain: str, domains_cfg: dict):
        cfg = domains_cfg.get(domain)
        if cfg is None:
            return None
        return self.registry.build(domain, cfg.impl, cfg.version, **cfg.params)

    async def run(self, task: Any) -> State:
        """执行 Agent 循环。"""
        self._ensure_plugins()
        state = State(task=task, status=TaskStatus.RUNNING)

        try:
            self.hooks.fire("on_task_start", state)
        except HookInterrupted as e:
            state.status = TaskStatus.FAILED
            state.error = e
            return state

        while not state.done and state.steps < self.profile.max_steps:
            try:
                await self._step(state)
            except HookInterrupted as e:
                logger.info("Loop interrupted by hook: %s (reason: %s)", e.hook_name, e.reason)
                state.status = TaskStatus.DONE
                break
            except Exception as e:
                logger.exception("Step %d failed", state.steps)
                self.hooks.fire("on_error", state, error=e)
                # 约束域恢复
                if self._constraint and hasattr(self._constraint, "recover"):
                    self._constraint.recover(e, state)
                else:
                    state.status = TaskStatus.FAILED
                    state.error = e
                    break

            # 连续无工具调用的文本响应达到阈值时终止（避免空转）
            if self._idle_steps(state) >= 3:
                logger.info("Loop terminated: %d consecutive text-only steps", self._idle_steps(state))
                state.status = TaskStatus.DONE
                break

        if not state.done:
            state.status = TaskStatus.DONE

        self.hooks.fire("on_task_end", state)
        return state

    async def _step(self, state: State) -> None:
        """执行单个 step。"""
        self.hooks.fire("pre_step", state)

        # 组装上下文
        if self._ctx_mgr:
            state.context = self._ctx_mgr.assemble(state.task, state)
        self.hooks.fire("pre_model_call", state)

        # 推理（streaming）
        action = await self._infer(state)
        self.hooks.fire("post_model_call", state, action)

        # 工具执行
        if action.get("type") == "tool_call" and self._tool_mgr:
            tool_name = action["tool"]
            tool_args = action.get("args", {})
            self.hooks.fire("pre_tool", state, tool=tool_name, args=tool_args)

            # 权限校验
            if self._gov and not self._gov.check_permission(tool_name, tool_args):
                action["result"] = {"error": f"Permission denied for tool '{tool_name}'"}
                self.hooks.fire("on_tool_error", state, tool=tool_name, error="permission_denied")
            else:
                try:
                    result = await self._tool_mgr.execute(tool_name, tool_args, state)
                    action["result"] = result
                    self.hooks.fire("post_tool", state, tool=tool_name, result=result)
                except Exception as e:
                    action["result"] = {"error": str(e)}
                    self.hooks.fire("on_tool_error", state, tool=tool_name, error=e)

        state.record(action)

        # 可观测性
        if self._obs:
            self._obs.trace(state)

        # 成本守卫
        degrade = self.cost_guard.check(state)
        if degrade != DegradeLevel.NONE:
            self._handle_degrade(state, degrade)

        # 评测
        if self._eval_mgr and self._eval_mgr.should_eval(state):
            feedback = await self._eval_mgr.eval(state)
            self.hooks.fire("on_eval", state, feedback=feedback)

        self.hooks.fire("post_step", state)

    def _idle_steps(self, state: State) -> int:
        """计算最近连续多少步是纯文本响应（无工具调用）。"""
        count = 0
        for action in reversed(state.actions):
            if action.get("type") == "tool_call":
                break
            count += 1
        return count

    async def _infer(self, state: State) -> dict:
        """调用模型推理，返回 action。"""
        if self.model is None:
            return {"type": "text", "content": "[no model configured]", "usage": {}}

        # Provider 层统一暴露 call() 与 stream()
        if hasattr(self.model, "stream"):
            # streaming：边接收边检测工具调用
            chunks = []
            async for chunk in self.model.stream(state.context, model=self.profile.model):
                chunks.append(chunk)
                if self._obs:
                    self._obs.trace(state)  # 可逐步渲染
            content = "".join(c.get("content", "") for c in chunks)
            usage = chunks[-1].get("usage", {}) if chunks else {}
            action = {"type": "text", "content": content, "usage": usage}
            # 检测工具调用（简化版，实际由 Provider 解析 function_call 结构）
            if chunks and chunks[-1].get("tool_call"):
                action = {
                    "type": "tool_call",
                    "tool": chunks[-1]["tool_call"]["name"],
                    "args": chunks[-1]["tool_call"].get("args", {}),
                    "usage": usage,
                }
            return action
        else:
            result = await self.model.call(state.context, model=self.profile.model)
            return {
                "type": "tool_call" if result.get("tool_call") else "text",
                "content": result.get("content", ""),
                "tool": result.get("tool_call", {}).get("name"),
                "args": result.get("tool_call", {}).get("args", {}),
                "usage": result.get("usage", {}),
            }

    def _handle_degrade(self, state: State, level: DegradeLevel) -> None:
        """处理成本降级。"""
        state.degrade_level = max(state.degrade_level, level)
        self.hooks.fire("on_cost_exceeded", state, level=level)

        if level == DegradeLevel.L1_COMPACT and self._ctx_mgr:
            logger.info("Cost guard L1: triggering compaction")
            state.context = self._ctx_mgr.compact(state.context, strategy="summary")
            self.hooks.fire("on_compaction", state)

        elif level == DegradeLevel.L2_SWITCH_MODEL and self.profile.model_fallback:
            logger.info("Cost guard L2: switching to fallback model %s", self.profile.model_fallback)
            self.profile.model = self.profile.model_fallback

        elif level == DegradeLevel.L4_TERMINATE:
            logger.warning("Cost guard L4: budget exceeded, terminating task")
            state.status = TaskStatus.DEGRADED
