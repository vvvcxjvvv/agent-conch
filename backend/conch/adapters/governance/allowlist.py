"""域9：最小权限治理。

提供 allowlist / denylist 权限校验与 JSONL 审计日志。
阶段二先落地最小可用版本，后续再扩到 RBAC / HITL。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from conch.core.extension import GovernanceProvider, Plugin
from conch.core.registry import registry


@registry.register("governance", "allowlist_perms", "1.0")
class AllowlistGovernance(Plugin, GovernanceProvider):
    """最小权限治理。

    Args:
        allowed_tools: 显式允许的工具名；为空且 allow_all=False 时表示不限制
        denied_tools: 显式拒绝的工具名
        allow_all: 是否默认允许所有工具
        require_approval_tools: 需要人工审批的工具名（阶段二预留）
        audit_file: 审计日志 JSONL 文件
    """

    domain = "governance"
    name = "allowlist_perms"
    version = "1.0"
    metadata = {
        "capabilities": ["permission", "audit", "allowlist"],
        "description": "最小权限治理：allowlist/denylist + 审计日志",
    }

    def __init__(
        self,
        allowed_tools: list[str] | None = None,
        denied_tools: list[str] | None = None,
        allow_all: bool = False,
        require_approval_tools: list[str] | None = None,
        audit_file: str | None = None,
    ):
        self.allowed_tools = set(allowed_tools or [])
        self.denied_tools = set(denied_tools or [])
        self.allow_all = allow_all
        self.require_approval_tools = set(require_approval_tools or [])
        self.audit_file = Path(audit_file) if audit_file else None
        self._entries: list[dict[str, Any]] = []

    def check_permission(self, tool: str, args: dict) -> bool:
        if tool in self.denied_tools:
            return False
        if self.allow_all:
            return True
        if not self.allowed_tools:
            return True
        return tool in self.allowed_tools

    def audit(self, action: str, detail: dict) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "detail": detail,
        }
        self._entries.append(entry)
        if self.audit_file is None:
            return
        self.audit_file.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def requires_approval(self, tool: str, args: dict) -> bool:
        return tool in self.require_approval_tools

    def recent_entries(self) -> list[dict[str, Any]]:
        return list(self._entries)
