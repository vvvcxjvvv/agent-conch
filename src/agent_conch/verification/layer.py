"""V 层：写工具执行后的自动 lint/type-check/test 质量门禁。"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from agent_conch.engine.layers.base import Layer, NodeContext
from agent_conch.sandbox.local import CommandResult
from agent_conch.verification.regression import RegressionStore
from agent_conch.verification.report import (
    VerificationCheck,
    VerificationReport,
    VerificationStore,
)

CommandRunner = Callable[[str, str | None, int], Awaitable[CommandResult]]


class VerificationLayer(Layer):
    """仅在成功写操作后触发，失败结果注入下一轮让 Agent 修复。"""

    name = "verification"
    WRITE_TOOLS = {"write_file", "edit_file"}

    def __init__(
        self,
        store: VerificationStore,
        runner: CommandRunner,
        commands: list[str] | None = None,
        cwd: str | None = None,
        timeout: int = 120,
        regression_store: RegressionStore | None = None,
        auto_capture_regressions: bool = True,
    ) -> None:
        self.store = store
        self.runner = runner
        self.commands = commands or []
        self.cwd = cwd
        self.timeout = timeout
        self.regression_store = regression_store
        self.auto_capture_regressions = auto_capture_regressions

    async def on_node_run_end(self, ctx: NodeContext, result: Any) -> None:
        records = list(result)
        wrote = any(
            getattr(record, "tool_name", "") in self.WRITE_TOOLS
            and getattr(record, "status", "") == "success"
            for record in records
        )
        if not wrote or not self.commands:
            return

        checks: list[VerificationCheck] = []
        for command in self.commands:
            started = time.time()
            command_result = await self.runner(command, self.cwd, self.timeout)
            checks.append(
                VerificationCheck(
                    name=command.split()[0],
                    command=command,
                    passed=command_result.exit_code == 0,
                    exit_code=command_result.exit_code,
                    output=(command_result.stdout + command_result.stderr)[-4000:],
                    duration_ms=int((time.time() - started) * 1000),
                )
            )
            if command_result.exit_code != 0:
                break

        claim = str((ctx.response or {}).get("content", ""))
        report = VerificationReport.create(ctx.session_id, ctx.turn_index, claim, checks)
        self.store.save(report)
        if not report.passed and self.regression_store is not None and self.auto_capture_regressions:
            regression_case = self.regression_store.capture(report)
            if regression_case is not None:
                ctx.metadata["regression_case_id"] = regression_case.case_id
        ctx.metadata["verification_report_id"] = report.report_id
        ctx.metadata["verification_passed"] = report.passed
        if not report.passed:
            failed = next(check for check in checks if not check.passed)
            ctx.inject_message(
                "Verification failed. Fix the issue before completing the task.\n"
                f"Command: {failed.command}\nOutput:\n{failed.output}"
            )
            ctx.block_progress("Verification quality gate failed")
