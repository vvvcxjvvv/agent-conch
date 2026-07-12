"""T 层: 工具策略控制.

设计文档要求:
- ToolPolicy: Allow/Deny + Sender Policy + Sandbox Policy 三层
- 读、写、执行、网络、部署操作分级管控
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ToolAction(str, Enum):
    """工具操作类型."""

    READ = "read"
    WRITE = "write"
    EXEC = "exec"
    NETWORK = "network"
    DEPLOY = "deploy"


class PolicyDecision(str, Enum):
    """策略决策."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass
class PolicyContext:
    """策略评估上下文."""

    tool_name: str
    action: ToolAction
    sender: str = "main"  # main | subagent | plugin | mcp
    sandbox_mode: str = "non-main"  # non-main | always | never
    is_main_session: bool = True
    arguments: dict[str, Any] = field(default_factory=dict)
    session_id: str = ""


@dataclass
class PolicyRule:
    """策略规则."""

    name: str
    condition: str  # 简化的条件表达式
    decision: PolicyDecision
    reason: str = ""


# 默认策略规则
DEFAULT_RULES: list[PolicyRule] = [
    # 子 Agent 禁止 deploy
    PolicyRule(
        name="no_subagent_deploy",
        condition="action == 'deploy' and sender == 'subagent'",
        decision=PolicyDecision.DENY,
        reason="Subagents cannot deploy",
    ),
    # 子 Agent 写操作需要审批
    PolicyRule(
        name="subagent_write_approval",
        condition="action == 'write' and sender == 'subagent'",
        decision=PolicyDecision.REQUIRE_APPROVAL,
        reason="Subagent write requires approval",
    ),
    # never 沙箱模式下禁止 exec
    PolicyRule(
        name="no_exec_in_never_sandbox",
        condition="action == 'exec' and sandbox_mode == 'never'",
        decision=PolicyDecision.DENY,
        reason="Exec not allowed in never-sandbox mode",
    ),
]


class ToolPolicy:
    """工具策略引擎.

    三层策略:
    1. Allow/Deny: 显式允许/拒绝列表
    2. Sender Policy: 根据调用者身份控制
    3. Sandbox Policy: 根据沙箱模式控制
    """

    def __init__(
        self,
        allow_list: list[str] | None = None,
        deny_list: list[str] | None = None,
        rules: list[PolicyRule] | None = None,
    ):
        self.allow_list = set(allow_list) if allow_list else set()
        self.deny_list = set(deny_list) if deny_list else set()
        self.rules = rules or list(DEFAULT_RULES)

    def evaluate(self, ctx: PolicyContext) -> tuple[PolicyDecision, str]:
        """评估策略.

        评估顺序:
        1. 显式 deny_list → DENY
        2. 显式 allow_list → 跳过规则检查
        3. 规则评估 (按顺序, 首个匹配生效)
        4. 默认 ALLOW
        """
        # 1. deny_list 优先
        if ctx.tool_name in self.deny_list:
            return PolicyDecision.DENY, f"Tool '{ctx.tool_name}' in deny list"

        # 2. allow_list 跳过规则
        if ctx.tool_name in self.allow_list:
            return PolicyDecision.ALLOW, f"Tool '{ctx.tool_name}' in allow list"

        # 3. 规则评估
        for rule in self.rules:
            if self._match_rule(rule, ctx):
                return rule.decision, rule.reason or rule.name

        # 4. 默认允许
        return PolicyDecision.ALLOW, "Default allow"

    def _match_rule(self, rule: PolicyRule, ctx: PolicyContext) -> bool:
        """简化条件匹配.

        支持 ==, !=, and 关键字.
        条件变量: action, sender, sandbox_mode, is_main_session, tool_name
        """
        cond = rule.condition.strip()
        if not cond:
            return False

        # 简单解析: 按 and 分割
        parts = cond.split(" and ")
        for part in parts:
            part = part.strip()
            if " == " in part:
                var, val = part.split(" == ", 1)
                var = var.strip()
                val = val.strip().strip("'\"")
                actual = self._get_var(var, ctx)
                if str(actual) != val:
                    return False
            elif " != " in part:
                var, val = part.split(" != ", 1)
                var = var.strip()
                val = val.strip().strip("'\"")
                actual = self._get_var(var, ctx)
                if str(actual) == val:
                    return False
            else:
                return False

        return True

    def _get_var(self, var: str, ctx: PolicyContext) -> Any:
        if var == "action":
            return ctx.action.value
        elif var == "sender":
            return ctx.sender
        elif var == "sandbox_mode":
            return ctx.sandbox_mode
        elif var == "is_main_session":
            return ctx.is_main_session
        elif var == "tool_name":
            return ctx.tool_name
        return None

    def add_rule(self, rule: PolicyRule) -> None:
        """添加策略规则."""
        self.rules.append(rule)

    def allow(self, tool_name: str) -> None:
        """添加到允许列表."""
        self.allow_list.add(tool_name)

    def deny(self, tool_name: str) -> None:
        """添加到拒绝列表."""
        self.deny_list.add(tool_name)
