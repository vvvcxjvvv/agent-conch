"""L 层: ConchEngine — 顶层编排器.

设计文档要求:
- ConchEngine: 交互编排器, 组装所有子系统
- 统一入口: run() / replay()

职责:
1. 初始化 SessionDB / SandboxRegistry / ToolRegistry / LayerManager
2. 注册 12 核心工具
3. 生成 System Prompt
4. 创建 AgentLoop + BuiltinConchRuntime
5. 提供 run() / replay() 接口
"""

from __future__ import annotations

import os
import uuid
from typing import Any

from agent_conch.config import ConchConfig
from agent_conch.engine.agent_loop import AgentLoop
from agent_conch.engine.layers.base import LayerManager
from agent_conch.engine.layers.execution_limits import ExecutionLimitsLayer
from agent_conch.engine.runtime.builtin import BuiltinConchRuntime
from agent_conch.engine.runtime.types import AgentResult, RuntimeConfig
from agent_conch.prompts.agents_md import discover_agents_md
from agent_conch.prompts.system_prompt import build_system_prompt
from agent_conch.sandbox.local import LocalBackend
from agent_conch.sandbox.path_validator import PathValidator
from agent_conch.sandbox.registry import SandboxRegistry
from agent_conch.state.session_db import SessionDB
from agent_conch.state.trajectory import TrajectoryStore
from agent_conch.tools.core.ask_user import AskUserTool
from agent_conch.tools.core.bash import BashTool
from agent_conch.tools.core.edit_file import EditFileTool
from agent_conch.tools.core.glob import GlobTool
from agent_conch.tools.core.grep import GrepTool
from agent_conch.tools.core.read_file import ReadFileTool
from agent_conch.tools.core.skill import SkillTool
from agent_conch.tools.core.task_manage import TaskManageTool
from agent_conch.tools.core.tool_search import ToolSearchTool
from agent_conch.tools.core.web_fetch import WebFetchTool
from agent_conch.tools.core.web_search import WebSearchTool
from agent_conch.tools.core.write_file import WriteFileTool
from agent_conch.tools.footprint import FootprintLadder
from agent_conch.tools.registry import ToolRegistry
from agent_conch.tools.tool_policy import ToolPolicy
from agent_conch.tools.tool_search import ToolSearch


