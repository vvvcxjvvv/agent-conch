import { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import agentConchLogo from "./assets/agent-conch-logo.png";
import { API_BASE, api } from "./api";
import type { Approval, DecisionTrace, Insight, JsonObject, RunResult } from "./types";

type Tab = "response" | "timeline" | "decisions" | "trajectory" | "traces" | "verification";

const tabLabels: Record<Tab, string> = {
  response: "最终回答",
  timeline: "实时事件",
  decisions: "决策轨迹",
  trajectory: "执行轨迹",
  traces: "Trace",
  verification: "验证报告",
};

const navigation: Array<{ tab: Tab; icon: string; label: string }> = [
  { tab: "response", icon: "⌂", label: "工作台" },
  { tab: "decisions", icon: "◇", label: "决策轨迹" },
  { tab: "timeline", icon: "◎", label: "实时事件" },
  { tab: "trajectory", icon: "↗", label: "执行轨迹" },
  { tab: "traces", icon: "◫", label: "Trace" },
  { tab: "verification", icon: "✓", label: "验证报告" },
];

const emptyInsight: Insight = {
  sessions: 0,
  success_rate: 0,
  total_tokens: 0,
  tool_calls: 0,
  average_tool_duration_ms: 0,
};

function JsonRows({ rows }: { rows: JsonObject[] }) {
  if (!rows.length) return <div className="empty">尚无数据</div>;
  return (
    <div className="event-list">
      {rows.map((row, index) => {
        const label = String(row.type ?? row.step_type ?? row.name ?? "Event");
        return (
          <details
            className="event"
            key={`${index}-${label}`}
            open={index === rows.length - 1}
          >
            <summary>
              <span className="event-icon">{String(index + 1).padStart(2, "0")}</span>
              <span className="event-name"><strong>{label}</strong><small>运行事件</small></span>
              <span className="event-chevron">⌄</span>
            </summary>
            <pre>{JSON.stringify(row, null, 2)}</pre>
          </details>
        );
      })}
    </div>
  );
}

function DecisionRows({ rows }: { rows: DecisionTrace[] }) {
  if (!rows.length) return <div className="empty">运行后将在这里展示可审计的决策摘要</div>;
  return (
    <div className="decision-list">
      {rows.map((row, index) => (
        <article className={`decision decision-${row.phase}`} key={row.decision_id}>
          <div className="decision-rail"><span>{index + 1}</span><i /></div>
          <div className="decision-body">
            <div className="decision-meta">
              <span>{row.phase}</span>
              <small>第 {row.turn_index} 轮</small>
            </div>
            <h3>{row.title}</h3>
            <p>{row.summary}</p>
            {Object.keys(row.evidence).length > 0 && (
              <details className="decision-evidence">
                <summary>查看决策证据</summary>
                <pre>{JSON.stringify(row.evidence, null, 2)}</pre>
              </details>
            )}
          </div>
        </article>
      ))}
    </div>
  );
}

function ResponsePanel({
  text,
  view,
  onViewChange,
}: {
  text: string;
  view: "markdown" | "source";
  onViewChange: (view: "markdown" | "source") => void;
}) {
  if (!text) return <div className="response-empty"><span>✦</span><h3>等待运行结果</h3><p>启动任务后，最终回答将在这里呈现。</p></div>;
  return (
    <div className="answer">
      <div className="answer-header">
        <span>FINAL RESPONSE</span>
        <div className="response-toggle" aria-label="回答展示格式">
          <button className={view === "markdown" ? "active" : ""} onClick={() => onViewChange("markdown")}>Markdown</button>
          <button className={view === "source" ? "active" : ""} onClick={() => onViewChange("source")}>源文本</button>
        </div>
      </div>
      {view === "markdown" ? (
        <div className="markdown-body"><ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown></div>
      ) : (
        <pre className="response-source">{text}</pre>
      )}
    </div>
  );
}

export default function App() {
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID().slice(0, 12));
  const [input, setInput] = useState("检查当前仓库并给出可验证的结果");
  const [tab, setTab] = useState<Tab>("response");
  const [timeline, setTimeline] = useState<JsonObject[]>([]);
  const [decisions, setDecisions] = useState<DecisionTrace[]>([]);
  const [trajectory, setTrajectory] = useState<JsonObject[]>([]);
  const [traces, setTraces] = useState<JsonObject[]>([]);
  const [verification, setVerification] = useState<JsonObject[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [audit, setAudit] = useState<JsonObject[]>([]);
  const [insight, setInsight] = useState<Insight>(emptyInsight);
  const [result, setResult] = useState<RunResult | null>(null);
  const [responseView, setResponseView] = useState<"markdown" | "source">("markdown");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    const settled = await Promise.allSettled([
      api.trajectory(sessionId),
      api.decisions(sessionId),
      api.traces(sessionId),
      api.verification(sessionId),
      api.approvals(),
      api.insights(),
      api.audit(),
    ]);
    if (settled[0].status === "fulfilled") setTrajectory(settled[0].value);
    if (settled[1].status === "fulfilled") setDecisions(settled[1].value);
    if (settled[2].status === "fulfilled") setTraces(settled[2].value);
    if (settled[3].status === "fulfilled") setVerification(settled[3].value);
    if (settled[4].status === "fulfilled") setApprovals(settled[4].value);
    if (settled[5].status === "fulfilled") setInsight(settled[5].value);
    if (settled[6].status === "fulfilled") setAudit(settled[6].value);
  }, [sessionId]);

  useEffect(() => {
    void refresh();
    const events = new EventSource(`${API_BASE}/events/${sessionId}`);
    events.onmessage = ({ data }) => {
      const event = JSON.parse(data) as JsonObject;
      setTimeline((current) => [...current, event]);
      if (event.type === "decision_trace" && typeof event.decision === "object") {
        setDecisions((current) => [...current, event.decision as DecisionTrace]);
      }
    };
    events.onerror = () => setError("实时事件连接暂不可用；静态查询仍可使用。");
    return () => events.close();
  }, [refresh, sessionId]);

  const activeRows =
    tab === "trajectory"
      ? trajectory
      : tab === "traces"
        ? traces
        : tab === "verification"
          ? verification
          : timeline;

  async function startRun() {
    setRunning(true);
    setError("");
    setResult(null);
    setResponseView("markdown");
    setTimeline([]);
    setDecisions([]);
    try {
      setResult(await api.run(input, sessionId));
      setTab("response");
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "运行失败");
    } finally {
      setRunning(false);
    }
  }

  async function decide(id: string, status: "approved" | "rejected") {
    await api.decide(id, status);
    setApprovals(await api.approvals());
  }

  return (
    <div className="app-shell">
      <aside className="global-sidebar">
        <div className="sidebar-brand"><div className="brand-mark"><img src={agentConchLogo} alt="Agent Conch" /></div><div><strong>Agent Conch</strong><small>AI Harness</small></div></div>
        <div className="project-switcher"><span>●</span><div><small>WORKSPACE</small><strong>Local Project</strong></div><b>⌄</b></div>
        <p className="nav-section">WORKBENCH</p>
        <nav className="side-nav">
          {navigation.map((item) => (
            <button className={tab === item.tab ? "active" : ""} onClick={() => setTab(item.tab)} key={item.tab}>
              <span>{item.icon}</span>{item.label}
              {item.tab === "decisions" && decisions.length > 0 && <b>{decisions.length}</b>}
            </button>
          ))}
        </nav>
        <div className="sidebar-spacer" />
        <div className="sidebar-status"><div><i /> API 已连接</div><code>{API_BASE.replace("http://", "")}</code></div>
      </aside>

      <section className="workspace-shell">
        <header className="topbar">
          <div className="breadcrumbs"><span>Agent Conch</span><i>/</i><strong>运行工作台</strong></div>
          <div className="topbar-actions"><span className="edition">P3 · Auditable</span><span className="session-chip">Session {sessionId.slice(0, 8)}</span></div>
        </header>

        <div className="workbench-grid">
          <section className="task-composer">
            <div className="composer-heading"><div><p>NEW RUN</p><h1>创建任务</h1></div><span className={`run-state state-${running ? "running" : result?.status ?? "idle"}`}>{running ? "RUNNING" : result?.status ?? "IDLE"}</span></div>
            <div className="runtime-card"><div className="runtime-logo">✦</div><div><small>RUNTIME</small><strong>Builtin Agent</strong><span>Auditable execution</span></div><b>›</b></div>
            <label>Session ID<input value={sessionId} onChange={(e) => setSessionId(e.target.value)} /></label>
            <label>任务描述<textarea rows={10} value={input} onChange={(e) => setInput(e.target.value)} /></label>
            <div className="run-options"><div><small>Context</small><strong>Auto compact</strong></div><div><small>Verification</small><strong>Automatic</strong></div></div>
            <button className="primary" disabled={running || !input.trim()} onClick={() => void startRun()}>{running ? "正在执行…" : "启动运行  ✦"}</button>
            {error && <p className="error">{error}</p>}
          </section>

          <section className="result-workspace">
            <section className="metrics">
              <div><span>成功率</span><strong>{(insight.success_rate * 100).toFixed(0)}%</strong></div>
              <div><span>会话</span><strong>{insight.sessions}</strong></div>
              <div><span>Token</span><strong>{insight.total_tokens.toLocaleString()}</strong></div>
              <div><span>工具调用</span><strong>{insight.tool_calls}</strong></div>
              <div><span>平均耗时</span><strong>{insight.average_tool_duration_ms.toFixed(0)}ms</strong></div>
            </section>

            <section className="result-panel panel">
              <div className="result-toolbar"><div><p>RUN OUTPUT</p><h2>{tabLabels[tab]}</h2></div><nav className="result-tabs">
                {(["response", "decisions", "timeline", "trajectory", "traces", "verification"] as Tab[]).map((item) => (
                  <button className={tab === item ? "active" : ""} onClick={() => setTab(item)} key={item}>{tabLabels[item]}</button>
                ))}
              </nav></div>
              <div className="result-content">
                {tab === "response" ? (
                  <ResponsePanel text={result?.final_response ?? ""} view={responseView} onViewChange={setResponseView} />
                ) : tab === "decisions" ? (
                  <DecisionRows rows={decisions} />
                ) : (
                  <JsonRows rows={activeRows} />
                )}
              </div>
            </section>

            <div className="utility-grid">
              <section className="panel side-card"><div className="panel-title"><span>审批队列</span><b>{approvals.length}</b></div>
                {approvals.length === 0 ? <div className="empty compact">暂无待审批操作</div> : approvals.map((item) => (
                  <article className="approval" key={item.approval_id}><strong>{item.operation}</strong><p>{item.reason}</p><small>{item.session_id}</small><div><button onClick={() => void decide(item.approval_id, "approved")}>批准</button><button onClick={() => void decide(item.approval_id, "rejected")}>拒绝</button></div></article>
                ))}
              </section>
              <section className="panel side-card"><div className="panel-title"><span>安全审计</span><b>{audit.length}</b></div>
                {audit.length === 0 ? <div className="safe">✓ 未发现危险配置</div> : audit.map((item, index) => (
                  <div className="finding" key={index}><strong>{String(item.severity)}</strong><span>{String(item.message)}</span></div>
                ))}
              </section>
            </div>
          </section>
        </div>
      </section>
    </div>
  );
}
