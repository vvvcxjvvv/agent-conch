"""实验框架 — 对比多个 Profile 在同一任务集上的表现。

核心价值：量化不同 harness 配置对效果/成本的影响。
- 原生集成标准基准（SWE-bench / MT-Bench）
- 输出标准化对比报告
- 支持消融实验（逐个关闭能力域，量化边际贡献）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TaskResult:
    """单个任务执行结果。"""

    task_id: str
    profile_name: str
    success: bool = False
    steps: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    duration_sec: float = 0.0
    context_resets: int = 0
    degrade_level: int = 0
    error: str | None = None
    raw_state: Any = None


@dataclass
class ExperimentResult:
    """实验汇总结果。"""

    task_suite: str
    results: list[TaskResult] = field(default_factory=list)

    def summary_by_profile(self) -> dict[str, dict[str, float]]:
        """按 Profile 聚合统计。"""
        from collections import defaultdict

        groups: dict[str, list[TaskResult]] = defaultdict(list)
        for r in self.results:
            groups[r.profile_name].append(r)

        summary = {}
        for profile_name, group in groups.items():
            n = len(group)
            summary[profile_name] = {
                "success_rate": sum(1 for r in group if r.success) / n if n else 0,
                "avg_steps": sum(r.steps for r in group) / n if n else 0,
                "avg_tokens": sum(r.total_tokens for r in group) / n if n else 0,
                "avg_cost": sum(r.total_cost for r in group) / n if n else 0,
                "avg_duration": sum(r.duration_sec for r in group) / n if n else 0,
                "context_resets": sum(r.context_resets for r in group),
                "degrade_count": sum(1 for r in group if r.degrade_level > 0),
            }
        return summary

    def comparison_table(self) -> str:
        """生成 Markdown 对比表。"""
        summary = self.summary_by_profile()
        if not summary:
            return "No results."

        headers = ["Profile", "成功率", "平均步数", "平均Token", "平均成本", "平均耗时(s)", "Reset次数", "降级次数"]
        rows = []
        for name, metrics in summary.items():
            rows.append([
                name,
                f"{metrics['success_rate']:.1%}",
                f"{metrics['avg_steps']:.1f}",
                f"{metrics['avg_tokens']:.0f}",
                f"${metrics['avg_cost']:.4f}",
                f"{metrics['avg_duration']:.1f}",
                str(metrics["context_resets"]),
                str(metrics["degrade_count"]),
            ])

        lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
        for row in rows:
            lines.append("| " + " | ".join(row) + " |")
        return "\n".join(lines)


class TaskSuite:
    """任务集 — 可加载本地目录或标准基准。"""

    @staticmethod
    def from_dir(dir_path: str | Path) -> list[dict]:
        """从本地目录加载任务（每个 .json 一个任务）。"""
        dir_path = Path(dir_path)
        tasks = []
        for f in sorted(dir_path.glob("*.json")):
            import json

            with open(f, encoding="utf-8") as fh:
                task = json.load(fh)
                task.setdefault("task_id", f.stem)
                tasks.append(task)
        return tasks

    @staticmethod
    def swe_bench_lite() -> list[dict]:
        """加载 SWE-bench Lite 标准基准。

        实际实现需下载 SWE-bench 数据集。
        MVP 返回占位，阶段二接入真实数据集。
        """
        logger.info("SWE-bench Lite: returning placeholder tasks (real dataset TBD)")
        return [
            {"task_id": "swe-bench-lite-001", "task": "修复 hello.py 中的语法错误", "type": "code"},
            {"task_id": "swe-bench-lite-002", "task": "为 utils.py 添加单元测试", "type": "code"},
        ]

    @staticmethod
    def swe_mini() -> list[dict]:
        """自建精简代码集 — MVP 快速验证用。"""
        return [
            {"task_id": "swe-mini-001", "task": "修复 hello.py 中的语法错误", "type": "code"},
            {"task_id": "swe-mini-002", "task": "为 utils.py 添加单元测试", "type": "code"},
            {"task_id": "swe-mini-003", "task": "重构 main.py 拆分函数", "type": "code"},
        ]


async def run_experiment(
    task_suite: str | list[dict],
    profiles: list[str],
    metrics: list[str] | None = None,
    profiles_dir: str = "profiles",
) -> ExperimentResult:
    """运行实验：对比多个 Profile 在同一任务集上的表现。

    Args:
        task_suite: 任务集路径或 "swe-mini" / "swe-bench-lite"
        profiles: 要对比的 Profile 名列表
        metrics: 要计算的指标（默认全部）
        profiles_dir: Profile 目录

    Returns:
        ExperimentResult，含所有任务的详细结果
    """
    import time

    from conch.core.profile import ProfileLoader

    # 加载任务集
    if isinstance(task_suite, str):
        if task_suite == "swe-mini":
            tasks = TaskSuite.swe_mini()
        elif task_suite == "swe-bench-lite":
            tasks = TaskSuite.swe_bench_lite()
        else:
            tasks = TaskSuite.from_dir(task_suite)
    else:
        tasks = task_suite

    suite_name = task_suite if isinstance(task_suite, str) else "custom"
    result = ExperimentResult(task_suite=suite_name)

    loader = ProfileLoader(profiles_dir)

    for profile_name in profiles:
        profile = loader.load(profile_name)
        logger.info("Running profile '%s' on %d tasks", profile_name, len(tasks))

        for task in tasks:
            task_id = task.get("task_id", str(hash(str(task))))
            task_desc = task.get("task", str(task))

            # 构建 Loop 并执行（MVP: 无 model 的情况只走骨架）
            from conch.core.loop import AgentLoop, TaskStatus
            from conch.core.registry import registry

            loop = AgentLoop(profile=profile, registry=registry, model=None)
            start = time.time()
            state = await loop.run(task_desc)
            elapsed = time.time() - start

            result.results.append(TaskResult(
                task_id=task_id,
                profile_name=profile_name,
                success=state.status == TaskStatus.DONE,
                steps=state.steps,
                total_tokens=state.total_tokens,
                total_cost=state.total_cost,
                duration_sec=elapsed,
                degrade_level=state.degrade_level.value,
                error=str(state.error) if state.error else None,
                raw_state=state,
            ))

    return result


async def run_ablation(
    task_suite: str,
    base_profile: str,
    domains_to_ablate: list[str],
    profiles_dir: str = "profiles",
) -> ExperimentResult:
    """消融实验：逐个关闭能力域，量化边际贡献。

    Args:
        task_suite: 任务集
        base_profile: 基准 Profile
        domains_to_ablate: 要逐个关闭的域名列表
    """
    from conch.core.profile import ProfileLoader

    loader = ProfileLoader(profiles_dir)
    base = loader.load(base_profile)

    profiles_to_run = [base_profile]
    # 动态生成消融配置（运行时从 base 移除某域）
    # MVP: 通过 Profile 名约定，实际可动态生成临时 Profile
    for domain in domains_to_ablate:
        profiles_to_run.append(f"{base_profile}-no-{domain}")

    return await run_experiment(task_suite, profiles_to_run, profiles_dir=profiles_dir)
