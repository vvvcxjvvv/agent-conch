"""T 层: 工具基类与数据模型.

接口策略:
- BaseTool: 统一工具接口
- Pydantic input_model 参数 Schema 校验
- JSON Schema 自动生成给 LLM
- check_fn 前置检查 (可用性验证)
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel


@dataclass
class ToolResult:
    """工具执行结果."""

    content: str  # 返回给 LLM 的文本内容
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    # 结构化数据 (可选, 供 verification layer 使用)
    structured: dict[str, Any] | None = None

    @classmethod
    def success(cls, content: str, **metadata: Any) -> ToolResult:
        return cls(content=content, is_error=False, metadata=metadata)

    @classmethod
    def error(cls, content: str, **metadata: Any) -> ToolResult:
        return cls(content=content, is_error=True, metadata=metadata)

    def to_llm_format(self) -> str:
        """转为 LLM 工具结果格式."""
        if self.is_error:
            return f"[ERROR] {self.content}"
        return self.content


# check_fn 类型: 返回 (is_available: bool, reason: str | None)
CheckFn = Callable[[], Awaitable[tuple[bool, str | None]]]


class BaseTool(ABC):
    """工具基类.

    所有核心工具和扩展工具都继承此类.
    子类必须实现:
    - name: 工具名称
    - description: 工具描述 (给 LLM 看)
    - input_model: Pydantic 模型 (参数校验)
    - execute(): 执行逻辑
    """

    name: str = ""
    description: str = ""
    input_model: type[BaseModel] = type("Empty", (BaseModel,), {})

    # 是否为写操作 (影响 VerificationLayer 和并行策略)
    is_write_tool: bool = False
    # 是否为危险操作 (需要审批)
    is_dangerous: bool = False
    # 是否为核心工具
    is_core: bool = False
    # 分类标签
    tags: list[str] = []

    # check_fn: 可用性前置检查 (可选)
    _check_fn: CheckFn | None = None

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """执行工具逻辑.

        kwargs 已通过 input_model 校验.
        """
        ...

    async def check_available(self) -> tuple[bool, str | None]:
        """检查工具是否可用.

        如果设置了 check_fn 则调用它;
        否则默认可用.
        """
        if self._check_fn is not None:
            return await self._check_fn()
        return True, None

    def set_check_fn(self, fn: CheckFn) -> None:
        """设置可用性检查函数."""
        self._check_fn = fn

    def to_schema(self) -> dict[str, Any]:
        """生成 JSON Schema (供 LLM function calling).

        格式兼容 OpenAI function calling:
        {
            "name": "...",
            "description": "...",
            "parameters": { ...JSON Schema... }
        }
        """
        schema = self.input_model.model_json_schema()
        # 移除 Pydantic 自动添加的 title (可选, 减少 token)
        if "title" in schema:
            schema.pop("title")
        return {
            "name": self.name,
            "description": self.description,
            "parameters": schema,
        }

    def validate_input(self, **kwargs: Any) -> dict[str, Any]:
        """校验输入参数, 返回合法化的 kwargs."""
        # 过滤掉 input_model 不接受的字段
        model_fields = set(self.input_model.model_fields.keys())
        filtered = {k: v for k, v in kwargs.items() if k in model_fields}
        instance = self.input_model(**filtered)
        return instance.model_dump()

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"


@dataclass
class ToolCall:
    """工具调用请求 (来自 LLM)."""

    id: str
    name: str
    arguments: dict[str, Any]

    @classmethod
    def from_llm(cls, raw: dict[str, Any]) -> ToolCall:
        """从 LLM 返回的 tool_call 结构构建."""
        import json

        call_id = raw.get("id", "")
        function = raw.get("function", {})
        name = function.get("name", "")
        args_str = function.get("arguments", "{}")
        try:
            arguments = json.loads(args_str) if isinstance(args_str, str) else args_str
        except json.JSONDecodeError:
            arguments = {}
        return cls(id=call_id, name=name, arguments=arguments)


@dataclass
class ToolExecutionRecord:
    """单次工具执行记录 (供轨迹和验证)."""

    tool_name: str
    tool_call_id: str
    arguments: dict[str, Any]
    result: ToolResult
    duration_ms: int
    timestamp: float = field(default_factory=time.time)
    status: str = "success"  # success | error | blocked | timeout
