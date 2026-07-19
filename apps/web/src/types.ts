export type JsonObject = Record<string, unknown>;

export interface RunResult extends JsonObject {
  session_id: string;
  status: string;
  final_response: string;
}

export interface Approval extends JsonObject {
  approval_id: string;
  session_id: string;
  operation: string;
  reason: string;
  status: string;
}

export interface Insight extends JsonObject {
  sessions: number;
  success_rate: number;
  total_tokens: number;
  tool_calls: number;
  average_tool_duration_ms: number;
}

export interface DecisionTrace extends JsonObject {
  decision_id: string;
  session_id: string;
  turn_index: number;
  phase: string;
  title: string;
  summary: string;
  evidence: JsonObject;
  created_at: number;
}

export interface GovernanceOverview extends JsonObject {
  policy: {
    approval_level: number;
    roles: Record<string, string[]>;
    rules: JsonObject[];
  };
  approvals: Approval[];
  budgets: JsonObject[];
  credentials: JsonObject[];
  regressions: {
    cases: number;
    latest_results: JsonObject[];
  };
  schedules: JsonObject[];
  coordinator: JsonObject[];
  snapshots: JsonObject[];
}
