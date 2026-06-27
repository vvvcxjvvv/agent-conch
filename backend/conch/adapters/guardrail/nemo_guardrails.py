"""NeMo Guardrails 护栏 — 输入输出筛查。

包装 nemoguardrails 的 LLMRails，实现 GuardrailProvider 接口。
MVP 用最小配置（3 条规则拦截有害指令），满足阶段一退出标准。

配置目录结构 (guardrail_configs/chat/):
    config.yml       — NeMo 主配置
    rails.co         — Colang 规则（输入/输出拦截）
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from conch.core.extension import GuardrailProvider, GuardrailResult, Plugin
from conch.core.registry import registry

logger = logging.getLogger(__name__)


# MVP 默认拦截关键词（NeMo 未配置时的兜底）
_DEFAULT_BLOCKED_PATTERNS = [
    "删除所有文件", "删除全部文件", "rm -rf /",
    "格式化磁盘", "format c:",
    "drop table", "drop database",
    "删除系统", "销毁数据",
]


@registry.register("guardrail", "nemo_guardrails", "1.0")
class NemoGuardrail(Plugin, GuardrailProvider):
    """NeMo Guardrails 护栏。

    Args:
        config_dir: NeMo 配置目录路径（含 config.yml + rails.co）
        use_nemo: True 用 NeMo引擎；False 用内置关键词兜底（MVP 简化）
    """

    domain = "guardrail"
    name = "nemo_guardrails"
    version = "1.0"
    metadata = {
        "capabilities": ["input_filter", "output_filter", "tool_guard"],
        "framework": "nemoguardrails",
        "description": "NeMo Guardrails 护栏（输入/输出/工具）",
    }

    def __init__(self, config_dir: str = "", use_nemo: bool = True):
        self.config_dir = config_dir
        self.use_nemo = use_nemo
        self._rails = None

    def on_load(self) -> None:
        if not self.use_nemo:
            logger.info("NemoGuardrail: using keyword fallback (NeMo disabled)")
            return

        config_path = Path(self.config_dir) if self.config_dir else None
        if config_path and config_path.exists():
            try:
                from nemoguardrails import LLMRails, RailsConfig

                rail_config = RailsConfig.from_path(str(config_path))
                self._rails = LLMRails(rail_config)
                logger.info("NemoGuardrail: NeMo rails loaded from %s", config_path)
            except ImportError:
                logger.warning("nemoguardrails not installed, falling back to keyword mode")
                self.use_nemo = False
            except Exception:
                logger.exception("Failed to load NeMo config, falling back to keyword mode")
                self.use_nemo = False
        else:
            logger.warning("NemoGuardrail: config dir not found, using keyword fallback")
            self.use_nemo = False

    def check_input(self, text: str, state: Any) -> GuardrailResult:
        """输入筛查 — 在 LLM 推理前检查用户输入。"""
        if self.use_nemo and self._rails:
            return self._check_with_nemo(text, state)
        return self._check_with_keywords(text)

    def check_output(self, text: str, state: Any) -> GuardrailResult:
        """输出筛查 — 在 LLM 输出后检查。"""
        if self.use_nemo and self._rails:
            return self._check_with_nemo(text, state, is_output=True)
        return self._check_with_keywords(text)

    def check_tool(self, tool: str, args: dict, state: Any) -> GuardrailResult:
        """工具护栏 — 检查工具调用是否危险。"""
        args_str = str(args).lower()
        for pattern in _DEFAULT_BLOCKED_PATTERNS:
            if pattern in args_str:
                return GuardrailResult(
                    blocked=True,
                    reason=f"Tool '{tool}' args matched blocked pattern: {pattern}",
                    action="block",
                )
        return GuardrailResult(action="pass")

    def _check_with_nemo(self, text: str, state: Any, is_output: bool = False) -> GuardrailResult:
        """用 NeMo LLMRails 检查。"""
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 在已有事件循环中，用 ensure_future（MVP 简化，实际应 async）
                # NeMo 的 generate 是同步的，直接调
                result = self._rails.generate(
                    messages=[{"role": "user", "content": text}]
                )
            else:
                result = self._rails.generate(
                    messages=[{"role": "user", "content": text}]
                )
            # NeMo 拦截时会返回拦截消息或修改内容
            content = ""
            if isinstance(result, dict):
                content = result.get("content", "")
            elif isinstance(result, list) and result:
                content = result[-1].get("content", "") if isinstance(result[-1], dict) else str(result[-1])

            # 简化判断：如果返回内容包含拦截标记
            if "blocked" in content.lower() or "拦截" in content:
                return GuardrailResult(
                    blocked=True,
                    reason=f"NeMo {'output' if is_output else 'input'} guardrail blocked",
                    action="block",
                )
            return GuardrailResult(action="pass")
        except Exception:
            logger.exception("NeMo check failed, falling back to keywords")
            return self._check_with_keywords(text)

    def _check_with_keywords(self, text: str) -> GuardrailResult:
        """关键词兜底检查（NeMo 未加载时用）。"""
        text_lower = text.lower()
        for pattern in _DEFAULT_BLOCKED_PATTERNS:
            if pattern in text_lower:
                return GuardrailResult(
                    blocked=True,
                    reason=f"Input matched blocked pattern: {pattern}",
                    action="block",
                )
        return GuardrailResult(action="pass")
