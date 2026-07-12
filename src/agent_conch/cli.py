"""CLI 入口.

设计文档要求:
- CLI: conch run / conch replay
- 使用 click 框架 + rich 终端渲染
"""
from __future__ import annotations

import asyncio
import sys

import click

from agent_conch import __version__
from agent_conch.config import ConchConfig


def _run_async(coro):
    """运行异步任务, 换用 SelectorEventLoop 避免 Windows SSL 清理报错."""
    import platform

    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(coro)

# rich 优雅降级: 不可用时退化为简单 print
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()

except ImportError:

    class _SimpleConsole:
        def print(self, *args, **kwargs):
            # rich 的 print 支持 Panel/Table 对象, 降级时直接 str()
            for arg in args:
                if hasattr(arg, "_plain"):
                    print(arg._plain)
                else:
                    print(arg)

    console = _SimpleConsole()

    class Panel:
        """rich.Panel 的简化替代."""

        def __init__(self, text: str, title: str = "", **kwargs):
            self._plain = f"=== {title} ===\n{text}" if title else text

    class Table:
        """rich.Table 的简化替代."""

        def __init__(self, title: str = "", **kwargs):
            self._title = title
            self._headers: list[str] = []
            self._rows: list[list[str]] = []

        def add_column(self, name: str, **kwargs):
            self._headers.append(name)

        def add_row(self, *values, **kwargs):
            self._rows.append([str(v) for v in values])

        def __str__(self):
            lines = [f"=== {self._title} ==="] if self._title else []
            if self._headers:
                lines.append("  ".join(self._headers))
                lines.append("-" * 40)
            for row in self._rows:
                lines.append("  ".join(row))
            return "\n".join(lines)

        @property
        def _plain(self):
            return str(self)


@click.group()
@click.version_option(__version__, prog_name="agent-conch")
def main() -> None:
    """Agent-Conch: 全栈通用 AI Agent Harness."""
    pass


@main.command()
@click.argument("user_input")
@click.option("--session-id", "-s", default=None, help="Session ID (auto-generated if omitted)")
@click.option("--config", "-c", "config_path", default=None, help="Path to conch.yaml")
@click.option("--cwd", default=None, help="Working directory")
@click.option("--model", "model_name", default=None, help="Override model name")
@click.option("--max-turns", default=None, type=int, help="Override max turns")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def run(
    user_input: str,
    session_id: str | None,
    config_path: str | None,
    cwd: str | None,
    model_name: str | None,
    max_turns: int | None,
    verbose: bool,
) -> None:
    """Run the agent with a user input.

    Example: conch run "Read README.md and summarize it"
    """
    config = ConchConfig.load(config_path)
    if model_name:
        config.model.name = model_name
    if max_turns:
        config.agent_loop.max_turns = max_turns

    from agent_conch.engine.conch_engine import ConchEngine

    engine = ConchEngine(config=config, cwd=cwd)

    if verbose:
        console.print(Panel(
            f"[bold]Agent-Conch v{__version__}[/bold]\n"
            f"Model: {config.model.name}\n"
            f"Max turns: {config.agent_loop.max_turns}\n"
            f"CWD: {engine.cwd}\n"
            f"Session: {session_id or 'auto'}",
            title="Configuration",
        ))

    try:
        result = _run_async(engine.run(user_input, session_id))

        # 输出结果
        console.print()
        if result.status == "completed":
            console.print(Panel(
                result.final_response or "(no response)",
                title=f"[green]✓ Completed[/green] (session: {result.session_id})",
            ))
        elif result.status == "max_turns":
            console.print(Panel(
                result.final_response or "(no response)",
                title=f"[yellow]⚠ Max turns reached[/yellow] (session: {result.session_id})",
            ))
        else:
            console.print(Panel(
                f"[red]Error:[/red] {result.error or 'Unknown error'}",
                title=f"[red]✗ Failed[/red] (session: {result.session_id})",
            ))

        # 统计信息
        stats = Table(title="Run Statistics", show_header=False)
        stats.add_column("key", style="dim")
        stats.add_column("value")
        stats.add_row("Turns", str(result.turn_count))
        stats.add_row("Tool calls", str(result.tool_calls_count))
        stats.add_row("Duration", f"{result.total_duration_ms}ms")
        stats.add_row("Session ID", result.session_id)
        console.print(stats)

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e!s}")
        if verbose:
            import traceback

            console.print(traceback.format_exc())
        sys.exit(1)
    finally:
        engine.close()


