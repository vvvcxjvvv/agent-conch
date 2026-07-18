# E 执行环境与沙箱层实现策略沉淀（P3 增量）

## 一、设计目标回顾

E 层为工具和验证提供受控执行环境。P3 的直接目标是让 VerificationLayer 复用沙箱命令执行协议；继续遵守路径校验、超时和后端可插拔约束。

## 二、核心实现方案

`VerificationLayer → ConchEngine._run_verification → LocalBackend.execute → CommandResult`。命令、工作目录、超时、输出和退出码统一进入验证报告。核心文件：`sandbox/local.py`、`verification/layer.py`、`engine/conch_engine.py`。

## 三、设计落地对照

- ✅ 验证命令不绕过 SandboxBackend。
- ✅ 超时和退出码进入确定性判断。
- ⚠️ 默认验证后端使用 LocalBackend；DockerBackend 保持 P2 能力但未按每次验证动态切换。

## 四、关键技术点与踩坑记录

验证 runner 采用窄接口 `(command, cwd, timeout)`，避免 V 层依赖具体 backend。命令按配置顺序串行执行并在首个失败处停止，减少失败后的无效成本。

## 五、验证与覆盖情况

成功和失败 CommandResult 均有专项测试；全量回归通过。真实 Docker daemon 用例因环境不可用跳过 1 项，不能据此宣称本机完成 Docker 端到端验收。

## 六、演进与优化方向

P4 按任务风险选择 Local/Docker/gVisor，并把网络白名单、资源预算和快照回滚纳入 PolicyEngine。
