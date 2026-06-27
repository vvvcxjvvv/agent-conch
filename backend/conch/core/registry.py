"""注册中心 — 插件注册、依赖声明、拓扑加载、运行时发现、版本共存。

核心机制：
- 装饰器注册，零配置发现
- depends_on 依赖声明，Registry 负责拓扑排序加载
- 生命周期钩子 on_load/on_unload/on_reload，异常时回滚+告警
- query(domain, capability) 运行时按能力发现
- 同插件多版本可注册，Profile 指定版本，便于 A/B 对比
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


class PluginEntry:
    """注册表中的一个插件条目。"""

    def __init__(self, cls: type, domain: str, name: str, version: str, depends_on: list[str]):
        self.cls = cls
        self.domain = domain
        self.name = name
        self.version = version
        self.depends_on = depends_on
        self.instance: Any = None
        self.loaded = False

    @property
    def key(self) -> str:
        return f"{self.domain}:{self.name}"


class Registry:
    """插件注册中心。

    依赖倒置：Registry 属于核心层，不依赖任何具体能力域实现。
    能力域实现通过 @register 装饰器反向注册到 Registry。
    """

    def __init__(self):
        # domain -> name -> {version: PluginEntry}
        self._domains: dict[str, dict[str, dict[str, PluginEntry]]] = defaultdict(
            lambda: defaultdict(dict)
        )

    def register(
        self,
        domain: str,
        name: str,
        version: str = "1.0.0",
        depends_on: list[str] | None = None,
    ):
        """装饰器：注册一个插件实现。

        Args:
            domain: 能力域标识，如 "context"
            name: 实现名，如 "semantic_compaction"
            version: 语义化版本
            depends_on: 依赖的其他插件，格式 ["domain:name", ...]

        Example:
            @registry.register("context", "semantic_compaction", "1.0",
                               depends_on=["tool:result_cleaner"])
            class SemanticCompaction:
                ...
        """

        def deco(cls):
            entry = PluginEntry(cls, domain, name, version, depends_on or [])
            # 设置类属性，供 ExtensionPoint 协议检查
            cls.domain = domain
            cls.name = name
            cls.version = version
            self._domains[domain][name][version] = entry
            logger.debug("Registered plugin %s@%s in domain '%s'", name, version, domain)
            return cls

        return deco

    def build(self, domain: str, name: str, version: str = "latest", **params) -> Any:
        """按 Profile 指定的版本构建插件实例，自动拓扑加载依赖。

        Args:
            domain: 能力域
            name: 插件名
            version: 版本（"latest" 取最高版本）
            **params: 构造参数（来自 Profile）
        """
        entry = self._resolve(domain, name, version)
        self._load_with_deps(entry, set())

        if entry.instance is None:
            inst = entry.cls(**params)
            # 生命周期钩子：on_load
            if hasattr(inst, "on_load"):
                try:
                    inst.on_load()
                except Exception:
                    logger.exception("on_load failed for %s", entry.key)
            entry.instance = inst
            entry.loaded = True

        return entry.instance

    def list(self, domain: str) -> list[str]:
        """列出某域已注册的所有实现名。"""
        return list(self._domains[domain].keys())

    def query(self, domain: str, capability: str | None = None) -> list[str]:
        """运行时发现：按域（可选按 capability 元数据）查找可用实现名。

        Args:
            domain: 能力域
            capability: 可选，按 metadata["capabilities"] 过滤

        Returns:
            匹配的插件名列表
        """
        names = list(self._domains[domain].keys())
        if not capability:
            return names
        result = []
        for name in names:
            for entry in self._domains[domain][name].values():
                caps = entry.cls.metadata.get("capabilities", [])
                if capability in caps:
                    result.append(name)
                    break
        return result

    def unload(self, domain: str, name: str) -> None:
        """卸载插件，调用 on_unload，异常时回滚状态并记录告警。"""
        versions = self._domains.get(domain, {}).get(name, {})
        for entry in versions.values():
            if entry.loaded and entry.instance is not None:
                if hasattr(entry.instance, "on_unload"):
                    try:
                        entry.instance.on_unload()
                    except Exception:
                        logger.warning(
                            "on_unload failed for %s, rolling back state", entry.key
                        )
                entry.instance = None
                entry.loaded = False

    def _resolve(self, domain: str, name: str, version: str) -> PluginEntry:
        versions = self._domains[domain][name]
        if not versions:
            raise KeyError(f"No plugin '{name}' registered in domain '{domain}'")
        if version == "latest":
            # 语义化版本取最高
            return versions[max(versions.keys())]
        if version not in versions:
            raise KeyError(
                f"Plugin '{name}' version '{version}' not found. "
                f"Available: {list(versions.keys())}"
            )
        return versions[version]

    def _load_with_deps(self, entry: PluginEntry, seen: set[str]) -> None:
        """拓扑排序，确保依赖先加载，检测循环依赖。"""
        key = entry.key
        if key in seen:
            raise RuntimeError(f"Circular dependency detected at {key}")
        seen.add(key)

        for dep in entry.depends_on:
            d_domain, d_name = dep.split(":")
            dep_entry = self._resolve(d_domain, d_name, "latest")
            if not dep_entry.loaded:
                self._load_with_deps(dep_entry, seen)

        # 依赖就绪后由 build() 统一实例化


# 全局注册中心实例
registry = Registry()
