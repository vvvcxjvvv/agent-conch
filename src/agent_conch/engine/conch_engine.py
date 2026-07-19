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
from dataclasses import asdict
from typing import Any

from agent_conch.api.approvals import Approval, WriteApprovalStore
from agent_conch.config import ConchConfig
from agent_conch.context.skills.curator import SkillCurator
from agent_conch.engine.agent_loop import AgentLoop
from agent_conch.engine.layers.base import Event, LayerManager, NodeContext
from agent_conch.engine.layers.execution_limits import ExecutionLimitsLayer
from agent_conch.engine.layers.llm_quota import LLMQuotaLayer
from agent_conch.engine.layers.suspend import PauseStatePersistLayer, SuspendLayer
from agent_conch.engine.runtime.builtin import BuiltinConchRuntime
from agent_conch.engine.runtime.types import AgentResult, RuntimeConfig
from agent_conch.governance.budget import BudgetLimits, BudgetManager, CostBudgetLayer
from agent_conch.governance.scheduler import CronScheduler
from agent_conch.hooks.executor import HookExecutor, HookExecutorLayer, HookSpec
from agent_conch.multiagent.coordinator import Coordinator, DecisionTable
from agent_conch.multiagent.subagent import SubagentRecord
from agent_conch.observability.decision_trace import DecisionTraceStore
from agent_conch.observability.events import EventBus
from agent_conch.observability.exit_status import classify_exit_status
from agent_conch.observability.insights import InsightsEngine
from agent_conch.observability.otel import ObservabilityLayer, OTelTracer
from agent_conch.observability.trace_store import TraceStore
from agent_conch.prompts.agents_md import discover_agents_md
from agent_conch.prompts.system_prompt import build_system_prompt
from agent_conch.sandbox.docker import DockerBackend, DockerConfig
from agent_conch.sandbox.local import LocalBackend
from agent_conch.sandbox.network_policy import NetworkPolicy
from agent_conch.sandbox.path_validator import PathValidator
from agent_conch.sandbox.registry import SandboxRegistry
from agent_conch.sandbox.snapshots import SnapshotManager
from agent_conch.sandbox.ssh import SSHBackend, SSHConfig
from agent_conch.security.audit import SecurityAudit
from agent_conch.security.content_safety import ContentSafetyGuard
from agent_conch.security.credentials import CredentialPool, CredentialRef
from agent_conch.security.permissions import RBAC, Permission
from agent_conch.security.policy_engine import PolicyEngine
from agent_conch.state.session_db import SessionDB
from agent_conch.state.trajectory import TrajectoryStep, TrajectoryStore
from agent_conch.tools.base import ToolCall, ToolExecutionRecord
from agent_conch.tools.core.ask_user import AskUserTool
from agent_conch.tools.core.bash import BashTool
from agent_conch.tools.core.edit_file import EditFileTool
from agent_conch.tools.core.glob import GlobTool
from agent_conch.tools.core.grep import GrepTool
from agent_conch.tools.core.read_file import ReadFileTool
from agent_conch.tools.core.session_search import SessionSearchTool
from agent_conch.tools.core.skill import SkillTool
from agent_conch.tools.core.task_manage import TaskManageTool
from agent_conch.tools.core.tool_search import ToolSearchTool
from agent_conch.tools.core.web_fetch import WebFetchTool
from agent_conch.tools.core.web_search import WebSearchTool
from agent_conch.tools.core.write_file import WriteFileTool
from agent_conch.tools.footprint import FootprintLadder
from agent_conch.tools.mcp_client import MCPClient, MCPServerSpec
from agent_conch.tools.output_manager import ToolOutputManager
from agent_conch.tools.registry import ToolRegistry
from agent_conch.tools.tool_policy import ToolPolicy
from agent_conch.tools.tool_search import ToolSearch
from agent_conch.verification.layer import VerificationLayer
from agent_conch.verification.regression import RegressionRunner, RegressionStore
from agent_conch.verification.report import VerificationStore
from agent_conch.verification.reviewer import Reviewer
from agent_conch.verification.self_review import SelfReview


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
        from agent_conch.state.checkpoint import CheckpointManager

        self.checkpoint_manager = CheckpointManager(self.session_db)

        # === O/V/G/S 层: 可观测、验证与 P4 治理 ===
        self.trace_store = TraceStore(self.session_db)
        self.decision_trace_store = DecisionTraceStore(self.session_db)
        self.otel_tracer = OTelTracer(self.trace_store)
        self.verification_store = VerificationStore(self.session_db)
        self.regression_store = RegressionStore(self.session_db)
        self.insights = InsightsEngine(self.session_db)
        self.event_bus = EventBus(self.session_db)
        self.security_audit = SecurityAudit()
        self.approval_store = WriteApprovalStore(self.session_db)
        self.rbac = RBAC()
        self.content_guard = ContentSafetyGuard(
            self.config.governance.content_safety_enabled,
            self.config.governance.redact_sensitive,
            self.config.governance.denied_content_patterns,
        )
        self.policy_engine = PolicyEngine.from_config(
            self.config.governance.policy_rules,
            self.config.governance.approval_level,
            self.content_guard,
        )
        budget_limits = BudgetLimits(
            max_tokens=self.config.budget.max_tokens,
            max_seconds=self.config.budget.max_seconds,
            max_tool_calls=self.config.budget.max_tool_calls,
            max_resource_units=self.config.budget.max_resource_units,
        )
        self.budget_manager = BudgetManager(self.session_db, budget_limits)
        credential_refs = [
            CredentialRef(
                alias=str(item["alias"]),
                provider=str(item["provider"]),
                reference=str(item["reference"]),
                backend=str(item.get("backend", "env")),
                priority=int(item.get("priority", 100)),
            )
            for item in self.config.credentials.entries
        ]
        if not any(item.provider == self.config.model.provider for item in credential_refs):
            credential_refs.append(
                CredentialRef(
                    alias="model-default",
                    provider=self.config.model.provider,
                    reference=self.config.model.api_key_env,
                    backend="env",
                    priority=100,
                )
            )
        self.credential_pool = CredentialPool(
            credential_refs,
            failure_cooldown=self.config.credentials.failure_cooldown,
        )
        self.output_manager = ToolOutputManager(
            self.config.state.storage_path / "tool-outputs",
            self.config.tools.output_max_chars,
            self.config.tools.output_preview_chars,
        )

        # === E 层: 沙箱 ===
        path_validator = PathValidator(
            allowed_roots=self.config.sandbox.allowed_roots or [self.cwd],
            user_sensitive_paths=self.config.sandbox.sensitive_paths,
            cwd=self.cwd,
        )
        self.local_backend = LocalBackend(validator=path_validator, default_cwd=self.cwd)
        self.network_policy = NetworkPolicy(
            self.config.sandbox.network_policy.enforce,
            self.config.sandbox.network_policy.allowlist,
        )
        self.sandbox_registry = SandboxRegistry(mode=self.config.sandbox.mode)
        self.sandbox_registry.register("local", self.local_backend)
        if self.config.sandbox.default_backend == "docker":
            docker = self.config.sandbox.docker
            self.sandbox_registry.register(
                "docker",
                DockerBackend(
                    DockerConfig(
                        image=docker.image,
                        memory_limit=docker.memory_limit,
                        cpu_limit=docker.cpu_limit,
                        network=docker.network,
                        runtime=docker.runtime,
                        volumes=docker.volumes,
                    )
                ),
            )
        if self.config.sandbox.default_backend == "ssh" or self.config.sandbox.ssh.host:
            ssh = self.config.sandbox.ssh
            self.sandbox_registry.register(
                "ssh",
                SSHBackend(
                    SSHConfig(
                        host=ssh.host,
                        user=ssh.user,
                        port=ssh.port,
                        identity_file=ssh.identity_file,
                        strict_host_key=ssh.strict_host_key,
                        connect_timeout=ssh.connect_timeout,
                        work_dir=ssh.work_dir,
                        allowed_roots=ssh.allowed_roots,
                    )
                ),
            )
        self.sandbox_registry.set_default(self.config.sandbox.default_backend)
        self.snapshot_manager = SnapshotManager(self.session_db, self.sandbox_registry)
        hook_specs = [HookSpec.from_dict(item) for item in self.config.hooks.commands]
        self.hook_executor = HookExecutor(self.session_db, self._run_hook, hook_specs)

        # === T 层: 工具系统 ===
        self.tool_policy = ToolPolicy()
        self.tool_registry = ToolRegistry(
            policy=self.tool_policy,
            check_ttl=self.config.tools.check_fn_ttl,
            transient_suppress=self.config.tools.transient_suppress,
            governance=self.policy_engine if self.config.governance.enabled else None,
            approvals=self.approval_store,
            budgets=self.budget_manager,
            default_role=self.config.governance.default_role,
            content_guard=self.content_guard,
            output_manager=self.output_manager,
        )

        self.tool_search = ToolSearch(
            registry=self.tool_registry,
            auto_threshold=self.config.tools.tool_search_threshold,
        )
        self.footprint_ladder = FootprintLadder()

        self._register_core_tools()
        self.mcp_client = MCPClient(
            [MCPServerSpec.from_dict(item) for item in self.config.mcp.servers]
        )
        self._mcp_initialized = False
        self._mcp_tool_names: set[str] = set()

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
        self.skill_curator = SkillCurator(
            self.session_db,
            self.config.state.storage_path / "skills-archive",
        )

        # 分层记忆
        self.memory_manager = MemoryManager(
            db=self.session_db,
            memory_dir=str(self.config.state.storage_path / "memory"),
        )
        self.tool_registry.register(SessionSearchTool(self.memory_manager.meta_memory))
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

        # === L 层: Subagent (P2) ===
        from agent_conch.multiagent.subagent import SubagentManager

        self.subagent_manager = SubagentManager(self.session_db)

        # === L/O/V/G 层: Layer、回归与评审闭环 ===
        self.regression_runner = RegressionRunner(
            self.regression_store,
            self._run_verification,
            self.cwd,
            self.config.verification.timeout,
            self.config.regression.minimum_pass_rate,
        )
        self.layer_manager = LayerManager()
        self._setup_layers()
        self.reviewer = Reviewer(self._call_auxiliary_model)
        self.self_review = SelfReview()

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
            event_sink=self.event_bus.publish,
            decision_trace_store=self.decision_trace_store,
            credential_pool=self.credential_pool,
            credential_provider=self.config.model.provider,
        )

        self.runtime = BuiltinConchRuntime(runtime_config, self.agent_loop)
        self.scheduler = CronScheduler(
            self.session_db,
            self._run_scheduled_task,
            self.config.scheduler.hard_timeout,
        )
        self.coordinator = Coordinator(
            self.session_db,
            self.subagent_manager,
            self._run_coordinator_worker,
            DecisionTable(default_role=self.config.coordinator.worker_role),
            self.config.coordinator.max_workers,
        )

    def _register_core_tools(self) -> None:
        """注册 12 核心工具."""
        backend = self.sandbox_registry.get_backend(is_main=True)
        fs = backend.fs

        tools = [
            BashTool(backend),
            ReadFileTool(fs),
            WriteFileTool(fs),
            EditFileTool(fs),
            GlobTool(fs),
            GrepTool(fs),
            WebSearchTool(self.network_policy),
            WebFetchTool(self.network_policy),
            SkillTool(
                skills_dir=os.path.join(os.path.dirname(__file__), "..", "..", "..", "skills")
            ),
            AskUserTool(),
            TaskManageTool(),
            ToolSearchTool(self.tool_search),
        ]

        for tool in tools:
            self.tool_registry.register(tool)

    async def refresh_mcp_tools(self) -> list[dict[str, Any]]:
        for name in self._mcp_tool_names:
            self.tool_registry.unregister(name)
        self._mcp_tool_names.clear()
        if not self.config.mcp.enabled:
            self._mcp_initialized = True
            return self.mcp_client.status()
        for server in self.mcp_client.servers.values():
            if not server.enabled:
                continue
            try:
                await self.mcp_client.connect(server.name)
                await self.mcp_client.refresh(server.name)
                for adapter in self.mcp_client.adapters(server.name):
                    self.tool_registry.register(adapter)
                    self._mcp_tool_names.add(adapter.name)
            except Exception as exc:
                self.mcp_client.errors[server.name] = str(exc)
        self._mcp_initialized = True
        return self.mcp_client.status()

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
            elif layer_name == "observability":
                self.layer_manager.add(ObservabilityLayer(self.otel_tracer))
            elif layer_name == "llm_quota":
                self.layer_manager.add(LLMQuotaLayer(self.config.quota.max_tokens))
            elif layer_name == "verification":
                self.layer_manager.add(
                    VerificationLayer(
                        self.verification_store,
                        self._run_verification,
                        self.config.verification.commands,
                        self.cwd,
                        self.config.verification.timeout,
                        self.regression_store,
                        self.config.regression.auto_capture,
                    )
                )
            elif layer_name == "suspend":
                self.layer_manager.add(SuspendLayer())
            elif layer_name == "pause_state_persist":
                self.layer_manager.add(PauseStatePersistLayer(self.checkpoint_manager))
            elif layer_name == "cost_budget":
                self.layer_manager.add(
                    CostBudgetLayer(
                        self.budget_manager,
                        BudgetLimits(
                            self.config.budget.max_tokens,
                            self.config.budget.max_seconds,
                            self.config.budget.max_tool_calls,
                            self.config.budget.max_resource_units,
                        ),
                    )
                )
        if self.config.hooks.enabled and self.hook_executor.specs:
            self.layer_manager.add(HookExecutorLayer(self.hook_executor))

    async def _run_verification(self, command: str, cwd: str | None, timeout: int) -> Any:
        return await self.local_backend.execute(command, cwd=cwd, timeout=timeout)

    async def _run_hook(
        self, command: str, cwd: str | None, timeout: int, env: dict[str, str]
    ) -> Any:
        return await self.local_backend.execute(command, cwd=cwd, timeout=timeout, env=env)

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

        kwargs: dict[str, Any] = {
            "model": self.config.model.name,
            "messages": messages,
            "temperature": 0,
            "max_tokens": min(1024, self.config.model.max_tokens),
            "timeout": self.config.model.timeout,
        }
        lease = self.credential_pool.acquire(self.config.model.provider)
        if lease is not None:
            kwargs["api_key"] = lease.secret
        try:
            response = await litellm.acompletion(**kwargs)
        except Exception:
            if lease is not None:
                self.credential_pool.record_failure(lease.alias)
            raise
        if lease is not None:
            self.credential_pool.record_success(lease.alias)
        return response.choices[0].message.content or ""

    async def run(
        self,
        user_input: str,
        session_id: str | None = None,
        *,
        principal: str = "local",
        role: str | None = None,
        sender: str = "main",
    ) -> AgentResult:
        """执行 Agent run.

        Args:
            user_input: 用户输入
            session_id: 会话 ID (None = 自动生成)

        Returns:
            AgentResult
        """
        if session_id is None:
            session_id = str(uuid.uuid4())[:12]
        selected_role = role or self.config.governance.default_role
        authorization = self.rbac.authorize(selected_role, Permission.RUN_CREATE)
        if not authorization.allowed:
            if self.session_db.get_session(session_id) is None:
                self.session_db.create_session(session_id, cwd=self.cwd, model_name=self.config.model.name)
            self.session_db.update_session_status(session_id, "blocked")
            return AgentResult(
                session_id=session_id,
                status="blocked",
                error=authorization.reason,
                trajectory_summary={"exit_status": "blocked"},
            )

        self.tool_registry.set_session_identity(session_id, principal, selected_role, sender)
        try:
            if not self._mcp_initialized and self.mcp_client.servers:
                await self.refresh_mcp_tools()
            result = await self.runtime.run(session_id, user_input)
            result.final_response = self.content_guard.redact(result.final_response)
            if self.config.verification.review_on_submit and result.status == "completed":
                report = self.verification_store.latest(session_id)
                review = await self.self_review.run(
                    user_input,
                    result.final_response,
                    report.passed if report is not None else True,
                )
                result.trajectory_summary["self_review"] = asdict(review)
                if not review.passed:
                    result.status = "error"
                    result.error = "Self review failed: " + "; ".join(review.issues)
            result.trajectory_summary["exit_status"] = classify_exit_status(
                result.status, result.error or ""
            ).value
            result.trajectory_summary["budget"] = self.budget_manager.summary(session_id)
            self.session_db.update_session_status(session_id, result.status)
            return result
        finally:
            self.tool_registry.clear_session_identity(session_id)

    async def replay(self, session_id_or_path: str) -> str:
        """回放轨迹."""
        steps = self.trajectory_store.replay(session_id_or_path)
        return self.trajectory_store.format_replay(steps)

    async def pause(self, session_id: str, turn_index: int = 0) -> None:
        await self.layer_manager.on_event(
            Event(type="pause", data={"session_id": session_id, "turn_index": turn_index})
        )
        await self.event_bus.publish(session_id, {"type": "paused", "turn_index": turn_index})

    async def resume(self, session_id: str) -> None:
        await self.layer_manager.on_event(Event(type="resume", data={"session_id": session_id}))
        self.session_db.update_session_status(session_id, "active")
        await self.event_bus.publish(session_id, {"type": "resumed"})

    async def resume_approval(self, approval: Approval) -> ToolExecutionRecord:
        """批准后执行持久化的原始工具请求；批准记录只能消费一次。"""
        if approval.status != "approved":
            raise ValueError("Only approved requests can be resumed")
        self.tool_registry.set_session_identity(
            approval.session_id,
            approval.principal,
            approval.role,
            "main",
        )
        try:
            record = await self.tool_registry.execute_tool_call(
                ToolCall(
                    id=f"approval-{approval.approval_id}",
                    name=approval.operation,
                    arguments=approval.payload,
                ),
                sandbox_mode=self.config.sandbox.mode,
                session_id=approval.session_id,
            )
            node_ctx = NodeContext(
                session_id=approval.session_id,
                turn_index=0,
                tool_results=[record],
                metadata={"approval_id": approval.approval_id},
            )
            await self.layer_manager.on_node_run_end(node_ctx, [record])
            self.trajectory_store.save_step(
                TrajectoryStep(
                    session_id=approval.session_id,
                    turn_index=0,
                    step_type="tool_call",
                    tool_name=record.tool_name,
                    tool_input=record.arguments,
                    tool_output=record.result.content[:2000],
                    tool_status=record.status,
                    duration_ms=record.duration_ms,
                    metadata={"approval_id": approval.approval_id},
                )
            )
            await self.event_bus.publish(
                approval.session_id,
                {
                    "type": "approval_resumed",
                    "approval_id": approval.approval_id,
                    "tool_name": record.tool_name,
                    "status": record.status,
                },
            )
            if record.status == "success":
                await self.resume(approval.session_id)
            return record
        finally:
            self.tool_registry.clear_session_identity(approval.session_id)

    async def _run_scheduled_task(self, task: str, session_id: str) -> AgentResult:
        return await self.run(
            task,
            session_id,
            principal="scheduler",
            role="operator",
            sender="plugin",
        )

    async def _run_coordinator_worker(
        self,
        record: SubagentRecord,
        role: str,
        metadata: dict[str, Any],
    ) -> str:
        result = await self.run(
            record.task,
            record.session_id,
            principal=f"subagent:{record.subagent_id}",
            role=role,
            sender="subagent",
        )
        if result.status != "completed":
            raise RuntimeError(result.error or f"Worker ended with {result.status}")
        return result.final_response

    def governance_overview(self) -> dict[str, Any]:
        return {
            "policy": self.policy_engine.describe(),
            "approvals": [asdict(item) for item in self.approval_store.list_all(20)],
            "budgets": self.budget_manager.list_recent(20),
            "credentials": self.credential_pool.metadata(),
            "regressions": {
                "cases": len(self.regression_store.list_cases()),
                "latest_results": self.regression_store.latest_results(),
            },
            "schedules": [asdict(item) for item in self.scheduler.list_schedules()],
            "coordinator": [asdict(item) for item in self.coordinator.list_runs(20)],
            "snapshots": self.snapshot_manager.overview(),
            "mcp": self.mcp_client.status(),
            "hooks": [asdict(item) for item in self.hook_executor.list_executions(limit=20)],
            "sandboxes": self.sandbox_registry.list_backends(),
        }

    def run_security_audit(self) -> list[Any]:
        return self.security_audit.scan(asdict(self.config))

    def create_api_app(self) -> Any:
        from agent_conch.api.server import create_app

        return create_app(self)

    def get_tool_health(self) -> dict[str, Any]:
        """获取工具健康状态."""
        return self.tool_registry.get_health_status()

    def close(self) -> None:
        """关闭引擎, 释放资源."""
        self.session_db.close()

    async def shutdown_services(self) -> None:
        await self.mcp_client.close_all()

    async def aclose(self) -> None:
        await self.shutdown_services()
        self.session_db.close()
