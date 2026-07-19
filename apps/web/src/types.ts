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

export interface Session extends JsonObject {
  id: string;
  status: string;
  updated_at: number;
  cwd: string;
}

export interface Message extends JsonObject {
  id: string | number | null;
  session_id: string;
  role: string;
  content: string;
  created_at: number;
}

export interface ToolCatalog extends JsonObject {
  schemas: Array<{ name: string; description: string; parameters: JsonObject }>;
  health: Record<string, JsonObject>;
}

export interface SkillSummary extends JsonObject {
  name: string;
  description: string;
  path: string;
}

export interface McpServer extends JsonObject {
  name: string;
  enabled: boolean;
  connected: boolean;
  error: string;
  tools: JsonObject[];
}
