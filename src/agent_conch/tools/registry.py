"""T 层: 工具注册表.

设计文档要求:
- ToolRegistry: 工具注册 + check_fn TTL 缓存 (30s)
- 瞬态故障抑制: 连续失败 60s 内不再暴露
- 核心工具默认注册
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from agent_conch.tools.base import BaseTool, ToolCall, ToolExecutionRecord, ToolResult
from agent_conch.tools.tool_policy import PolicyContext, PolicyDecision, ToolAction, ToolPolicy


@dataclass
class ToolHealthState:
    """工具健康状态 (用于 check_fn TTL 和瞬态故障抑制)."""

    last_check_time: float = 0.0
    last_check_available: bool = True
    last_check_reason: str | None = None
    consecutive_failures: int = 0
    first_failure_time: float = 0.0
    suppressed_until: float = 0.0  # 抑制到此时间


class ToolRegistry:
    """工具注册表.

    职责:
    1. 注册/注销工具
    2. check_fn 可用性检查 + TTL 缓存 (默认 30s)
    3. 瞬态故障抑制 (默认 60s)
    4. 生成工具 schema 列表给 LLM
    5. 执行工具调用 (经 ToolPolicy 策略检查)
    """

    def __init__(
        self,
        policy: ToolPolicy | None = None,
        check_ttl: int = 30,
        transient_suppress: int = 60,
    ):
        self._tools: dict[str, BaseTool] = {}
        self._health: dict[str, ToolHealthState] = {}
        self.policy = policy or ToolPolicy()
        self.check_ttl = check_ttl
        self.transient_suppress = transient_suppress

    def register(self, tool: BaseTool) -> None:
        """注册工具."""
        self._tools[tool.name] = tool
        self._health[tool.name] = ToolHealthState()

    def unregister(self, name: str) -> None:
        """注销工具."""
        self._tools.pop(name, None)
        self._health.pop(name, None)

    def get(self, name: str) -> BaseTool | None:
        """获取工具."""
        return self._tools.get(name)

    def list_names(self) -> list[str]:
        """列出所有已注册工具名."""
        return list(self._tools.keys())

    async def check_tool_available(self, name: str) -> tuple[bool, str | None]:
        """检查工具可用性 (带 TTL 缓存).

        - 如果距上次检查 < check_ttl 秒, 返回缓存结果
        - 否则调用 tool.check_available() 并更新缓存
        """
        tool = self._tools.get(name)
        if tool is None:
            return False, f"Tool '{name}' not registered"

        health = self._health[name]
        now = time.time()

        # TTL 缓存
        if now - health.last_check_time < self.check_ttl:
            return health.last_check_available, health.last_check_reason

        # 瞬态故障抑制
        if now < health.suppressed_until:
            return False, f"Tool suppressed due to transient failures (until {health.suppressed_until:.0f})"

        # 实际检查
        available, reason = await tool.check_available()
        health.last_check_time = now
        health.last_check_available = available
        health.last_check_reason = reason

        return available, reason

    def is_suppressed(self, name: str) -> bool:
        """检查工具是否被瞬态故障抑制."""
        health = self._health.get(name)
        if health is None:
            return False
        return time.time() < health.suppressed_until

    def record_failure(self, name: str) -> None:
        """记录工具执行失败 (用于瞬态故障抑制)."""
        health = self._health.get(name)
        if health is None:
            return
        now = time.time()
        if health.consecutive_failures == 0:
            health.first_failure_time = now
        health.consecutive_failures += 1
        # 连续失败 2 次以上 → 抑制
        if health.consecutive_failures >= 2:
            health.suppressed_until = now + self.transient_suppress

    def record_success(self, name: str) -> None:
        """记录工具执行成功 (重置故障计数)."""
        health = self._health.get(name)
        if health is None:
            return
        health.consecutive_failures = 0
        health.first_failure_time = 0.0
        health.suppressed_until = 0.0

    async def get_available_schemas(self, include_core_only: bool = False) -> list[dict[str, Any]]:
        """获取可用工具的 schema 列表 (给 LLM).

        过滤掉:
        1. 被瞬态故障抑制的工具
        2. check_fn 检查不可用的工具 (非核心工具)
        """
        schemas: list[dict[str, Any]] = []
        for name, tool in self._tools.items():
            if include_core_only and not tool.is_core:
                continue
            if self.is_suppressed(name):
                continue
            # 核心工具不强制 check (默认可用)
            if not tool.is_core:
                available, _ = await self.check_tool_available(name)
                if not available:
                    continue
            schemas.append(tool.to_schema())
        return schemas

    async def execute_tool_call(
        self,
        call: ToolCall,
        sender: str = "main",
        sandbox_mode: str = "non-main",
        is_main_session: bool = True,
    ) -> ToolExecutionRecord:
        """执行工具调用.

        流程:
        1. 查找工具
        2. 参数校验
        3. 策略检查
        4. 执行
        5. 记录健康状态
        6. 返回执行记录
        """
        import time as _time

        start = _time.time()
        tool = self._tools.get(call.name)

        if tool is None:
            result = ToolResult.error(f"Tool '{call.name}' not found")
            return ToolExecutionRecord(
                tool_name=call.name,
                tool_call_id=call.id,
                arguments=call.arguments,
                result=result,
                duration_ms=int((_time.time() - start) * 1000),
                status="error",
            )

        # 参数校验
        try:
            validated = tool.validate_input(**call.arguments)
        except Exception as e:
            result = ToolResult.error(f"Invalid arguments: {e!s}")
            return ToolExecutionRecord(
                tool_name=call.name,
                tool_call_id=call.id,
                arguments=call.arguments,
                result=result,
                duration_ms=int((_time.time() - start) * 1000),
                status="error",
            )

        # 策略检查
        action = self._infer_action(tool)
        ctx = PolicyContext(
            tool_name=call.name,
            action=action,
            sender=sender,
            sandbox_mode=sandbox_mode,
            is_main_session=is_main_session,
            arguments=validated,
        )
        decision, reason = self.policy.evaluate(ctx)

        if decision == PolicyDecision.DENY:
            result = ToolResult.error(f"Tool blocked by policy: {reason}")
            return ToolExecutionRecord(
                tool_name=call.name,
                tool_call_id=call.id,
                arguments=validated,
                result=result,
                duration_ms=int((_time.time() - start) * 1000),
                status="blocked",
            )

        if decision == PolicyDecision.REQUIRE_APPROVAL:
            # P1: 暂时放行, P4 接入 WriteApproval 审批流程
            pass

        # 执行
        try:
            result = await tool.execute(**validated)
            if result.is_error:
                self.record_failure(call.name)
                status = "error"
            else:
                self.record_success(call.name)
                status = "success"
        except Exception as e:
            self.record_failure(call.name)
            result = ToolResult.error(f"Tool execution error: {e!s}")
            status = "error"

        return ToolExecutionRecord(
            tool_name=call.name,
            tool_call_id=call.id,
            arguments=validated,
            result=result,
            duration_ms=int((_time.time() - start) * 1000),
            status=status,
        )

    def _infer_action(self, tool: BaseTool) -> ToolAction:
        """推断工具操作类型."""
        if tool.is_write_tool:
            return ToolAction.WRITE
        if tool.name in ("bash", "task_manage"):
            return ToolAction.EXEC
        if tool.name in ("web_search", "web_fetch"):
            return ToolAction.NETWORK
        return ToolAction.READ

    def get_health_status(self) -> dict[str, dict[str, Any]]:
        """获取所有工具健康状态 (供调试/监控)."""
        result = {}
        for name, health in self._health.items():
            result[name] = {
                "available": health.last_check_available,
                "consecutive_failures": health.consecutive_failures,
                "suppressed": self.is_suppressed(name),
                "last_check": health.last_check_time,
            }
        return result
