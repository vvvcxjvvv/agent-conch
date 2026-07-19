"""T 层核心工具: web_search — Web 搜索."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agent_conch.sandbox.network_policy import NetworkPolicy
from agent_conch.tools.base import BaseTool, ToolResult


class WebSearchInput(BaseModel):
    query: str = Field(..., description="Search query")
    max_results: int = Field(5, description="Max results to return")


class WebSearchTool(BaseTool):
    """Web 搜索工具.

使用 httpx 调用搜索 API。
    默认使用 DuckDuckGo HTML 搜索 (无需 API key).
    """

    name = "web_search"
    description = (
        "Search the web for information. Returns search result titles, URLs, and snippets."
    )
    input_model = WebSearchInput
    is_write_tool = False
    is_core = True
    tags = ["web", "search", "network"]

    def __init__(self, network_policy: NetworkPolicy | None = None) -> None:
        self.network_policy = network_policy or NetworkPolicy()

    async def execute(self, **kwargs: Any) -> ToolResult:
        validated = WebSearchInput(**kwargs)
        try:
            import re

            import httpx

            # DuckDuckGo HTML 搜索 (无需 API key)
            url = "https://html.duckduckgo.com/html/"
            self.network_policy.require_url(url)
            headers = {"User-Agent": "Mozilla/5.0 (compatible; AgentConch/1.0)"}

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    url,
                    data={"q": validated.query},
                    headers=headers,
                    follow_redirects=True,
                )
                html = resp.text

            # 简单解析搜索结果
            results: list[str] = []
            # 提取结果标题和链接
            link_pattern = re.compile(
                r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                re.DOTALL,
            )
            snippet_pattern = re.compile(
                r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
                re.DOTALL,
            )

            links = link_pattern.findall(html)
            snippets = snippet_pattern.findall(html)

            for i, ((raw_url, title), snippet) in enumerate(zip(links, snippets, strict=False), 1):
                if i > validated.max_results:
                    break
                # 清理 HTML 标签
                clean_title = re.sub(r"<[^>]+>", "", title).strip()
                clean_snippet = re.sub(r"<[^>]+>", "", snippet).strip()
                # DuckDuckGo 的 URL 重定向
                clean_url = raw_url
                if "uddg=" in raw_url:
                    from urllib.parse import parse_qs, urlparse

                    parsed = urlparse(raw_url)
                    params = parse_qs(parsed.query)
                    if "uddg" in params:
                        clean_url = params["uddg"][0]

                results.append(f"{i}. {clean_title}\n   URL: {clean_url}\n   {clean_snippet}")

            if not results:
                return ToolResult(
                    content=f"No search results found for: {validated.query}",
                    metadata={"query": validated.query, "results_count": 0},
                )

            return ToolResult(
                content="\n\n".join(results),
                metadata={
                    "query": validated.query,
                    "results_count": len(results),
                },
            )
        except Exception as e:
            return ToolResult.error(f"Web search error: {e!s}")