@main.command()
@click.argument("session_id_or_file")
@click.option("--config", "-c", "config_path", default=None, help="Path to conch.yaml")
def replay(session_id_or_file: str, config_path: str | None) -> None:
    """Replay a trajectory by session ID or JSONL file.

    Example: conch replay abc123def456
    Example: conch replay ~/.agent-conch/trajectories/abc123.jsonl
    """
    config = ConchConfig.load(config_path)

    from agent_conch.engine.conch_engine import ConchEngine

    engine = ConchEngine(config=config)
    try:
        output = _run_async(engine.replay(session_id_or_file))
        console.print(output)
    except Exception as e:
        console.print(f"[red]Replay error:[/red] {e!s}")
        sys.exit(1)
    finally:
        engine.close()


@main.command()
@click.option("--config", "-c", "config_path", default=None, help="Path to conch.yaml")
def tools(config_path: str | None) -> None:
    """List registered tools."""
    config = ConchConfig.load(config_path)

    from agent_conch.engine.conch_engine import ConchEngine

    engine = ConchEngine(config=config)
    try:
        table = Table(title="Registered Tools")
        table.add_column("Name", style="cyan")
        table.add_column("Core", justify="center")
        table.add_column("Write", justify="center")
        table.add_column("Dangerous", justify="center")
        table.add_column("Tags", style="dim")
        table.add_column("Description")

        for name in sorted(engine.tool_registry.list_names()):
            tool = engine.tool_registry.get(name)
            if tool:
                table.add_row(
                    tool.name,
                    "✓" if tool.is_core else "",
                    "✓" if tool.is_write_tool else "",
                    "⚠" if tool.is_dangerous else "",
                    ", ".join(tool.tags),
                    tool.description[:80] + "..." if len(tool.description) > 80 else tool.description,
                )

        console.print(table)
    finally:
        engine.close()


@main.command()
@click.option("--config", "-c", "config_path", default=None, help="Path to conch.yaml")
def health(config_path: str | None) -> None:
    """Check tool health status."""
    config = ConchConfig.load(config_path)

    from agent_conch.engine.conch_engine import ConchEngine

    engine = ConchEngine(config=config)
    try:
        health_status = engine.get_tool_health()

        table = Table(title="Tool Health Status")
        table.add_column("Tool", style="cyan")
        table.add_column("Available", justify="center")
        table.add_column("Failures", justify="right")
        table.add_column("Suppressed", justify="center")

        for name, status in sorted(health_status.items()):
            avail_color = "green" if status["available"] else "red"
            supp_color = "red" if status["suppressed"] else "green"
            table.add_row(
                name,
                f"[{avail_color}]{'✓' if status['available'] else '✗'}[/{avail_color}]",
                str(status["consecutive_failures"]),
                f"[{supp_color}]{'⚠' if status['suppressed'] else 'ok'}[/{supp_color}]",
            )

        console.print(table)
    finally:
        engine.close()


@main.command()
@click.option("--config", "-c", "config_path", default=None, help="Path to conch.yaml")
def config(config_path: str | None) -> None:
    """Show current configuration."""
    cfg = ConchConfig.load(config_path)

    console.print(Panel(
        f"[bold]Model:[/bold] {cfg.model.name} (provider: {cfg.model.provider})\n"
        f"[bold]Max turns:[/bold] {cfg.agent_loop.max_turns}\n"
        f"[bold]Max time:[/bold] {cfg.agent_loop.max_time}s\n"
        f"[bold]Sandbox mode:[/bold] {cfg.sandbox.mode}\n"
        f"[bold]Sandbox backend:[/bold] {cfg.sandbox.default_backend}\n"
        f"[bold]Storage:[/bold] {cfg.state.storage_path}\n"
        f"[bold]DB:[/bold] {cfg.state.db_path}\n"
        f"[bold]Layers:[/bold] {', '.join(cfg.layers.enabled)}\n"
        f"[bold]Parallel tools:[/bold] {cfg.tools.parallel_execution}\n"
        f"[bold]ToolSearch threshold:[/bold] {cfg.tools.tool_search_threshold}",
        title="Agent-Conch Configuration",
    ))


if __name__ == "__main__":
    main()
