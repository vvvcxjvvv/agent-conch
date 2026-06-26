# 04 · Profile 与实验框架

> 配置即实验——一组插件 + 参数 = 一个实验配置，切换配置即可切换实验。

## Profile

Profile 是声明式的实验配置，YAML 格式：

```yaml
name: coding-agent-v1
description: 基础 coding agent
domains:
  information: { impl: agents_md, params: { file: ./AGENTS.md } }
  tool: { impl: builtin_shell, params: { sandbox: docker } }
  context: { impl: jit_compaction, params: { threshold: 0.4 } }
  memory: { impl: notes_file, params: { path: ./NOTES.md } }
  orchestration: { impl: single_loop, params: { max_steps: 50 } }
  observability: { impl: console_tracer, params: {} }
  governance: { impl: allowlist_perms, params: { tools: [read,write,bash] } }
max_steps: 50
max_tokens: 100000
model: gpt-4o
model_fallback: gpt-4o-mini   # 降级时切换的廉价模型
```

### 配置继承（extends）

子 Profile 继承父配置，仅覆写差异项：

```yaml
# coding-agent-v2-subagents.yaml
name: coding-agent-v2-subagents
extends: coding-agent-v1        # 继承全部
domains:
  orchestration: { impl: orchestrator_worker, params: { max_workers: 3 } }
```

只覆写了编排域，其余域继承 v1。避免配置重复。

### Pydantic 校验

启动前全量校验：插件名是否存在、参数类型是否正确、域名是否合法、必填项是否缺失。非法配置在启动时即被拦截，不会带到运行时崩溃。

### 环境变量覆盖

支持 `CONCH_*` 环境变量覆盖参数：

```bash
CONCH_MAX_TOKENS=50000 CONCH_MODEL=claude-sonnet-4 python -m conch run ...
```

> **动态配置边界**：MVP 仅支持环境变量覆盖。配置中心、基于任务标签自动切换插件组合属 L4 企业级，延后。

## 实验框架

### Profile 对比

```python
results = await run_experiment(
    task_suite="swe-mini",
    profiles=["coding-agent-v1", "coding-agent-v2-subagents"],
)
print(results.comparison_table())
```

输出 Markdown 对比表：

| Profile | 成功率 | 平均步数 | 平均Token | 平均成本 | 降级次数 |
|---|---|---|---|---|---|
| coding-agent-v1 | 60.0% | 12.3 | 8500 | $0.1203 | 0 |
| coding-agent-v2-subagents | 80.0% | 8.5 | 12000 | $0.1805 | 0 |

### 消融实验

逐个关闭能力域，量化每个域的边际贡献：

```python
results = await run_ablation(
    task_suite="swe-mini",
    base_profile="coding-agent-v1",
    domains_to_ablate=["context", "memory", "constraint"],
)
```

> 借鉴 Anthropic 洞察：harness 中每个组件都编码了"模型不能独立完成什么"的假设。模型变强后，定期跑消融实验，移除已不必要的机制。

### 标准基准对接

实验框架原生集成业内通用基准，保证结果横向可比：

| 基准 | 类型 | 用途 |
|---|---|---|
| SWE-bench Lite | 代码任务 | 对齐业内公开结果 |
| MT-Bench | 多轮对话 | 评估上下文管理 |
| swe-mini（自建） | 精简代码集 | MVP 快速验证 |

## 相关文件

- `conch/core/profile.py` — Profile + ProfileLoader
- `conch/core/experiment.py` — 实验框架
- `profiles/` — 示例配置
