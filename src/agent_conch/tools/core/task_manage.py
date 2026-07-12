"""T 层核心工具: task_manage — 后台任务管理."""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from agent_conch.tools.base import BaseTool, ToolResult


class TaskManageInput(BaseModel):
    action: str = Field(
        ...,
        description="Action: 'create' | 'status' | 'wait' | 'cancel' | 'list'",
    )
    task_id: str | None = Field(None, description="Task ID (for status/wait/cancel)")
    command: str | None = Field(
        None, description="Shell command to run as background task (for 'create')"
    )
    timeout: int = Field(300, description="Task timeout in seconds (for 'create')")


@dataclass
class BackgroundTask:
    """后台任务."""

    id: str
    command: str
    status: str = "running"  # running | completed | error | cancelled | timeout
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    created_at: float = field(default_factory=lambda: __import__("time").time())
    finished_at: float | None = None


class TaskManageTool(BaseTool):
    """后台任务管理工具.

    创建/查询/等待/取消后台异步任务.
    用于长时间运行的命令 (构建、测试等).
    """

    name = "task_manage"
    description = (
        "Manage background tasks. Create long-running commands, check their status, "
        "wait for completion, or cancel them. Useful for builds, tests, and watch processes."
    )
    input_model = TaskManageInput
    is_write_tool = True
    is_core = True
    tags = ["task", "background", "async"]

    def __init__(self):
        self._tasks: dict[str, BackgroundTask] = {}
        self._async_tasks: dict[str, asyncio.Task] = {}

    async def execute(self, **kwargs: Any) -> ToolResult:
        validated = TaskManageInput(**kwargs)

        if validated.action == "create":
            return await self._create_task(validated.command or "", validated.timeout)
        elif validated.action == "status":
            return self._get_status(validated.task_id or "")
        elif validated.action == "wait":
            return await self._wait_task(validated.task_id or "", validated.timeout)
        elif validated.action == "cancel":
            return await self._cancel_task(validated.task_id or "")
        elif validated.action == "list":
            return self._list_tasks()
        else:
            return ToolResult.error(f"Unknown action: {validated.action}")

    async def _create_task(self, command: str, timeout: int) -> ToolResult:
        if not command:
            return ToolResult.error("command is required for 'create' action")

        task_id = str(uuid.uuid4())[:8]
        bg_task = BackgroundTask(id=task_id, command=command)
        self._tasks[task_id] = bg_task

        # 启动后台任务
        async def _run():
            try:
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                bg_task._proc = proc  # type: ignore[attr-defined]
                try:
                    stdout, stderr = await asyncio.wait_for(
                        proc.communicate(), timeout=timeout
                    )
                    bg_task.stdout = stdout.decode("utf-8", errors="replace")
                    bg_task.stderr = stderr.decode("utf-8", errors="replace")
                    bg_task.exit_code = proc.returncode
                    bg_task.status = "completed" if proc.returncode == 0 else "error"
                except TimeoutError:
                    proc.kill()
                    bg_task.status = "timeout"
                    bg_task.stderr = f"Task timed out after {timeout}s"
            except Exception as e:
                bg_task.status = "error"
                bg_task.stderr = str(e)
            finally:
                import time

                bg_task.finished_at = time.time()

        self._async_tasks[task_id] = asyncio.create_task(_run())

        return ToolResult(
            content=f"Background task created: {task_id}\nCommand: {command}",
            metadata={"task_id": task_id, "command": command},
        )

    def _get_status(self, task_id: str) -> ToolResult:
        task = self._tasks.get(task_id)
        if task is None:
            return ToolResult.error(f"Task not found: {task_id}")

        content = f"Task {task_id}: {task.status}\nCommand: {task.command}"
        if task.exit_code is not None:
            content += f"\nExit code: {task.exit_code}"
        if task.stdout:
            preview = task.stdout[:500]
            if len(task.stdout) > 500:
                preview += "..."
            content += f"\nstdout: {preview}"
        if task.stderr:
            preview = task.stderr[:500]
            if len(task.stderr) > 500:
                preview += "..."
            content += f"\nstderr: {preview}"

        return ToolResult(content=content, metadata={"task_id": task_id, "status": task.status})

    async def _wait_task(self, task_id: str, timeout: int) -> ToolResult:
        task = self._tasks.get(task_id)
        if task is None:
            return ToolResult.error(f"Task not found: {task_id}")

        async_task = self._async_tasks.get(task_id)
        if async_task and not async_task.done():
            try:
                await asyncio.wait_for(async_task, timeout=timeout)
            except TimeoutError:
                return ToolResult(
                    content=f"Task {task_id} still running after {timeout}s",
                    metadata={"task_id": task_id, "status": "still_running"},
                )

        return self._get_status(task_id)

    async def _cancel_task(self, task_id: str) -> ToolResult:
        task = self._tasks.get(task_id)
        if task is None:
            return ToolResult.error(f"Task not found: {task_id}")

        async_task = self._async_tasks.get(task_id)
        if async_task and not async_task.done():
            async_task.cancel()
            try:
                await async_task
            except asyncio.CancelledError:
                pass

        task.status = "cancelled"
        return ToolResult(
            content=f"Task {task_id} cancelled",
            metadata={"task_id": task_id, "status": "cancelled"},
        )

    def _list_tasks(self) -> ToolResult:
        if not self._tasks:
            return ToolResult(content="No background tasks.", metadata={"count": 0})

        lines = [f"  {t.id}: {t.status} — {t.command[:60]}" for t in self._tasks.values()]
        return ToolResult(
            content=f"Background tasks ({len(lines)}):\n" + "\n".join(lines),
            metadata={"count": len(self._tasks)},
        )
