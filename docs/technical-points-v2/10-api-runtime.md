# 10 — API 层 + 运行时

> **代码位置**：`backend/conch/api/`（9 文件）、`backend/conch/runtime/sandbox/docker_sandbox.py`
> **对应 ETCLOVG**：G 层（治理与安全管控）+ 基础设施

## 1. API 层架构

```
FastAPI app (api/__init__.py)
├── CORS → 允许 localhost:3000 跨域
├── /api/health                              (健康检查)
├── /api/chat/sessions/{id}/stream  [POST]   (SSE 流式对话)
├── /api/chat/sessions/{id}/resume/{rid}/stream [POST] (审批后原地恢复)
├── /api/chat/sessions/{id}/ws      [WS]     (HITL 审批双向通道)
├── /api/chat/sessions              [CRUD]   (会话管理)
├── /api/profiles                   [GET]    (Profile 列表/详情)
└── /api/plugins                   [GET]     (插件查询)
```

### 依赖注入（api/deps.py）

```python
def _ensure_adapters_loaded():
    """import 所有 adapter → @register 触发注册"""
    from conch.adapters.llm.litellm_provider import LiteLLMProvider
    from conch.adapters.orchestration.langgraph_react import LangGraphReActOrchestrator
    # ... 11 个 adapter

def build_runtime(profile: Profile) -> AgentRuntime:
    """按 Profile 构建各域 Plugin → AgentRuntime 容器"""
    _ensure_adapters_loaded()
    rt = AgentRuntime(profile=profile, hook_bus=HookBus())

    # 按 Profile.domains 逐域构建
    if "llm" in d:     rt.llm = registry.build("llm", d["llm"].impl, ...)
    if "orchestration": rt.orchestrator = registry.build("orchestration", ...)
    if "tool":         rt.tools = registry.build("tool", ...)
    if "guardrail":    rt.guardrail_provider = registry.build("guardrail", ...)
    # ... 其余域

    rt.cost_guard = CostGuard(max_tokens=profile.max_tokens)
    rt.guardrail_pipeline = GuardrailPipeline(rt.guardrail_provider, rt.state)
    return rt

# 阶段二新增：
remember_pending_resume(session_id, request_id, message, profile)
_record_guardrail_event(...)
```

### AgentRuntime 容器

```python
@dataclass
class AgentRuntime:
    profile: Profile
    llm: Any = None              # LiteLLMProvider 实例
    orchestrator: Any = None     # LangGraphReActOrchestrator / SingleLoop
    tools: Any = None            # MCPToolProvider 实例
    guardrail_provider: Any = None
    guardrail_pipeline: GuardrailPipeline = None
    observability: Any = None
    cost_guard: CostGuard = None
    hook_bus: HookBus
    state: State
```

## 2. SSE 流式对话端点

### 事件格式

```python
# api/sse.py
def sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"

# 事件类型
text_delta  → {"content": "正在..."}
tool_call   → {"tool": "read_file", "args": {...}, "call_id": "abc123"}
tool_result → {"call_id": "abc123", "result": "..."}
guardrail   → {"action": "blocked", "reason": "有害指令"}
cost_update → {"tokens": 5230, "cost": 0.023, "steps": 5}
hitl_request→ {"request_id": "...", "tool": "write_file", "args": {...}, "reason": "..."}
done        → {"success": true/false, "error": null}
```

### 请求-响应流程

```python
# api/routes/chat.py
@router.post("/sessions/{session_id}/stream")
async def stream_chat(session_id, req: ChatRequest):
    profile = loader.load(req.profile)
    rt = build_runtime(profile, session_id=session_id)
    rt.state.task = req.message

    # 构建 LangGraph 图（注入 tools + system_prompt + recalled memory）
    tools = rt.tools.tools_for("", rt.state)
    sys_prompt = rt.info_provider.assemble("", rt.state)
    memory_context = rt.memory.recall(req.message, "episodic", limit=3)
    rt.orchestrator.build_graph(tools, sys_prompt)

    async def event_generator():
        async for event in rt.orchestrator.run(req.message, [], rt.state):
            yield sse_event(event["type"], event)
        rt.memory.store("user:...", {"role": "user", "content": req.message}, "episodic")
        rt.memory.store("assistant:...", {"role": "assistant", "content": reply}, "episodic")
        yield sse_event("cost_update", {"tokens": ..., "cost": ..., "steps": ...})

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.post("/sessions/{session_id}/resume/{request_id}/stream")
async def resume_chat(session_id, request_id):
    """审批后恢复同一任务，不重复追加 user message"""
```

