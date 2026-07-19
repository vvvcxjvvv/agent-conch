"""C 层: Prompt Caching.

缓存策略:
- system_and_3 策略: 4 个 cache_control 断点
  1. system prompt 末尾
  2-4. 最后 3 条非 system 消息
- _can_carry_marker 检查防止浪费断点
- 统一 TTL (5m 或 1h)

铁律: 不允许变更过去上下文、不允许切换 toolset、不允许重建 system prompt
唯一例外: context compression

注意: cache_control 仅对 Anthropic 模型生效; OpenAI/DeepSeek 自动缓存.
此模块对不支持 cache_control 的模型为 no-op.
"""

from __future__ import annotations

from typing import Any


class PromptCaching:
    """Prompt Caching — system_and_3 策略.

    在消息列表中插入 cache_control 断点:
    - 断点 1: system prompt 末尾 (如果存在)
    - 断点 2-4: 最后 3 条非 system 消息

    缓存稳定性要求:
    - 过去的 cache_control 断点不能被移除
    - 只能在新增消息上添加断点
    - _can_carry_marker 检查: 确保消息有足够内容值得缓存
    """

    # 支持的 TTL
    TTL_5M = "5m"
    TTL_1H = "1h"

    # 最小可缓存内容长度 (chars) — 太短不值得占用断点
    MIN_CACHEABLE_CHARS = 100

    def __init__(
        self,
        ttl: str = "5m",
        enabled: bool = True,
        provider: str = "anthropic",
    ):
        """
        Args:
            ttl: 缓存 TTL ("5m" 或 "1h")
            enabled: 是否启用
            provider: 模型提供商 ("anthropic" 支持 cache_control, 其他为 no-op)
        """
        self.ttl = ttl
        self.enabled = enabled
        self.provider = provider

    def apply(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """对消息列表应用 cache_control 断点.

        system_and_3 策略:
        - 断点 1: system prompt 末尾
        - 断点 2-4: 最后 3 条非 system 消息

        对于不支持 cache_control 的 provider, 原样返回.
        """
        if not self.enabled or self.provider not in ("anthropic",):
            return messages

        result = [dict(msg) for msg in messages]  # shallow copy

        # 分离 system 和非 system 消息
        system_indices = [i for i, m in enumerate(result) if m.get("role") == "system"]
        non_system_indices = [i for i, m in enumerate(result) if m.get("role") != "system"]

        # 断点 1: system prompt 末尾
        if system_indices:
            last_sys = system_indices[-1]
            if self._can_carry_marker(result[last_sys]):
                result[last_sys] = self._add_cache_control(result[last_sys])

        # 断点 2-4: 最后 3 条非 system 消息
        last_three = non_system_indices[-3:] if len(non_system_indices) >= 3 else non_system_indices
        for idx in last_three:
            if self._can_carry_marker(result[idx]):
                result[idx] = self._add_cache_control(result[idx])

        return result

    def _can_carry_marker(self, message: dict[str, Any]) -> bool:
        """检查消息是否有足够内容值得缓存.

        太短的消息不值得占用 cache_control 断点.
        """
        content = message.get("content", "")
        if isinstance(content, str):
            return len(content) >= self.MIN_CACHEABLE_CHARS
        elif isinstance(content, list):
            # 多模态内容: 检查总文本长度
            total = sum(len(str(p.get("text", ""))) for p in content if isinstance(p, dict))
            return total >= self.MIN_CACHEABLE_CHARS
        return False

    def _add_cache_control(self, message: dict[str, Any]) -> dict[str, Any]:
        """给消息添加 cache_control 断点.

        Anthropic 格式:
        {
            "role": "...",
            "content": [
                {"type": "text", "text": "...", "cache_control": {"type": "ephemeral", "ttl": "5m"}}
            ]
        }

        如果 content 是字符串, 转为列表格式.
        如果已有 cache_control, 不重复添加.
        """
        msg = dict(message)
        content = msg.get("content", "")

        # 检查是否已有 cache_control
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and "cache_control" in part:
                    return msg  # 已有, 不重复
        elif isinstance(content, dict) and "cache_control" in content:
            return msg

        # 转换为 Anthropic content 格式
        if isinstance(content, str):
            msg["content"] = [
                {
                    "type": "text",
                    "text": content,
                    "cache_control": {
                        "type": "ephemeral",
                        "ttl": self.ttl,
                    },
                }
            ]
        elif isinstance(content, list):
            # 在最后一个 content block 上添加 cache_control
            new_content = []
            for i, part in enumerate(content):
                part_copy = dict(part) if isinstance(part, dict) else part
                if i == len(content) - 1 and isinstance(part_copy, dict):
                    part_copy["cache_control"] = {
                        "type": "ephemeral",
                        "ttl": self.ttl,
                    }
                new_content.append(part_copy)
            msg["content"] = new_content

        return msg

    def estimate_cache_savings(
        self, messages: list[dict[str, Any]], cache_hit_rate: float = 0.75
    ) -> dict[str, int]:
        """估算缓存节省 (用于成本分析).

        Args:
            messages: 消息列表
            cache_hit_rate: 预估缓存命中率 (默认 75%)

        Returns:
            {"cached_tokens": int, "saved_tokens": int}
        """
        from agent_conch.context.engine import SimpleTokenCounter

        counter = SimpleTokenCounter()

        # 计算 system prompt + 最后 3 条消息的 token
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]
        last_three = non_system[-3:] if len(non_system) >= 3 else non_system

        cacheable = system_msgs + last_three
        cached_tokens = counter.estimate(cacheable)
        saved_tokens = int(cached_tokens * cache_hit_rate)

        return {
            "cached_tokens": cached_tokens,
            "saved_tokens": saved_tokens,
        }
