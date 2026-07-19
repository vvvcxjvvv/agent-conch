"""配置加载: 解析 conch.yaml 并合并默认值.

设计文档要求: YAML 驱动 Agent 行为配置。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ModelConfig:
    """LLM 模型配置."""

    provider: str = "litellm"
    name: str = "gpt-4o"
    api_base: str | None = None
    api_key_env: str = "OPENAI_API_KEY"
    temperature: float = 0.0
    max_tokens: int = 4096
    timeout: int = 120


@dataclass
class AgentLoopConfig:
    """Agent Loop 配置."""

    max_turns: int = 50
    max_time: int = 600
    auto_compact: bool = True


@dataclass
class ToolsConfig:
    """工具系统配置."""

    core_enabled: bool = True
    tool_search_threshold: float = 0.10
    check_fn_ttl: int = 30
    transient_suppress: int = 60
    parallel_execution: bool = True
    output_max_chars: int = 20_000
    output_preview_chars: int = 4_000


@dataclass
class DockerSandboxConfig:
    image: str = "python:3.12-slim"
    memory_limit: str = "512m"
    cpu_limit: str = "1.0"
    network: str = "none"
    runtime: str = ""
    volumes: list[str] = field(default_factory=list)


@dataclass
class SSHSandboxConfig:
    host: str = ""
    user: str = ""
    port: int = 22
    identity_file: str = ""
    strict_host_key: bool = True
    connect_timeout: int = 10
    work_dir: str = "."
    allowed_roots: list[str] = field(default_factory=list)


@dataclass
class NetworkPolicyConfig:
    enforce: bool = False
    allowlist: list[str] = field(default_factory=list)


@dataclass
class SandboxConfig:
    """沙箱配置."""

    mode: str = "non-main"
    default_backend: str = "local"
    sensitive_paths: list[str] = field(
        default_factory=lambda: ["/etc", "~/.ssh", "/.env", "~/.config"]
    )
    allowed_roots: list[str] = field(default_factory=list)
    docker: DockerSandboxConfig = field(default_factory=DockerSandboxConfig)
    ssh: SSHSandboxConfig = field(default_factory=SSHSandboxConfig)
    network_policy: NetworkPolicyConfig = field(default_factory=NetworkPolicyConfig)


@dataclass
class StateConfig:
    """状态存储配置."""

    storage_dir: str = "~/.agent-conch"
    db_name: str = "state.db"
    trajectory_dir: str = "trajectories"

    @property
    def storage_path(self) -> Path:
        return Path(os.path.expanduser(self.storage_dir))

    @property
    def db_path(self) -> Path:
        return self.storage_path / self.db_name

    @property
    def trajectory_path(self) -> Path:
        return self.storage_path / self.trajectory_dir


@dataclass
class LayersConfig:
    """Layer 配置."""

    enabled: list[str] = field(default_factory=lambda: ["execution_limits"])


@dataclass
class QuotaConfig:
    """单次运行 LLM Token 配额。"""

    max_tokens: int = 200_000


@dataclass
class VerificationConfig:
    """写操作后的自动质量门禁。"""

    commands: list[str] = field(default_factory=list)
    timeout: int = 120
    review_on_submit: bool = True


@dataclass
class ApiConfig:
    """P3 HTTP API 与 Web Console 服务配置。"""

    host: str = "127.0.0.1"
    port: int = 8765


@dataclass
class GovernanceConfig:
    """P4 RBAC、PolicyEngine 与 WriteApproval 配置。"""

    enabled: bool = True
    default_role: str = "admin"
    approval_level: int = 4
    policy_rules: list[dict[str, Any]] = field(default_factory=list)
    content_safety_enabled: bool = True
    redact_sensitive: bool = True
    denied_content_patterns: list[str] = field(default_factory=list)


@dataclass
class MCPConfig:
    enabled: bool = True
    servers: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class HooksConfig:
    enabled: bool = True
    commands: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class BudgetConfig:
    """单任务综合预算。"""

    max_tokens: int = 200_000
    max_seconds: int = 600
    max_tool_calls: int = 500
    max_resource_units: int = 1_000


@dataclass
class CredentialsConfig:
    """Credential Pool 仅引用外部 secret，不存储明文。"""

    failure_cooldown: int = 60
    entries: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RegressionConfig:
    auto_capture: bool = True
    minimum_pass_rate: float = 1.0


@dataclass
class SchedulerConfig:
    hard_timeout: int = 180


@dataclass
class CoordinatorConfig:
    max_workers: int = 4
    worker_role: str = "worker"


@dataclass
class PromptConfig:
    """Prompt 配置."""

    system_prompt_mode: str = "base"
    discover_agents_md: bool = True


@dataclass
class LoggingConfig:
    """日志配置."""

    level: str = "INFO"
    format: str = "rich"


@dataclass
class ConchConfig:
    """Agent-Conch 全局配置."""

    model: ModelConfig = field(default_factory=ModelConfig)
    agent_loop: AgentLoopConfig = field(default_factory=AgentLoopConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    state: StateConfig = field(default_factory=StateConfig)
    layers: LayersConfig = field(default_factory=LayersConfig)
    quota: QuotaConfig = field(default_factory=QuotaConfig)
    verification: VerificationConfig = field(default_factory=VerificationConfig)
    api: ApiConfig = field(default_factory=ApiConfig)
    governance: GovernanceConfig = field(default_factory=GovernanceConfig)
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    credentials: CredentialsConfig = field(default_factory=CredentialsConfig)
    regression: RegressionConfig = field(default_factory=RegressionConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    coordinator: CoordinatorConfig = field(default_factory=CoordinatorConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    hooks: HooksConfig = field(default_factory=HooksConfig)
    prompt: PromptConfig = field(default_factory=PromptConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConchConfig:
        """从字典构建配置, 缺失字段使用默认值."""
        sandbox_data = dict(data.get("sandbox", {}))
        docker_data = dict(sandbox_data.pop("docker", {}))
        ssh_data = dict(sandbox_data.pop("ssh", {}))
        network_data = dict(sandbox_data.pop("network_policy", {}))
        sandbox = SandboxConfig(
            **sandbox_data,
            docker=DockerSandboxConfig(**docker_data),
            ssh=SSHSandboxConfig(**ssh_data),
            network_policy=NetworkPolicyConfig(**network_data),
        )
        return cls(
            model=ModelConfig(**data.get("model", {})),
            agent_loop=AgentLoopConfig(**data.get("agent_loop", {})),
            tools=ToolsConfig(**data.get("tools", {})),
            sandbox=sandbox,
            state=StateConfig(**data.get("state", {})),
            layers=LayersConfig(**data.get("layers", {})),
            quota=QuotaConfig(**data.get("quota", {})),
            verification=VerificationConfig(**data.get("verification", {})),
            api=ApiConfig(**data.get("api", {})),
            governance=GovernanceConfig(**data.get("governance", {})),
            budget=BudgetConfig(**data.get("budget", {})),
            credentials=CredentialsConfig(**data.get("credentials", {})),
            regression=RegressionConfig(**data.get("regression", {})),
            scheduler=SchedulerConfig(**data.get("scheduler", {})),
            coordinator=CoordinatorConfig(**data.get("coordinator", {})),
            mcp=MCPConfig(**data.get("mcp", {})),
            hooks=HooksConfig(**data.get("hooks", {})),
            prompt=PromptConfig(**data.get("prompt", {})),
            logging=LoggingConfig(**data.get("logging", {})),
        )

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> ConchConfig:
        """加载配置文件.

        查找顺序:
        1. 显式指定的 config_path
        2. 环境变量 CONCH_CONFIG
        3. 当前目录下的 conch.yaml
        4. 包内置默认 conch.yaml
        """
        candidates: list[Path] = []
        if config_path:
            candidates.append(Path(config_path))
        env_path = os.environ.get("CONCH_CONFIG")
        if env_path:
            candidates.append(Path(env_path))
        candidates.append(Path.cwd() / "conch.yaml")

        for path in candidates:
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                return cls.from_dict(data)

        return cls()

    def ensure_storage(self) -> Path:
        """确保存储目录存在, 返回存储路径."""
        self.state.storage_path.mkdir(parents=True, exist_ok=True)
        self.state.trajectory_path.mkdir(parents=True, exist_ok=True)
        return self.state.storage_path
