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


@dataclass
class SandboxConfig:
    """沙箱配置."""

    mode: str = "non-main"
    default_backend: str = "local"
    sensitive_paths: list[str] = field(
        default_factory=lambda: ["/etc", "~/.ssh", "/.env", "~/.config"]
    )
    allowed_roots: list[str] = field(default_factory=list)


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
    prompt: PromptConfig = field(default_factory=PromptConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConchConfig:
        """从字典构建配置, 缺失字段使用默认值."""
        return cls(
            model=ModelConfig(**data.get("model", {})),
            agent_loop=AgentLoopConfig(**data.get("agent_loop", {})),
            tools=ToolsConfig(**data.get("tools", {})),
            sandbox=SandboxConfig(**data.get("sandbox", {})),
            state=StateConfig(**data.get("state", {})),
            layers=LayersConfig(**data.get("layers", {})),
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
