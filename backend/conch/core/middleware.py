"""中间件链 — 链式处理数据流。

与 Hook 的区别：
- Pipeline 处理数据流（对数据做变换并传递），禁止中断执行流程
- Hook 处理控制流（在节点上触发副作用、可中断流程）

两者不互斥：context reset 的"触发条件判断"是 Hook（控制流），
而"执行压缩清理"是 Pipeline（数据流）。
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

T = TypeVar("T")


class Middleware(Generic[T]):
    """中间件基类 — 处理数据流变换。

    子类实现 process() 方法，接收数据，返回变换后的数据。
    """

    def process(self, data: T) -> T:
        """对数据做变换并返回。"""
        return data


class Pipeline(Generic[T]):
    """中间件链 — 按顺序应用多个中间件。

    用法:
        pipeline = Pipeline([
            JitLoader(),
            MetadataEnricher(),
            ToolResultClearer(),
            SemanticCompactor(),
            UtilizationGuard(0.4),
        ])
        context = pipeline.run(context)
    """

    def __init__(self, middlewares: list[Middleware[T]] | None = None):
        self._middlewares = middlewares or []

    def add(self, middleware: Middleware[T]) -> "Pipeline[T]":
        """追加一个中间件，返回 self 支持链式调用。"""
        self._middlewares.append(middleware)
        return self

    def run(self, data: T) -> T:
        """按顺序应用所有中间件。"""
        for mw in self._middlewares:
            data = mw.process(data)
        return data

    def __len__(self) -> int:
        return len(self._middlewares)
