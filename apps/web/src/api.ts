import type { Approval, DecisionTrace, GovernanceOverview, Insight, JsonObject, RunResult } from "./types";

export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8765";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
  return response.json() as Promise<T>;
}

export const api = {
  run: (input: string, sessionId: string) =>
    request<RunResult>("/runs", {
      method: "POST",
      body: JSON.stringify({ input, session_id: sessionId }),
    }),
  trajectory: (id: string) => request<JsonObject[]>(`/runs/${id}/trajectory`),
  decisions: (id: string) => request<DecisionTrace[]>(`/runs/${id}/decisions`),
  traces: (id: string) => request<JsonObject[]>(`/runs/${id}/traces`),
  verification: (id: string) => request<JsonObject[]>(`/runs/${id}/verification`),
  insights: () => request<Insight>("/insights"),
  audit: () => request<JsonObject[]>("/security/audit"),
  approvals: () => request<Approval[]>("/approvals"),
  decide: (id: string, status: "approved" | "rejected") =>
    request<Approval>(`/approvals/${id}/decision`, {
      method: "POST",
      body: JSON.stringify({ status }),
    }),
  governance: () => request<GovernanceOverview>("/governance/overview"),
  runRegressions: () => request<JsonObject>("/regressions/run", { method: "POST" }),
  analyzeSkills: () => request<JsonObject[]>("/curator/analyze", { method: "POST" }),
  runSchedules: () => request<JsonObject[]>("/schedules/run-due", { method: "POST" }),
};
