"""AgentConch API — FastAPI 应用入口。

路由:
    POST /api/chat/sessions/{id}/stream  — SSE 流式对话
    POST/GET/DELETE /api/chat/sessions   — 会话管理
    GET /api/profiles                    — Profile 列表/详情
    GET /api/plugins                     — 插件查询
    GET /api/health                      — 健康检查
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from conch.api.routes import chat, plugin, profile, session

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例。"""
    app = FastAPI(
        title="AgentConch API",
        description="Agent Harness Engineering 平台 — v2",
        version="2.0.0",
    )

    # CORS — 允许前端跨域（开发环境）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 路由挂载
    app.include_router(session.router, prefix="/api/chat/sessions", tags=["sessions"])
    app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
    app.include_router(profile.router, prefix="/api/profiles", tags=["profiles"])
    app.include_router(plugin.router, prefix="/api/plugins", tags=["plugins"])

    @app.get("/api/health", tags=["health"])
    async def health():
        return {"status": "ok", "version": "2.0.0"}

    return app


# 全局 app 实例（uvicorn conch.api:app）
app = create_app()
