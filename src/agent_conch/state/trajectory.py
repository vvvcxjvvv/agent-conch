"""S 层: 轨迹持久化与回放.

记录策略:
- Trajectory JSONL 每步保存 + conch replay 回放
- SQLite 保存运行时状态(可查询), JSONL 导出用于审计/回放

轨迹同时保存到 SQLite，并可导出 JSONL 供审计和回放。
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agent_conch.state.session_db import SessionDB


@dataclass
class TrajectoryStep:
    """单步轨迹记录."""

    session_id: str
    turn_index: int
    step_type: str  # "llm_call" | "tool_call" | "tool_result" | "user_input"
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_output: str | None = None
    tool_status: str = "success"  # success | error | blocked
    duration_ms: int = 0
    token_usage: dict[str, int] | None = None  # {prompt, completion, total}
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


class TrajectoryStore:
    """轨迹存储: SQLite (可查询) + JSONL (可回放/审计).

    运行时轨迹写入 SQLite trajectories 表;
    会话结束时可选导出为 JSONL 文件供 conch replay 使用.
    """

    def __init__(self, db: SessionDB, trajectory_dir: str | Path):
        self.db = db
        self.trajectory_dir = Path(trajectory_dir)
        self.trajectory_dir.mkdir(parents=True, exist_ok=True)

    def save_step(self, step: TrajectoryStep) -> int:
        """保存单步轨迹到 SQLite."""
        step_data = asdict(step)
        # tool_output 可能很长, 存完整但标记截断状态
        if step.tool_output and len(step.tool_output) > 10000:
            step_data["tool_output_truncated"] = True
            step_data["tool_output_full_length"] = len(step.tool_output)
        return self.db.save_trajectory_step(
            session_id=step.session_id,
            turn_id=None,
            step_data=step_data,
        )

    def get_steps(self, session_id: str) -> list[TrajectoryStep]:
        """从 SQLite 加载轨迹步骤."""
        raw = self.db.get_trajectory(session_id)
        steps: list[TrajectoryStep] = []
        for item in raw:
            steps.append(TrajectoryStep(**item))
        return steps

    def export_jsonl(self, session_id: str) -> Path:
        """将会话轨迹导出为 JSONL 文件.

        文件路径: trajectory_dir/{session_id}.jsonl
        """
        steps = self.get_steps(session_id)
        out_path = self.trajectory_dir / f"{session_id}.jsonl"
        with open(out_path, "w", encoding="utf-8") as f:
            for step in steps:
                f.write(json.dumps(asdict(step), ensure_ascii=False) + "\n")
        return out_path

    def replay(self, session_id: str | Path) -> list[TrajectoryStep]:
        """回放轨迹.

        支持两种输入:
        - session_id: 从 SQLite 加载
        - .jsonl 文件路径: 从文件加载
        """
        path = Path(session_id) if isinstance(session_id, str) else session_id

        # 如果是 .jsonl 文件路径
        if str(path).endswith(".jsonl") and path.exists():
            steps: list[TrajectoryStep] = []
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        steps.append(TrajectoryStep(**json.loads(line)))
            return steps

        # 否则当作 session_id 从 DB 加载
        return self.get_steps(str(session_id))

    def format_replay(self, steps: list[TrajectoryStep]) -> str:
        """将轨迹步骤格式化为可读文本."""
        lines: list[str] = []
        for i, step in enumerate(steps, 1):
            ts = time.strftime("%H:%M:%S", time.localtime(step.timestamp))
            header = f"[{i}] {ts} turn={step.turn_index} {step.step_type}"
            if step.tool_name:
                header += f" tool={step.tool_name}"
            header += f" ({step.duration_ms}ms) {step.tool_status}"
            lines.append(header)

            if step.tool_input:
                input_str = json.dumps(step.tool_input, ensure_ascii=False)
                if len(input_str) > 200:
                    input_str = input_str[:200] + "..."
                lines.append(f"    input: {input_str}")

            if step.tool_output:
                output = step.tool_output
                if len(output) > 300:
                    output = output[:300] + "..."
                lines.append(f"    output: {output}")

            if step.token_usage:
                lines.append(f"    tokens: {step.token_usage}")

        return "\n".join(lines)