## 3. 前端 API 通信

```
Next.js (localhost:3000)
  └─ next.config.js rewrites:
       /api/* → http://localhost:8000/api/*  (代理到后端)
       
  └─ lib/sse-client.ts:
       streamChat(sessionId, message, profile, onEvent)
         └─ fetch POST /api/chat/sessions/{id}/stream
              └─ ReadableStream 逐行解析 SSE
                   └─ event → zustand store action
       resumeChat(sessionId, requestId)
         └─ fetch POST /api/chat/sessions/{id}/resume/{requestId}/stream

  └─ lib/ws-client.ts:
       connect(sessionId)
         └─ WebSocket /api/chat/sessions/{id}/ws
              ├─ hitl_request  → 待审批面板
              ├─ hitl_decision → 批准后原地恢复任务
              └─ memory recall 依然走 SSE 主链路，无额外前端协议

后端默认运行时 Hook 现已覆盖：

- `pre_model_call`：输入护栏（NeMo → LlamaGuard）
- `pre_tool`：治理校验 + 工具护栏
- `post_model_call`：输出分类事件 + usage/cost 计账
- `post_step`：trace
- `hitl approval`：缓存并恢复待审批任务
- `retrieval recall`：记录召回与过滤事件
```

## 4. 会话存储（MVP 内存）

```python
# api/deps.py
_session_store: dict[str, dict] = {}

# 会话生命周期
POST   /api/chat/sessions     → 创建 {id, profile, title, created_at, messages}
GET    /api/chat/sessions     → 列表
GET    /api/chat/sessions/{id}→ 详情
DELETE /api/chat/sessions/{id}→ 删除
```

阶段二新增 `pending_resume`：

```python
session["pending_resume"] = {
    "request_id": "...",
    "message": "...",
    "profile": "user-chat-v1",
}
```

审批通过后由 `/resume/{request_id}/stream` 消费，不重复追加用户消息。

## 5. Docker 沙箱（runtime/sandbox/docker_sandbox.py）

v1 迁移，加固基线：CPU/MEM 限制、禁用特权、只读挂载。

```python
class DockerSandbox:
    def run(self, command, workdir, timeout=30):
        """Docker 隔离执行命令"""
        # docker run --rm --cpus=1 --memory=512m
        #            --network=none --read-only
        #            -v {workdir}:/workspace
        #            sandbox-image {command}
```

`BuiltinShellProvider.run_bash()` 在 Docker 可用时走沙箱，不可用时降级本地执行。沙箱由 `pre_tool` Hook 的权限校验 + `GovernanceProvider` 双重保护。

## 6. 加载全链路总结

```
用户输入
  └─ POST /api/chat/sessions/{id}/stream
       ├─ ProfileLoader.load(profile_name)     → Profile
       ├─ build_runtime(profile)               → AgentRuntime
       │    ├─ registry.build(各域)             → Plugin 实例
       │    ├─ CostGuard(profile.max_tokens)    → 成本守卫
       │    ├─ HookBus()                        → Hook 总线
       │    └─ GuardrailPipeline(...)           → 护栏管道
       ├─ orchestrator.build_graph(tools, sys_prompt)
       └─ orchestrator.run(task, [], state)
            └─ LangGraphHookBridge → 语义 Hook
                 └─ hook_bus.fire("pre_model_call") → guardrail_pipeline.run_input()
                 └─ litellm.acompletion(stream=True) → yield text_delta
                 └─ hook_bus.fire("pre_tool")
                      ├─ governance.check_permission()
                      ├─ require_approval → create hitl_request + remember_pending_resume
                      └─ MCP execute → yield tool_result
                 └─ cost_guard.check(state) → apply degrade
            ├─ SSE → 前端三栏 UI
            └─ WebSocket → HITL 批准/拒绝
```

## 7. 可扩展点

- 新 API 端点 → `api/routes/` 加文件 + `api/__init__.py` 注册路由
- 新存储后端 → 替换 `_session_store`（POST/PG 适配）
- 沙箱加固 → `DockerSandbox` 扩展安全参数
- WebSocket HITL → 当前已支持任务内原地恢复，可继续扩成任务级状态机恢复
