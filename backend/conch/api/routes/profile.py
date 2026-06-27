"""Profile 管理路由。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from conch.api.deps import get_profile_loader

router = APIRouter()


@router.get("")
async def list_profiles():
    """列出所有可用 Profile。"""
    loader = get_profile_loader()
    profiles_dir = loader.profiles_dir
    result = []
    for f in profiles_dir.glob("*.yaml"):
        result.append({"name": f.stem, "file": str(f.name)})
    return {"profiles": result}


@router.get("/{name}")
async def get_profile(name: str):
    """获取 Profile 详细配置。"""
    loader = get_profile_loader()
    try:
        profile = loader.load(name)
        return {
            "name": profile.name,
            "description": profile.description,
            "model": profile.model,
            "model_fallback": profile.model_fallback,
            "max_steps": profile.max_steps,
            "max_tokens": profile.max_tokens,
            "domains": {
                d: {"impl": cfg.impl, "params": cfg.params}
                for d, cfg in profile.domains.items()
            },
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")
