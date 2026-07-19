from __future__ import annotations

import asyncio
import stat
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent_conch.api.server import create_app
from agent_conch.config import ConchConfig
from agent_conch.engine.conch_engine import ConchEngine
from agent_conch.hooks.executor import HookExecutor, HookSpec
from agent_conch.sandbox.docker import DockerBackend, DockerConfig
from agent_conch.sandbox.local import CommandResult
from agent_conch.sandbox.network_policy import NetworkPolicy
from agent_conch.sandbox.ssh import SSHBackend, SSHConfig
from agent_conch.security.content_safety import ContentSafetyGuard
from agent_conch.state.session_db import SessionDB
from agent_conch.tools.base import ToolResult
from agent_conch.tools.mcp_client import MCPClient, MCPServerSpec, MCPToolAdapter
from agent_conch.tools.output_manager import ToolOutputManager


def test_network_policy_supports_wildcards_and_cidr() -> None:
    policy = NetworkPolicy(True, ["*.example.com", "10.0.0.0/8"])
    assert policy.evaluate_url("https://api.example.com/data").allowed
    assert policy.evaluate_url("http://10.2.3.4/health").allowed
    assert not policy.evaluate_url("https://example.net").allowed
    with pytest.raises(PermissionError):
        policy.require_url("file:///etc/passwd")


def test_content_safety_blocks_secret_egress_and_redacts_outputs() -> None:
    guard = ContentSafetyGuard()
    secret = "sk-1234567890abcdef"
    decision = guard.evaluate_arguments({"url": "https://example.com", "token": secret}, "network")
    assert not decision.allowed
    sanitized = guard.sanitize_result(
        ToolResult("token=" + secret, metadata={"authorization": "Bearer abcdefghijklmnop"})
    )
    assert secret not in sanitized.content
    assert "[REDACTED:api_key]" in sanitized.content
    assert "Bearer abcdefghijklmnop" not in str(sanitized.metadata)


def test_tool_output_is_offloaded_with_private_permissions(tmp_path: Path) -> None:
    manager = ToolOutputManager(tmp_path, max_chars=10, preview_chars=4)
    result = manager.process("bash", "session/one", ToolResult("0123456789ABCDEF"))
    artifact = Path(str(result.metadata["artifact_path"]))
    assert result.metadata["offloaded"] is True
    assert artifact.read_text(encoding="utf-8") == "0123456789ABCDEF"
    assert stat.S_IMODE(artifact.stat().st_mode) == 0o600
    assert result.content.startswith("0123")


async def test_hook_executor_persists_and_honors_fail_closed(tmp_db: SessionDB) -> None:
    calls: list[str] = []

    async def runner(
        command: str, cwd: str | None, timeout: int, env: dict[str, str]
    ) -> CommandResult:
        calls.append(command)
        return CommandResult(command, "", "failed", 1, 2, cwd=cwd or "")

    executor = HookExecutor(
        tmp_db,
        runner,
        [
            HookSpec("gate", "graph_start", "false", fail_closed=True),
            HookSpec("never", "graph_start", "echo never"),
        ],
    )
    results = await executor.run_event("graph_start", "session-1")
    assert calls == ["false"]
    assert results[0][1].status == "failed"
    assert executor.list_executions("session-1")[0].hook_name == "gate"


async def test_mcp_adapter_exposes_schema_and_delegates_call() -> None:
    class FakeClient:
        async def call_tool(
            self, server: str, tool: str, arguments: dict[str, Any]
        ) -> ToolResult:
            return ToolResult(f"{server}/{tool}:{arguments['value']}")

    adapter = MCPToolAdapter(
        FakeClient(),  # type: ignore[arg-type]
        "local server",
        "echo",
        "Echo input",
        {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
        {"readOnlyHint": True},
    )
    assert adapter.name == "mcp__local_server__echo"
    assert adapter.to_schema()["parameters"]["required"] == ["value"]
    assert adapter.governance_action == "network"
    assert not adapter.is_write_tool
    assert (await adapter.execute(value="ok")).content == "local server/echo:ok"
    with pytest.raises(ValueError):
        adapter.validate_input()


async def test_mcp_stdio_lifecycle_and_real_tool_call(tmp_path: Path) -> None:
    server = tmp_path / "server.py"
    server.write_text(
        "from mcp.server.fastmcp import FastMCP\n"
        "app = FastMCP('test')\n"
        "@app.tool()\n"
        "def echo(value: str) -> str:\n"
        "    return value\n"
        "if __name__ == '__main__':\n"
        "    app.run(transport='stdio')\n",
        encoding="utf-8",
    )
    client = MCPClient([MCPServerSpec("test", sys.executable, [str(server)])])
    try:
        connection = await client.connect("test")
        assert connection.tools[0]["name"] == "echo"
        result = await client.adapters("test")[0].execute(value="round-trip")
        assert result.content == "round-trip"
    finally:
        await client.close_all()
    assert client.connections == {}


async def test_docker_backend_adds_gvisor_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    arguments: list[str] = []

    class Process:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"container-id\n", b""

    async def create(*args: str, **kwargs: Any) -> Process:
        arguments.extend(args)
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    backend = DockerBackend(DockerConfig(runtime="runsc"))
    assert await backend._create_container("s1") == "container-id"
    assert arguments[arguments.index("--runtime") + 1] == "runsc"


def test_ssh_backend_uses_strict_host_key_and_validates_roots() -> None:
    backend = SSHBackend(
        SSHConfig(
            host="example.com",
            user="agent",
            port=2222,
            strict_host_key=True,
            work_dir="/workspace",
            allowed_roots=["/workspace"],
        )
    )
    command = backend._base_command()
    assert "StrictHostKeyChecking=yes" in command
    assert command[-1] == "agent@example.com"
    assert backend.fs._validate("/workspace/src/main.py", "read") == "/workspace/src/main.py"  # type: ignore[attr-defined]
    assert backend.fs._validate("src/main.py", "read") == "/workspace/src/main.py"  # type: ignore[attr-defined]
    with pytest.raises(PermissionError):
        backend.fs._validate("/etc/passwd", "read")  # type: ignore[attr-defined]


def test_management_api_exposes_sessions_tools_skills_mcp_and_hooks(tmp_path: Path) -> None:
    config = ConchConfig()
    config.state.storage_dir = str(tmp_path / "state")
    engine = ConchEngine(config, cwd=str(tmp_path))
    engine.session_db.create_session("session-1", cwd=str(tmp_path))
    engine.session_db.add_message("session-1", "assistant", "done")
    client = TestClient(create_app(engine))
    try:
        assert client.get("/sessions").json()[0]["id"] == "session-1"
        assert client.get("/sessions/session-1/messages").json()[0]["content"] == "done"
        assert "schemas" in client.get("/tools").json()
        assert client.get("/skills").status_code == 200
        assert client.get("/mcp/servers").status_code == 200
        assert client.get("/hooks/executions").status_code == 200
    finally:
        engine.close()
