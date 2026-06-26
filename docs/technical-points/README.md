# 技术点文档索引

> 每个核心技术点一份独立文档，深入讲解设计理念、实现细节与参考实践。

| # | 技术点 | 文档 | 对应代码 |
|---|---|---|---|
| 01 | 扩展点契约 | [01-extension-point.md](01-extension-point.md) | `conch/core/extension.py` |
| 02 | 注册中心 | [02-registry.md](02-registry.md) | `conch/core/registry.py` |
| 03 | Hook 与中间件 | [03-hook-and-middleware.md](03-hook-and-middleware.md) | `conch/core/hooks.py` `middleware.py` |
| 04 | Profile 与实验框架 | [04-profile-and-experiment.md](04-profile-and-experiment.md) | `conch/core/profile.py` `experiment.py` |
| 05 | Agent Loop 引擎 | [05-agent-loop.md](05-agent-loop.md) | `conch/core/loop.py` |
| 06 | 上下文管理 | [06-context-management.md](06-context-management.md) | `conch/domains/context/` |
| 07 | 工具系统与 MCP | [07-tool-system-mcp.md](07-tool-system-mcp.md) | `conch/domains/tool/` |
| 08 | 记忆五分法 | [08-memory-five-types.md](08-memory-five-types.md) | `conch/domains/memory/` |
| 09 | 多 Agent 协作 | [09-multi-agent-orchestration.md](09-multi-agent-orchestration.md) | `conch/domains/orchestration/` |
| 10 | 可观测性与自观测 | [10-observability.md](10-observability.md) | `conch/domains/observability/` |
| 11 | 沙箱与安全治理 | [11-sandbox-security.md](11-sandbox-security.md) | `conch/runtime/sandbox/` `conch/domains/governance/` |
| 12 | 成本守卫与分级降级 | [12-cost-guard.md](12-cost-guard.md) | `conch/core/loop.py` (CostGuard) |
| 13 | Skill 系统 | [13-skill-system.md](13-skill-system.md) | `conch/domains/information/` |

## 阅读建议

**入门顺序**：01 → 02 → 03 → 05 → 04（先理解核心抽象，再看循环和实验）

**按域深入**：06-13 各对应一个能力域或横切关注点

**完整方案**：[../technical-design.md](../technical-design.md)
