"""G 层：YAML 驱动的统一 PolicyEngine。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from agent_conch.security.permissions import RBAC, ActionLevel, Permission


class PolicyEffect(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True)
class PolicyRequest:
    principal: str
    role: str
    permission: Permission
    action_level: ActionLevel
    tool_name: str = ""
    action: str = ""
    sender: str = "main"
    session_id: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyResult:
    effect: PolicyEffect
    reason: str
    matched_rule: str = ""

    @property
    def allowed(self) -> bool:
        return self.effect == PolicyEffect.ALLOW


@dataclass(frozen=True)
class GovernanceRule:
    name: str
    effect: PolicyEffect
    reason: str = ""
    roles: tuple[str, ...] = ()
    senders: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    minimum_level: ActionLevel | None = None
    argument_contains: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GovernanceRule:
        raw_level = data.get("minimum_level")
        argument_contains = {
            str(key): tuple(str(item) for item in value)
            for key, value in dict(data.get("argument_contains", {})).items()
        }
        return cls(
            name=str(data["name"]),
            effect=PolicyEffect(str(data.get("effect", "deny"))),
            reason=str(data.get("reason", "")),
            roles=tuple(str(item) for item in data.get("roles", [])),
            senders=tuple(str(item) for item in data.get("senders", [])),
            tools=tuple(str(item) for item in data.get("tools", [])),
            actions=tuple(str(item) for item in data.get("actions", [])),
            minimum_level=ActionLevel(int(raw_level)) if raw_level is not None else None,
            argument_contains=argument_contains,
        )

    def matches(self, request: PolicyRequest) -> bool:
        if self.roles and request.role not in self.roles:
            return False
        if self.senders and request.sender not in self.senders:
            return False
        if self.tools and request.tool_name not in self.tools:
            return False
        if self.actions and request.action not in self.actions:
            return False
        if self.minimum_level is not None and request.action_level < self.minimum_level:
            return False
        for key, needles in self.argument_contains.items():
            value = str(request.arguments.get(key, ""))
            if not any(needle in value for needle in needles):
                return False
        return True


DEFAULT_GOVERNANCE_RULES = (
    GovernanceRule(
        name="subagent_deploy_denied",
        effect=PolicyEffect.DENY,
        reason="Subagents cannot perform deployment operations",
        senders=("subagent",),
        actions=("deploy",),
    ),
    GovernanceRule(
        name="critical_operation_approval",
        effect=PolicyEffect.REQUIRE_APPROVAL,
        reason="Critical operations require explicit approval",
        minimum_level=ActionLevel.CRITICAL,
    ),
    GovernanceRule(
        name="memory_skill_write_approval",
        effect=PolicyEffect.REQUIRE_APPROVAL,
        reason="Memory and Skill writes require explicit approval",
        tools=("write_file", "edit_file"),
        argument_contains={
            "path": ("MEMORY.md", "SKILL.md", "/memory/", "/skills/", "\\memory\\", "\\skills\\")
        },
    ),
)


class PolicyEngine:
    """按 RBAC、显式规则、风险阈值顺序产生单一治理决策。"""

    def __init__(
        self,
        rbac: RBAC | None = None,
        rules: list[GovernanceRule] | None = None,
        approval_level: ActionLevel = ActionLevel.ADMIN,
    ) -> None:
        self.rbac = rbac or RBAC()
        self.rules = list(rules) if rules is not None else list(DEFAULT_GOVERNANCE_RULES)
        self.approval_level = approval_level

    @classmethod
    def from_config(
        cls,
        rules: list[dict[str, Any]] | None = None,
        approval_level: int = int(ActionLevel.ADMIN),
    ) -> PolicyEngine:
        configured = [GovernanceRule.from_dict(item) for item in (rules or [])]
        return cls(rules=[*DEFAULT_GOVERNANCE_RULES, *configured], approval_level=ActionLevel(approval_level))

    def evaluate(self, request: PolicyRequest) -> PolicyResult:
        authorization = self.rbac.authorize(request.role, request.permission)
        if not authorization.allowed:
            return PolicyResult(PolicyEffect.DENY, authorization.reason, "rbac")

        for rule in self.rules:
            if rule.matches(request):
                return PolicyResult(rule.effect, rule.reason or rule.name, rule.name)

        if request.action_level >= self.approval_level:
            return PolicyResult(
                PolicyEffect.REQUIRE_APPROVAL,
                f"Action level {int(request.action_level)} requires approval",
                "action_level_threshold",
            )
        return PolicyResult(PolicyEffect.ALLOW, "Policy checks passed", "default_allow")

    def describe(self) -> dict[str, Any]:
        return {
            "approval_level": int(self.approval_level),
            "roles": self.rbac.roles(),
            "rules": [
                {
                    "name": rule.name,
                    "effect": rule.effect.value,
                    "reason": rule.reason,
                    "roles": list(rule.roles),
                    "senders": list(rule.senders),
                    "tools": list(rule.tools),
                    "actions": list(rule.actions),
                    "minimum_level": int(rule.minimum_level) if rule.minimum_level else None,
                    "argument_contains": {
                        key: list(values) for key, values in rule.argument_contains.items()
                    },
                }
                for rule in self.rules
            ],
        }
