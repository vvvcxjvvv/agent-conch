"""扩展点契约 — 所有能力域的基类抽象。

核心设计哲学：能力域接口定义 WHAT（做什么），不定义 HOW（怎么做）。
这保证技术演进时接口依然稳定，新技术点只需新实现，不改核心。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ExtensionPoint(Protocol):
    """所有能力域的基类契约。

    每个能力域 = 一个 ExtensionPoint，定义稳定接口。
    具体技术点实现此接口，通过 @registry.register 注册。

    属性:
        domain: 能力域标识，如 "context"、"tool"、"information"
        name: 实现名，如 "compaction_v1"、"builtin_shell"
        version: 语义化版本，如 "1.0.0"
        metadata: 自描述元数据（成本/上下文消耗/适用场景/capabilities）
    """

    domain: str
    name: str
    version: str
    metadata: dict[str, Any]


class Plugin:
    """插件基类 — 可选的生命周期钩子，默认空实现。

    插件可选择继承此类获得生命周期管理能力，
    也可直接实现 ExtensionPoint 协议（鸭子类型）。
    """

    # ExtensionPoint 属性默认值（子类可覆盖）
    domain: str = ""
    name: str = ""
    version: str = "1.0.0"
    metadata: dict[str, Any] = {}

    def on_load(self) -> None:
        """加载时初始化资源（如连接数据库、打开文件）。"""

    def on_unload(self) -> None:
        """卸载时清理资源。异常时自动回滚状态并记录告警。"""

    def on_reload(self) -> None:
        """热重载（实验切换 Profile 时）。默认等同于 unload + load。"""
        self.on_unload()
        self.on_load()


# ── 9 大能力域的扩展点接口定义 ──────────────────────────────────
# 每个域定义自己的 Protocol，实现者需满足对应接口。
# 核心层只定义接口，不提供实现——实现层在 conch/domains/。


class InformationProvider(ExtensionPoint, Protocol):
    """域1：信息边界与指令系统。

    决定 Agent 该知道什么、不该知道什么。
    负责加载指令文件（AGENTS.md）、匹配并注入 Skill。
    """

    def assemble(self, task: Any, state: Any) -> Any:
        """组装指令上下文：系统提示 + 指令片段 + Skill 注入。"""
        ...


class ToolProvider(ExtensionPoint, Protocol):
    """域2：工具系统与协议。

    工具注册、发现、执行，MCP 对齐。
    """

    def tools_for(self, task: Any, state: Any) -> list[Any]:
        """返回当前可用的工具子集（按任务筛选）。"""
        ...

    async def execute(self, tool: str, args: dict, state: Any) -> Any:
        """执行工具，返回 ToolResult。"""
        ...


class ContextManager(ExtensionPoint, Protocol):
    """域3：上下文管理。

    JIT 加载、压缩、Context Reset、利用率守卫。
    """

    def assemble(self, task: Any, state: Any) -> Any:
        """组装完整上下文（指令 + 记忆摘要 + 即时检索）。"""
        ...

    def compact(self, context: Any, strategy: str = "summary") -> Any:
        """上下文压缩/摘要蒸馏。"""
        ...

    def should_compact(self, context: Any) -> bool:
        """判断是否需要压缩（40% 利用率阈值）。"""
        ...


class MemoryProvider(ExtensionPoint, Protocol):
    """域4：记忆与状态（五分法）。

    短期 / 情景 / 语义 / 长期 / 程序性。
    """

    def store(self, key: str, value: Any, mem_type: str = "short") -> None:
        """存储记忆。"""
        ...

    def recall(self, query: str, mem_type: str = "short", limit: int = 5) -> list[Any]:
        """检索记忆。"""
        ...


class OrchestrationMode(ExtensionPoint, Protocol):
    """域5：执行编排与生命周期。

    single_loop / orchestrator_worker / fan_out / gan / state_machine 均实现此接口。
    """

    async def run(self, task: Any, agents: list[Any], state: Any) -> Any:
        """执行编排。"""
        ...

    async def task_split(self, task: Any, state: Any) -> list[Any]:
        """任务拆分（L3 多 Agent 时实现）。"""
        ...

    async def state_sync(self, agents: list[Any], state: Any) -> None:
        """状态同步（L3 实现）。"""
        ...

    async def conflict_resolve(self, results: list[Any], state: Any) -> Any:
        """冲突解决（L3 实现）。"""
        ...


class Evaluator(ExtensionPoint, Protocol):
    """域6：评估与验证。

    三层评测：单步 / 回合 / 多轮，环境可重置。
    """

    def should_eval(self, state: Any) -> bool:
        """判断当前是否需要评测。"""
        ...

    async def eval(self, state: Any) -> Any:
        """执行评测，返回反馈。"""
        ...


class ObservabilityProvider(ExtensionPoint, Protocol):
    """域7：可观测性。

    轨迹、成本、失败、可靠性信号。四级指标集。
    """

    def trace(self, state: Any) -> None:
        """记录一个 step 的轨迹。"""
        ...

    def metrics(self) -> dict[str, Any]:
        """返回当前累计指标。"""
        ...


class ConstraintProvider(ExtensionPoint, Protocol):
    """域8：约束、校验与恢复。

    Linter + 修复指令、沙箱加固、重试/回滚/降级。
    """

    def validate(self, action: Any, state: Any) -> Any:
        """校验动作是否合规，返回校验结果。"""
        ...

    def recover(self, error: Exception, state: Any) -> Any:
        """故障恢复策略。"""
        ...


class GovernanceProvider(ExtensionPoint, Protocol):
    """域9：治理。

    权限模型（MVP: allowlist）、审计日志、人工监督。
    """

    def check_permission(self, tool: str, args: dict) -> bool:
        """权限校验。"""
        ...

    def audit(self, action: str, detail: dict) -> None:
        """记录审计日志。"""
        ...


# ── 域10：护栏（v2 新增，六层纵深防御）─────────────────────────


@dataclass
class GuardrailResult:
    """护栏检查结果。"""

    blocked: bool = False
    reason: str = ""
    sanitized: str | None = None  # 清洗后的文本（若做了 sanitize 而非 block）
    action: str = "pass"  # pass / block / sanitize / warn


class GuardrailProvider(ExtensionPoint, Protocol):
    """域10：护栏 — 六层纵深防御的统一接口。

    每层护栏（输入筛查/输出筛查/工具护栏等）实现此接口。
    通过 Hook 挂载到 pre_model_call / post_model_call / pre_tool 节点。
    """

    def check_input(self, text: str, state: Any) -> GuardrailResult:
        """输入筛查 — 在 LLM 推理前检查用户输入。"""
        ...

    def check_output(self, text: str, state: Any) -> GuardrailResult:
        """输出筛查 — 在 LLM 输出后、返回用户前检查。"""
        ...

    def check_tool(self, tool: str, args: dict, state: Any) -> GuardrailResult:
        """工具护栏 — 在工具执行前检查参数与意图。"""
        ...


# 能力域注册表 — 核心层知道有哪些域，但不知道实现
DOMAINS = [
    "information",    # 域1
    "tool",           # 域2
    "context",        # 域3
    "memory",         # 域4
    "orchestration",  # 域5
    "eval",           # 域6
    "observability",  # 域7
    "constraint",     # 域8
    "governance",     # 域9
    "guardrail",      # 域10 (v2 新增)
]