class ConchEngine:
    """Agent-Conch 顶层引擎.

    使用方式:
        engine = ConchEngine(config)
        result = await engine.run("帮我读取 README.md 并总结")
    """

    def __init__(self, config: ConchConfig | None = None, cwd: str | None = None):
        self.config = config or ConchConfig.load()
        self.cwd = cwd or os.getcwd()

        # 确保存储目录
        self.config.ensure_storage()

        # === S 层: 状态存储 ===
        self.session_db = SessionDB(self.config.state.db_path)
        self.trajectory_store = TrajectoryStore(self.session_db, self.config.state.trajectory_path)

        # === E 层: 沙箱 ===
        path_validator = PathValidator(
            allowed_roots=self.config.sandbox.allowed_roots or [self.cwd],
            user_sensitive_paths=self.config.sandbox.sensitive_paths,
            cwd=self.cwd,
        )
        self.local_backend = LocalBackend(validator=path_validator, default_cwd=self.cwd)
        self.sandbox_registry = SandboxRegistry(mode=self.config.sandbox.mode)
        self.sandbox_registry.register("local", self.local_backend)
        self.sandbox_registry.set_default(self.config.sandbox.default_backend)

        # === T 层: 工具系统 ===
        self.tool_policy = ToolPolicy()
        self.tool_registry = ToolRegistry(
            policy=self.tool_policy,
            check_ttl=self.config.tools.check_fn_ttl,
            transient_suppress=self.config.tools.transient_suppress,
        )

        self.tool_search = ToolSearch(
            registry=self.tool_registry,
            auto_threshold=self.config.tools.tool_search_threshold,
        )
        self.footprint_ladder = FootprintLadder()

        self._register_core_tools()

        # === L 层: Layer ===
        self.layer_manager = LayerManager()
        self._setup_layers()

        # === Prompt ===
        agents_md = discover_agents_md(self.cwd) if self.config.prompt.discover_agents_md else ""
        self.system_prompt = build_system_prompt(
            mode=self.config.prompt.system_prompt_mode,
            cwd=self.cwd,
            env_info=self._collect_env_info(),
            agents_md=agents_md,
        )

        # === C 层: Context Engine + 压缩 + Caching + Skill + Memory (P2) ===
        from agent_conch.context.compact.pipeline import ContextCompressor
        from agent_conch.context.engine import (
            LegacyEngine,
            SimpleTokenCounter,
            TokenBudget,
        )
        from agent_conch.context.memory.manager import MemoryManager
        from agent_conch.context.prompt_caching import PromptCaching
        from agent_conch.context.skills.registry import SkillInjector, SkillLoader

        self.token_counter = SimpleTokenCounter()
        self.context_compressor = ContextCompressor(
            token_counter=self.token_counter,
            llm_caller=self._call_auxiliary_model,
        )

        # Prompt Caching (Anthropic 支持 cache_control, 其他 no-op)
        model_provider = (
            self.config.model.name.split("/")[0] if "/" in self.config.model.name else ""
        )
        self.prompt_caching = PromptCaching(
            enabled=self.config.agent_loop.auto_compact,
            provider=model_provider,
        )

        # Skill 体系
        self.skill_loader = SkillLoader(
            cwd=self.cwd,
            bundled_dir=os.path.join(os.path.dirname(__file__), "..", "..", "..", "skills"),
        )
        self.skills = self.skill_loader.load_all()
        self.skill_injector = SkillInjector(self.skills)
        # 注入匹配的 skills 到 system prompt
        self.system_prompt = self.skill_injector.inject(
            self.system_prompt, query="agent coding tools"
        )

        # 分层记忆
        self.memory_manager = MemoryManager(
            db=self.session_db,
            memory_dir=str(self.config.state.storage_path / "memory"),
        )
        self.context_engine = LegacyEngine(
            db=self.session_db,
            system_prompt=self.system_prompt,
            token_counter=self.token_counter,
            compressor=self.context_compressor,
            memory_manager=self.memory_manager,
            llm_caller=self._call_auxiliary_model,
            auto_compact=self.config.agent_loop.auto_compact,
            token_budget=TokenBudget(
                reserved_for_response=self.config.model.max_tokens,
            ),
        )

        # === S 层: Checkpoint (P2) ===
        from agent_conch.state.checkpoint import CheckpointManager

        self.checkpoint_manager = CheckpointManager(self.session_db)

        # === L 层: Subagent (P2) ===
        from agent_conch.multiagent.subagent import SubagentManager

        self.subagent_manager = SubagentManager(self.session_db)

        # === Runtime ===
        runtime_config = RuntimeConfig(
            name="builtin",
            max_turns=self.config.agent_loop.max_turns,
            max_time=self.config.agent_loop.max_time,
            parallel_tools=self.config.tools.parallel_execution,
            model_name=self.config.model.name,
            temperature=self.config.model.temperature,
            max_tokens=self.config.model.max_tokens,
        )

        self.agent_loop = AgentLoop(
            config=runtime_config,
            session_db=self.session_db,
            tool_registry=self.tool_registry,
            trajectory_store=self.trajectory_store,
            layers=self.layer_manager,
            system_prompt=self.system_prompt,
            sandbox_mode=self.config.sandbox.mode,
            context_engine=self.context_engine,
            prompt_caching=self.prompt_caching,
        )

        self.runtime = BuiltinConchRuntime(runtime_config, self.agent_loop)

    def _register_core_tools(self) -> None:
        """注册 12 核心工具."""
        backend = self.sandbox_registry.get_backend(is_main=True)
        fs = backend.fs

        tools = [
            BashTool(backend),
            ReadFileTool(fs),
            WriteFileTool(fs),
            EditFileTool(fs),
            GlobTool(backend.validator),  # type: ignore[attr-defined]
            GrepTool(backend.validator),  # type: ignore[attr-defined]
            WebSearchTool(),
            WebFetchTool(),
            SkillTool(
                skills_dir=os.path.join(os.path.dirname(__file__), "..", "..", "..", "skills")
            ),
            AskUserTool(),
            TaskManageTool(),
            ToolSearchTool(self.tool_search),
        ]

        for tool in tools:
            self.tool_registry.register(tool)

    def _setup_layers(self) -> None:
        """配置 Layer."""
        for layer_name in self.config.layers.enabled:
            if layer_name == "execution_limits":
                self.layer_manager.add(
                    ExecutionLimitsLayer(
                        max_turns=self.config.agent_loop.max_turns,
                        max_time=self.config.agent_loop.max_time,
                    )
                )

    def _collect_env_info(self) -> str:
        """收集环境信息 (供 system prompt)."""
        import platform

        return (
            f"OS: {platform.system()} {platform.release()}\n"
            f"Python: {platform.python_version()}\n"
            f"Working directory: {self.cwd}\n"
            f"Model: {self.config.model.name}"
        )

    async def _call_auxiliary_model(self, messages: list[dict[str, Any]]) -> str:
        """执行不带工具的摘要/记忆辅助模型调用。"""
        import litellm

        response = await litellm.acompletion(
            model=self.config.model.name,
            messages=messages,
            temperature=0,
            max_tokens=min(1024, self.config.model.max_tokens),
            timeout=self.config.model.timeout,
        )
        return response.choices[0].message.content or ""

    async def run(self, user_input: str, session_id: str | None = None) -> AgentResult:
        """执行 Agent run.

        Args:
            user_input: 用户输入
            session_id: 会话 ID (None = 自动生成)

        Returns:
            AgentResult
        """
        if session_id is None:
            session_id = str(uuid.uuid4())[:12]

        return await self.runtime.run(session_id, user_input)

    async def replay(self, session_id_or_path: str) -> str:
        """回放轨迹."""
        steps = self.trajectory_store.replay(session_id_or_path)
        return self.trajectory_store.format_replay(steps)

    def get_tool_health(self) -> dict[str, Any]:
        """获取工具健康状态."""
        return self.tool_registry.get_health_status()

    def close(self) -> None:
        """关闭引擎, 释放资源."""
        self.session_db.close()
