# Agent Conch Desktop

Electron 仅负责窗口、目录选择和安全 IPC。终端命令发送到
`POST /desktop/terminal`，由 Agent Conch 的 RBAC、PolicyEngine、审批、预算和审计链路统一执行。

```bash
cd apps/web && npm run build
cd ../desktop && npm install && npm start
```

生成可分发目录或平台安装包：

```bash
npm run pack
npm run dist
```

`dist` 的签名与公证使用 CI 注入的平台证书；仓库不保存签名密钥。

开发时可通过 `CONCH_WEB_URL=http://127.0.0.1:5173` 加载 Vite 页面，
通过 `CONCH_API_BASE` 指定后端地址。
