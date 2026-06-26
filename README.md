# AgentConch

> Agent Harness Engineering 技术实践平台 — 以可扩展性为核心。

**Agent = Model + Harness。** 模型是 CPU，Harness 是操作系统。当模型能力趋于稳定，任务执行的可靠性越来越取决于模型外层的那层工程。

AgentConch 把 Harness 拆解为 **9 大能力域**，每个域定义稳定接口、支持插件化实现，配套注册中心 + Profile + 实验框架三件套，使"接入新技术点"等同于"写插件 + 一行注册"，对核心零侵入。

## 快速开始

```bash
# 安装
pip install -e ".[dev]"

# 用示例 Profile 跑一个任务
python -m conch run --profile profiles/coding-agent-v1.yaml --task "修复 hello.py 中的语法错误"
```

## 核心文档

- [技术方案 v0.3](docs/technical-design.md) — 完整架构设计
- [技术点详解](docs/technical-points/) — 逐个技术点深入文档

## 设计哲学

- **可扩展性 > 功能完备性**
- **核心稳定，边界常新**
- **反对过度工程**，渐进式补层

## License

MIT
