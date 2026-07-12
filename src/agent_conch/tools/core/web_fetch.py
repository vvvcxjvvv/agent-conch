"""T 层核心工具: web_fetch — Web 页面抓取."""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from agent_conch.tools.base import BaseTool, ToolResult


class WebFetchInput(BaseModel):
    url: str = Field(..., description="URL to fetch")
    max_chars: int = Field(20000, description="Max characters to return")


class WebFetchTool(BaseTool):
    """Web 页面抓取工具.

    获取 URL 内容, 转为纯文本 (去除 HTML 标签).
    """

    name = "web_fetch"
    description = (
        "Fetch content from a URL. Returns the page content as plain text "
        "(HTML tags removed). Useful for reading documentation or web pages."
    )
    input_model = WebFetchInput
    is_write_tool = False
    is_core = True
    tags = ["web", "fetch", "network"]

    async def execute(self, **kwargs: Any) -> ToolResult:
        validated = WebFetchInput(**kwargs)
        try:
            import httpx

            headers = {"User-Agent": "Mozilla/5.0 (compatible; AgentConch/1.0)"}
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                resp = await client.get(validated.url, headers=headers)
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "")

                if "html" in content_type or "<html" in resp.text[:500].lower():
                    text = self._html_to_text(resp.text)
                else:
                    text = resp.text

            # 截断
            truncated = len(text) > validated.max_chars
            if truncated:
                text = text[: validated.max_chars] + f"\n... [truncated, {len(text)} total chars]"

            return ToolResult(
                content=text,
                metadata={
                    "url": validated.url,
                    "status_code": resp.status_code,
                    "content_type": content_type,
                    "total_chars": len(text),
                    "truncated": truncated,
                },
            )
        except Exception as e:
            return ToolResult.error(f"Web fetch error: {e!s}")

    @staticmethod
    def _html_to_text(html: str) -> str:
        """简单 HTML → 纯文本转换."""
        # 移除 script 和 style
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
        # 移除标签
        text = re.sub(r"<[^>]+>", " ", html)
        # 清理空白
        text = re.sub(r"\s+", " ", text).strip()
        # 解码常见 HTML 实体
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
        return text
