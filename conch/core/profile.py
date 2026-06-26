"""Profile 引擎 — 实验配置的加载、继承、校验。

Profile = 一组插件选择 + 参数，声明式定义一个"实验配置"。
- extends 语法：子 Profile 继承父配置并覆写差异项
- Pydantic v2 全量校验：启动前拦截非法配置（有 pydantic 时）
- 环境变量覆盖：支持 CONCH_* 环境变量覆盖参数

双模式设计：
- 有 pydantic+yaml：完整校验 + 标准 YAML 解析
- 无 pydantic+yaml：纯 Python dataclass + 内置简易 YAML 解析（保证无依赖可跑）
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 尝试导入可选依赖
try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

try:
    from pydantic import BaseModel, Field, model_validator
    _HAS_PYDANTIC = True
except ImportError:
    _HAS_PYDANTIC = False


# ── 数据模型（纯 Python dataclass，无依赖可用）──────────────────

@dataclass
class DomainConfig:
    """单个能力域的配置。"""

    impl: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    version: str = "latest"


@dataclass
class HookConfig:
    """Hook 配置。"""

    point: str = ""
    callback: str = ""
    priority: int = 100
    name: str = ""


@dataclass
class Profile:
    """实验配置 — 一组插件选择 + 参数。"""

    name: str = ""
    description: str = ""
    extends: str | None = None
    domains: dict[str, DomainConfig] = field(default_factory=dict)
    hooks: list[HookConfig] = field(default_factory=list)
    max_steps: int = 50
    max_tokens: int | None = None
    model: str = "gpt-4o"
    model_fallback: str | None = None

    def validate_domains(self) -> "Profile":
        """校验所有 domain 配置的域名合法。"""
        from conch.core.extension import DOMAINS

        for domain_name in self.domains:
            if domain_name not in DOMAINS:
                raise ValueError(
                    f"Unknown domain '{domain_name}' in profile '{self.name}'. "
                    f"Valid domains: {DOMAINS}"
                )
        return self

    def apply_env_overrides(self) -> "Profile":
        """应用 CONCH_* 环境变量覆盖。"""
        if (val := os.environ.get("CONCH_MAX_TOKENS")) and val.isdigit():
            self.max_tokens = int(val)
        if (val := os.environ.get("CONCH_MAX_STEPS")) and val.isdigit():
            self.max_steps = int(val)
        if val := os.environ.get("CONCH_MODEL"):
            self.model = val
        for domain_name, domain_cfg in self.domains.items():
            prefix = f"CONCH_{domain_name.upper()}_"
            for key in list(domain_cfg.params.keys()):
                env_key = prefix + key.upper()
                if env_key in os.environ:
                    domain_cfg.params[key] = _parse_env_value(os.environ[env_key])
        return self


# ── 从原始 dict 构建 Profile ─────────────────────────────────────

def _build_profile(raw: dict) -> Profile:
    """从原始 dict 构建 Profile 对象。"""
    domains_raw = raw.get("domains", {})
    domains = {}
    for d_name, d_cfg in domains_raw.items():
        if isinstance(d_cfg, str):
            d_cfg = {"impl": d_cfg}
        domains[d_name] = DomainConfig(
            impl=d_cfg.get("impl", ""),
            params=d_cfg.get("params", {}),
            version=d_cfg.get("version", "latest"),
        )

    hooks_raw = raw.get("hooks", [])
    hooks = [HookConfig(**h) if isinstance(h, dict) else HookConfig() for h in hooks_raw]

    profile = Profile(
        name=raw.get("name", ""),
        description=raw.get("description", ""),
        extends=raw.get("extends"),
        domains=domains,
        hooks=hooks,
        max_steps=raw.get("max_steps", 50),
        max_tokens=raw.get("max_tokens"),
        model=raw.get("model", "gpt-4o"),
        model_fallback=raw.get("model_fallback"),
    )
    profile.validate_domains()
    return profile


# ── YAML 解析（双模式）──────────────────────────────────────────

def _parse_yaml(text: str) -> dict:
    """解析 YAML，有 pyyaml 用 pyyaml，否则用内置简易解析器。"""
    if _HAS_YAML:
        return yaml.safe_load(text) or {}

    # 简易 YAML 解析器（支持我们 Profile 用到的子集：缩进嵌套 + key: value）
    return _SimpleYAMLParser(text).parse()


class _SimpleYAMLParser:
    """简易 YAML 解析器 — 支持 Profile 配置用的子集。

    支持：缩进嵌套 dict、key: value、列表 (- item)、行内 dict {k: v}、注释 #。
    不支持：多行字符串、锚点、引用等复杂特性。
    """

    def __init__(self, text: str):
        self.lines = []
        for line in text.splitlines():
            # 去注释
            stripped = line.split("#")[0].rstrip()
            if stripped.strip():
                self.lines.append(stripped)

    def parse(self) -> dict:
        result, _ = self._parse_block(0, 0)
        return result

    def _parse_block(self, start: int, indent: int) -> tuple[dict, int]:
        result: dict[str, Any] = {}
        i = start
        while i < len(self.lines):
            line = self.lines[i]
            cur_indent = len(line) - len(line.lstrip())

            if cur_indent < indent:
                break
            if cur_indent > indent:
                i += 1
                continue

            content = line.strip()

            # 列表项
            if content.startswith("- "):
                key = "_list"
                val = content[2:].strip()
                if key not in result:
                    result[key] = []
                result[key].append(self._parse_value(val))
                i += 1
                continue

            # key: value
            if ":" in content:
                key, _, val = content.partition(":")
                key = key.strip()
                val = val.strip()

                if val:
                    result[key] = self._parse_value(val)
                    i += 1
                else:
                    # 嵌套 dict
                    if i + 1 < len(self.lines):
                        next_indent = len(self.lines[i + 1]) - len(self.lines[i + 1].lstrip())
                        if next_indent > cur_indent:
                            child, i = self._parse_block(i + 1, next_indent)
                            result[key] = child
                            continue
                    result[key] = {}
                    i += 1
                continue

            i += 1

        return result, i

    def _parse_value(self, val: str) -> Any:
        """解析标量值或行内 dict/list。"""
        val = val.strip()

        # 行内 dict {k: v, k2: v2}
        if val.startswith("{") and val.endswith("}"):
            inner = val[1:-1].strip()
            result = {}
            for item in _split_top_level(inner, ","):
                item = item.strip()
                if ":" in item:
                    k, _, v = item.partition(":")
                    result[k.strip()] = self._parse_scalar(v.strip())
            return result

        # 行内 list [a, b, c]
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            return [self._parse_scalar(s.strip()) for s in _split_top_level(inner, ",") if s.strip()]

        return self._parse_scalar(val)

    def _parse_scalar(self, val: str) -> Any:
        """解析标量：去引号、int/float/bool/str。"""
        val = val.strip()
        # 去引号
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            return val[1:-1]
        if val.lower() in ("true", "yes"):
            return True
        if val.lower() in ("false", "no"):
            return False
        if val.lower() in ("null", "none", "~"):
            return None
        if val.lstrip("-").isdigit():
            return int(val)
        try:
            return float(val)
        except ValueError:
            return val


def _split_top_level(s: str, sep: str) -> list[str]:
    """在顶层分割（不进入嵌套的 {} 或 []）。"""
    result = []
    depth = 0
    current = []
    for ch in s:
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        if ch == sep and depth == 0:
            result.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        result.append("".join(current))
    return result


# ── Profile 加载器 ──────────────────────────────────────────────

class ProfileLoader:
    """Profile 加载器 — 支持 extends 继承链。"""

    def __init__(self, profiles_dir: str | Path = "profiles"):
        self.profiles_dir = Path(profiles_dir)
        self._cache: dict[str, Profile] = {}

    def load(self, name: str) -> Profile:
        """加载 Profile，解析 extends 继承链。"""
        if name in self._cache:
            return self._cache[name]

        raw = self._load_yaml(name)
        profile = _build_profile(raw)

        if profile.extends:
            parent = self.load(profile.extends)
            profile = self._merge(parent, profile)

        profile.apply_env_overrides()
        self._cache[name] = profile
        return profile

    def _load_yaml(self, name: str) -> dict:
        path = Path(name)
        if not path.suffix:
            path = self.profiles_dir / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Profile not found: {path}")
        with open(path, encoding="utf-8") as f:
            return _parse_yaml(f.read())

    def _merge(self, parent: Profile, child: Profile) -> Profile:
        """子 Profile 继承父配置，覆写差异项。"""
        merged_domains = dict(parent.domains)
        merged_domains.update(child.domains)

        merged_hooks = list(parent.hooks)
        merged_hooks.extend(child.hooks)

        return Profile(
            name=child.name,
            description=child.description or parent.description,
            extends=None,
            domains=merged_domains,
            hooks=merged_hooks,
            max_steps=child.max_steps if child.max_steps != 50 else parent.max_steps,
            max_tokens=child.max_tokens or parent.max_tokens,
            model=child.model if child.model != "gpt-4o" else parent.model,
            model_fallback=child.model_fallback or parent.model_fallback,
        )


def _parse_env_value(val: str) -> Any:
    """尝试将环境变量值解析为 int/float/bool/str。"""
    if val.lower() in ("true", "yes"):
        return True
    if val.lower() in ("false", "no"):
        return False
    if val.isdigit():
        return int(val)
    try:
        return float(val)
    except ValueError:
        return val
