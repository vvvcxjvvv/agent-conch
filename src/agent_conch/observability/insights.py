"""O 层：会话成功率、失败原因、Token 与工具耗时统计。"""

from __future__ import annotations

import json
from typing import Any

from agent_conch.state.session_db import SessionDB


class InsightsEngine:
    def __init__(self, db: SessionDB) -> None:
        self.db = db

    def summary(self) -> dict[str, Any]:
        sessions = self.db.conn.execute(
            "SELECT status, COUNT(*) AS count FROM sessions GROUP BY status"
        ).fetchall()
        status_counts = {str(row["status"]): int(row["count"]) for row in sessions}
        total = sum(status_counts.values())
        success = status_counts.get("completed", 0)

        steps = self.db.conn.execute("SELECT step_data FROM trajectories").fetchall()
        total_tokens = 0
        tool_duration_ms = 0
        tool_calls = 0
        failures: dict[str, int] = {}
        for row in steps:
            data = json.loads(row["step_data"])
            usage = data.get("token_usage") or {}
            total_tokens += int(usage.get("total", 0))
            if data.get("step_type") == "tool_call":
                tool_calls += 1
                tool_duration_ms += int(data.get("duration_ms", 0))
                if data.get("tool_status") == "error":
                    name = str(data.get("tool_name") or "unknown")
                    failures[name] = failures.get(name, 0) + 1

        return {
            "sessions": total,
            "status_counts": status_counts,
            "failure_reasons": {
                status: count for status, count in status_counts.items() if status != "completed"
            },
            "success_rate": success / total if total else 0.0,
            "total_tokens": total_tokens,
            "tool_calls": tool_calls,
            "average_tool_duration_ms": tool_duration_ms / tool_calls if tool_calls else 0.0,
            "tool_failures": failures,
        }
