# AgentConch 项目记忆

## 项目定位
agent-conch 是 Agent Harness Engineering 技术实践平台，目标是系统性落地 harness 各技术点，并以可扩展性为核心设计诉求（AI agent 领域技术更新快，新技术点要能零侵入接入）。

## 核心架构（v0.1 方案）
- **9 大能力域**（融合六层架构 + ETCLOVG 七层）：信息边界、工具系统、上下文管理、记忆状态、执行编排、评估验证、可观测性、约束恢复、治理
- **三层扩展模型**：Plugin（域内新实现）/ Hook+中间件（横切逻辑）/ 自定义能力域（全新维度）
- **三件套**：Registry 注册中心 + Profile 实验配置 + Experiment 对比框架
- **设计哲学**：能力域接口定义 WHAT 不定义 HOW，核心稳定、边界常新
- **Skill 系统定位**：作为域1插件（skill_loader）实现，不独立成域；兼容 SKILL.md 规范，可双向加载/产出 skill

## 关键文件
- 技术方案：`docs/technical-design.md`（当前 v0.3）
- 技术点文档：`docs/technical-points/`（13 篇 + 索引 README）
- 核心包：`conch/core/`（7 文件：extension/registry/hooks/middleware/profile/loop/experiment，已实现）
- 能力域：`conch/domains/`（9 域默认实现，MVP 4域完整+5域占位）
- 运行时：`conch/runtime/`（model/sandbox/store）

## 实现状态
- 核心抽象层 conch/core/ 全部实现（v0.3 设计完整落地）
- 9 域默认实现 + 运行时层 + 示例profile + CLI 入口（实现中）
- 13 篇技术点文档完成

## v0.3 关键决策
- 依赖倒置：核心层只定义接口，9域反向依赖核心
- 编排能力收敛到域5（取消独立编排层）
- Hook三约束：职责隔离+优先级+中断白名单；Profile支持extends继承+Pydantic校验
- 沙箱加固基线+Agent自观测+四级指标集(先做执行/成本)+标准基准对接(SWE-bench/MT-Bench)进入MVP
- 明确延后L4：资源池调度/RBAC/审计防篡改/预算分组/配置中心/签名校验——防止过度工程

## 技术选型
- 主语言 Python（LLM 生态优势），asyncio；可平移到 Go/TS
- LLM 自抽象 Provider 层；可观测性 OpenTelemetry；沙箱 Docker；向量库可插拔（Chroma 默认）

## 开发路线
- 阶段一 MVP：L1 闭环（AGENTS.md + builtin shell + Linter + 单 loop + console 轨迹）
- 阶段二：反馈回路（三层评测 + OTel + Compaction + Context Reset + A/B 实验）
- 阶段三：多 Agent 协作 + 持久记忆 + MCP
- 阶段四：治理 + 自治循环

## 评估理念
harness 每个组件编码"模型不能独立完成什么"的假设；模型变强后定期跑消融实验做减法（Manus 越做越简单）。

## v2.0 架构决策（2026-06-27，推翻 v0.3 实现）
- **路线转向**：从"自建一切"改为"成熟框架底座 + agent-conch 式可扩展层"。v0.3 的 9 域骨架从未接真实 LLM，推翻重写
- **技术方案**：`docs/technical-design-v2.md`（v2.0，新交付）
- **成熟框架底座**：LangGraph(编排) + MCP(工具) + Mem0(记忆) + NeMo/LlamaGuard(护栏) + Langfuse(可观测) + DeepEval(评测) + litellm(LLM)
- **核心创新**：Hook 桥接层（`core/hook_bridge.py`）——框架原生事件→框架无关语义Hook总线，换引擎只需新写桥接Plugin，已有Hook零改动复用。这是"成熟框架+零侵入可扩展"叠加的根本保证
- **三件套叠加机制**：Registry 包装框架组件为 Plugin / Profile 声明框架组合(YAML) / Hook 桥接到框架事件点
- **前端**：Next.js 14 三栏布局（会话列表/对话+轨迹/实时指标），SSE流式+WebSocket(HITL)+REST
- **迁移**：conch/core/ 8文件 80%保留；9域骨架→adapters；自建Loop降级为可选Plugin（LangGraph为默认）；静态HTML→Next.js；ScriptedProvider→litellm
- **分阶段**：MVP用户前台(1-2周) → 生产加固(2-4周) → 开发者后台+实验(2-3周) → 多Agent+治理(2-3周)
- **v0.3 文档保留**作历史参考，v2 为当前主线
