"""G 层：RBAC 权限点与五级操作分级。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum


class ActionLevel(IntEnum):
    """操作风险等级：只读、低风险写、中风险执行、高风险管理、关键操作。"""

    READ = 1
    WRITE = 2
    EXECUTE = 3
    ADMIN = 4
    CRITICAL = 5


class Permission(str, Enum):
    SESSION_CREATE = "session.create"
    SESSION_READ = "session.read"
    SESSION_UPDATE = "session.update"
    SESSION_DELETE = "session.delete"
    SESSION_SEARCH = "session.search"
    RUN_CREATE = "run.create"
    RUN_READ = "run.read"
    RUN_CANCEL = "run.cancel"
    RUN_REPLAY = "run.replay"
    TOOL_READ = "tool.read"
    TOOL_WRITE = "tool.write"
    TOOL_EXECUTE = "tool.execute"
    TOOL_NETWORK = "tool.network"
    TOOL_DEPLOY = "tool.deploy"
    TOOL_ADMIN = "tool.admin"
    MEMORY_READ = "memory.read"
    MEMORY_WRITE = "memory.write"
    MEMORY_DELETE = "memory.delete"
    SKILL_READ = "skill.read"
    SKILL_WRITE = "skill.write"
    SKILL_ARCHIVE = "skill.archive"
    SKILL_CONSOLIDATE = "skill.consolidate"
    APPROVAL_READ = "approval.read"
    APPROVAL_CREATE = "approval.create"
    APPROVAL_DECIDE = "approval.decide"
    POLICY_READ = "policy.read"
    POLICY_WRITE = "policy.write"
    ROLE_READ = "role.read"
    ROLE_WRITE = "role.write"
    AUDIT_READ = "audit.read"
    TRACE_READ = "trace.read"
    VERIFICATION_READ = "verification.read"
    VERIFICATION_RUN = "verification.run"
    REGRESSION_READ = "regression.read"
    REGRESSION_WRITE = "regression.write"
    REGRESSION_RUN = "regression.run"
    BUDGET_READ = "budget.read"
    BUDGET_WRITE = "budget.write"
    CREDENTIAL_READ = "credential.read"
    CREDENTIAL_ROTATE = "credential.rotate"
    SCHEDULE_READ = "schedule.read"
    SCHEDULE_WRITE = "schedule.write"
    SCHEDULE_RUN = "schedule.run"
    COORDINATOR_READ = "coordinator.read"
    COORDINATOR_RUN = "coordinator.run"
    SNAPSHOT_READ = "snapshot.read"
    SNAPSHOT_CREATE = "snapshot.create"
    SNAPSHOT_RESTORE = "snapshot.restore"
    SNAPSHOT_DELETE = "snapshot.delete"
    INSIGHTS_READ = "insights.read"
    SYSTEM_HEALTH = "system.health"
    SYSTEM_ADMIN = "system.admin"


ALL_PERMISSIONS = frozenset(Permission)


ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "viewer": frozenset(
        {
            Permission.SESSION_READ,
            Permission.SESSION_SEARCH,
            Permission.RUN_READ,
            Permission.RUN_REPLAY,
            Permission.TOOL_READ,
            Permission.MEMORY_READ,
            Permission.SKILL_READ,
            Permission.APPROVAL_READ,
            Permission.POLICY_READ,
            Permission.ROLE_READ,
            Permission.AUDIT_READ,
            Permission.TRACE_READ,
            Permission.VERIFICATION_READ,
            Permission.REGRESSION_READ,
            Permission.BUDGET_READ,
            Permission.SCHEDULE_READ,
            Permission.COORDINATOR_READ,
            Permission.SNAPSHOT_READ,
            Permission.INSIGHTS_READ,
            Permission.SYSTEM_HEALTH,
        }
    ),
    "operator": frozenset(
        {
            Permission.SESSION_CREATE,
            Permission.SESSION_READ,
            Permission.SESSION_UPDATE,
            Permission.SESSION_SEARCH,
            Permission.RUN_CREATE,
            Permission.RUN_READ,
            Permission.RUN_CANCEL,
            Permission.RUN_REPLAY,
            Permission.TOOL_READ,
            Permission.TOOL_NETWORK,
            Permission.MEMORY_READ,
            Permission.SKILL_READ,
            Permission.APPROVAL_READ,
            Permission.APPROVAL_CREATE,
            Permission.POLICY_READ,
            Permission.ROLE_READ,
            Permission.AUDIT_READ,
            Permission.TRACE_READ,
            Permission.VERIFICATION_READ,
            Permission.REGRESSION_READ,
            Permission.BUDGET_READ,
            Permission.SCHEDULE_READ,
            Permission.SCHEDULE_RUN,
            Permission.COORDINATOR_READ,
            Permission.SNAPSHOT_READ,
            Permission.INSIGHTS_READ,
            Permission.SYSTEM_HEALTH,
        }
    ),
    "developer": frozenset(
        {
            Permission.SESSION_CREATE,
            Permission.SESSION_READ,
            Permission.SESSION_UPDATE,
            Permission.SESSION_SEARCH,
            Permission.RUN_CREATE,
            Permission.RUN_READ,
            Permission.RUN_CANCEL,
            Permission.RUN_REPLAY,
            Permission.TOOL_READ,
            Permission.TOOL_WRITE,
            Permission.TOOL_EXECUTE,
            Permission.TOOL_NETWORK,
            Permission.MEMORY_READ,
            Permission.MEMORY_WRITE,
            Permission.SKILL_READ,
            Permission.APPROVAL_READ,
            Permission.APPROVAL_CREATE,
            Permission.POLICY_READ,
            Permission.ROLE_READ,
            Permission.AUDIT_READ,
            Permission.TRACE_READ,
            Permission.VERIFICATION_READ,
            Permission.VERIFICATION_RUN,
            Permission.REGRESSION_READ,
            Permission.REGRESSION_RUN,
            Permission.BUDGET_READ,
            Permission.SCHEDULE_READ,
            Permission.SCHEDULE_RUN,
            Permission.COORDINATOR_READ,
            Permission.SNAPSHOT_READ,
            Permission.SNAPSHOT_CREATE,
            Permission.INSIGHTS_READ,
            Permission.SYSTEM_HEALTH,
        }
    ),
    "maintainer": frozenset(ALL_PERMISSIONS - {Permission.SYSTEM_ADMIN, Permission.ROLE_WRITE}),
    "admin": ALL_PERMISSIONS,
    "worker": frozenset(
        {
            Permission.SESSION_CREATE,
            Permission.SESSION_READ,
            Permission.RUN_CREATE,
            Permission.RUN_READ,
            Permission.TOOL_READ,
            Permission.TOOL_WRITE,
            Permission.TOOL_EXECUTE,
            Permission.MEMORY_READ,
            Permission.SKILL_READ,
            Permission.TRACE_READ,
            Permission.VERIFICATION_READ,
            Permission.BUDGET_READ,
        }
    ),
}


@dataclass(frozen=True)
class AuthorizationResult:
    allowed: bool
    role: str
    permission: Permission
    reason: str


class RBAC:
    def __init__(self, roles: dict[str, frozenset[Permission]] | None = None) -> None:
        self._roles = dict(roles or ROLE_PERMISSIONS)

    def authorize(self, role: str, permission: Permission) -> AuthorizationResult:
        permissions = self._roles.get(role)
        if permissions is None:
            return AuthorizationResult(False, role, permission, f"Unknown role: {role}")
        allowed = permission in permissions
        reason = "permission granted" if allowed else f"Role '{role}' lacks {permission.value}"
        return AuthorizationResult(allowed, role, permission, reason)

    def roles(self) -> dict[str, list[str]]:
        return {
            role: sorted(permission.value for permission in permissions)
            for role, permissions in sorted(self._roles.items())
        }


ACTION_PERMISSIONS: dict[str, Permission] = {
    "read": Permission.TOOL_READ,
    "write": Permission.TOOL_WRITE,
    "exec": Permission.TOOL_EXECUTE,
    "network": Permission.TOOL_NETWORK,
    "deploy": Permission.TOOL_DEPLOY,
}

ACTION_LEVELS: dict[str, ActionLevel] = {
    "read": ActionLevel.READ,
    "write": ActionLevel.WRITE,
    "network": ActionLevel.EXECUTE,
    "exec": ActionLevel.EXECUTE,
    "deploy": ActionLevel.CRITICAL,
}
