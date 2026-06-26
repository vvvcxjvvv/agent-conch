"""AgentConch CLI 入口。

用法:
    python -m conch run --profile <name> --task <desc>
    python -m conch experiment --suite swe-mini --profiles <p1> <p2>
    python -m conch plugins [--domain <domain>]

子命令:
    run         执行单个任务
    experiment  运行实验对比（多 Profile × 任务集）
    plugins     列出已注册插件
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

logger = logging.getLogger("conch")


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _ensure_domains_loaded() -> None:
    """导入所有域子模块，触发 @registry.register 装饰器执行。"""
    import conch.domains  # noqa: F401  — 各域 __init__.py 会导入子模块


def cmd_run(args: argparse.Namespace) -> int:
    """执行单个任务。"""
    _ensure_domains_loaded()

    from conch.core.loop import AgentLoop, TaskStatus
    from conch.core.profile import ProfileLoader
    from conch.core.registry import registry
    from conch.runtime.model.base import MockProvider

    loader = ProfileLoader(args.profiles_dir)
    profile = loader.load(args.profile)

    # MVP 未接入真实 LLM SDK，默认用 MockProvider
    if args.mock:
        model = MockProvider(response=args.mock_response or "[mock response]")
        logger.info("Using MockProvider with custom response")
    else:
        logger.warning("No real LLM provider configured, using MockProvider")
        model = MockProvider(response="[no real LLM configured]")

    loop = AgentLoop(profile=profile, registry=registry, model=model)
    state = asyncio.run(loop.run(args.task))

    # 输出结果
    print("\n=== Task Result ===")
    print(f"Status:    {state.status.value}")
    print(f"Steps:     {state.steps}")
    print(f"Tokens:    {state.total_tokens}")
    print(f"Cost:      ${state.total_cost:.4f}")
    if state.degrade_level.value > 0:
        print(f"Degrade:   {state.degrade_level.name}")
    if state.error:
        print(f"Error:     {state.error}")
    if state.result:
        print(f"Result:    {state.result}")
    return 0 if state.status == TaskStatus.DONE else 1


def cmd_experiment(args: argparse.Namespace) -> int:
    """运行实验对比。"""
    _ensure_domains_loaded()

    from conch.core.experiment import run_experiment

    result = asyncio.run(
        run_experiment(
            task_suite=args.suite,
            profiles=args.profiles,
            profiles_dir=args.profiles_dir,
        )
    )

    print(f"\n=== Experiment Result (suite: {result.task_suite}) ===")
    print(f"Tasks: {len(result.results)} | Profiles: {len(args.profiles)}\n")
    print(result.comparison_table())
    return 0


def cmd_plugins(args: argparse.Namespace) -> int:
    """列出已注册的插件。"""
    _ensure_domains_loaded()

    from conch.core.extension import DOMAINS
    from conch.core.registry import registry

    for domain in DOMAINS:
        if args.domain and domain != args.domain:
            continue
        names = registry.list(domain)
        print(f"[{domain}] ({len(names)} plugins)")
        for name in names:
            # 尝试获取版本信息
            versions = list(registry._domains[domain][name].keys())
            ver_str = ", ".join(versions) if versions else "?"
            print(f"  - {name} (v{ver_str})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="conch",
        description="AgentConch — Agent Harness Engineering 实验平台",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="详细日志")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # run 子命令
    p_run = sub.add_parser("run", help="执行单个任务")
    p_run.add_argument("--profile", required=True, help="Profile 名")
    p_run.add_argument("--task", required=True, help="任务描述")
    p_run.add_argument("--profiles-dir", default="profiles", help="Profile 目录")
    p_run.add_argument("--mock", action="store_true", help="使用 MockProvider")
    p_run.add_argument(
        "--mock-response", default=None, help="Mock 响应内容（--mock 时生效）"
    )
    p_run.set_defaults(func=cmd_run)

    # experiment 子命令
    p_exp = sub.add_parser("experiment", help="运行实验对比")
    p_exp.add_argument("--suite", required=True, help="任务集（swe-mini / 路径）")
    p_exp.add_argument(
        "--profiles", nargs="+", required=True, help="要对比的 Profile 列表"
    )
    p_exp.add_argument("--profiles-dir", default="profiles", help="Profile 目录")
    p_exp.set_defaults(func=cmd_experiment)

    # plugins 子命令
    p_plg = sub.add_parser("plugins", help="列出已注册插件")
    p_plg.add_argument("--domain", default=None, help="按域过滤")
    p_plg.set_defaults(func=cmd_plugins)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        logger.exception("Command failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
