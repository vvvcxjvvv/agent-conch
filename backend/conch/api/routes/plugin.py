"""插件查询路由。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from conch.api.deps import get_registry

router = APIRouter()


@router.get("")
async def list_plugins(domain: str | None = Query(None, description="按域过滤")):
    """列出已注册的插件。"""
    reg = get_registry()
    if domain:
        return {"domain": domain, "plugins": reg.list(domain)}
    # 列出所有域
    all_domains = [
        "llm", "orchestration", "tool", "guardrail", "observability",
        "information", "context", "memory", "eval", "governance",
    ]
    result = {}
    for d in all_domains:
        impls = reg.list(d)
        if impls:
            result[d] = impls
    return {"plugins": result}
