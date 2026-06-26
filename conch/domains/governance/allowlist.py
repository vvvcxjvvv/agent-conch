"""域9：allowlist 权限模型 — 配置允许的工具列表 + 审计日志。

MVP 治理实现：
- check_permission() 工具必须在 allowlist 中
- audit() 记录审计日志（可选写文件）
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from conch.core.extension import Plugin
from conch.core.registry import registry

logger = logging.getLogger(__name__)


@registry.register("governance", "allowlist_perms", "1.0")
class AllowlistPermissions(Plugin):
    """allowlist 权限模型 + 审计日志。

    Args:
        tools: 允许的工具名列表（默认允许所有内置工具）
        audit_log: 审计日志文件路径（空则仅内存记录）
    """

    domain = "governance"
    name = "allowlist_perms"
    version = "1.0"
    metadata = {
        "cost": "low",
        "context_save": "low",
        "capabilities": ["permission", "audit"],
        "description": "allowlist 权限模型 + 审计日志",
    }

    def __init__(
        self,
        tools: list[str] | None = None,
        audit_log: str = "",
    ):
        # 默认允许所有内置工具
        self.allowed = set(tools) if tools else {
            "read_file", "write_file", "run_bash", "list_files",
        }
        self.audit_log = audit_log
        self._audit_entries: list[dict] = []

    def check_permission(self, tool: str, args: dict) -> bool:
        """权限校验：tool 必须在 allowlist 中。"""
        allowed = tool in self.allowed
        if not allowed:
            logger.warning(
                "Permission denied for tool '%s' (not in allowlist: %s)",
                tool, sorted(self.allowed),
            )
        return allowed

    def audit(self, action: str, detail: dict) -> None:
        """记录审计日志。

        Args:
            action: 动作名（如 "tool_call" / "permission_denied"）
            detail: 详情字典
        """
        entry = {"action": action, "detail": detail}
        self._audit_entries.append(entry)

        if self.audit_log:
            try:
                p = Path(self.audit_log)
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(p, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception:
                logger.debug("Failed to write audit log", exc_info=True)

    def entries(self) -> list[dict]:
        """返回当前内存中的审计条目（测试/查看用）。"""
        return list(self._audit_entries)
